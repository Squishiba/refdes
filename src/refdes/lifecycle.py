"""Baselines: `refdes revision <name>` and `refdes release <name>`.

Three states, two commands, no flags on either (docs/design/lifecycle.md).
**draft** is the state a project is in when nothing has been stamped -- not a
command, nothing to run; `check`/`build` already tolerate it, unchanged.
`revision` cuts an internal checkpoint unconditionally (modulo the error
floor). `release` runs the full readiness gate and stamps only if it passes;
running it when you're not ready *is* the check, which is why there is no
`--dry-run`.

This is assembly, not new machinery: every value a baseline records --
`item.content_hash`, `item.type`, `item.title`, `project.coverage`,
`project.board_moves`, `item.citations`, `item.checks` -- already exists by
the time `build.build()` returns. Deliberately not the git-history layer: with
the shipped default (`baseline_identity: os_user`), nothing here ever invokes
git, reads `.git/config`, or touches the object database.
"""

from __future__ import annotations

import getpass
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import yaml

from . import build as build_mod
from .model import INFO, RELEASE_GATE_DEFAULTS, Item, Project, SchemaError

BASELINES_DIR = ".refdes/baselines"

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_HEADER = (
    "# Refdes baseline. Written once by `refdes revision <name>` or\n"
    "# `refdes release <name>` and never modified afterward -- a second stamp\n"
    "# of this name with different content is a build error. See\n"
    "# docs/lifecycle.md.\n"
)


# --------------------------------------------------------------------- naming


def validate_name(name: str) -> None:
    """A baseline name becomes `.refdes/baselines/<name>.yaml` -- ordinary
    input hygiene, the same posture an item id or board name gets: safe
    characters only, nothing that could escape the baselines directory."""
    if not name or name in (".", "..") or not _NAME_RE.match(name):
        raise SchemaError(
            f"{name!r} is not a valid revision/release name -- use letters, "
            "digits, '-', '_', and '.' only"
        )


def baselines_dir(project: Project) -> str:
    return os.path.join(project.root, BASELINES_DIR)


def baseline_path(project: Project, name: str) -> str:
    return os.path.join(baselines_dir(project), f"{name}.yaml")


# ------------------------------------------------------------------ artifact


@dataclass
class Baseline:
    name: str
    kind: str
    stamped_at: str
    stamped_by: str
    refdes_version: str
    # Per item: hash, type, title, hash_format (see _items_map) -- plus,
    # exceptionally, `verdict` and `calc_hash` when they apply.
    #
    # docs/design/lifecycle.md §3 says a baseline diff is item-scoped and
    # deliberately does not store old field values, to avoid the new
    # machinery general field-level diffing would need. `verdict` (a copy of
    # the item's own `status` value, stored the same way `title` already is)
    # and `calc_hash` (a hash of the item's ```calc block source, alongside
    # the existing whole-item `hash`) are a narrow, deliberate exception to
    # that, not a reversal of it -- see docs/design/stale-arithmetic-signal.md
    # and lifecycle.md §3's own note on this. They exist for exactly one
    # purpose (lifecycle.diff_against's stale_arithmetic list: did the
    # verdict move while the arithmetic didn't) and reconstruct nothing else
    # about an item's prior state -- unlike general field-level diffing, there
    # is no way to ask this baseline what any *other* field used to be.
    items: dict[str, dict] = field(default_factory=dict)
    gate: dict[str, str] | None = None
    # {base, version} the project was pinned to when this baseline was
    # stamped -- distinct from refdes_version (the tool, not the vocabulary).
    # None for a baseline stamped under `standard: none`, or one written
    # before this field existed: revise.py's carry-forward refuses to touch
    # such a baseline's hashes rather than assume it started at whatever the
    # project's *current* pin happens to be, which could simply be wrong.
    standard: dict[str, object] | None = None


def _load_baseline_file(path: str) -> Baseline:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    gate = data.get("gate")
    standard = data.get("standard")
    return Baseline(
        name=str(data.get("name", "")),
        kind=str(data.get("kind", "")),
        stamped_at=str(data.get("stamped_at", "")),
        stamped_by=str(data.get("stamped_by", "")),
        refdes_version=str(data.get("refdes_version", "")),
        items={k: dict(v) for k, v in (data.get("items") or {}).items()},
        gate=dict(gate) if gate is not None else None,
        standard=dict(standard) if isinstance(standard, dict) else None,
    )


def load_baseline(project: Project, name: str) -> Baseline | None:
    path = baseline_path(project, name)
    if not os.path.isfile(path):
        return None
    return _load_baseline_file(path)


def list_baselines(project: Project) -> list[Baseline]:
    """Every stamped baseline, in no particular order. `latest()` picks the
    one that matters -- there is no separate "latest" pointer file to
    maintain (docs/design/lifecycle.md §3): deleting a baseline self-heals
    on the next call, since this is a plain directory scan."""
    d = baselines_dir(project)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".yaml"):
            out.append(_load_baseline_file(os.path.join(d, name)))
    return out


def latest(baselines: list[Baseline], kind: str | None = None) -> Baseline | None:
    """Most recently stamped baseline, of `kind` if given (else either kind)."""
    candidates = baselines if kind is None else [b for b in baselines if b.kind == kind]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.stamped_at)


def _save_baseline_file(project: Project, data: dict) -> str:
    """Two dump passes, not one: `default_flow_style=None` (PyYAML's
    per-node heuristic) would flow-style *both* `gate:` and each item entry,
    which makes `gate:` -- one rule per line is what's actually worth
    git-diffing -- collapse into a wrapped blob. So the head (kind through
    gate) is dumped block-style, and each item entry is dumped individually
    flow-style (still through `yaml.safe_dump`, so a title with a colon or
    quote in it is escaped correctly, not hand-formatted) -- the shape
    docs/design/lifecycle.md §2 shows.
    """
    path = baseline_path(project, data["name"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    items = data["items"]
    head = {k: v for k, v in data.items() if k != "items"}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_HEADER)
        fh.write(yaml.safe_dump(head, sort_keys=False, default_flow_style=False))
        if not items:
            fh.write("items: {}\n")
        else:
            fh.write("items:\n")
            for item_id, entry in items.items():
                line = yaml.safe_dump(
                    entry, default_flow_style=True, sort_keys=False, allow_unicode=True
                ).strip()
                fh.write(f"  {item_id}: {line}\n")
    return path


def _items_map(project: Project) -> dict[str, dict]:
    """`project.local_items` only -- imports are excluded from baselines the
    same way they're excluded from coverage and validation.

    `hash_format` records which content-hash definition `hash` was computed
    under (build.HASH_FORMAT -- currently 2, docs/design/keys.md §5)
    directly on every freshly-stamped entry, so a reader of this baseline
    later never has to guess: absent means format 1 (a baseline stamped
    before keys existed, or an entry migrate_hash_format() below left
    untouched because it couldn't account for it), present and current
    means it's directly comparable to a freshly computed hash.

    `verdict` and `calc_hash` are docs/design/stale-arithmetic-signal.md's
    two probes, and are the one deliberate exception to this module's
    "assembly, not new machinery" framing above -- see the note on
    `Baseline.items` for why that's a bounded exception and not a reversal
    of it. Both are per-item *optional*: `verdict` only for a type with a
    verdict-bearing `status` field (`_verdict_field_name`), `calc_hash` only
    for an item with at least one ```calc block (`build_mod.calc_hash_for`
    returns None otherwise) -- omitted entirely, not written as null/empty,
    when they don't apply. That covers most items in a typical project: no
    `status` field, or no `calc` block, or both.
    """
    out = {}
    for item in project.local_items:
        entry: dict[str, object] = {
            "hash": item.content_hash, "type": item.type, "title": item.title,
            "hash_format": build_mod.HASH_FORMAT,
        }
        spec = project.types.get(item.type)
        field_name = _verdict_field_name(spec) if spec is not None else None
        if field_name is not None:
            entry["verdict"] = item.fields.get(field_name)
        calc_hash = build_mod.calc_hash_for(item)
        if calc_hash is not None:
            entry["calc_hash"] = calc_hash
        out[item.id] = entry
    return out


# --------------------------------------------------------- hash-format migration


@dataclass
class BaselineMigration:
    """What happened when a stamped baseline was checked for hash-format-1
    (pre-keys) entries -- see migrate_hash_format()'s docstring for the rule.
    `changed` is whether the baseline file itself was rewritten (only true
    when `carried` is non-empty and `write` was set)."""

    carried: list[str] = field(default_factory=list)       # format-1 entries safely upgraded
    uncomparable: list[str] = field(default_factory=list)  # format-1 entries genuinely stale
    changed: bool = False


def migrate_hash_format(project: Project, baseline: Baseline, write: bool = True) -> BaselineMigration:
    """docs/design/keys.md §5's "conditional carry-forward" rule (option c),
    applied to one already-loaded baseline, in place.

    A baseline stamped before keys existed recorded every entry's hash under
    the old definition (link targets hashed as display-id text) -- it has no
    `hash_format` key at all, since the field didn't exist yet. Comparing
    that hash directly against a freshly computed hash_format-2 hash would
    make every single item in that baseline look changed, which is false:
    nothing about their content moved, only the *definition* of the hash did.

    The rule, for each format-1 entry (recorded id `item_id`, stored hash
    `old_hash`): find the live item still using that id, and recompute what
    its hash would be *right now* under the OLD definition
    (build.legacy_hash_for). If that recomputed old-format hash matches what
    was actually stored, the item's content has demonstrably not changed
    since the baseline was stamped -- so the item's *current* hash_format-2
    hash (already sitting on item.content_hash from this build) is the
    correct new-format hash of the baseline's own content, and the entry is
    safely rewritten in place (`carried`). If it does not match, the item
    genuinely changed since the stamp, for a reason that has nothing to do
    with hash formats -- that entry is left exactly as it was, still
    format 1, and reported as `uncomparable` rather than guessed at. An id
    with no live item at all (deleted, or renamed with no `former_ids:`
    recorded) is left alone too: that is the ordinary "removed" case
    diff_against() already reports, not a migration failure.

    `write=False` computes the same report without touching the file --
    the `--no-write` posture (docs/design/keys.md §2), threaded through by
    every caller below.
    """
    report = BaselineMigration()
    for item_id, entry in baseline.items.items():
        if "hash_format" in entry:
            continue  # already hash_format 2 (or a later format): nothing to do
        item = project.items.get(item_id)
        if item is None:
            continue  # no live item to recompute against -- an ordinary removal
        if build_mod.legacy_hash_for(item, project) != entry.get("hash"):
            report.uncomparable.append(item_id)
            continue
        entry["hash"] = item.content_hash
        entry["hash_format"] = build_mod.HASH_FORMAT
        report.carried.append(item_id)

    if report.carried and write:
        data = {
            "kind": baseline.kind, "name": baseline.name,
            "stamped_at": baseline.stamped_at, "stamped_by": baseline.stamped_by,
            "refdes_version": baseline.refdes_version,
        }
        if baseline.standard is not None:
            data["standard"] = baseline.standard
        if baseline.gate is not None:
            data["gate"] = baseline.gate
        data["items"] = dict(sorted(baseline.items.items()))
        _save_baseline_file(project, data)
        report.changed = True

    return report


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refdes_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("refdes")
    except PackageNotFoundError:
        return "unknown"


# ------------------------------------------------------------------ identity


def _git_identity(project: Project) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=project.root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def resolve_stamped_by(project: Project) -> str:
    """os_user (default) needs no subprocess and reads no git state at all.
    git_identity is opt-in; if it can't be resolved (git missing, not a
    repo, or user.name unset), warn and fall back rather than erroring --
    stamped_by is metadata no gate rule depends on, so a missing name string
    should never be able to block a release (docs/design/lifecycle.md §2)."""
    if project.baseline_identity == "git_identity":
        name = _git_identity(project)
        if name:
            return name
        project.warn(
            "baseline_identity: git_identity, but 'git config user.name' failed "
            "(git not installed, not a git repository, or identity unset) -- "
            "stamped_by falls back to the OS username."
        )
    return getpass.getuser()


# ---------------------------------------------------------------------- gate


def _draft_field_name(item_type) -> str | None:
    """The field this type marks as its status field, if its choices make
    'draft' a real state -- the same field-existence convention
    satisfying_statuses:/coverable_statuses: already use (a field literally
    named `status`), constrained to `type: enum` the same way a
    `required_when:` condition field must be (docs/design/standard-library.md
    §2), so no second "what counts as a status field" convention is invented."""
    fspec = item_type.fields.get("status")
    if fspec is not None and fspec.type == "enum" and "draft" in (fspec.choices or []):
        return "status"
    return None


def _verdict_field_name(item_type) -> str | None:
    """The field docs/design/stale-arithmetic-signal.md calls verdict-bearing:
    the same field-literally-named-`status`, `type: enum` convention
    _draft_field_name uses above, minus the "'draft' is one of its choices"
    narrowing -- a type like `decision`, whose status list has no `draft`
    choice at all, still reaches a verdict via `status`, so this signal isn't
    restricted to types that also happen to have a draft state."""
    fspec = item_type.fields.get("status")
    if fspec is not None and fspec.type == "enum":
        return "status"
    return None


def _is_draft(item: Item, project: Project) -> bool:
    spec = project.types.get(item.type)
    if spec is None:
        return False
    field_name = _draft_field_name(spec)
    return field_name is not None and item.fields.get(field_name) == "draft"


def _rule_draft_items(project: Project) -> list[str]:
    return sorted(item.id for item in project.local_items if _is_draft(item, project))


def _rule_unpinned_citations(project: Project) -> list[str]:
    return sorted(
        {
            item.id
            for item in project.local_items
            for status in item.citations
            if status.state == "unpinned"
        }
    )


def _rule_missing_vendored_copies(project: Project) -> list[str]:
    return sorted(
        {
            item.id
            for item in project.local_items
            for status in item.citations
            if status.state == "cache_missing"
        }
    )


def _coverable_offenders(project: Project, predicate: Callable[[str], bool]) -> list[str]:
    """Coverable items (already filtered to a type's coverable/
    coverable_statuses:, since that's exactly what populates
    project.coverage) whose stage matches `predicate`, excluding draft items
    -- a draft item isn't expected to be covered yet, so its open coverage
    isn't the same problem as an active item nobody has touched
    (docs/design/lifecycle.md §1's uncovered_requirements/
    unverified_requirements rows)."""
    out = []
    for item_id, cov in project.coverage.items():
        item = project.items.get(item_id)
        if item is None or _is_draft(item, project):
            continue
        if predicate(cov.stage):
            out.append(item_id)
    return sorted(out)


def _rule_uncovered_requirements(project: Project) -> list[str]:
    return _coverable_offenders(project, lambda stage: stage == "open")


def _rule_unverified_requirements(project: Project) -> list[str]:
    return _coverable_offenders(project, lambda stage: stage != "verified")


def _rule_info_check_failures(project: Project) -> list[str]:
    out = []
    for item in project.local_items:
        spec = project.types.get(item.type)
        if spec is None or spec.check_severity != INFO:
            continue
        if any(c.ok is False for c in item.checks):
            out.append(item.id)
    return sorted(out)


def _rule_unaccepted_board_moves(project: Project) -> list[str]:
    return sorted({item_id for item_id, _old, _new in project.board_moves})


def _rule_unaccepted_workspace_moves(project: Project) -> list[str]:
    return sorted({item_id for item_id, _old, _new in project.workspace_moves})


_RULES: dict[str, Callable[[Project], list[str]]] = {
    "draft_items": _rule_draft_items,
    "unpinned_citations": _rule_unpinned_citations,
    "missing_vendored_copies": _rule_missing_vendored_copies,
    "uncovered_requirements": _rule_uncovered_requirements,
    "unverified_requirements": _rule_unverified_requirements,
    "info_check_failures": _rule_info_check_failures,
    "unaccepted_board_moves": _rule_unaccepted_board_moves,
    "unaccepted_workspace_moves": _rule_unaccepted_workspace_moves,
}

# Fixed order, matching the table in docs/design/lifecycle.md §1 -- also the
# order rule names print in on a blocked stamp.
RULE_NAMES = tuple(RELEASE_GATE_DEFAULTS)


@dataclass
class GateRuleResult:
    name: str
    enabled: bool
    offenders: list[str]

    @property
    def status(self) -> str:
        if not self.enabled:
            return "skipped"
        return "pass" if not self.offenders else "FAIL"


def evaluate_gate(project: Project, kind: str) -> list[GateRuleResult]:
    """One result per configured rule, in RULE_NAMES order. `kind` is
    "release" or "revision" -- which half of each rule's (release, revision)
    pair is consulted. Only ever reads `project.release_gate`, already
    parsed and validated from refdes-project.yaml; this function is the only
    place those eight rules are actually evaluated."""
    results = []
    for name in RULE_NAMES:
        enabled = bool(project.release_gate.get(name, RELEASE_GATE_DEFAULTS[name])[kind])
        offenders = _RULES[name](project) if enabled else []
        results.append(GateRuleResult(name=name, enabled=enabled, offenders=offenders))
    return results


# ----------------------------------------------------------------- stamping


@dataclass
class StampOutcome:
    kind: str
    name: str
    status: str  # "stamped" | "unchanged" | "conflict" | "gate_failed"
    path: str = ""
    item_count: int = 0
    stamped_at: str = ""
    stamped_by: str = ""
    gate_results: list[GateRuleResult] = field(default_factory=list)
    conflict_detail: str = ""


def stamp(project: Project, kind: str, name: str, write: bool = True) -> StampOutcome:
    """Stamp `name` as a `kind` ("revision" | "release") baseline.

    Caller's responsibility, both already true by the time this runs: the
    name has passed validate_name(), and `build.build()` has already run in
    read-only mode with `project.errors` confirmed empty -- the
    unconditional error floor (docs/design/lifecycle.md §1) is checked by
    the caller against the same `project.errors` every other command uses,
    not re-checked here.

    `write` only gates the hash-format migration below, not the stamp
    itself: an existing same-name baseline stamped before keys existed has
    to be migrated (or at least compared correctly) before its `.items` can
    be checked against a fresh `items_map` at all, or a byte-identical
    re-run would misreport as "conflict" purely because of the format
    change, not any real content difference (docs/design/keys.md §5).
    """
    items_map = _items_map(project)

    existing = load_baseline(project, name)
    if existing is not None:
        migrate_hash_format(project, existing, write=write)
        if existing.kind == kind and existing.items == items_map:
            # Byte-identical re-run: skip entirely, file untouched -- not even
            # stamped_at rewritten, mirroring `refdes fetch` skipping an
            # already-pinned url. No gate re-evaluation: nothing is being
            # written, so there's nothing for the gate to gate.
            return StampOutcome(
                kind=kind, name=name, status="unchanged", path=baseline_path(project, name),
                item_count=len(items_map), stamped_at=existing.stamped_at,
                stamped_by=existing.stamped_by,
            )
        raise_detail = (
            f"{name!r} is already stamped as a {existing.kind} "
            f"(at {existing.stamped_at}) with different content. Baseline "
            f"names are permanent once written -- delete "
            f"{os.path.relpath(baseline_path(project, name), project.root)} "
            f"first if that was intentional, or choose a new name."
        )
        return StampOutcome(kind=kind, name=name, status="conflict", conflict_detail=raise_detail)

    gate_results = evaluate_gate(project, kind)
    if any(r.enabled and r.offenders for r in gate_results):
        return StampOutcome(kind=kind, name=name, status="gate_failed", gate_results=gate_results)

    stamped_at = _now_iso()
    stamped_by = resolve_stamped_by(project)
    data: dict = {
        "kind": kind,
        "name": name,
        "stamped_at": stamped_at,
        "stamped_by": stamped_by,
        "refdes_version": _refdes_version(),
    }
    if project.standard_base:
        data["standard"] = {"base": project.standard_base, "version": project.standard_version}
    if kind == "release":
        # Only for kind: release -- records which rules were active and
        # passed, so re-reading an old release stays meaningful after the
        # gate config is later tightened (docs/design/lifecycle.md §2).
        data["gate"] = {r.name: r.status for r in gate_results}
    data["items"] = dict(sorted(items_map.items()))

    path = _save_baseline_file(project, data)
    return StampOutcome(
        kind=kind, name=name, status="stamped", path=path, item_count=len(items_map),
        stamped_at=stamped_at, stamped_by=stamped_by, gate_results=gate_results,
    )


# -------------------------------------------------------------------- diffs


@dataclass
class DiffResult:
    baseline_name: str
    stamped_at: str
    changed: list[str]
    added: list[str]
    removed: list[tuple[str, str, str]]  # id, type, title
    unchanged_count: int
    # Subset of `changed` (docs/design/stale-arithmetic-signal.md): this
    # item's verdict-bearing `status` moved since `baseline`, but its ```calc
    # block's source text did not. Always [] for a baseline that predates
    # this field (no `verdict`/`calc_hash` recorded to compare against) --
    # a false negative, never a false positive; see _stale_arithmetic below.
    stale_arithmetic: list[str]


def _stale_arithmetic(project: Project, baseline: Baseline, changed: list[str]) -> list[str]:
    """The one-shot transition signal: which of `changed` moved verdict
    without moving arithmetic, per docs/design/stale-arithmetic-signal.md.

    Deliberately scoped to `changed` rather than every local item -- an item
    whose `hash` didn't move can't have moved its `status` either, since
    `status` is itself part of what `hash` covers (an `invalidate` field).
    Nothing here is a second hash comparison of the same fact; it's asking
    a narrower question of the items already known to have moved.

    Silent (via `continue`, never an error) for exactly the cases the design
    doc requires silence for: `old` lacks `verdict`/`calc_hash` (baseline
    stamped before this signal existed, or the item didn't qualify for one
    or both fields at stamp time); the live item is gone, or its type no
    longer declares a verdict-bearing `status` field; the verdict itself
    didn't move (the hash changed for some other reason); or the item has no
    calc block *now* (its calc block was removed, which is itself a change,
    not staleness -- calc_hash_for returning None is a real "no" here, not
    a missing-data case, since a present `old["calc_hash"]` already proved
    the item had a block at baseline time).
    """
    out = []
    for item_id in changed:
        old = baseline.items.get(item_id, {})
        if "verdict" not in old or "calc_hash" not in old:
            continue
        item = project.items.get(item_id)
        if item is None:
            continue
        spec = project.types.get(item.type)
        field_name = _verdict_field_name(spec) if spec is not None else None
        if field_name is None:
            continue
        if item.fields.get(field_name) == old["verdict"]:
            continue
        current_calc_hash = build_mod.calc_hash_for(item)
        if current_calc_hash is None or current_calc_hash != old["calc_hash"]:
            continue
        out.append(item_id)
    return sorted(out)


def diff_against(project: Project, baseline: Baseline, write: bool = True) -> DiffResult:
    """Item-scoped, hash-only: which local items changed, were added, or were
    removed since `baseline` was stamped. Not field-level -- that's one
    `git diff` away once you know which two commits to compare (this
    function is precisely what supplies that scope), and is deliberately
    left to git rather than reimplemented (docs/design/lifecycle.md §3) --
    `stale_arithmetic` below is a narrow, explicit exception to that (see
    `Baseline.items` and docs/design/stale-arithmetic-signal.md), not a
    second field-level diff mechanism.

    Migrates `baseline` from hash_format 1 to 2 first, in place (§5) -- a
    baseline stamped before keys existed would otherwise show every one of
    its items as "changed" purely because the hash *definition* moved, which
    isn't the question this function exists to answer. `write` threads
    through to migrate_hash_format() (`--no-write`, docs/design/keys.md §2);
    defaults True so former_ids.propose(), which calls this without knowing
    about the flag, keeps its existing unconditional-load behaviour.
    """
    migrate_hash_format(project, baseline, write=write)
    current = _items_map(project)
    changed, added = [], []
    unchanged = 0
    for item_id, entry in current.items():
        old = baseline.items.get(item_id)
        if old is None:
            added.append(item_id)
        elif old.get("hash") != entry["hash"]:
            changed.append(item_id)
        else:
            unchanged += 1
    removed = sorted(
        (item_id, str(entry.get("type", "")), str(entry.get("title", "")))
        for item_id, entry in baseline.items.items()
        if item_id not in current
    )
    changed = sorted(changed)
    return DiffResult(
        baseline_name=baseline.name,
        stamped_at=baseline.stamped_at,
        changed=changed,
        added=sorted(added),
        removed=removed,
        unchanged_count=unchanged,
        stale_arithmetic=_stale_arithmetic(project, baseline, changed),
    )
