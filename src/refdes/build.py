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
from . import calc, dates, imports, seal
from . import chains as chains_mod
from . import citations as citations_mod
from . import ids as ids_mod
from . import keys as keys_mod
from . import nav as nav_mod
from . import pages as pages_mod
from . import workspaces as workspaces_mod
from .model import (
    CHECK_VIOLATION,
    ERROR,
    INFO,
    INVALIDATE,
    WARNING,
    CalcLine,
    CheckResult,
    Coverage,
    Item,
    ItemType,
    Project,
)

# Explicit reference: [[REQ-PWR-002]] or [[REQ-PWR-002|the input range]]. The
# ':' admits the "fig:" namespace (docs/design/index-blocks.md §9) -- item ids
# are allocated as PREFIX-BOARD-NNN and never contain one, so this only ever
# matches the new namespace on real projects, never an existing item id. The
# optional '#field' fragment (finding 19 Part A) links to one field's row on
# the target item's page; it is never inlined, and a composite `ID@key` target
# is not admitted here because those only ever appear in structured link
# fields, never in prose (docs/design/keys.md).
EXPLICIT_REF_RE = re.compile(
    r"\[\[\s*([A-Za-z0-9\-_:]+)(?:#([A-Za-z0-9_\-]+))?\s*"
    r"(?:\|\s*([^\]]+?)\s*)?\]\]"
)
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
# A declared citation `id:` (finding 19 Part B) -- the same character set
# EXPLICIT_REF_RE's own id group admits, so anything this rejects could never
# be addressed by `[[cite:id]]` in the first place. Unlike a figure's `id=`
# attribute, which is never format-checked and can end up silently
# unreferenceable, a citation id is rejected outright at declaration time
# instead of accepted and left permanently unreachable.
CITATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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

        if spec.body_required and not item.body.strip():
            project.warn(
                "body: is empty -- title: is an optional short label, not a "
                "substitute for the content itself. A warning, not an error, "
                "so a stub can exist while it's still being drafted.",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )

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
            elif fspec.type == "date":
                try:
                    dates.parse_date(value, project.date_format)
                except ValueError:
                    _field_error(
                        project,
                        item,
                        fname,
                        f"{fname}: {value!r} is not a valid date; expected {project.date_format}",
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
                            continue
                        cite_id = entry.get("id")
                        if not cite_id:
                            continue
                        cite_id = str(cite_id)
                        if not CITATION_ID_RE.match(cite_id):
                            _field_error(
                                project, item, fname,
                                f"{fname}[{index}].id: {cite_id!r} is not a valid "
                                f"citation id (letters, digits, '-', '_' only)",
                            )
                            continue
                        existing = project.citation_ids.get(cite_id)
                        if existing is not None:
                            owner, owner_file, owner_line = existing
                            loc = f"{owner_file}:{owner_line}" if owner_line is not None else owner_file
                            project.error(
                                f"citation id {cite_id!r} is already used by {owner} ({loc}). "
                                f"Citation ids must be unique across the project.",
                                file=item.source_file, line=item.source_line, item_id=item.id,
                            )
                        else:
                            project.citation_ids[cite_id] = (item.id, item.source_file, item.source_line)


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
        owner = project.item_by_id(owner_id)
        project.warn(
            f"former_ids: {old_id!r} does not match the bare-reference shape "
            f"(PREFIX-NNN) and will never autolink in prose -- reference it "
            f"explicitly as [[{old_id}]]",
            file=owner.source_file, line=owner.source_line, item_id=owner_id,
        )


def _key_index(project: Project) -> dict[str, Item]:
    """Every item that has a surrogate key (docs/design/keys.md), keyed by
    that key. Built fresh on every call rather than cached on Project: it's
    cheap (one dict comprehension over items already parsed into memory),
    and a cached copy would need its own invalidation story every time an
    item's key changes (a reparse after `keys.mint_missing()` writes new
    ones, in particular).

    keys.validate() has already reported every duplicate before this runs,
    so a collision cannot make the build succeed even though this downstream
    index necessarily retains only one of the colliding items.
    """
    return {item.key: item for item in project.items.values() if item.key}


def _is_bare_key_token(target: str) -> bool:
    """Whether ``target`` has key-token shape rather than display-ID shape.

    Display IDs are conventionally hyphenated. A separator-free,
    11-character token is a key spelling, even when Layer 1 later finds it
    corrupt (uppercase and excluded alphabet characters included).
    """
    return len(target) == keys_mod.KEY_LEN and "@" not in target and "-" not in target


def _is_well_formed_bare_key(target: str) -> bool:
    return _is_bare_key_token(target) and keys_mod.malformed_key_message(target) is None


def resolve_link_target(by_key: dict[str, Item], project: Project, target: str) -> Item | None:
    """Resolve one structured link's target string to the item it names.

    Composite form `DISPLAY-ID@key` (docs/design/keys.md §3): resolution
    uses only the key, the part after `@` -- the display half is
    tool-maintained (refreshed when the target renames) and never consulted
    for resolution, not even as a fallback when the key doesn't resolve.
    That is deliberate, not an oversight: falling back to the display text
    would resurrect exactly the ambiguity keys exist to remove (two items
    momentarily sharing a stale display id after a rename, say). A bare,
    well-formed key resolves directly by key. Any other bare token remains a
    display-ID lookup, preserving the authoring path for unfrozen links.

    No `former_ids:` fallback here: that is a prose-only mechanism
    (`validate_former_ids` / `_linkify`'s "(formerly X)" marker). A
    structured link (`satisfies:`, `refines:`, ...) must name a still-live
    id or key directly, same as always.

    Also used by compute_hashes (build.py's own _link_hash_token), so hashing
    stays correct regardless of whether a target is still a bare id or has
    already been expanded to a composite by links.expand_missing.
    """
    if "@" in target:
        _display, _, key = target.partition("@")
        return by_key.get(key)
    if _is_well_formed_bare_key(target):
        return by_key.get(target)
    return project.item_by_id(target)


def _unknown_key_message(pointer: str, target_id: str) -> str:
    """Layer-3 diagnostic for a composite or bare key with no live target.

    Shared, not duplicated, between structured links (`resolve_links`) and
    `checks: against:` (`run_checks`): both point at a target the same way,
    and `pointer` supplies only the verb phrase (for example, "refines
    points at" or "check against"). The remaining text deliberately never
    falls back to a display ID; for a composite its label may be stale, and
    for a bare key the key itself is the immutable identity.
    """
    label, separator, key = target_id.partition("@")
    if not separator:
        return (
            f"{pointer} key {target_id!r}, which no item declares. Either the "
            "target was deleted, or this reference predates it."
        )
    return (
        f"{pointer} key {key!r} (labelled {label}), which no item declares. "
        "The label may be stale; the key is what resolves. Either the target "
        "was deleted, or this reference predates it."
    )


def resolve_links(project: Project) -> None:
    by_key = _key_index(project)
    for item in project.items.values():
        spec = project.types.get(item.type)
        if spec is None:  # imported item of an undeclared type
            continue
        for link_name, targets in item.links.items():
            allowed = spec.links.get(link_name, [])
            for target_id in targets:
                bare_key = _is_bare_key_token(target_id)
                if "@" in target_id or bare_key:
                    label, _, key = target_id.partition("@")
                    if bare_key:
                        key = target_id
                    malformed = keys_mod.malformed_key_message(
                        key,
                        context=(
                            f" in {link_name} target (labelled {label})"
                            if "@" in target_id
                            else f" in {link_name} target"
                        ),
                    )
                    if malformed is not None:
                        project.error(
                            malformed,
                            file=item.source_file,
                            line=item.source_line,
                            item_id=item.id,
                        )
                        continue

                target = resolve_link_target(by_key, project, target_id)
                if target is None:
                    if "@" in target_id or bare_key:
                        message = _unknown_key_message(f"{link_name} points at", target_id)
                    else:
                        message = f"{link_name} points at {target_id!r}, which does not exist"
                    project.error(
                        message,
                        file=item.source_file,
                        line=item.source_line,
                        item_id=item.id,
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
                source_ref = item.id or item.key
                target_ref = target.id or target.key
                target.backlinks.setdefault(inverse, []).append(source_ref)
                item.resolved_links.setdefault(link_name, []).append(target_ref)


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


def _group_type_names(project: Project) -> set[str]:
    """Which types are groups, derived from the schema rather than a type name.

    A group is whatever some type's `part_of:` may point at -- in the bundled
    hardware@3 standard that is exactly `group` (docs/design/backlog.md
    finding 14). Deriving it keeps this generic the way `_verifier_type_names`
    already is, and means a project with no `part_of:` declared anywhere has no
    group types, so any `conforms_to:` target is an error rather than a hit.
    """
    names: set[str] = set()
    for spec in project.types.values():
        names.update(spec.links.get("part_of", []))
    return names


def validate_conforms_to(project: Project) -> None:
    """Every `conforms_to:` target must name an existing group item.

    A typo here would silently discharge a whole board's obligations -- the
    same silent-and-optimistic failure an unregistered `board:` is a hard error
    for (boards.resolve), so this matches that posture exactly: name the fix,
    and do not let the build pass. Runs after resolve_links(), which is what
    populates the `contains` backlinks the per-board coverage below reads.
    """
    if not project.boards:
        return
    group_types = _group_type_names(project)
    for bname, spec in sorted(project.boards.items()):
        for target in spec.conforms_to:
            item = project.item_by_id(target)
            if item is None:
                project.error(
                    f"boards.{bname} conforms_to {target!r}, which does not "
                    f"exist -- a group item must be declared before a board can "
                    f"conform to it",
                    file="refdes-project.yaml",
                )
            elif item.type not in group_types:
                project.error(
                    f"boards.{bname} conforms_to {target!r}, which is a "
                    f"{item.type}, not a group -- conforms_to names group items",
                    file="refdes-project.yaml",
                )


def _board_gate(project: Project, board: str | None):
    """Filter for the satisfiers/verifiers that count toward `board`.

    `board is None` is the ordinary per-item coverage: everything counts, exactly
    as before. Otherwise only items actually on that board count -- and an item
    with no board counts for *no* board, so a satisfier sitting outside the
    registry can never quietly discharge a per-board obligation (finding 24).
    """
    def keep(ref: str) -> bool:
        if board is None:
            return True
        other = project.item_by_ref(ref)
        return other is not None and other.board == board

    return keep

def _coverage_status(project: Project, entry: Item | None, chain_graph) -> object | None:
    """Status coverage tests use an entry's declaration, then its thread.

    This applies identically to `satisfying_statuses` and
    `verifying_statuses`: a status inherited from a file `defaults:` block
    is not the entry declaring it. For a thread entry the current thread
    value is used instead; an unmerged fork resolves to None and cannot
    settle either kind of coverage. A non-thread item keeps its established
    effective-default behavior, preserving projects without `follows:`.
    """
    if entry is None:
        return None
    if "status" in entry.fields and "status" not in entry.inherited_fields:
        return entry.fields["status"]
    if not chains_mod.is_threaded(project, entry, graph=chain_graph):
        return entry.fields.get("status")
    return chains_mod.resolve_current(project, entry, "status", graph=chain_graph)


def _coverage_for(
    item: Item, project: Project, board: str | None = None, chain_graph=None
) -> Coverage:
    """One item's Coverage, optionally restricted to satisfiers on `board`.

    Same rules either way -- the only difference is which linked items count.
    """
    keep = _board_gate(project, board)
    cov = Coverage(item_id=item.id)
    cov.addressed_by = sorted(
        i
        for i in set(item.backlinks.get("addressed_by", []))
        | set(item.resolved_links.get("addresses", []))
        if keep(i)
    )

    settled: list[str] = []
    claimed: list[str] = []
    for satisfier_id in sorted(
        i
        for i in set(item.backlinks.get("satisfied_by", []))
        | set(item.resolved_links.get("satisfies", []))
        if keep(i)
    ):
        satisfier = project.item_by_ref(satisfier_id)
        satisfier_spec = project.types.get(satisfier.type) if satisfier else None
        allowed = satisfier_spec.satisfying_statuses if satisfier_spec else None
        # Unconfigured type: every link counts as settled, same as before
        # satisfying_statuses existed.
        status = _coverage_status(project, satisfier, chain_graph)
        if allowed is not None and status not in allowed:
            claimed.append(satisfier_id)
        else:
            settled.append(satisfier_id)
    cov.satisfied_by = settled
    cov.claimed_by = claimed

    verified: list[str] = []
    for verifier_id in sorted(
        i
        for i in set(item.backlinks.get("verified_by", []))
        | set(item.resolved_links.get("verified_by", []))
        if keep(i)
    ):
        verifier = project.item_by_ref(verifier_id)
        verifier_spec = project.types.get(verifier.type) if verifier else None
        allowed = verifier_spec.verifying_statuses if verifier_spec else None
        # Unconfigured: every link counts, mirroring satisfying_statuses.
        status = _coverage_status(project, verifier, chain_graph)
        if allowed is None or status in allowed:
            verified.append(verifier_id)
    cov.verified_by = verified
    return cov


def compute_board_coverage(project: Project, chain_graph=None) -> None:
    """Per-(item, board) coverage for the members of each board's `conforms_to:` groups.

    A platform-wide contract -- "every board with an ARM MCU uses the standard
    debug header" -- is one requirement item, so per-item coverage reports it
    satisfied the moment *any* board complies (docs/design/backlog.md finding
    24). This computes the same four stages again, once per (item, board) pair,
    counting only that board's own satisfiers, and warns on any pair still short
    of `satisfied`.

    Ordinary per-item coverage is untouched: this writes `project.board_coverage`
    only, and a project with no `conforms_to:` gets an empty dict and no warnings
    -- byte-identical output to before this existed.
    """
    if not project.boards:
        return
    warned_fallback_types: set[str] = set()
    for bname, spec in sorted(project.boards.items()):
        # A board with no items of its own gets no report pages at all, so its
        # warning must not point at a coverage page that will never be written.
        # nav.scope_reports is render's own condition for the page set -- it
        # decides emptiness from the board's items alone, so asking it here
        # before citations have been verified is still the same answer, and
        # this cannot drift from what actually lands in _site/.
        has_coverage_page = bool(
            spec.conforms_to and nav_mod.scope_reports(project, board=bname)
        )
        for group_id in spec.conforms_to:
            group = project.item_by_id(group_id)
            if group is None:
                continue  # validate_conforms_to() already errored on this
            for member_id in sorted(group.backlinks.get("contains", [])):
                member = project.item_by_ref(member_id)
                if member is None:
                    continue
                member_spec = project.types.get(member.type)
                if member_spec is None:
                    continue
                coverable, _via_fallback = _resolve_coverable(
                    member_spec, project, warned_fallback_types
                )
                if not coverable or _excluded_by_status(member, member_spec):
                    continue
                cov = _coverage_for(member, project, board=bname, chain_graph=chain_graph)
                project.board_coverage[(member.id, bname)] = cov
                if cov.stage in ("satisfied", "verified"):
                    continue
                pointer = f" — see coverage-{bname}.html" if has_coverage_page else ""
                project.warn(
                    f"{member.id} is not satisfied on board {bname!r} "
                    f"(board conforms to {group_id}) -- its "
                    f"{cov.stage} stage counts only {bname}'s own items{pointer}",
                    file=member.source_file,
                    line=member.source_line,
                    item_id=member.id,
                )


def compute_coverage(project: Project, chain_graph=None) -> None:
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

        # Each edge may be declared from either end. resolved_links, not raw
        # links: the raw form can hold `DISPLAY@key` composite text, while the
        # derived form holds a display id or surrogate key reference that
        # `_coverage_for()` resolves through `Project.item_by_ref()`.
        cov = _coverage_for(item, project, chain_graph=chain_graph)
        claimed = cov.claimed_by
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
        root = project.item_by_id(root_id)
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
        # name -> line first assigned, threaded across every block of this item
        # exactly like `env` -- what lets evaluate_block catch a name reused in
        # a later block, not just within one block.
        origins: dict[str, int | None] = {}
        for block, offset in calc.extract_blocks_with_lines(item.body):
            start_line = item.body_line + offset if item.body_line is not None else None
            for outcome in calc.evaluate_block(block, env, start_line=start_line, origins=origins):
                line = CalcLine(
                    name=outcome.name,
                    expression=outcome.expression,
                    comment=outcome.comment,
                    annotation=outcome.annotation,
                    line=outcome.line,
                )
                diag_line = outcome.line if outcome.line is not None else item.source_line
                if outcome.warning:
                    project.warn(
                        f"calc {outcome.name}: {outcome.warning}",
                        file=item.source_file, line=diag_line, item_id=item.id,
                    )
                if outcome.error:
                    line.error = outcome.error
                    project.error(
                        f"calc {outcome.name or outcome.expression!r}: {outcome.error}",
                        file=item.source_file, line=diag_line, item_id=item.id,
                    )
                else:
                    line.result = calc.format_value(outcome.value, project.sigfigs)
                    line.bounds = calc.format_bounds(outcome.value, project.sigfigs)
                    item.calc_values[outcome.name] = line.result
                item.calcs.append(line)
        item._env = env  # retained for check evaluation


_CHECK_EMITTERS = {ERROR: Project.error, WARNING: Project.warn, INFO: Project.info}


def run_checks(project: Project) -> None:
    by_key = _key_index(project)
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

            # `against:` accepts a bare display id or a `DISPLAY-ID@key`
            # composite, resolved exactly as a structured link target is
            # (docs/design/keys.md §3) -- reusing resolve_link_target and the
            # same Layer 1/3 diagnostics rather than re-implementing either.
            if "@" in target_id:
                label, _, key = target_id.partition("@")
                malformed = keys_mod.malformed_key_message(
                    key, context=f" in check against target (labelled {label})",
                )
                if malformed is not None:
                    project.error(
                        malformed,
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )
                    item.checks.append(CheckResult(value_name=name, against=target_id))
                    continue

            target = resolve_link_target(by_key, project, target_id)
            # Diagnostics and rendering always show the target's current
            # display id, never the raw composite text (docs/design/keys.md
            # §3) -- a rename refreshes the stored label, not the result of
            # a single build's resolution.
            display_against = target.id if target is not None else target_id
            result = CheckResult(value_name=name, against=display_against)

            if target is None:
                if "@" in target_id:
                    result.detail = f"key {target_id.partition('@')[2]!r} does not resolve"
                    message = _unknown_key_message("check against", target_id)
                else:
                    result.detail = f"{target_id} does not exist"
                    message = f"check against {target_id!r}, which does not exist"
                project.error(
                    message,
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif name not in env:
                result.detail = f"no calc value named {name!r} in this item"
                project.error(
                    f"check refers to {name!r}, which no calc block defines",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            elif not target.fields.get("limit"):
                result.detail = f"{display_against} has no 'limit' to check against"
                project.error(
                    f"check against {display_against}, which declares no limit",
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
                        message = f"{name} violates {display_against}: {detail}"
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
                        f"check {name} against {display_against}: {exc}",
                        file=item.source_file, line=item.source_line, item_id=item.id,
                    )

            item.checks.append(result)


# ------------------------------------------------------------------- content hashing

# Bumped whenever what compute_hashes() feeds into the hash changes in a way
# that would churn every existing hash for a reason unrelated to content.
# Two bumps so far, both docs/design/keys.md §5:
#   2 -- link targets switched from display-id text to resolved keys.
#   3 (2026-09-14) -- `checks: against:` entries that resolve to a keyed
#      item are likewise reduced to that key; an unresolved or keyless
#      target keeps its raw text, same as a link target does.
# Recorded per baseline entry (lifecycle.py) so a partially-migrated baseline
# stays precisely describable; consulted by the migration in
# lifecycle.py/seal.py/keys.py, never by an ordinary build.
HASH_FORMAT = 3


def _hash_payload(
    item: Item,
    spec: ItemType,
    project: Project,
    link_values,
    checks_values=None,
) -> dict[str, object]:
    """Everything compute_hashes() and hash_for_format() have in common: which
    fields/body enter the hash, and under what normalization. The two things
    that differ between hash-format definitions are how a link's *targets*
    turn into hashable values (`link_values`, called once per link name with
    that link's raw target list) and, from format 3 on, how a `checks:`
    entry's `against:` does (`checks_values`, called once with the raw
    `checks:` list; ``None`` leaves `checks:` hashed verbatim, as every
    format before 3 did) -- everything else here is shared, so the hash
    definitions can never drift apart from each other by accident.
    """
    payload: dict[str, object] = {"type": item.type}

    for fname in sorted(item.fields):
        mode = item.on_change_for(fname, spec, project.default_on_change)
        if mode != INVALIDATE:
            continue
        if fname == "checks" and checks_values is not None:
            payload[fname] = checks_values(item.fields[fname])
        else:
            payload[fname] = item.fields[fname]

    for lname in sorted(item.links):
        payload[f"link:{lname}"] = link_values(item.links[lname])

    # Same precedence as fields: item field override > whole-item mode > schema.
    body_mode = item.on_change_for("body", spec, spec.body_on_change)
    if body_mode == INVALIDATE:
        normalized = re.sub(r"\s+", " ", item.body).strip()
        payload["body"] = normalized

    return payload


def _hash_blob(payload: dict[str, object]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def calc_hash_for(item: Item) -> str | None:
    """A hash of just item's ```calc block(s) -- the second, narrower probe
    docs/design/stale-arithmetic-signal.md needs alongside content_hash, so
    lifecycle.diff_against can tell "the calc block changed" apart from "the
    item changed" without storing the block's actual text anywhere.

    None (not a hash of an empty payload) when the item has no calc block at
    all -- most items -- so lifecycle._items_map can omit the baseline field
    entirely rather than recording a hash that can never mean anything.

    Normalized the same way _hash_payload normalizes body text (collapse
    whitespace, strip), so reflowing a calc block's comments or indentation
    doesn't register as the arithmetic having changed. Deliberately reads
    item.body directly rather than item.calcs/calc_values: this hashes the
    block's *source* -- the expressions themselves -- not its evaluated
    results, which is what "the arithmetic" means for this signal. A result
    changing because an upstream value moved, with this item's own block
    untouched, is a different question this function doesn't answer.
    """
    blocks = calc.extract_blocks(item.body)
    if not blocks:
        return None
    normalized = [re.sub(r"\s+", " ", block).strip() for block in blocks]
    return _hash_blob({"calc_blocks": normalized})


def _link_hash_token(by_key: dict[str, Item], project: Project, target: str) -> str:
    """The value one link target contributes to its owner's content hash
    (docs/design/keys.md §5). Three cases, deliberately distinct so none of
    them can ever collide with each other or with a real key:

    - Resolves, and the target has a key: the key itself. This is the whole
      point -- renaming the target's display id changes nothing here, so
      renaming it changes nothing about *this* item's hash either.
    - Resolves, but the target has no key yet (§2: a keyless item stays
      fully usable, it just isn't durably referenced yet): a sentinel built
      from the target's *current* id, tagged so it can never be mistaken for
      a real key (no real key contains "!" or ":"). This is deliberately
      NOT rename-stable -- that instability is correct, not a bug: a link
      can't be rename-immune to a target that has no immutable identity to
      pin to yet. `refdes check`'s existing "N item(s) have no key yet" info
      line is what surfaces this state; it doesn't need a second diagnostic
      raised from inside hashing.
    - Doesn't resolve at all: a different tagged sentinel, built from the
      raw target text. `resolve_links()` already reports this exact case as
      a build error elsewhere in the same build (it runs first, see
      build()) -- this only needs to be deterministic and distinct from the
      other two cases, not to raise a second diagnostic for the same fault.
    """
    item = resolve_link_target(by_key, project, target)
    if item is None:
        return f"!unresolved:{target}"
    if item.key:
        return item.key
    return f"!nokey:{item.id}"


def _checks_display_only(entries) -> object:
    """The value `checks:` contributes to its owner's content hash under
    HASH_FORMAT 1 and 2 (before `against:` reduced to a resolved key):
    each entry's `against:` reduced to its display half only (everything
    before '@'), mirroring the format-1 link reconstruction
    (`t.split('@', 1)[0]` in hash_payload_builder).

    Before HASH_FORMAT 3, `checks:` composites did not exist -- `against:`
    was always bare, so a format-1 or format-2 hash was always computed
    from bare text. `links.expand_missing_checks` (docs/design/keys.md §3)
    can since have rewritten that same text to `DISPLAY@key` on disk, with
    no content change at all. Reconstructing formats 1/2 from *that* text
    verbatim would hash a string that never existed when those formats were
    actually in force, making an untouched item look edited. Stripping back
    to the display half undoes exactly that syntax upgrade, the same way
    the link path already does for format 1.
    """
    if not isinstance(entries, list):
        return entries
    reduced = []
    for entry in entries:
        if not isinstance(entry, dict) or "against" not in entry:
            reduced.append(entry)
            continue
        new_entry = dict(entry)
        new_entry["against"] = str(entry["against"]).split("@", 1)[0]
        reduced.append(new_entry)
    return reduced


def _checks_hash_value(by_key: dict[str, Item], project: Project, entries) -> object:
    """The value `checks:` contributes to its owner's content hash under
    HASH_FORMAT 3 (docs/design/keys.md §5, decided 2026-09-14): each entry's
    `against:` reduced to the target's resolved key, exactly as a link
    target is (_link_hash_token) -- renaming the checked-against item's
    display id then changes nothing about the checking item's hash.

    An entry that isn't a well-formed {value, against} mapping is left
    exactly as parsed -- run_checks() reports its own diagnostic for that
    shape and this only needs to not crash on it. A target that does not
    resolve, or resolves to a keyless item, keeps its *raw* `against:` text
    (the `!unresolved:`/`!nokey:` sentinels are how _link_hash_token signals
    those cases, and neither is stable across an edit -- unlike a real key,
    a bare id or a stale composite must still be able to invalidate).
    """
    if not isinstance(entries, list):
        return entries
    reduced = []
    for entry in entries:
        if not isinstance(entry, dict) or "against" not in entry:
            reduced.append(entry)
            continue
        token = _link_hash_token(by_key, project, str(entry["against"]))
        new_entry = dict(entry)
        if not token.startswith("!"):
            new_entry["against"] = token
        reduced.append(new_entry)
    return reduced


def compute_hashes(project: Project) -> None:
    """Hash only the fields whose on_change mode is `invalidate`.

    This is what a link records at review time, so that a change to a `log` or
    `ignore` field (owner, tags) never marks downstream items suspect -- the two
    modes are indistinguishable here. `log` is reserved for a future history layer
    and currently behaves as `ignore`. Imported items keep the hash their own
    project computed.

    Link targets, and (from HASH_FORMAT 3) `checks: against:` targets that
    resolve to a keyed item, are hashed as their *resolved keys*
    (docs/design/keys.md §5), not as composite text and not as the display
    id -- see _link_hash_token for the three cases and why each is safe.
    This is the change §5 calls load-bearing: renaming a target's display id
    no longer touches the hash of anything that links to it or checks
    against it, whether the on-disk reference is still bare or has already
    been expanded to a `DISPLAY@key` composite.

    Two things stay deliberately absent from the payload, same as before
    keys existed: the display id (unchanged -- it was never hashed), and
    the item's *own* key. Hashing an item's own key would mean minting one
    -- an identity-only event with no content behind it -- rewrites that
    item's hash for no content reason, and the first time every item in a
    project adopts a key at once, that would be every item's hash in the
    project. Identity is what a hash's key-lookups point at from other
    items; it is not itself content to be hashed.
    """
    payload_for = hash_payload_builder(project, HASH_FORMAT)
    for item in project.local_items:
        spec = project.types[item.type]
        item.content_hash = _hash_blob(payload_for(item, spec))


def hash_payload_builder(project: Project, hash_format: int):
    """A ``(item, spec) -> payload`` closure computing _hash_payload() under
    ``hash_format``'s definition, reused by compute_hashes() (current
    format) and hash_for_format() (any earlier one) so the two can never
    define "current" and "historical" hashing differently by accident.

    Format 1 (pre-keys): link targets hashed as bare display-id text,
    `checks: against:` hashed as its display half only (composites did not
    exist yet for checks: at this format, so this undoes any expansion
    links.expand_missing_checks has since done to the live source --
    _checks_display_only). Format 2 (docs/design/keys.md §5): link targets
    hashed as resolved keys, `checks: against:` still display-half-only for
    the same reason -- `against:` composites didn't exist under format 2
    either. Format 3 (§5, 2026-09-14): format 2, plus `checks: against:`
    entries reduced to a resolved key the same way a link target is
    (_checks_hash_value).
    """
    if hash_format <= 1:
        return lambda item, spec: _hash_payload(
            item, spec, project,
            link_values=lambda targets: sorted(t.split("@", 1)[0] for t in targets),
            checks_values=_checks_display_only,
        )
    by_key = _key_index(project)
    checks_values = (
        (lambda entries: _checks_hash_value(by_key, project, entries))
        if hash_format >= 3 else _checks_display_only
    )
    return lambda item, spec: _hash_payload(
        item, spec, project,
        link_values=lambda targets: sorted(
            _link_hash_token(by_key, project, t) for t in targets
        ),
        checks_values=checks_values,
    )


def hash_for_format(item: Item, project: Project, hash_format: int) -> str:
    """The content hash this item would have under hash-format
    ``hash_format``, recomputed from its *current* parsed state.

    Deliberately not "whatever the target string looks like right now": if
    links.expand_missing has already rewritten a target to a `DISPLAY@key`
    composite, format 1's reconstruction only uses the display half
    (everything before '@'), because that is what the *original*,
    pre-adoption hash was computed from. Using the live composite text here
    would make an item that has not actually changed look changed, purely
    because its own link syntax was upgraded -- exactly the false positive
    the hash-format migration exists to avoid. `checks: against:` needs the
    identical treatment under formats 1 *and* 2 (_checks_display_only):
    `against:` composites did not exist at either format, so
    links.expand_missing_checks rewriting a bare target to a composite on
    the live source must not change either reconstruction either. Only
    format 3 reduces a resolving `against:` to its key instead of stripping
    it (_checks_hash_value); an unresolved or keyless target still keeps
    its raw text there too.

    Used only by the hash-format migration (lifecycle.migrate_hash_format,
    seal._matches_sealed_hash's carry-forward comparison, and
    keys.plan_surrogate_storage/`refdes keys adopt`, all through
    keys.hash_in_format, the one shared caller) to decide whether a stored
    old-format hash still matches current content. Never called during an
    ordinary build.
    """
    spec = project.types[item.type]
    payload = hash_payload_builder(project, hash_format)(item, spec)
    return _hash_blob(payload)


def legacy_hash_for(item: Item, project: Project) -> str:
    """hash_for_format(item, project, 1) -- kept as its own name because it
    predates hash_for_format and is still the common case callers reach for
    when they mean specifically "the pre-keys hash"."""
    return hash_for_format(item, project, 1)


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
        .replace("'", "&#39;")
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

    def field_anchor(item: Item, field: str | None) -> str | None:
        """`#field` checked against the target's own type, as an href suffix.

        None means the type does not declare the field -- reported, never
        swallowed, and the caller must not emit an anchor for it. A field that
        is declared but empty on this item still resolves: item.html.j2 keeps
        an anchor for every declared field, rendered or not.
        """
        if field is None:
            return ""
        spec = project.types.get(item.type)
        if spec is not None and field in spec.fields:
            return f"#field-{field}"
        project.warn(
            f"reference to {item.id!r} names field {field!r}, which type "
            f"{item.type!r} does not declare",
            file=where_file, line=where_line, item_id=where_id,
        )
        return None

    def link(
        target_id: str,
        label: str | None,
        explicit: bool,
        field: str | None = None,
    ) -> str:
        if explicit and field is not None and target_id.startswith("fig:"):
            # Figures are addressed by their own id, not by field; saying so
            # beats silently dropping the fragment.
            project.warn(
                f"reference to {target_id!r} has a #{field} fragment, which "
                "figure references do not have",
                file=where_file, line=where_line, item_id=where_id,
            )
            field = None
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
        if explicit and field is not None and target_id.startswith("cite:"):
            # Citations are addressed by their own id, not by field, exactly
            # like figures.
            project.warn(
                f"reference to {target_id!r} has a #{field} fragment, which "
                "citation references do not have",
                file=where_file, line=where_line, item_id=where_id,
            )
            field = None
        if explicit and target_id.startswith("cite:"):
            # Not deferred, unlike fig: -- a citation belongs to exactly one
            # item and always links to a row on that item's own page, never
            # renumbered or reused across documents, so its existence and its
            # href are both fully known from project.citation_ids the moment
            # every item has been parsed and validated, well before any body
            # renders.
            cite_id = target_id[len("cite:") :]
            entry = project.citation_ids.get(cite_id)
            if entry is None:
                project.warn(
                    f"reference to citation {cite_id!r}, which does not exist",
                    file=where_file, line=where_line, item_id=where_id,
                )
                return f'<span class="ref ref-missing" title="unknown citation">{label or cite_id}</span>'
            owner_id, _owner_file, _owner_line = entry
            owner = project.item_by_id(owner_id)
            text = label or cite_id
            return (
                f'<a class="ref cite-ref" href="{owner.slug}.html#cite-{_esc(cite_id)}">{text}</a>'
            )
        target = project.item_by_id(target_id)
        if target is None:
            former_owner_id = project.former_ids.get(target_id)
            if former_owner_id is not None:
                # Resolves, but never silently -- a reader following an old id
                # must see it landed somewhere else, not be quietly redirected
                # (finding 12).
                owner = project.item_by_id(former_owner_id)
                anchor = field_anchor(owner, field) or ""
                text = label or target_id
                return (
                    f'<a class="ref ref-former" href="{owner.slug}.html{anchor}" '
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
        anchor = field_anchor(target, field)
        if anchor is None:
            return (
                f'<span class="ref ref-missing" title="unknown field">'
                f"{label or f'{target_id}#{field}'}"
                f"</span>"
            )
        text = label or (f"{target_id}#{field}" if field else target_id)
        return (
            f'<a class="ref" href="{target.slug}.html{anchor}" data-ref="{target.id}">{text}</a>'
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
            chunks.append(link(m.group(1), m.group(3), True, m.group(2)))
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
            project.warn(f"site.assets entry {rel_dir!r} is not a directory", file="refdes-project.yaml")
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
    keys_mod.validate(project)
    resolve_links(project)
    chain_graph = chains_mod.build_graph(project)
    chains_mod.resolve(project, graph=chain_graph)
    validate_conforms_to(project)
    workspaces_mod.lint_cross_workspace_references(project)
    blocked_mod.resolve(project)
    run_calcs(project)
    run_checks(project)
    compute_hashes(project)
    seal.verify(project, write=seal_write, reseal=reseal)
    boards_mod.verify(project, write=seal_write, accept_move=accept_board_move)
    boards_mod.lint_tokens(project)
    lint_own_tags(project)
    compute_coverage(project, chain_graph=chain_graph)
    compute_board_coverage(project, chain_graph=chain_graph)
    citations_mod.verify(project, require=require_citations)
    render_bodies(project)
    render_pages(project)
    validate_figure_refs(project)
    return project
