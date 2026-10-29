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
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import yaml

from . import build as build_mod
from . import chains as chains_mod
from . import history as history_mod
from . import keys as keys_mod
from . import model, textio
from . import seal as seal_mod
from .model import INFO, RELEASE_GATE_DEFAULTS, Item, Project, SchemaError
from .parse import read_store_text, yaml_safe_load

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
    # and `calc_hash` (a hash of the item's ```calc block source and inline
    # calc spans, alongside the existing whole-item `hash`) are a narrow,
    # deliberate exception to
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
        right.pop("id", None)
        stored_identity = keys_mod.baseline_identity(record_id, stored_entry)
        if stored_identity is not None:
            left.pop("key", None)
            right.pop("key", None)
        else:
            right.pop("key", None)
        if left != right:
            return False
    return len(matched_records) == len(stored)


def _load_baseline_file(path: str, project: Project) -> Baseline:
    try:
        data = yaml_safe_load(read_store_text(path)) or {}
    except IsADirectoryError as exc:
        raise SchemaError(f"{path}: baseline file is a directory, not a file") from exc
    except UnicodeDecodeError as exc:
        raise SchemaError(f"{path}: baseline file is not valid UTF-8 ({exc})") from exc
    except yaml.YAMLError as exc:
        raise SchemaError(f"{path}: baseline file does not parse ({exc})") from exc
    for record_id, entry in (data.get("items") or {}).items():
        if "key" in entry:
            keys_mod.report_storage_key(project, entry["key"], path)
        elif "id" in entry:
            keys_mod.report_storage_key(project, record_id, path)
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
    if not os.path.exists(path):
        return None
    return _load_baseline_file(path, project)


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
            out.append(_load_baseline_file(os.path.join(d, name), project))
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
        # Unlike the entry, this map key is formatted by hand. Quote older
        # YAML-ambiguous surrogate keys when the baseline is rewritten.
        label = (
            item_id if keys_mod.yaml_plain_scalar_is_string(item_id)
            else json.dumps(item_id)
        )
        out += f"  {label}: {line}\n"
    return out


class BaselineUnwritable(OSError):
    """The baseline file could not be written (a read-only checkout, a
    read-only bind mount -- a condition of the filesystem, not of the
    project). Carries the project-relative path so the caller can name the
    file it refused to write.

    Its own type rather than a bare `OSError` because the three callers want
    three different shapes and none of them is "print a traceback":
    `stamp()` refuses outright (a stamp that did not happen must not read as
    one that did), `migrate_hash_format()` degrades to a warning (the
    comparison it feeds is computed in memory and is still correct), and
    `refdes revise`/`calc-rewrite`/`standard upgrade` propagate it to their
    own handlers unchanged.
    """

    def __init__(self, rel: str, cause: OSError) -> None:
        super().__init__(f"{rel}: {cause.strerror or cause}")
        self.rel = rel
        self.cause = cause


def _save_baseline_file(project: Project, data: dict) -> str:
    """Persist ``format_baseline``'s source-reviewable baseline shape.

    Raises `BaselineUnwritable` rather than letting the raw `OSError` out,
    so every caller above this line reports a refusal in the house style
    instead of a traceback.
    """
    path = baseline_path(project, data["name"])
    rel = os.path.relpath(path, project.root).replace("\\", "/")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_text(path, format_baseline(data))
    except OSError as exc:
        raise BaselineUnwritable(rel, exc) from exc
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
    (``build.HASH_FORMAT`` -- currently 6, docs/design/keys.md §5, finding 35,
    the image-bytes bump and the span-references bump) directly
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
    least one ``calc`` block or inline calc span (an inline-only item is
    stamped). They exist solely to identify the bounded
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
        refs = build_mod.calc_reference_snapshot(project, item)
        if refs:
            entry["calc_refs"] = refs
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
    the live item still using that id, and recompute the hashes its current
    content has *right now* under `old_format`'s definition
    (`keys.hashes_in_format`, the shared comparison set). If the stored hash
    is one of them, the item's content has demonstrably not changed since
    the baseline was stamped -- so the item's *current* hash (already
    sitting on item.content_hash from this build) is the correct
    current-format hash of the baseline's own content, and the entry is
    safely rewritten in place (`carried`). If it is not, the item genuinely
    changed since the stamp, for a reason that has nothing to do with hash
    formats -- that entry is left exactly as it was and reported as
    `uncomparable` rather than guessed at. An id with no live item at all
    (deleted, or renamed with no `former_ids:` recorded) is left alone too:
    that is the ordinary "removed" case diff_against() already reports, not
    a migration failure.

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
        expected = keys_mod.hashes_in_format(item, project, recorded_format)
        if not keys_mod.stored_hash_matches(entry.get("hash"), expected):
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
        try:
            _save_baseline_file(project, data)
        except BaselineUnwritable as exc:
            # A migration is a rewrite of a file that already holds a correct
            # baseline -- the entries above were carried in memory and the
            # comparison this feeds is computed from them, so nothing is lost
            # but the on-disk format bump, which the next writable command
            # rediscovers. Warn and keep the report; refusing here would take
            # `audit` and `former-ids propose` down over a rewrite neither of
            # them needs in order to answer its question.
            #
            # Once per file, not once per call: `audit` diffs the latest
            # revision *and* the latest release, which are routinely the same
            # file, and the second warning would be the same sentence twice.
            if exc.rel not in project.load_writes.blocked:
                project.load_writes.blocked.append(exc.rel)
                project.warn(
                    model.read_only_refusal(
                        "this baseline keeps its older stored-hash format on "
                        "disk; the comparison below is unaffected"
                    ),
                    file=exc.rel,
                    line=1,
                )
            return report
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


def _rule_missing_kept_copies(project: Project) -> list[str]:
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
    # Per-item resolution (docs/design/candidate-parts.md §4.5): with a
    # status-mapped check_severity, a status change alone moves an item in or
    # out of this bucket -- candidate -> selected turns an info failure into a
    # build-blocking error, so the gate must resolve severity per item, not per
    # type.
    out = []
    for item in project.local_items:
        spec = project.types.get(item.type)
        if build_mod._severity_for(spec, item) != INFO:
            continue
        if any(c.ok is False for c in item.checks):
            out.append(item.id)
    return sorted(out)


def _rule_unaccepted_board_moves(project: Project) -> list[str]:
    return sorted({item_id for item_id, _old, _new in project.board_moves})


def _rule_unaccepted_workspace_moves(project: Project) -> list[str]:
    return sorted({item_id for item_id, _old, _new in project.workspace_moves})


def _rule_open_tasks(project: Project) -> list[str]:
    """Living notes H8 (§5 rule 5): a release blocks while any thread tip
    carries an open author task.

    Reads the fold, never a re-implementation of it: `chains.fold_tasks` is
    the same per-tip walk `threads.threads_projection` reads, memoized per
    component on the `ChainGraph`, so starting it once per local item costs
    one walk per tip. §5 rule 2 makes the fold exactly the author's own
    rows -- derived rows (uncovered coverage, failing checks, blocked
    chains, stale citations) live beside it in the projection's `derived`
    list and are each already their own gate rule, so they are not
    re-counted here.

    A fork counts every open tip (a tip is what fold_tasks yields, one per
    open end -- there is no tip to read only one of). A tip whose fold is
    `ambiguous` blocks too, said as a conflicting list: the gate must not
    pass something it couldn't read. Malformed rows are a build *error*
    (`validate_items`), so the error floor refuses the stamp before the
    gate ever runs; a legal row with no `state` is not `open`.

    Offenders name the tip and the task ("LOG-002: open task T-thermal")
    because a bare thread ref wouldn't say which task to go tick; a row
    whose id is absent (validation allows it) names its position in the
    folded list; and each offender carries the source location of the row
    it names -- "items/log.yaml:6" -- so it is clickable where the CLI is.
    The row's own line comes from `Item.field_lines` (parse's own line
    tagging, kept for `tasks` rows); the location is the *declaring*
    entry's file (the fold's source, which is not always the tip), and an
    entry whose list came from its file's `defaults:` block has no row
    lines to keep -- there the location is the declaring entry's own line.
    A conflicting fold names the tip's own entry line: the tip is
    ambiguous precisely because it declares no list of its own, so it has
    no `tasks:` line to point at. Imported items are skipped like every
    other rule: an imported tip's open tasks are the other project's work.
    """
    graph = chains_mod.build_graph(project)
    local = {id(item) for item in project.local_items}
    offenders: list[str] = []
    seen: set[int] = set()
    for item in project.local_items:
        for tip_tasks in chains_mod.fold_tasks(project, item, graph=graph):
            if id(tip_tasks.tip) in seen or id(tip_tasks.tip) not in local:
                continue
            seen.add(id(tip_tasks.tip))
            label = tip_tasks.tip.id or tip_tasks.tip.key
            if tip_tasks.ambiguous:
                tip = tip_tasks.tip
                offenders.append(
                    f"{label}: conflicting task list (task reconciliation "
                    f"required) ({tip.source_file}:{tip.source_line})"
                )
                continue
            source = tip_tasks.source
            lines = source.field_lines.get(chains_mod.TASKS) if source else None
            for index, row in enumerate(tip_tasks.rows or []):
                if not isinstance(row, dict) or row.get("state") != "open":
                    continue
                task_id = row.get("id")
                shown = task_id if task_id else f"#{index + 1}"
                line = lines[index] if lines and index < len(lines) else None
                location = (
                    f"{source.source_file}:{line}"
                    if source is not None and line is not None
                    else f"{source.source_file}:{source.source_line}"
                    if source is not None
                    else ""
                )
                suffix = f" ({location})" if location else ""
                offenders.append(f"{label}: open task {shown}{suffix}")
    return sorted(offenders)


def _rule_captured_edits(project: Project) -> list[str]:
    """Living notes H8: a release blocks while any item is edited after
    captured -- the H3 diagnostic (`history.edited_after_captured`), read
    as it is, never recomputed. Offenders carry the same label
    `warn_edited_after_captured` prints (`item.id or item.key`). A store
    that refuses to be read yields no offenders here: the build's own
    warning already says the check declined (H3's "the build proceeds"
    posture), and a corrupt-key store is an error the floor refuses first.
    """
    try:
        findings = history_mod.edited_after_captured(project)
    except (history_mod.HistoryError, OSError):
        return []
    local = {id(item) for item in project.local_items}
    return sorted(
        {
            finding.item.id or finding.item.key
            for finding in findings
            if id(finding.item) in local
        }
    )


def _inline_calc_local_items(
    project: Project, diagnostic, local: set[int]
) -> list[Item]:
    """Local items owning a stale inline-calc warning, including permanently
    id-less continuations.

    A warning's display id is the normal lookup. An id-less item has
    ``item_id=""``, and ``item_by_id("")`` is deliberately None, so invert the
    build's location rule: a Markdown span is located anywhere inside its
    body range, while a list-file ``body:`` key reports the item's source
    line. Matching the whole body range is required for a continuation whose
    span is not the first body line. Matches are intentionally plural:
    duplicate-source handles can put two items at the same location, and each
    owns its warning.
    """

    def local_only(matches: list[Item]) -> list[Item]:
        return [item for item in matches if id(item) in local]

    if diagnostic.item_id:
        item = project.item_by_id(diagnostic.item_id)
        return local_only([item]) if item is not None else []
    if not diagnostic.file or diagnostic.line is None:
        return []
    return [
        item
        for item in project.local_items
        if item.source_file == diagnostic.file
        and item.id == diagnostic.item_id
        and (
            (
                item.body_line is not None
                and item.body_line
                <= diagnostic.line
                < item.body_line + len(item.body.splitlines())
            )
            or (item.body_line is None and diagnostic.line == item.source_line)
        )
    ]


def _inline_calc_span(diagnostic) -> str:
    """The warning's own head, "inline calc Vout", is the span name."""
    return diagnostic.message.split(": ", 1)[0]


def _inline_calc_location(diagnostic) -> str:
    if diagnostic.file and diagnostic.line is not None:
        return f" ({diagnostic.file}:{diagnostic.line})"
    return ""


def _unreadable_history_gate_line(exc: Exception) -> str:
    """One gate-table-safe line naming the store the gate failed closed on.

    History errors can include multi-line parser context; the gate row must
    stay one row, and the CLI joins offenders with ", ", so the error text
    is whitespace-collapsed. The store is named by its location relative to
    the project root, the path the author can check."""
    detail = " ".join(str(exc).split())
    store = history_mod.HISTORY_DIR.replace(os.sep, "/")
    return (
        f"stale inline-calc gate: cannot read the history store {store} "
        f"({detail}) -- failing closed"
    )


def _rule_inline_calc_results(project: Project) -> list[str]:
    """Inline calc freshness (docs/design/inline-calc.md §2, decided Q5): a
    release blocks while an editable item carries a stale stored result --
    the build's own warning (`build.py:_run_inline_span`, tagged
    `model.INLINE_CALC_STALE`), read as it is, never recomputed. Offenders
    name the item, the span, and the span's line ("LOG-001: inline calc Vout
    (items/log.md:7)"), so the failure is clickable where the CLI is. An
    id-less continuation has no display id on its diagnostic, so lookup falls
    back to the body range containing that line (list-file bodies report the
    item's source line) and the offender names its key. A coded stale warning
    that resolves to no local item fails closed too, so the gate cannot turn
    a resolver miss into a silent exemption.

    The exemptions are the design's, read narrowly: an item the build locks
    (a build seal, `seal.is_sealed`) and an item frozen into captured history
    are not editable prose a release can demand fresher. The history half
    uses `history.capture_index`'s edited flag, not merely its presence: only
    an unedited capture whose live digest still matches the snapshot (flag
    false) is
    frozen. A post-capture edit leaves the live item editable, so its stale
    warning remains a release offender -- `captured_edits` defaults off and
    cannot be relied on to catch that prose. Imported items' stale spans are
    the other project's problem, skipped like every other rule. Unlike
    `_rule_captured_edits`, this rule fails CLOSED when the history store
    cannot be read and it has stale spans to adjudicate: a silent exemption
    would let a stale editable result pass precisely when the tool cannot
    prove the frozen-text exemption. Sealed items remain exempt by their seal,
    imported spans by scope, and a broken store with no inline-calc work is
    not this rule's business. In the fail-closed case the offender list opens
    with one line naming the unreadable store and the cause, so a span that
    was capture-exempt while the store was readable reads as "the gate could
    not prove the exemption", not as "my capture expired".
    """
    stale = [d for d in project.warnings if d.code == model.INLINE_CALC_STALE]
    if not stale:
        return []
    local = {id(item) for item in project.local_items}
    store_line: str | None = None
    try:
        frozen_captures = {
            key
            for key, (_event, edited) in history_mod.capture_index(project).items()
            if not edited
        }
    except (history_mod.HistoryError, OSError) as exc:
        # Fail closed: the frozen-text exemption is unprovable, so no capture
        # exempts anything and every editable stale span is adjudicated as
        # if it had no capture at all.
        frozen_captures = set()
        store_line = _unreadable_history_gate_line(exc)
    offenders: set[str] = set()
    for diagnostic in stale:
        items = _inline_calc_local_items(project, diagnostic, local)
        span = _inline_calc_span(diagnostic)
        location = _inline_calc_location(diagnostic)
        if not items:
            if diagnostic.item_id and project.item_by_id(diagnostic.item_id):
                continue
            offenders.add(f"{span}: did not resolve to a local item{location}")
            continue
        for item in items:
            if seal_mod.is_sealed(project, item) or (
                item.key and item.key in frozen_captures
            ):
                continue
            # The warning's own head, "inline calc Vout", is the span name.
            offenders.add(f"{item.id or item.key}: {span}{location}")
    if store_line is not None and offenders:
        return [store_line, *sorted(offenders)]
    return sorted(offenders)


_RULES: dict[str, Callable[[Project], list[str]]] = {
    "draft_items": _rule_draft_items,
    "unpinned_citations": _rule_unpinned_citations,
    "missing_kept_copies": _rule_missing_kept_copies,
    "uncovered_requirements": _rule_uncovered_requirements,
    "unverified_requirements": _rule_unverified_requirements,
    "info_check_failures": _rule_info_check_failures,
    "unaccepted_board_moves": _rule_unaccepted_board_moves,
    "unaccepted_workspace_moves": _rule_unaccepted_workspace_moves,
    "open_tasks": _rule_open_tasks,
    "captured_edits": _rule_captured_edits,
    "inline_calc_results": _rule_inline_calc_results,
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
    place the configured rules are actually evaluated."""
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
    status: str  # "stamped" | "unchanged" | "conflict" | "gate_failed" | "unwritable"
    path: str = ""
    item_count: int = 0
    stamped_at: str = ""
    stamped_by: str = ""
    gate_results: list[GateRuleResult] = field(default_factory=list)
    conflict_detail: str = ""
    # Project-relative baseline path, set only for status="unwritable": the
    # file the filesystem would not accept. The CLI turns it into a refusal
    # naming the file; nothing was stamped, so there is no `stamped_at` to
    # report either.
    refusal: str = ""
    # The `OSError` behind that refusal (`BaselineUnwritable.cause`), when the
    # refusal came from a caught write. The CLI's parenthetical follows it:
    # `(read-only tree?)` is a claim only the permission errnos earn, and a
    # full disk stamped as a permission hunt is DIAG-WORD-008's false hint
    # (see model.destination_refusal). A refusal with no cause in hand keeps
    # the marker.
    refusal_cause: OSError | None = None
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
    try:
        path = _save_baseline_file(project, data)
    except BaselineUnwritable as exc:
        # Not a degraded outcome: `revision`/`release` exist to write this
        # one file, and the whole value of the command is that a stamp which
        # happened is durable and named. A stamp that did not happen reported
        # as one that did is the exact failure this refuses to commit -- so
        # the caller is told the path and refuses rather than printing
        # "stamped".
        return StampOutcome(
            kind=kind, name=name, status="unwritable",
            path=baseline_path(project, name), item_count=len(items_map),
            gate_results=gate_results, refusal=exc.rel, refusal_cause=exc.cause,
        )
    # Living notes H9: snapshot events beside the baseline (plan §H9;
    # docs/design/living-notes.md §4) -- one per keyed item, so the site
    # disclosure answers "what did this item say at `name`?" from the store.
    # The baseline file is the gate artifact and is already on disk: a store
    # failure must not claim the stamp did not happen (it did), and the
    # writer's rollback means it cannot leave a baseline whose events cover
    # only some of its items -- so a swallowed failure warns, loudly, and
    # the stamp stands. A failed snapshot write is deliberately NOT retried
    # on a re-stamp: the re-stamp returns "unchanged" on a matching content
    # hash and never reaches this line, and backfilling there would snapshot
    # the OLD baseline with TODAY's content the moment an unhashed
    # (`timeline`/`ignore`) field diverged -- the exact fabrication this
    # phase exists to prevent. The warning says so; to record snapshots for
    # that baseline, re-stamp under a new name. `write=False` never reaches
    # this line.
    try:
        history_mod.baseline_events(project, kind, name, occurred_at=stamped_at)
    except (history_mod.HistoryError, OSError) as exc:
        project.warn(
            f"stamped {kind} baseline {name!r}, but its history snapshot "
            f"events were not written: {exc} -- the baseline file is "
            "complete; re-running this stamp records nothing (the name is "
            "stamped, and a re-stamp never backfills: it would snapshot the "
            "old baseline with today's content), so re-stamp under a new "
            "name to record the snapshots",
            file=os.path.relpath(path, project.root).replace("\\", "/"),
        )
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
    # Finding 35 §4: for a `changed` item whose cross-item calc references
    # resolved to a different value than at stamp time, one line per moved
    # reference -- `referenced DEC-PWR-001.V_in: 12 V (...) -> 11.4 V (...)` --
    # so a dependent marked changed with nothing in its own text to point at
    # says what moved. Empty for a baseline stamped before this was recorded.
    moved_refs: dict[str, list[str]] = field(default_factory=dict)


def _moved_refs(
    project: Project, changed: list[str], current: dict[str, dict],
    old_entries: dict[str, dict],
) -> dict[str, list[str]]:
    """The `referenced X.name: old -> new` lines for each changed item whose
    baseline entry recorded ``calc_refs`` (see build.calc_reference_snapshot).
    Silent for a baseline without them -- a missing record is not a claim that
    nothing moved, and inventing an old value would be worse than saying
    nothing. A reference present now but not at stamp time is the item's own
    edit, not an upstream move, and is not listed."""
    by_key = {i.key: i for i in project.local_items if i.key}
    now_by_id = {}
    for record_id, entry in current.items():
        identity = keys_mod.baseline_identity(record_id, entry)
        now_by_id[identity[1] if identity is not None else record_id] = entry
    out: dict[str, list[str]] = {}
    for item_id in changed:
        old_refs = old_entries.get(item_id, {}).get("calc_refs") or {}
        new_refs = now_by_id.get(item_id, {}).get("calc_refs") or {}
        lines = []
        for ref, new_text in new_refs.items():
            old_text = old_refs.get(ref)
            if old_text is None or old_text == new_text:
                continue
            target_ref, _, name = ref.rpartition(".")
            target = by_key.get(target_ref) or project.item_by_id(target_ref)
            shown = f"{target.id}.{name}" if target is not None and target.id else ref
            lines.append(f"referenced {shown}: {old_text} -> {new_text}")
        if lines:
            out[item_id] = lines
    return out


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
    calc block and no inline span *now* (its arithmetic was removed, which
    is itself a change, not staleness -- calc_hash_for returning None is a
    real "no" here, not a missing-data case, since a present
    ``old["calc_hash"]`` already proved the item had a probe -- fence block
    and/or inline span -- at baseline time).
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

    Migrates `baseline` to the current hash format first, in place (§5) --
    an entry recorded under an older format (pre-keys, which records no
    format at all, through format 5) would otherwise show as "changed"
    purely because the hash *definition* moved, which isn't the question
    this function exists to answer. `write` threads
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
        moved_refs=_moved_refs(project, changed, current, old_entries),
        # Anything the migration named but no current item matched stays in
        # the report under the id it was recorded with -- dropping it would
        # silently bury an entry we already know we can't check.
        uncomparable=sorted(set(uncomparable) | uncomparable_pending),
    )
