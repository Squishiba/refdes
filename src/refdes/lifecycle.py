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
    items: dict[str, dict] = field(default_factory=dict)
    gate: dict[str, str] | None = None


def _load_baseline_file(path: str) -> Baseline:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    gate = data.get("gate")
    return Baseline(
        name=str(data.get("name", "")),
        kind=str(data.get("kind", "")),
        stamped_at=str(data.get("stamped_at", "")),
        stamped_by=str(data.get("stamped_by", "")),
        refdes_version=str(data.get("refdes_version", "")),
        items={k: dict(v) for k, v in (data.get("items") or {}).items()},
        gate=dict(gate) if gate is not None else None,
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
    same way they're excluded from coverage and validation."""
    return {
        item.id: {"hash": item.content_hash, "type": item.type, "title": item.title}
        for item in project.local_items
    }


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


_RULES: dict[str, Callable[[Project], list[str]]] = {
    "draft_items": _rule_draft_items,
    "unpinned_citations": _rule_unpinned_citations,
    "missing_vendored_copies": _rule_missing_vendored_copies,
    "uncovered_requirements": _rule_uncovered_requirements,
    "unverified_requirements": _rule_unverified_requirements,
    "info_check_failures": _rule_info_check_failures,
    "unaccepted_board_moves": _rule_unaccepted_board_moves,
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
    place those seven rules are actually evaluated."""
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


def stamp(project: Project, kind: str, name: str) -> StampOutcome:
    """Stamp `name` as a `kind` ("revision" | "release") baseline.

    Caller's responsibility, both already true by the time this runs: the
    name has passed validate_name(), and `build.build()` has already run in
    read-only mode with `project.errors` confirmed empty -- the
    unconditional error floor (docs/design/lifecycle.md §1) is checked by
    the caller against the same `project.errors` every other command uses,
    not re-checked here.
    """
    items_map = _items_map(project)

    existing = load_baseline(project, name)
    if existing is not None:
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


def diff_against(project: Project, baseline: Baseline) -> DiffResult:
    """Item-scoped, hash-only: which local items changed, were added, or were
    removed since `baseline` was stamped. Not field-level -- that's one
    `git diff` away once you know which two commits to compare (this
    function is precisely what supplies that scope), and is deliberately
    left to git rather than reimplemented (docs/design/lifecycle.md §3)."""
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
    return DiffResult(
        baseline_name=baseline.name,
        stamped_at=baseline.stamped_at,
        changed=sorted(changed),
        added=sorted(added),
        removed=removed,
        unchanged_count=unchanged,
    )
