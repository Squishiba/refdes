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
from . import keys as keys_mod
from .model import INFO, RELEASE_GATE_DEFAULTS, Item, Project, SchemaError
from .parse import yaml_safe_load

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
    # Per item: hash, type, title, hash_format, and the immutable surrogate
    # key when one existed at stamp time (see _items_map) -- plus,
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


def _baseline_indexes(
    items: dict[str, dict],
) -> tuple[
    dict[str, tuple[str, str, dict]],
    dict[str, tuple[str, str, dict]],
]:
    """Index either §5 baseline shape by surrogate key and display id."""
    by_key: dict[str, tuple[str, str, dict]] = {}
    by_display_id: dict[str, tuple[str, str, dict]] = {}
    for record_id, entry in items.items():
        identity = keys_mod.baseline_identity(record_id, entry)
        key, display_id = identity if identity is not None else (None, record_id)
        indexed = (record_id, display_id, entry)
        by_display_id[display_id] = indexed
        if key is not None:
            by_key[key] = indexed
    return by_key, by_display_id


def _match_baseline_entry(
    indexes: tuple[
        dict[str, tuple[str, str, dict]],
        dict[str, tuple[str, str, dict]],
    ],
    item_id: str,
    entry: dict,
) -> tuple[str, str, dict] | None:
    """Match either current storage shape by key, then by display id."""
    by_key, by_display_id = indexes
    identity = keys_mod.baseline_identity(item_id, entry)
    key, display_id = identity if identity is not None else (None, item_id)
    if key:
        matched = by_key.get(key)
        if matched is not None:
            return matched
    matched = by_display_id.get(display_id)
    if matched is None:
        return None
    old_identity = keys_mod.baseline_identity(matched[0], matched[2])
    if key and old_identity is not None:
        return None
    return matched


def _same_baseline_items(stored: dict[str, dict], current: dict[str, dict]) -> bool:
    """Semantic equality across display-id-keyed and key-keyed storage."""
    if len(stored) != len(current):
        return False
    indexes = _baseline_indexes(stored)
    matched_records: set[str] = set()
    for item_id, current_entry in current.items():
        current_identity = keys_mod.baseline_identity(item_id, current_entry)
        current_display_id = (
            current_identity[1] if current_identity is not None else item_id
        )
        matched = _match_baseline_entry(indexes, item_id, current_entry)
        if matched is None:
            return False
        record_id, stored_id, stored_entry = matched
        if stored_id != current_display_id or record_id in matched_records:
            return False
        matched_records.add(record_id)
        left = dict(stored_entry)
        right = dict(current_entry)
        left.pop("id", None)
        stored_identity = keys_mod.baseline_identity(record_id, stored_entry)
        if stored_identity is not None:
            left.pop("key", None)
            right.pop("key", None)
        else:
            right.pop("key", None)
        if left != right:
            return False
    return len(matched_records) == len(stored)


def _load_baseline_file(path: str) -> Baseline:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml_safe_load(fh) or {}
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


def format_baseline(data: dict) -> str:
    """Two dump passes, not one: ``default_flow_style=None`` (PyYAML's
    per-node heuristic) would flow-style both ``gate:`` and each item entry.
    That collapses the gate -- where one rule per line is worth diffing --
    into a wrapped blob. The head (kind through gate) is therefore dumped
    block-style, while each item entry is dumped individually in flow style.
    Both still go through ``yaml.safe_dump``, so titles containing colons or
    quotes are escaped correctly rather than hand-formatted. This is the
    source-reviewable shape shown in docs/design/lifecycle.md §2.
    """
    items = data["items"]
    head = {k: v for k, v in data.items() if k != "items"}
    out = _HEADER + yaml.safe_dump(
        head, sort_keys=False, default_flow_style=False
    )
    if not items:
        return out + "items: {}\n"
    out += "items:\n"
    for item_id, entry in items.items():
        line = yaml.safe_dump(
            entry, default_flow_style=True, sort_keys=False, allow_unicode=True
        ).strip()
        out += f"  {item_id}: {line}\n"
    return out


def _save_baseline_file(project: Project, data: dict) -> str:
    """Persist ``format_baseline``'s source-reviewable baseline shape."""
    path = baseline_path(project, data["name"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(format_baseline(data))
    return path


def _items_map(project: Project) -> dict[str, dict]:
    """Snapshot ``project.local_items`` only; imports are excluded from
    baselines the same way they are excluded from coverage and validation.

    Explicit adoption is recorded by ``keys.ADOPTION_MARKER``. Adopted
    projects key each entry by immutable surrogate and carry the display id
    inside; legacy projects key by display id and carry the surrogate inside.
    Readers accept both shapes, including mixtures left by an uncomparable
    historical entry.

    In the legacy shape, ``key`` records the item's immutable surrogate for
    the baseline corruption lint (docs/design/keys.md §6 Layers 4-5). It
    remains optional: a pre-keys baseline, or one stamped under ``--no-write``
    before keys were minted, has no identity evidence for that entry and the
    lint must skip it rather than guess. In the adopted shape the map key is
    that same surrogate and ``id`` preserves the human-facing label.

    ``hash_format`` records which content-hash definition produced ``hash``
    (``build.HASH_FORMAT`` -- currently 3, docs/design/keys.md §5) directly
    on every freshly-stamped entry, so a later reader never has to guess.
    Absent means format 1: either the baseline predates keys, or
    ``migrate_hash_format`` left the entry untouched because it could not
    account for it. Present and current means it is directly comparable to a
    freshly computed hash.

    ``verdict`` and ``calc_hash`` are
    docs/design/stale-arithmetic-signal.md's two probes, and are the one
    deliberate exception to this module's \"assembly, not new machinery\"
    framing. Both are optional per item: ``verdict`` only for a type with a
    verdict-bearing status field, and ``calc_hash`` only for an item with at
    least one ``calc`` block. They exist solely to identify the bounded
    verdict-without-arithmetic transition; unlike general field-level
    history, they cannot reconstruct any other prior field value.
    """
    out = {}
    adopted = keys_mod.is_adopted(project)
    for item in project.local_items:
        entry: dict[str, object] = {
            "hash": item.content_hash, "type": item.type, "title": item.title,
            "hash_format": build_mod.HASH_FORMAT,
        }
        if adopted and item.key:
            record_id = item.key
            entry["id"] = item.id
        else:
            # A permanently id-less item (docs/design/threads.md §2) has no
            # display id to key this entry by -- falling back to `item.id`
            # unconditionally would collide every such item on "". Its
            # surrogate key is the next best identity available, even in the
            # legacy (non-adopted) shape.
            record_id = item.id or item.key
            if item.key:
                entry["key"] = item.key
        spec = project.types.get(item.type)
        field_name = _verdict_field_name(spec) if spec is not None else None
        if field_name is not None:
            entry["verdict"] = item.fields.get(field_name)
        calc_hash = build_mod.calc_hash_for(item)
        if calc_hash is not None:
            entry["calc_hash"] = calc_hash
        out[record_id] = entry
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
    `hash_format` key at all, since the field didn't exist yet. A baseline
    stamped under an earlier HASH_FORMAT (2: link targets as resolved keys,
    `checks: against:` still raw text) carries that number instead. Either
    way, comparing the stored hash directly against a freshly computed
    current-format hash would make every single item in that baseline look
    changed, which is false: nothing about their content moved, only the
    *definition* of the hash did.

    The rule, for each entry not already at the current format (recorded id
    `item_id`, stored hash `old_hash`, recorded format `old_format`): find
    the live item still using that id, and recompute what its hash would be
    *right now* under `old_format`'s definition (keys.hash_in_format). If
    that recomputed old-format hash matches what was actually stored, the
    item's content has demonstrably not changed since the baseline was
    stamped -- so the item's *current* hash (already sitting on
    item.content_hash from this build) is the correct current-format hash of
    the baseline's own content, and the entry is safely rewritten in place
    (`carried`). If it does not match, the item genuinely changed since the
    stamp, for a reason that has nothing to do with hash formats -- that
    entry is left exactly as it was and reported as `uncomparable` rather
    than guessed at. An id with no live item at all (deleted, or renamed
    with no `former_ids:` recorded) is left alone too: that is the ordinary
    "removed" case diff_against() already reports, not a migration failure.

    `write=False` computes the same report without touching the file --
    the `--no-write` posture (docs/design/keys.md §2), threaded through by
    every caller below.
    """
    report = BaselineMigration()
    for record_id, entry in baseline.items.items():
        try:
            recorded_format = int(entry["hash_format"]) if "hash_format" in entry else 1
        except (TypeError, ValueError):
            recorded_format = -1
        if recorded_format == build_mod.HASH_FORMAT:
            continue  # already current: nothing to do
        identity = keys_mod.baseline_identity(record_id, entry)
        display_id = identity[1] if identity is not None else record_id
        item = keys_mod.item_for_baseline_entry(project, record_id, entry)
        if item is None:
            continue  # no live item to recompute against -- an ordinary removal
        expected = keys_mod.hash_in_format(item, project, recorded_format)
        if expected is None or expected != entry.get("hash"):
            report.uncomparable.append(display_id)
            continue
        entry["hash"] = item.content_hash
        entry["hash_format"] = build_mod.HASH_FORMAT
        report.carried.append(display_id)

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
        item = project.item_by_id(item_id)
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
    # Older-format entries the existing baseline carries that the hash-format
    # migration could not verify (migrate_hash_format's `uncomparable`). The
    # stamp path never silently drops or silently re-stamps them: they keep
    # the stored content unequal to the fresh items_map, so the outcome is
    # "conflict" -- but "conflict" alone overclaims "different content"
    # when part of the mismatch may only be the hash definition having
    # moved, so the CLI names them alongside it.
    uncomparable: list[str] = field(default_factory=list)


def stamp(project: Project, kind: str, name: str, write: bool = True) -> StampOutcome:
    """Stamp `name` as a `kind` ("revision" | "release") baseline.

    Caller's responsibility, both already true by the time this runs: the
    name has passed validate_name(), and `build.build()` has already run in
    read-only mode with `project.errors` confirmed empty -- the
    unconditional error floor (docs/design/lifecycle.md §1) is checked by
    the caller against the same `project.errors` every other command uses,
    not re-checked here.

    An existing same-name baseline stamped before keys existed has to be
    migrated (or at least compared correctly) before its `.items` can be
    checked against a fresh `items_map` at all. Its absent `key` metadata
    must likewise stay absent for comparison rather than being manufactured
    from the current item. Otherwise a byte-identical re-run would misreport
    as "conflict" purely because the stored format gained new metadata, not
    because any content changed (docs/design/keys.md §5).

    `write=False` (the global `--no-write`, docs/design/keys.md §2) keeps
    that migration but runs it in memory only: the baseline is migrated for
    comparison, no baseline file is ever written, and once every check
    below passes the outcome is reported as "would_stamp" -- the same "say
    what would change, change nothing" posture the rest of the flag takes.
    The migration's *write* is gated because `.refdes/baselines/` is
    exactly what `--no-write` promises not to touch; its in-memory step is
    not, because skipping it would make the comparison above lie.
    """
    items_map = _items_map(project)

    existing = load_baseline(project, name)
    uncomparable: list[str] = []
    if existing is not None:
        uncomparable = sorted(migrate_hash_format(project, existing, write=write).uncomparable)
        if existing.kind == kind and _same_baseline_items(existing.items, items_map):
            # Byte-identical re-run: skip entirely, file untouched -- not even
            # stamped_at rewritten, mirroring `refdes fetch` skipping an
            # already-pinned url. No gate re-evaluation: nothing is being
            # written, so there's nothing for the gate to gate.
            return StampOutcome(
                kind=kind, name=name, status="unchanged", path=baseline_path(project, name),
                item_count=len(items_map), stamped_at=existing.stamped_at,
                stamped_by=existing.stamped_by, uncomparable=uncomparable,
            )
        raise_detail = (
            f"{name!r} is already stamped as a {existing.kind} "
            f"(at {existing.stamped_at}) with different content. Baseline "
            f"names are permanent once written -- delete "
            f"{os.path.relpath(baseline_path(project, name), project.root)} "
            f"first if that was intentional, or choose a new name."
        )
        return StampOutcome(
            kind=kind, name=name, status="conflict", conflict_detail=raise_detail,
            uncomparable=uncomparable,
        )

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

    if not write:
        return StampOutcome(
            kind=kind, name=name, status="would_stamp",
            path=baseline_path(project, name), item_count=len(items_map),
            stamped_at=stamped_at, stamped_by=stamped_by, gate_results=gate_results,
        )
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
    relabelled: list[tuple[str, str, str]]  # old id, new id, surrogate key
    unchanged_count: int
    # Subset of `changed` (docs/design/stale-arithmetic-signal.md): this
    # item's verdict-bearing `status` moved since `baseline`, but its ```calc
    # block's source text did not. Always [] for a baseline that predates
    # this field (no `verdict`/`calc_hash` recorded to compare against) --
    # a false negative, never a false positive; see _stale_arithmetic below.
    stale_arithmetic: list[str]
    # Baseline entries the hash-format migration could not verify at all
    # (docs/change-tracking.md): older-format entries whose recorded hash no
    # longer matches the item under the *old* hash definition, so refdes
    # cannot tell whether the content moved or only the definition did. They
    # appear here instead of in `changed` -- "changed" claims more than
    # "can't tell" -- and are deliberately not counted as unchanged either.
    # Ids are the entry's current display id (see diff_against's docstring).
    uncomparable: list[str] = field(default_factory=list)


def _stale_arithmetic(
    project: Project, changed: list[str], old_entries: dict[str, dict]
) -> list[str]:
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
        old = old_entries.get(item_id, {})
        if "verdict" not in old or "calc_hash" not in old:
            continue
        item = project.item_by_id(item_id)
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
    defaults True for callers that load a project writably by construction,
    and `cli` threads `not args.no_write` from both `audit` and
    `former-ids propose`.

    Entries the migration reports as `uncomparable` -- content change or
    definition move, indistinguishable -- are reported on their own
    (`DiffResult.uncomparable`), never folded into `changed`, and never
    counted as unchanged. The migration names them by the id recorded at
    stamp time, so the exclusion matches on the baseline side (`old_id`)
    and each is reported once under its *current* display id -- a renamed
    uncomparable entry would otherwise slip back into `changed` under the
    new id while `uncomparable` still carried the old one.
    """
    migration = migrate_hash_format(project, baseline, write=write)
    uncomparable_pending = set(migration.uncomparable)
    uncomparable: list[str] = []
    current = _items_map(project)
    indexes = _baseline_indexes(baseline.items)
    changed, added = [], []
    relabelled: list[tuple[str, str, str]] = []
    old_entries: dict[str, dict] = {}
    matched_records: set[str] = set()
    unchanged = 0
    for item_id, entry in current.items():
        identity = keys_mod.baseline_identity(item_id, entry)
        current_id = identity[1] if identity is not None else item_id
        key = identity[0] if identity is not None else entry.get("key")
        matched = _match_baseline_entry(indexes, item_id, entry)
        if matched is None:
            added.append(current_id)
            continue
        record_id, old_id, old = matched
        matched_records.add(record_id)
        old_entries[current_id] = old
        if key and old_id != current_id:
            relabelled.append((old_id, current_id, str(key)))
        if old_id in uncomparable_pending:
            uncomparable_pending.discard(old_id)
            uncomparable.append(current_id)
            continue  # neither "changed" nor "unchanged" -- reported as uncomparable
        if old.get("hash") != entry["hash"]:
            changed.append(current_id)
        elif old_id == current_id:
            unchanged += 1
    removed = sorted(
        (
            keys_mod.baseline_identity(record_id, entry)[1]
            if keys_mod.baseline_identity(record_id, entry) is not None
            else record_id,
            str(entry.get("type", "")),
            str(entry.get("title", "")),
        )
        for record_id, entry in baseline.items.items()
        if record_id not in matched_records
    )
    changed = sorted(changed)
    return DiffResult(
        baseline_name=baseline.name,
        stamped_at=baseline.stamped_at,
        changed=changed,
        added=sorted(added),
        removed=removed,
        relabelled=sorted(relabelled),
        unchanged_count=unchanged,
        stale_arithmetic=_stale_arithmetic(project, changed, old_entries),
        # Anything the migration named but no current item matched stays in
        # the report under the id it was recorded with -- dropping it would
        # silently bury an entry we already know we can't check.
        uncomparable=sorted(set(uncomparable) | uncomparable_pending),
    )
