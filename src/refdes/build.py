"""Turn parsed items into a resolved, evaluated, validated project."""

from __future__ import annotations

import hashlib
import html as html_entities
import json
import os
import re

from markdown_it import MarkdownIt

from . import blocked as blocked_mod
from . import blocks as blocks_mod
from . import boards as boards_mod
from . import calc, citations as citations_mod, imports, pages as pages_mod, seal
from . import ids as ids_mod
from . import workspaces as workspaces_mod
from .model import (
    CHECK_VIOLATION, ERROR, INFO, INVALIDATE, WARNING,
    CalcLine, CheckResult, Coverage, Item, ItemType, Project,
)

# Explicit reference: [[REQ-PWR-002]] or [[REQ-PWR-002|the input range]]. The
# ':' admits the "fig:" namespace (docs/design/index-blocks.md §9) -- item ids
# are allocated as PREFIX-BOARD-NNN and never contain one, so this only ever
# matches the new namespace on real projects, never an existing item id.
EXPLICIT_REF_RE = re.compile(r"\[\[\s*([A-Za-z0-9\-_:]+)\s*(?:\|\s*([^\]]+?)\s*)?\]\]")
# Bare reference: REQ-PWR-002 appearing in prose.
BARE_REF_RE = re.compile(r"(?<![\w\-/])([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6})(?![\w\-])")
# Inline calc value: {{P_diss}}
INLINE_VALUE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# Regions of rendered HTML where references must not be linkified.
PROTECTED_RE = re.compile(r"<pre\b[\s\S]*?</pre>|<code\b[\s\S]*?</code>", re.IGNORECASE)
# `<img src="...">` as markdown-it emits it -- html is off, so this only ever comes
# from `![alt](src)`, never from a literal tag the author typed. Three groups so a
# rewrite can replace just the URL and leave the rest of the tag untouched.
IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)
# A URL (has a scheme) or protocol-relative reference: not ours to validate.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:|^//")
# A whole paragraph that is nothing but one image immediately followed by a
# Quarto-style attribute suffix: `![alt](src){width=60% caption="..."}`. Anything
# else -- no suffix, other text in the paragraph -- is left completely alone.
FIGURE_RE = re.compile(
    r'<p>\s*(<img\b[^>]*?>)\s*\{([^{}]*)\}\s*</p>', re.IGNORECASE
)
FIGURE_ATTR_RE = re.compile(r'([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|(\S+))')
IMG_ALT_RE = re.compile(r'\balt="([^"]*)"', re.IGNORECASE)
# A resolved figure's number, filled in once the whole rendered document is
# known (docs/design/index-blocks.md §9) -- emitted by _apply_figure_attrs,
# consumed by resolve_figures.
FIG_NUM_MARKER_RE = re.compile(r'<span class="fig-num" data-fig="([^"]*)"></span>')
# A `[[fig:id]]` reference, deferred the same way: the id's existence anywhere
# in the project, and whether it lands in *this* rendered document, both
# depend on state that isn't complete until every item and page has been
# processed. Context is smuggled through as data attributes so the deferred
# warning can still be attributed to the line that wrote the reference.
FIG_REF_PENDING_RE = re.compile(
    r'<span class="fig-ref-pending" data-fig="([^"]*)" data-label="([^"]*)"'
    r' data-where-file="([^"]*)" data-where-line="([^"]*)" data-where-id="([^"]*)"></span>'
)


# ----------------------------------------------------------------------- validation


def _required_when_satisfied(item: Item, condition: dict[str, object]) -> bool:
    """All condition keys AND together; a key's own value(s) OR together.

    The reserved key "links" checks whether the item declares at least one
    target under any of the named links; every other key names a sibling field
    and matches against its current value. See
    docs/design/standard-library.md §2 and §11.
    """
    for key, raw_values in condition.items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        if key == "links":
            if not any(item.links.get(str(name)) for name in values):
                return False
        elif item.fields.get(key) not in values:
            return False
    return True


def _format_required_when(condition: dict[str, object]) -> str:
    clauses = []
    for key, raw_values in condition.items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        if key == "links":
            joined = " or ".join(repr(str(v)) for v in values)
            clauses.append(f"it has a link under {joined}")
        else:
            joined = " or ".join(repr(v) for v in values)
            clauses.append(f"{key} is {joined}")
    return " and ".join(clauses)


def _field_error(project: Project, item: Item, fname: str, message: str) -> None:
    """Finding 6: a `defaults:` block is merged into every item in its file
    unconditionally, regardless of whether the item overrode `type:` to
    something the value doesn't apply to (`status: active` from a file's
    `requirement` defaults, merged onto a `component` entry whose own status
    vocabulary is `candidate`/`selected`/`obsolete`). When the failing value
    is one `item` never wrote itself, say so and point at the `defaults:`
    block instead of reporting it identically to a value the item actually
    typed -- `defaults_line` is only ever unset when the file has no
    `defaults:` at all, which is also exactly when a field can't be
    inherited, so the two conditions can only ever agree.
    """
    if fname in item.inherited_fields and item.defaults_line is not None:
        project.error(
            f"{message} -- inherited from this file's defaults:, not set on "
            f"{item.id or 'this item'} itself; defaults: doesn't apply to "
            f"every value once an item overrides type:",
            file=item.source_file, line=item.defaults_line, item_id=item.id,
        )
    else:
        project.error(
            message, file=item.source_file, line=item.source_line, item_id=item.id,
        )


def validate_items(project: Project) -> None:
    for item in project.local_items:
        spec = project.types[item.type]

        for fname, fspec in spec.fields.items():
            value = item.fields.get(fname)
            effective_required = fspec.required or (
                fspec.required_when is not None
                and _required_when_satisfied(item, fspec.required_when)
            )
            if effective_required and (value is None or str(value).strip() == ""):
                if fspec.required_when is not None:
                    project.error(
                        f"{fname!r} is required when "
                        f"{_format_required_when(fspec.required_when)} "
                        f"(required_when: {fspec.required_when})",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                else:
                    project.error(
                        f"missing required field {fname!r}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                continue
            if value is None:
                continue
            if fspec.type == "enum" and fspec.choices and value not in fspec.choices:
                import difflib

                close = difflib.get_close_matches(str(value), fspec.choices, n=1, cutoff=0.5)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                _field_error(
                    project, item, fname,
                    f"{fname}: {value!r} is not one of {fspec.choices}.{hint}",
                )
            elif fspec.type == "limit":
                try:
                    calc.parse_limit(str(value))
                except calc.CalcError as exc:
                    _field_error(project, item, fname, f"{fname}: {exc}")
            elif fspec.type == "citations":
                if not isinstance(value, list):
                    _field_error(
                        project, item, fname,
                        f"{fname}: must be a list of citation entries",
                    )
                else:
                    for index, entry in enumerate(value):
                        if not isinstance(entry, dict) or not entry.get("url"):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}]: each citation needs a 'url'",
                            )


def lint_own_tags(project: Project) -> None:
    """Finding 11, sequenced after finding 9 (`refdes ls --tag`): warn on an
    item with no `tags:` of its own -- opt-in, following `boards.lint_tokens()`'s
    own precedent for an advisory lint, since `tags:` is optional by design
    (`field_sets.provenance`, no `required:`) and plenty of projects will
    reasonably not want the noise.

    A bare presence check (warn when `tags:` is unset) would fire on
    essentially nothing: `tags:` is almost always declared once in a file's
    `defaults:` block, so every item in that file inherits a non-empty list
    automatically, satisfying a presence check while changing nothing about
    findability. `item.inherited_fields` (finding 6) is what makes the real
    signal checkable at all -- an item whose `tags:` is entirely inherited
    is exactly as hard to find as one with none, since a file-level tag set
    is identical across every item in the file and just re-encodes which
    file/board the item is already in.
    """
    if not project.lint_own_tags:
        return
    for item in project.local_items:
        spec = project.types[item.type]
        if "tags" not in spec.fields:
            continue
        if "tags" in item.inherited_fields:
            project.warn(
                "tags: are entirely inherited from this file's defaults: -- "
                "no tags of its own, which makes it as hard to find later as "
                "having none; add at least one item-specific tag",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
        elif not item.fields.get("tags"):
            project.warn(
                "no tags: at all, which makes it harder to find later; add "
                "at least one",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )


def validate_former_ids(project: Project) -> None:
    """Populate `project.former_ids` and flag one the linker can never reach.

    `BARE_REF_RE` requires an id to end in `-<digits>` -- deliberately: prose
    is full of hyphen-free, underscore-joined, all-caps tokens (`MAX_RETRY_3`,
    `GPIO_12`) that would false-positive as references if bare-word matching
    were loosened to catch them. Rather than widen that regex and trade
    autolink precision for former-id recall, an old id shaped like that is
    still fully linkable -- just only explicitly, as `[[old_id]]` -- and this
    warns so the gap is visible instead of a silent no-op.
    """
    ids_mod.collect_former_ids(project)
    for old_id, owner_id in project.former_ids.items():
        if BARE_REF_RE.fullmatch(old_id):
            continue
        owner = project.items[owner_id]
        project.warn(
            f"former_ids: {old_id!r} does not match the bare-reference shape "
            f"(PREFIX-NNN) and will never autolink in prose -- reference it "
            f"explicitly as [[{old_id}]]",
            file=owner.source_file, line=owner.source_line, item_id=owner_id,
        )


def resolve_links(project: Project) -> None:
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of an undeclared type
            continue
        for link_name, targets in item.links.items():
            allowed = spec.links.get(link_name, [])
            for target_id in targets:
                target = project.items.get(target_id)
                if target is None:
                    project.error(
                        f"{link_name} points at {target_id!r}, which does not exist",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    continue
                if allowed and target.type not in allowed:
                    project.error(
                        f"{link_name} may point at {allowed}, but {target_id} is a "
                        f"{target.type}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    continue
                inverse = project.inverse_of.get(link_name, f"{link_name}_by")
                target.backlinks.setdefault(inverse, []).append(item.id)


# Preserved exactly for the name-based coverable/verifier fallback below -- the
# behavior every project had before `coverable:`/verifies-link detection existed.
_FALLBACK_COVERABLE_TYPES = ("requirement", "constraint")


def _verifier_type_names(project: Project) -> set[str]:
    """Which types can verify something, derived from `links:`, not a type name.

    A type declaring `verifies` on itself is the verifier (the standard's own
    convention: test.links.verifies: [...]). A type declaring `verified_by`
    naming its own verifier target types (the legacy convention: a requirement
    declaring `verified_by: [test]`) makes each named target type a verifier
    instead. Either spelling of the pair is recognized, so this needs no new
    flag -- every project's link declarations already carry the information
    (docs/design/standard-library.md §2).
    """
    names: set[str] = set()
    for tname, spec in project.types.items():
        for lname, targets in spec.links.items():
            if lname == "verifies":
                names.add(tname)
            elif lname == "verified_by":
                names.update(targets)
    return names


def _resolve_coverable(
    spec: ItemType, project: Project, warned: set[str]
) -> tuple[bool, bool]:
    """(is_coverable, via_fallback). Emits the one-time fallback warning only for
    the two names the fallback has ever recognized -- see the compatibility
    hazard writeup in docs/design/standard-library.md §2."""
    if spec.coverable is not None:
        return spec.coverable, False
    is_fallback_coverable = spec.name in _FALLBACK_COVERABLE_TYPES
    if is_fallback_coverable and spec.name not in warned:
        project.warn(
            f"types.{spec.name} does not declare 'coverable:'; falling back to "
            "name-based detection (requirement/constraint are coverable by "
            "convention). Add 'coverable: true' explicitly -- this fallback is "
            "removed in refdes 1.0."
        )
        warned.add(spec.name)
    return is_fallback_coverable, True


def _excluded_by_status(item: Item, spec: ItemType) -> bool:
    """True if this item's current status keeps it out of coverage.

    `coverable_statuses` set: inclusion list -- coverable only when status is in
    it. Unset: falls back to excluding `status == "retired"` if a status field
    exists, and excluding nothing otherwise -- the exact pre-existing behavior.
    """
    if spec.coverable_statuses is not None:
        return item.fields.get("status") not in spec.coverable_statuses
    if "status" in spec.fields:
        return item.fields.get("status") == "retired"
    return False


def compute_coverage(project: Project) -> None:
    """Distinct notions of done, which people routinely conflate.

    addressed  — somebody has worked on it and written it up in the design log
    claimed    — a decision or component says it meets it, but hasn't settled
                 (its status is not in the type's satisfying_statuses:, if declared)
    satisfied  — a settled decision or component claims to meet it
    verified   — a test proves it

    A requirement can be satisfied without being verified, and addressed without
    being satisfied. Collapsing those into one "done" flag is how open work goes
    missing.

    Two of these are individually uninteresting at scale, so they're counted
    rather than reported per item -- coverage.html carries the detail:

    - "nothing addresses, satisfies, or verifies this yet" -- every item starts
      here, so a project early in its life is mostly this.
    - "satisfied but not verified" -- routine noise when the project has not
      written a test plan yet, which is why it's suppressed entirely when no
      verifier items exist at all (the moment the first one is added, these
      become real findings again and start appearing).

    "Claimed but not verified" stays per item: it names an unsettled decision,
    which is the one class of coverage warning that is actually actionable.

    Participation is gated by `coverable:`/`coverable_statuses:` and which
    verifier links actually settle by `verifying_statuses:` -- schema-engine
    flags, not standard-specific plumbing (see model.ItemType and
    docs/design/standard-library.md §2). A type that never declares `coverable:`
    falls back to the old requirement/constraint-by-name convention, with a
    one-time warning; on that fallback path only, the requirement/constraint
    asymmetry in which types get the per-item warnings below is preserved
    exactly. Once a type explicitly declares `coverable: true`, it gets the
    same warnings as any other coverable type -- no further name restriction.
    """
    verifier_type_names = _verifier_type_names(project)
    has_verifiers = any(item.type in verifier_type_names for item in project.items.values())
    open_items: list[str] = []
    unverified_items: list[str] = []
    warned_fallback_types: set[str] = set()
    chains_by_claimer = blocked_mod.by_item(project)
    # One bucket per root blocker that accounts for >=1 claimed-but-unsettled
    # item with *exactly one* distinct root -- deliberately conservative,
    # see the aggregate line below.
    unsettled_by_root: dict[str, list[str]] = {}

    for item in project.local_items:
        spec = project.types[item.type]
        coverable, via_fallback = _resolve_coverable(spec, project, warned_fallback_types)
        if not coverable:
            continue
        if _excluded_by_status(item, spec):
            continue

        cov = Coverage(item_id=item.id)
        # Each edge may be declared from either end.
        cov.addressed_by = sorted(
            set(item.backlinks.get("addressed_by", []))
            | set(item.links.get("addresses", []))
        )

        satisfying_ids = sorted(
            set(item.backlinks.get("satisfied_by", []))
            | set(item.links.get("satisfies", []))
        )
        settled: list[str] = []
        claimed: list[str] = []
        for satisfier_id in satisfying_ids:
            satisfier = project.items.get(satisfier_id)
            satisfier_spec = project.types.get(satisfier.type) if satisfier else None
            allowed = satisfier_spec.satisfying_statuses if satisfier_spec else None
            # Unconfigured type: every link counts as settled, same as before
            # satisfying_statuses existed.
            if allowed is not None and satisfier.fields.get("status") not in allowed:
                claimed.append(satisfier_id)
            else:
                settled.append(satisfier_id)
        cov.satisfied_by = settled
        cov.claimed_by = claimed

        verifying_ids = sorted(
            set(item.backlinks.get("verified_by", []))
            | set(item.links.get("verified_by", []))
        )
        verified: list[str] = []
        for verifier_id in verifying_ids:
            verifier = project.items.get(verifier_id)
            verifier_spec = project.types.get(verifier.type) if verifier else None
            allowed = verifier_spec.verifying_statuses if verifier_spec else None
            # Unconfigured: every link counts, mirroring satisfying_statuses.
            if allowed is None or (verifier and verifier.fields.get("status") in allowed):
                verified.append(verifier_id)
        cov.verified_by = verified
        project.coverage[item.id] = cov

        # On the fallback path, only items literally named "requirement" get the
        # two warnings below, matching pre-existing behavior exactly (constraint
        # was always coverable but never got these). Once a type explicitly opts
        # in with `coverable: true`, it gets the same treatment as any other
        # coverable type -- an opt-in improvement, not a compatibility break.
        warn_eligible = not via_fallback or item.type == "requirement"

        if cov.stage == "open":
            open_items.append(item.id)
        elif cov.stage == "claimed" and warn_eligible:
            # Every claimer's own blocked_by chain(s), if it has any -- no
            # ambiguity to resolve here, unlike the aggregate line below:
            # this is naming this one item's actual claimer(s) and their
            # actual chain(s), whatever that is.
            notes = []
            claimer_roots: set[str] = set()
            for claimer_id in claimed:
                claimer_chains = chains_by_claimer.get(claimer_id)
                if not claimer_chains:
                    continue
                claimer_roots.update(c.root_id for c in claimer_chains)
                chain_text = "; ".join(
                    f"blocked_by {' <- '.join(c.path[1:])}"
                    + (f" ({c.root_status})" if c.root_status else "")
                    for c in claimer_chains
                )
                notes.append(f"claimed by {claimer_id}, which is {chain_text}")
            message = "claimed but not verified (no test links to it)"
            if notes:
                message += "; " + "; ".join(notes)
            project.warn(
                message, file=item.source_file, line=item.source_line, item_id=item.id,
            )
            # Deliberately conservative: only when every blocked claimer
            # traces to the *same single* root is this item unambiguous
            # enough to fold into the aggregate line -- no chain at all, or
            # several claimers tracing to different roots, is left out and
            # simply keeps the per-item warning above.
            if len(claimer_roots) == 1:
                unsettled_by_root.setdefault(next(iter(claimer_roots)), []).append(item.id)
        elif cov.stage == "satisfied" and warn_eligible and has_verifiers:
            unverified_items.append(item.id)

    if open_items:
        project.warn(
            f"{len(open_items)} item(s) with no coverage — see coverage.html"
        )
    if unverified_items:
        project.warn(
            f"{len(unverified_items)} requirement(s) satisfied but not verified "
            f"— see coverage.html"
        )
    for root_id, items in sorted(unsettled_by_root.items()):
        root = project.items.get(root_id)
        status = root.fields.get("status") if root else None
        status_text = f" is {status}" if status else " is unsettled"
        project.warn(
            f"{len(items)} requirement(s) unsettled because {root_id}{status_text} "
            f"— see coverage.html"
        )


# ----------------------------------------------------------------------------- calc


def run_calcs(project: Project) -> None:
    for item in project.local_items:
        env: dict[str, calc.Value] = {}
        for block in calc.extract_blocks(item.body):
            for outcome in calc.evaluate_block(block, env):
                line = CalcLine(
                    name=outcome.name,
                    expression=outcome.expression,
                    comment=outcome.comment,
                    annotation=outcome.annotation,
                )
                if outcome.warning:
                    project.warn(
                        f"calc {outcome.name}: {outcome.warning}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                if outcome.error:
                    line.error = outcome.error
                    project.error(
                        f"calc {outcome.name or outcome.expression!r}: {outcome.error}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                else:
                    line.result = calc.format_value(outcome.value, project.sigfigs)
                    line.bounds = calc.format_bounds(outcome.value, project.sigfigs)
                    item.calc_values[outcome.name] = line.result
                item.calcs.append(line)
        item._env = env  # retained for check evaluation


_CHECK_EMITTERS = {ERROR: Project.error, WARNING: Project.warn, INFO: Project.info}


def run_checks(project: Project) -> None:
    for item in project.local_items:
        spec = project.types.get(item.type)
        check_severity = spec.check_severity if spec else ERROR
        # A failing check on a candidate item (check_severity: info) is the
        # finding, not a defect -- everything else about a `checks:` entry
        # (malformed shape, an unresolved target, a target with no limit) is a
        # real authoring mistake regardless of type, so those stay project.error.
        emit_violation = _CHECK_EMITTERS.get(check_severity, Project.error)

        entries = item.fields.get("checks") or []
        if not isinstance(entries, list):
            project.error(
                "checks: must be a list of {value, against} entries",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            continue

        env = getattr(item, "_env", {})
        for entry in entries:
            if not isinstance(entry, dict) or "value" not in entry or "against" not in entry:
                project.error(
                    "each checks: entry needs 'value' and 'against'",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue

            name, target_id = str(entry["value"]), str(entry["against"])
            result = CheckResult(value_name=name, against=target_id)

            target = project.items.get(target_id)
            if target is None:
                result.detail = f"{target_id} does not exist"
                project.error(
                    f"check against {target_id!r}, which does not exist",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif name not in env:
                result.detail = f"no calc value named {name!r} in this item"
                project.error(
                    f"check refers to {name!r}, which no calc block defines",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif not target.fields.get("limit"):
                result.detail = f"{target_id} has no 'limit' to check against"
                project.error(
                    f"check against {target_id}, which declares no limit",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            else:
                try:
                    limit = calc.parse_limit(str(target.fields["limit"]))
                    ok, detail = limit.check(env[name], project.sigfigs)
                    result.ok, result.detail = ok, detail
                    result.actual = calc.format_value(env[name], project.sigfigs)
                    result.limit = limit.text
                    result.margin = limit.margin(env[name])
                    if not ok:
                        message = f"{name} violates {target_id}: {detail}"
                        if env[name].has_width and limit.kind in ("<=", "<", ">=", ">"):
                            message += f" (nominal {result.actual})"
                        emit_violation(
                            project, message,
                            file=item.source_file, line=item.source_line, item_id=item.id,
                            code=CHECK_VIOLATION,
                        )
                except calc.CalcError as exc:
                    result.detail = str(exc)
                    project.error(
                        f"check {name} against {target_id}: {exc}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )

            item.checks.append(result)


# ------------------------------------------------------------------- content hashing


def compute_hashes(project: Project) -> None:
    """Hash only the fields whose on_change mode is `invalidate`.

    This is what a link records at review time, so that a change to a `log` or
    `ignore` field (owner, tags) never marks downstream items suspect -- the two
    modes are indistinguishable here. `log` is reserved for a future history layer
    and currently behaves as `ignore`. Imported items keep the hash their own
    project computed.
    """
    for item in project.local_items:
        spec = project.types[item.type]
        payload: dict[str, object] = {"type": item.type}

        for fname in sorted(item.fields):
            mode = item.on_change_for(fname, spec, project.default_on_change)
            if mode == INVALIDATE:
                payload[fname] = item.fields[fname]

        for lname in sorted(item.links):
            payload[f"link:{lname}"] = sorted(item.links[lname])

        # Same precedence as fields: item field override > whole-item mode > schema.
        body_mode = item.on_change_for("body", spec, spec.body_on_change)
        if body_mode == INVALIDATE:
            normalized = re.sub(r"\s+", " ", item.body).strip()
            payload["body"] = normalized

        blob = json.dumps(payload, sort_keys=True, default=str)
        item.content_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# -------------------------------------------------------------------------- markdown


def _calc_table_html(lines: list[CalcLine]) -> str:
    rows = []
    for line in lines:
        name_cell = _esc(line.name)
        if line.annotation:
            name_cell += f'<span class="calc-annotation">: {_esc(line.annotation)}</span>'
        if line.error:
            rows.append(
                f'<tr class="calc-row calc-error">'
                f'<td class="calc-name">{name_cell}</td>'
                f'<td class="calc-expr">{_esc(line.expression)}</td>'
                f'<td class="calc-result" colspan="2">⚠ {_esc(line.error)}</td></tr>'
            )
            continue
        bounds = (
            f'<span class="calc-bounds">{_esc(line.bounds)}</span>' if line.bounds else ""
        )
        comment = (
            f'<td class="calc-comment">{_esc(line.comment)}</td>' if line.comment
            else "<td></td>"
        )
        rows.append(
            f'<tr class="calc-row">'
            f'<td class="calc-name">{name_cell}</td>'
            f'<td class="calc-expr">{_esc(line.expression)}</td>'
            f'<td class="calc-result">{_esc(line.result)} {bounds}</td>'
            f"{comment}</tr>"
        )
    return '<table class="calc">' + "".join(rows) + "</table>"


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _placeholder(index: int) -> str:
    """A token markdown will pass through untouched."""
    return f"xxrefdescalc{index}xx"


def _calc_line_count(block: str) -> int:
    """Rows a calc block contributes -- must match evaluate_block's line filtering."""
    return sum(
        1
        for raw in block.splitlines()
        if raw.strip() and not raw.strip().startswith("#")
    )


def _linkify(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Turn IDs into preview-bearing links, skipping code and pre regions."""

    def link(target_id: str, label: str | None, explicit: bool) -> str:
        if explicit and target_id.startswith("fig:"):
            # Deferred: existence (anywhere, and in this document) can't be
            # known until every item/page has run _apply_figure_attrs and the
            # whole document this reference lands in has been assembled --
            # see resolve_figures.
            fig_id = target_id[len("fig:") :]
            return (
                f'<span class="fig-ref-pending" data-fig="{_esc(fig_id)}" '
                f'data-label="{_esc(label) if label else ""}" '
                f'data-where-file="{_esc(where_file)}" '
                f'data-where-line="{where_line if where_line is not None else ""}" '
                f'data-where-id="{_esc(where_id) if where_id else ""}"></span>'
            )
        target = project.items.get(target_id)
        if target is None:
            former_owner_id = project.former_ids.get(target_id)
            if former_owner_id is not None:
                # Resolves, but never silently -- a reader following an old id
                # must see it landed somewhere else, not be quietly redirected
                # (finding 12).
                owner = project.items[former_owner_id]
                text = label or target_id
                return (
                    f'<a class="ref ref-former" href="{owner.slug}.html" '
                    f'data-ref="{owner.id}">{text}</a>'
                    f'<span class="ref-former-marker" '
                    f'title="{owner.id} was formerly {target_id}">(formerly {target_id})</span>'
                )
            if explicit:
                project.warn(
                    f"reference to {target_id!r}, which does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                return f'<span class="ref ref-missing" title="unknown item">{target_id}</span>'
            return target_id
        text = label or target_id
        return (
            f'<a class="ref" href="{target.slug}.html" data-ref="{target.id}">{text}</a>'
        )

    def bare(segment: str) -> str:
        return BARE_REF_RE.sub(lambda m: link(m.group(1), None, False), segment)

    def process(segment: str) -> str:
        # Bare-ref scanning must only ever see the literal gaps between
        # explicit refs, never an explicit ref's own replacement HTML --
        # that HTML embeds the target id again (as link text, and now also in
        # a fig-ref-pending marker's data attributes), and a second sweep
        # over the whole already-substituted string would match that
        # embedded id and linkify it a second time, nesting <a> inside <a>.
        chunks: list[str] = []
        last = 0
        for m in EXPLICIT_REF_RE.finditer(segment):
            chunks.append(bare(segment[last : m.start()]))
            chunks.append(link(m.group(1), m.group(2), True))
            last = m.end()
        chunks.append(bare(segment[last:]))
        return "".join(chunks)

    out: list[str] = []
    last = 0
    for match in PROTECTED_RE.finditer(html):
        out.append(process(html[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(process(html[last:]))
    return "".join(out)


def _hashed_leaf(rel: str, digest: str) -> str:
    """`figures/curve.png` + digest -> `figures/curve.<digest>.png` -- source
    directory structure preserved, hash and extension appended to the leaf
    filename only (docs/design/index-blocks.md §10)."""
    directory, _, leaf = rel.rpartition("/")
    base, dot, ext = leaf.rpartition(".")
    hashed_leaf = f"{base}.{digest}.{ext}" if dot else f"{leaf}.{digest}"
    return f"{directory}/{hashed_leaf}" if directory else hashed_leaf


def _process_images(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Resolve, validate, register, and rewrite local `<img src>` references.

    A local src is resolved relative to the source file's own directory -- the
    same base a browser would use to open the rendered page next to its markdown
    source. One that resolves is registered in `project.assets` (source path ->
    a content-hashed destination path, computed once per source and reused for
    every further reference to the same file) and rewritten to
    `assets/<hashed path>`, which is where `render_site` copies it. One that does
    not resolve is a build error, not a warning: unlike a dangling cross-reference,
    there is no sensible way to render a missing image, and now that a resolving
    src is actually made to work end to end, a broken one should stop the build.
    """

    def swap(match: re.Match) -> str:
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        if not src or _URL_SCHEME_RE.match(src):
            return match.group(0)
        full_path = os.path.normpath(
            os.path.join(project.root, os.path.dirname(where_file), src)
        )
        if not os.path.isfile(full_path):
            project.error(
                f"image src {src!r} does not exist",
                file=where_file, line=where_line, item_id=where_id,
            )
            return match.group(0)
        rel = os.path.relpath(full_path, project.root).replace("\\", "/")
        dest = project.assets.get(rel)
        if dest is None:
            # Read once, on the path already being opened to confirm it
            # resolves -- not a second I/O pass. Cached by source path, so
            # the same image referenced from many items/pages hashes once.
            with open(full_path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()[:16]
            dest = _hashed_leaf(rel, digest)
            project.assets[rel] = dest
        return f"{prefix}assets/{dest}{suffix}"

    return IMG_SRC_RE.sub(swap, html)


def _apply_figure_attrs(
    html: str,
    project: Project,
    where_file: str,
    where_line: int | None = None,
    where_id: str | None = None,
) -> str:
    """Wrap `![alt](src){width=60% caption="..."}` in a real `<figure>`, and
    register an explicit `id=` in the project-wide figure registry
    (docs/design/index-blocks.md §9).

    Only a paragraph containing nothing but one image immediately followed by a
    `{...}` suffix is touched -- matched the same way `_process_images` and
    `_linkify` scan rendered HTML with a regex rather than a markdown-it plugin.
    With no suffix the image passes through completely untouched. `alt` always
    stays on the `<img>`; `caption` falls back to it when not given. `id=` is
    optional exactly like `width=`/`caption=` already are -- a figure with no
    id renders exactly as it does today, numbered nowhere, referenced by
    nobody. A duplicate id is a build error naming both locations; the second
    figure keeps rendering, just without an id (which would be invalid HTML
    twice over) or a number.
    """

    def swap(match: re.Match) -> str:
        img_tag, attrs_text = match.group(1), match.group(2)
        # markdown-it escapes '"' in plain text the same as '&', '<', '>', so the
        # quoted-value delimiters in `attrs_text` are themselves `&quot;` by the
        # time this regex ever sees them. Unescape first to parse the attributes,
        # then re-escape whatever ends up in the caption before it goes back into
        # the page as HTML text.
        attrs = {
            m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
            for m in FIGURE_ATTR_RE.finditer(html_entities.unescape(attrs_text))
        }
        alt_match = IMG_ALT_RE.search(img_tag)
        alt = alt_match.group(1) if alt_match else ""  # already HTML-escaped text
        caption = _esc(attrs["caption"]) if "caption" in attrs else alt
        style = f' style="width: {_esc(attrs["width"])}"' if attrs.get("width") else ""

        id_attr = ""
        num_marker = ""
        fig_id = attrs.get("id")
        if fig_id:
            existing = project.figures.get(fig_id)
            if existing is not None:
                owner, owner_file, owner_line = existing
                loc = f"{owner_file}:{owner_line}" if owner_line is not None else owner_file
                project.error(
                    f"figure id {fig_id!r} is already used by {owner} ({loc}). "
                    f"Figure ids must be unique across the project.",
                    file=where_file, line=where_line, item_id=where_id,
                )
            else:
                project.figures[fig_id] = (where_id or where_file, where_file, where_line)
                id_attr = f' id="{_esc(fig_id)}"'
                num_marker = f'<span class="fig-num" data-fig="{_esc(fig_id)}"></span>'
                # Baked in now, not at resolution time: whether a caption
                # follows the number is static, only the number itself
                # depends on which document this figure ends up rendered in.
                if caption:
                    num_marker += " — "

        figcaption = f"<figcaption>{num_marker}{caption}</figcaption>" if (caption or num_marker) else ""
        return f'<figure class="md-figure"{id_attr}{style}>{img_tag}{figcaption}</figure>'

    return FIGURE_RE.sub(swap, html)


def assign_figure_numbers(bodies: list[str]) -> dict[str, int]:
    """Number every `{id="..."}` figure across `bodies`, in the order given.

    Each rendered document computes its own figure numbers, fresh, in its own
    reading order (docs/design/index-blocks.md §9) -- `bodies` is that
    document's own sequence of rendered item/page bodies, e.g. one item's
    `body_html` for `item.html.j2`, or every section's items in
    `_document_sections`' order for `document.html`.
    """
    numbers: dict[str, int] = {}
    for html in bodies:
        for match in FIG_NUM_MARKER_RE.finditer(html):
            fig_id = match.group(1)
            if fig_id not in numbers:
                numbers[fig_id] = len(numbers) + 1
    return numbers


def validate_figure_refs(project: Project) -> None:
    """Eagerly catch a `[[fig:id]]` reference to an id that doesn't exist
    ANYWHERE in the project -- the one class of figure-reference mistake
    that's knowable without ever assembling a rendered document, so it's
    checked once here, right after every item/page body has been rendered,
    rather than only inside `resolve_figures` (which only ever runs from
    `render_site`, so `refdes check` -- which never renders -- would
    otherwise never catch a dangling `[[fig:...]]` the way it already
    catches a dangling `[[ITEM-ID]]`).

    The complementary "exists, but not in this specific rendered document"
    check is inherently document-shaped (the same body can render into up to
    three different documents, each with its own answer) and stays in
    `resolve_figures`, which is why this only handles the anywhere-or-not
    question and never re-warns what `resolve_figures` goes on to check.
    """
    bodies = [item.body_html for item in project.local_items] + [
        page.body_html for page in project.pages
    ]
    for html in bodies:
        for match in FIG_REF_PENDING_RE.finditer(html):
            fig_id, _label_raw, where_file, where_line_raw, where_id = match.groups()
            if fig_id in project.figures:
                continue
            where_line = int(where_line_raw) if where_line_raw else None
            project.warn(
                f"reference to figure {fig_id!r}, which does not exist. "
                f'Check the figure\'s {{id="..."}} attribute.',
                file=where_file, line=where_line, item_id=where_id or None,
            )


def resolve_figures(html: str, project: Project, numbers: dict[str, int]) -> str:
    """Fill in figure-number markers and `[[fig:id]]` cross-references in one
    piece of already-rendered HTML, using `numbers` (this document's own id ->
    Figure N map, from `assign_figure_numbers` run over the same document).

    A reference to a figure id that doesn't exist anywhere has already been
    warned about by `validate_figure_refs` (run once, at build() time) --
    this only warns about the complementary, document-scoped case: the id is
    real, just not present in *this* rendered document.
    """

    def num_marker(match: re.Match) -> str:
        return f"Figure {numbers[match.group(1)]}"

    def ref(match: re.Match) -> str:
        fig_id, label_raw, where_file, where_line_raw, where_id = match.groups()
        label = html_entities.unescape(label_raw) if label_raw else None
        where_line = int(where_line_raw) if where_line_raw else None
        item_id = where_id or None
        if fig_id not in project.figures:
            return f'<span class="ref ref-missing" title="unknown figure">{label or fig_id}</span>'
        if fig_id not in numbers:
            owner, _owner_file, _owner_line = project.figures[fig_id]
            project.warn(
                f"reference to figure {fig_id!r}, which exists on {owner} but is "
                f"not rendered on this page — figure references only resolve "
                f"within the same rendered document.",
                file=where_file, line=where_line, item_id=item_id,
            )
            return f'<span class="ref ref-missing" title="unknown figure">{label or fig_id}</span>'
        text = label or f"Figure {numbers[fig_id]}"
        return f'<a class="ref fig-ref" href="#{fig_id}">{text}</a>'

    html = FIG_NUM_MARKER_RE.sub(num_marker, html)
    return FIG_REF_PENDING_RE.sub(ref, html)


def render_bodies(project: Project) -> None:
    # gfm-like adds tables and strikethrough, which a hardware document needs for
    # pin maps and BOM excerpts. linkify stays off: bare IDs are our own concern,
    # and raw HTML stays off so a document can never inject markup.
    md = MarkdownIt("gfm-like", {"html": False, "linkify": False})

    for item in project.local_items:
        # Substitute inline calc values before markdown sees the text.
        def replace_inline(match: re.Match) -> str:
            name = match.group(1)
            if name in item.calc_values:
                return f"`{item.calc_values[name]}`"
            project.warn(
                f"{{{{{name}}}}} does not name a calc value in this item",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            return match.group(0)

        source = INLINE_VALUE_RE.sub(replace_inline, item.body)

        # Swap calc blocks for placeholders, render, then inject the evaluated
        # tables. The placeholder has to be plain text -- an HTML comment would be
        # escaped, since we render markdown with html disabled on purpose.
        blocks = calc.extract_blocks(source)
        for index in range(len(blocks)):
            source = calc.CALC_BLOCK_RE.sub(
                f"\n{_placeholder(index)}\n", source, count=1
            )

        html = md.render(source)

        cursor = 0
        for index in range(len(blocks)):
            count = _calc_line_count(blocks[index])
            chunk = item.calcs[cursor : cursor + count]
            cursor += count
            table = _calc_table_html(chunk)
            token = _placeholder(index)
            if f"<p>{token}</p>" in html:
                html = html.replace(f"<p>{token}</p>", table)
            else:
                html = html.replace(token, table)

        html = _process_images(html, project, item.source_file, item.source_line, item.id)
        html = _apply_figure_attrs(html, project, item.source_file, item.source_line, item.id)
        item.body_html = _linkify(
            html, project, item.source_file, item.source_line, item.id
        )


def render_pages(project: Project) -> None:
    """Render narrative pages: markdown, generated blocks, item cross-references,
    page-to-page links."""
    md = MarkdownIt("gfm-like", {"html": False, "linkify": False})
    known = {page.slug for page in project.pages}

    for page in project.pages:
        # Generated blocks ({{index}}, {{cascade}}) extract from raw source
        # and placeholder-swap before md.render, then get their real HTML
        # back immediately after -- same two-step calc blocks already use.
        # This has to land before _linkify (next): an index/cascade table's
        # cells are item IDs, and injecting the table before _linkify runs
        # means _linkify's own pass over the whole page picks up every ID
        # for free, with the standard hover preview -- see blocks.py's
        # module docstring.
        source, block_htmls = blocks_mod.extract_blocks(project, page.body, page.source_file)
        html = md.render(source)
        for index, block_html in enumerate(block_htmls):
            token = blocks_mod.placeholder(index)
            if f"<p>{token}</p>" in html:
                html = html.replace(f"<p>{token}</p>", block_html)
            else:
                html = html.replace(token, block_html)

        html = _process_images(html, project, page.source_file)
        html = _apply_figure_attrs(html, project, page.source_file)
        html = _linkify(html, project, page.source_file)
        page.body_html = pages_mod.rewrite_page_links(html, known)
        pages_mod.add_heading_anchors(page)


# --------------------------------------------------------------------- static assets


def collect_static_assets(project: Project) -> None:
    """Register every file under a `site.assets:` directory, no reference needed.

    For a local file that is linked to (a PDF, a datasheet not managed as a
    citation) rather than embedded as an `<img>`, there is nothing in the
    rendered HTML to resolve automatically -- the author writes the `href`
    themselves, pointed at `assets/<path under the declared directory>`. This
    just makes sure the file is actually there to be linked to.

    Registered as an identity mapping (source path -> itself), never hashed --
    unlike `<img src>`, refdes doesn't own the `href` an author types by hand
    into a `site.assets:`-backed link, so hashing the destination would
    silently break it with no way for the tool to catch that at build time
    (docs/design/index-blocks.md §10's explicit scope line).
    """
    for rel_dir in project.asset_dirs:
        full_dir = os.path.join(project.root, rel_dir)
        if not os.path.isdir(full_dir):
            project.warn(f"site.assets entry {rel_dir!r} is not a directory", file="refdes.yaml")
            continue
        for dirpath, _dirnames, filenames in os.walk(full_dir):
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                rel = os.path.relpath(full_path, project.root).replace("\\", "/")
                project.assets[rel] = rel


# ------------------------------------------------------------------------ entry point


def build(
    project: Project,
    seal_write: bool = False,
    reseal: bool = False,
    accept_board_move: bool = False,
    require_citations: bool = False,
) -> Project:
    pages_mod.load_pages(project)
    collect_static_assets(project)
    calc.set_unit_aliases(project.unit_aliases)
    calc.set_preferred_units(project.preferred_units)
    imports.load_imports(project)
    workspaces_mod.resolve(project)
    boards_mod.resolve(project)
    pages_mod.validate_boards(project)
    pages_mod.validate_workspaces(project)
    validate_items(project)
    validate_former_ids(project)
    ids_mod.validate_prefixes(project)
    resolve_links(project)
    workspaces_mod.lint_cross_workspace_references(project)
    blocked_mod.resolve(project)
    run_calcs(project)
    run_checks(project)
    compute_hashes(project)
    seal.verify(project, write=seal_write, reseal=reseal)
    boards_mod.verify(project, write=seal_write, accept_move=accept_board_move)
    boards_mod.lint_tokens(project)
    lint_own_tags(project)
    compute_coverage(project)
    citations_mod.verify(project, require=require_citations)
    render_bodies(project)
    render_pages(project)
    validate_figure_refs(project)
    return project
