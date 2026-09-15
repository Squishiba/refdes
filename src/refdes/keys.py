"""Surrogate keys: opaque, immutable per-item identity (docs/design/keys.md).

Implements key minting plus the corruption lint's context-free well-formedness
and uniqueness checks and its baseline-backed identity checks. Link-target
resolution diagnostics live in build.py, beside the resolver they replace.

An item's key, once minted, is never regenerated and never rewritten. Nothing
here ever changes an existing `item.key`.
"""

from __future__ import annotations

import os
import secrets
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from . import ids as ids_mod
from .model import Diagnostic, Item, Project
from .parse import yaml_safe_load

if TYPE_CHECKING:
    from .revise import FileRewrite

ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32 -- i, l, o, u excluded
ADOPTION_MARKER = ".refdes/keys-adopted.yaml"
MANIFEST_SOURCE = "the membership manifest (.refdes/boards.yaml)"
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}

DATA_LEN = 10
KEY_LEN = DATA_LEN + 1

# ---------------------------------------------------------------------------
# The Damm quasigroup table -- WIRE FORMAT, FIXED FOREVER.
#
# This is a permanent compatibility contract from the moment the first key is
# minted against it: every key this tool has ever written, in every project,
# has a check character computed from exactly this table. Changing a single
# entry does not "improve" the algorithm -- it invalidates every key minted
# under the old one, silently, because a corrupted-vs-valid verdict would
# flip for keys nobody touched. If the algorithm is ever revisited, that is a
# new table under a new name, not an edit to this one.
#
# It is a literal constant, not something computed at import time from a
# generator function, precisely so there is no algorithm left to audit (or
# accidentally change) at runtime -- only a fixed 32x32 array. It happens to
# have been constructed from GF(32) arithmetic (x*y = 2 . (x XOR y), field
# multiplication modulo the primitive polynomial x^5+x^2+1, field elements
# labelled 0..31 in polynomial-coefficient order) and then verified and
# frozen here; the construction is not part of the contract, only the
# resulting table is. test_keys.py's property test checks the table itself,
# independent of how it was built, which is the point: a subtly wrong table
# would silently lose exactly the property Damm was chosen for, and nobody
# could tell by eye.
#
# Totally anti-symmetric quasigroup of order 32, zero diagonal:
#   for all c, x, y: (c*x)*y == (c*y)*x  implies  x == y
#   for all x:        x*x == 0
DAMM_TABLE: tuple[tuple[int, ...], ...] = (
    ( 0,  2,  4,  6,  8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30,  5,  7,  1,  3, 13, 15,  9, 11, 21, 23, 17, 19, 29, 31, 25, 27),
    ( 2,  0,  6,  4, 10,  8, 14, 12, 18, 16, 22, 20, 26, 24, 30, 28,  7,  5,  3,  1, 15, 13, 11,  9, 23, 21, 19, 17, 31, 29, 27, 25),
    ( 4,  6,  0,  2, 12, 14,  8, 10, 20, 22, 16, 18, 28, 30, 24, 26,  1,  3,  5,  7,  9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31),
    ( 6,  4,  2,  0, 14, 12, 10,  8, 22, 20, 18, 16, 30, 28, 26, 24,  3,  1,  7,  5, 11,  9, 15, 13, 19, 17, 23, 21, 27, 25, 31, 29),
    ( 8, 10, 12, 14,  0,  2,  4,  6, 24, 26, 28, 30, 16, 18, 20, 22, 13, 15,  9, 11,  5,  7,  1,  3, 29, 31, 25, 27, 21, 23, 17, 19),
    (10,  8, 14, 12,  2,  0,  6,  4, 26, 24, 30, 28, 18, 16, 22, 20, 15, 13, 11,  9,  7,  5,  3,  1, 31, 29, 27, 25, 23, 21, 19, 17),
    (12, 14,  8, 10,  4,  6,  0,  2, 28, 30, 24, 26, 20, 22, 16, 18,  9, 11, 13, 15,  1,  3,  5,  7, 25, 27, 29, 31, 17, 19, 21, 23),
    (14, 12, 10,  8,  6,  4,  2,  0, 30, 28, 26, 24, 22, 20, 18, 16, 11,  9, 15, 13,  3,  1,  7,  5, 27, 25, 31, 29, 19, 17, 23, 21),
    (16, 18, 20, 22, 24, 26, 28, 30,  0,  2,  4,  6,  8, 10, 12, 14, 21, 23, 17, 19, 29, 31, 25, 27,  5,  7,  1,  3, 13, 15,  9, 11),
    (18, 16, 22, 20, 26, 24, 30, 28,  2,  0,  6,  4, 10,  8, 14, 12, 23, 21, 19, 17, 31, 29, 27, 25,  7,  5,  3,  1, 15, 13, 11,  9),
    (20, 22, 16, 18, 28, 30, 24, 26,  4,  6,  0,  2, 12, 14,  8, 10, 17, 19, 21, 23, 25, 27, 29, 31,  1,  3,  5,  7,  9, 11, 13, 15),
    (22, 20, 18, 16, 30, 28, 26, 24,  6,  4,  2,  0, 14, 12, 10,  8, 19, 17, 23, 21, 27, 25, 31, 29,  3,  1,  7,  5, 11,  9, 15, 13),
    (24, 26, 28, 30, 16, 18, 20, 22,  8, 10, 12, 14,  0,  2,  4,  6, 29, 31, 25, 27, 21, 23, 17, 19, 13, 15,  9, 11,  5,  7,  1,  3),
    (26, 24, 30, 28, 18, 16, 22, 20, 10,  8, 14, 12,  2,  0,  6,  4, 31, 29, 27, 25, 23, 21, 19, 17, 15, 13, 11,  9,  7,  5,  3,  1),
    (28, 30, 24, 26, 20, 22, 16, 18, 12, 14,  8, 10,  4,  6,  0,  2, 25, 27, 29, 31, 17, 19, 21, 23,  9, 11, 13, 15,  1,  3,  5,  7),
    (30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10,  8,  6,  4,  2,  0, 27, 25, 31, 29, 19, 17, 23, 21, 11,  9, 15, 13,  3,  1,  7,  5),
    ( 5,  7,  1,  3, 13, 15,  9, 11, 21, 23, 17, 19, 29, 31, 25, 27,  0,  2,  4,  6,  8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30),
    ( 7,  5,  3,  1, 15, 13, 11,  9, 23, 21, 19, 17, 31, 29, 27, 25,  2,  0,  6,  4, 10,  8, 14, 12, 18, 16, 22, 20, 26, 24, 30, 28),
    ( 1,  3,  5,  7,  9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31,  4,  6,  0,  2, 12, 14,  8, 10, 20, 22, 16, 18, 28, 30, 24, 26),
    ( 3,  1,  7,  5, 11,  9, 15, 13, 19, 17, 23, 21, 27, 25, 31, 29,  6,  4,  2,  0, 14, 12, 10,  8, 22, 20, 18, 16, 30, 28, 26, 24),
    (13, 15,  9, 11,  5,  7,  1,  3, 29, 31, 25, 27, 21, 23, 17, 19,  8, 10, 12, 14,  0,  2,  4,  6, 24, 26, 28, 30, 16, 18, 20, 22),
    (15, 13, 11,  9,  7,  5,  3,  1, 31, 29, 27, 25, 23, 21, 19, 17, 10,  8, 14, 12,  2,  0,  6,  4, 26, 24, 30, 28, 18, 16, 22, 20),
    ( 9, 11, 13, 15,  1,  3,  5,  7, 25, 27, 29, 31, 17, 19, 21, 23, 12, 14,  8, 10,  4,  6,  0,  2, 28, 30, 24, 26, 20, 22, 16, 18),
    (11,  9, 15, 13,  3,  1,  7,  5, 27, 25, 31, 29, 19, 17, 23, 21, 14, 12, 10,  8,  6,  4,  2,  0, 30, 28, 26, 24, 22, 20, 18, 16),
    (21, 23, 17, 19, 29, 31, 25, 27,  5,  7,  1,  3, 13, 15,  9, 11, 16, 18, 20, 22, 24, 26, 28, 30,  0,  2,  4,  6,  8, 10, 12, 14),
    (23, 21, 19, 17, 31, 29, 27, 25,  7,  5,  3,  1, 15, 13, 11,  9, 18, 16, 22, 20, 26, 24, 30, 28,  2,  0,  6,  4, 10,  8, 14, 12),
    (17, 19, 21, 23, 25, 27, 29, 31,  1,  3,  5,  7,  9, 11, 13, 15, 20, 22, 16, 18, 28, 30, 24, 26,  4,  6,  0,  2, 12, 14,  8, 10),
    (19, 17, 23, 21, 27, 25, 31, 29,  3,  1,  7,  5, 11,  9, 15, 13, 22, 20, 18, 16, 30, 28, 26, 24,  6,  4,  2,  0, 14, 12, 10,  8),
    (29, 31, 25, 27, 21, 23, 17, 19, 13, 15,  9, 11,  5,  7,  1,  3, 24, 26, 28, 30, 16, 18, 20, 22,  8, 10, 12, 14,  0,  2,  4,  6),
    (31, 29, 27, 25, 23, 21, 19, 17, 15, 13, 11,  9,  7,  5,  3,  1, 26, 24, 30, 28, 18, 16, 22, 20, 10,  8, 14, 12,  2,  0,  6,  4),
    (25, 27, 29, 31, 17, 19, 21, 23,  9, 11, 13, 15,  1,  3,  5,  7, 28, 30, 24, 26, 20, 22, 16, 18, 12, 14,  8, 10,  4,  6,  0,  2),
    (27, 25, 31, 29, 19, 17, 23, 21, 11,  9, 15, 13,  3,  1,  7,  5, 30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10,  8,  6,  4,  2,  0),
)


def check_char(data: str) -> str:
    """The Damm check character for a 10-character data string."""
    interim = 0
    for ch in data:
        interim = DAMM_TABLE[interim][_INDEX[ch]]
    return ALPHABET[interim]


def mint() -> str:
    """A fresh 11-character key: 10 random data characters plus a check
    character. `secrets`, not `random` -- not because an adversary matters,
    but so no seeded generator can make two projects mint the same sequence,
    and it costs nothing (docs/design/keys.md §1)."""
    data = "".join(ALPHABET[b % 32] for b in secrets.token_bytes(DATA_LEN))
    return data + check_char(data)


def malformed_key_message(key: str, *, context: str = "") -> str | None:
    """Return the Layer-1 corruption diagnostic for ``key``, if malformed.

    ``context`` identifies a composite link occurrence; an item's own key
    declaration leaves it empty. Length and alphabet must be checked before
    computing the check character because ``check_char`` deliberately assumes
    valid data.
    """
    if len(key) != KEY_LEN:
        reason = f"expected exactly {KEY_LEN} characters"
        expected = None
    elif any(ch not in _INDEX for ch in key):
        reason = "contains a character outside the key alphabet"
        expected = None
    else:
        expected = check_char(key[:DATA_LEN])
        if key[-1] == expected:
            return None
        reason = "check character mismatch"

    message = (
        f"key {key!r}{context} is malformed: {reason}. A key is written by "
        "refdes and never edited by hand, so this line has been corrupted — "
        "restore it from git rather than guessing."
    )
    if expected is not None:
        message += f" (Expected check character {expected!r}.)"
    return message


def validate(project: Project) -> None:
    """Report §6 Layers 1, 2, and 4 for this project.

    Layers 1-2 cover the whole resolution scope. Pending items participate
    too: they already own durable keys even though they do not yet have
    display ids and cannot be linked to until allocation. Layer 4 compares
    local items with the most recent revision or release baseline.
    """
    items = [*project.items.values(), *project.pending]
    by_key: dict[str, Item] = {}

    for item in items:
        if not item.key:
            continue

        malformed = malformed_key_message(item.key)
        if malformed is not None:
            project.error(
                malformed,
                file=item.source_file,
                line=item.source_line,
                item_id=item.id or None,
            )

        owner = by_key.get(item.key)
        if owner is None:
            by_key[item.key] = item
            continue

        item_name = item.id or "an item without a display id"
        owner_name = owner.id or "an item without a display id"
        item_loc = (
            f"import {item.origin!r}" if item.external
            else f"local {item.source_file}:{item.source_line}"
        )
        owner_loc = (
            f"import {owner.origin!r}" if owner.external
            else f"local {owner.source_file}:{owner.source_line}"
        )
        project.error(
            f"key {item.key!r} on {item_name} ({item_loc}) is already used by "
            f"{owner_name} ({owner_loc}). A key is unique by construction; two "
            "items sharing one means a line was duplicated. Delete the key "
            "from one of them and rebuild — it will be re-minted.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id or None,
        )

    _validate_deleted_keys(project)
    _validate_latest_baseline(project)


def _validate_deleted_keys(project: Project) -> None:
    """Report a hand-deleted key as its own error (§6, 2026-09-15).

    Distinct from "key changed": nothing rewrote the key, the line was
    deleted. Minting is skipped for these items, so this is the only thing
    standing between a hand-deleted key and a silently re-minted one.
    """
    for record in deleted_key_records(project):
        project.error(
            deleted_key_message(record),
            file=record.item.source_file,
            line=record.item.source_line,
            item_id=record.item.id,
        )


def baseline_identity(record_id: str, entry: dict) -> tuple[str, str] | None:
    """Return (key, display id) for keyed entries in either baseline shape.

    Baselines remain display-id keyed until `refdes keys adopt` lands, so new
    stamps carry `key` inside each entry. The adopted shape specified by §5
    instead keys the map by surrogate and carries `id` inside. Supporting
    both here keeps the lint valid across that eventual clean cutover.
    Pre-keys entries have neither marker and deliberately return None.
    """
    entry_key = entry.get("key")
    if isinstance(entry_key, str) and entry_key:
        return entry_key, str(entry.get("id", record_id))
    display_id = entry.get("id")
    if isinstance(display_id, str) and display_id:
        return record_id, display_id
    return None


@dataclass
class SurrogateStoragePlan:
    """Write-free §5 storage conversion for one baseline and one seal file."""

    baseline_items: dict[str, dict] = field(default_factory=dict)
    seals: dict[str, object] = field(default_factory=dict)
    baseline_uncomparable: list[str] = field(default_factory=list)
    seal_uncomparable: list[str] = field(default_factory=list)


def item_for_baseline_entry(project: Project, record_id: str, entry: dict) -> Item | None:
    identity = baseline_identity(record_id, entry)
    if identity is None:
        return project.item_by_id(record_id)
    key, _display_id = identity
    return next((item for item in project.local_items if item.key == key), None)


def hash_in_format(item: Item, project: Project, hash_format: int) -> str | None:
    """item's content hash exactly as hash-format ``hash_format`` would
    compute it right now, or ``None`` if ``hash_format`` isn't one this
    build understands.

    The one shared reconstruction every hash-format migration site uses --
    lifecycle.migrate_hash_format, seal._matches_sealed_hash, and
    plan_surrogate_storage below (which `refdes keys adopt` calls through)
    -- so "does this stored hash still describe this item's current
    content" is answered identically everywhere (docs/design/keys.md §5(c)).
    A single shared helper, not four copies that could drift.
    """
    from . import build as build_mod

    if hash_format == build_mod.HASH_FORMAT:
        return item.content_hash
    if hash_format in (1, 2):
        return build_mod.hash_for_format(item, project, hash_format)
    return None


def plan_surrogate_storage(
    project: Project,
    baseline_items: Mapping[str, Mapping],
    seals: Mapping[str, object],
) -> SurrogateStoragePlan:
    """Plan §5's key-keyed baseline/seal storage without mutating or writing.

    Already key-keyed entries are copied through, making the operation
    idempotent. A display-id-keyed entry moves only when its live item is
    identified and its stored hash still describes that item's current
    content under the entry's recorded format. Format-1 hashes are then
    carried to the current format. Anything else remains display-id keyed,
    is explicitly marked format 1, and is reported as uncomparable.
    """
    from . import build as build_mod

    plan = SurrogateStoragePlan()
    for record_id, original in baseline_items.items():
        entry = dict(original)
        if isinstance(entry.get("id"), str) and entry["id"]:
            plan.baseline_items[record_id] = entry
            continue

        display_id = record_id
        item = item_for_baseline_entry(project, record_id, entry)
        try:
            hash_format = int(entry.get("hash_format", 1))
        except (TypeError, ValueError):
            hash_format = -1
        expected = hash_in_format(item, project, hash_format) if item is not None else None
        if item is not None and item.key and expected == entry.get("hash"):
            converted = dict(entry)
            converted.pop("key", None)
            converted["id"] = display_id
            converted["hash"] = item.content_hash
            converted["hash_format"] = build_mod.HASH_FORMAT
            plan.baseline_items[item.key] = converted
            continue

        entry["hash_format"] = 1
        plan.baseline_items[record_id] = entry
        plan.baseline_uncomparable.append(display_id)

    by_display_id = {item.id: item for item in project.local_items}
    for record_id, original in seals.items():
        if isinstance(original, Mapping):
            entry = dict(original)
            if isinstance(entry.get("id"), str) and entry["id"]:
                plan.seals[record_id] = entry
                continue
            recorded_hash = entry.get("hash")
            try:
                hash_format = int(entry.get("hash_format", 1))
            except (TypeError, ValueError):
                hash_format = -1
        else:
            entry = {"hash": original}
            recorded_hash = original
            hash_format = 0  # unversioned seals may contain either format

        item = by_display_id.get(record_id)
        matched_format = hash_format
        if item is not None and hash_format == 0:
            # Legacy scalar seal, no format marker of its own -- try the
            # newest definition first, then each older one (docs/design/
            # keys.md §5(c)), same "newest wins" posture as everywhere else
            # a format has to be inferred rather than read off the entry.
            for candidate in (build_mod.HASH_FORMAT, 2, 1):
                if recorded_hash == hash_in_format(item, project, candidate):
                    matched_format = candidate
                    break
        expected = (
            hash_in_format(item, project, matched_format)
            if item is not None and matched_format in (1, 2, build_mod.HASH_FORMAT)
            else None
        )
        if item is not None and item.key and expected == recorded_hash:
            converted = dict(entry)
            converted["id"] = record_id
            converted["hash"] = item.content_hash
            converted["hash_format"] = build_mod.HASH_FORMAT
            plan.seals[item.key] = converted
            continue

        entry["hash_format"] = 1
        plan.seals[record_id] = entry
        plan.seal_uncomparable.append(record_id)

    plan.baseline_items = dict(sorted(plan.baseline_items.items()))
    plan.seals = dict(sorted(plan.seals.items()))
    plan.baseline_uncomparable.sort()
    plan.seal_uncomparable.sort()
    return plan


@dataclass
class DeletedKey:
    """A keyless local item whose key is recorded in an existing record.

    The record is what distinguishes a hand-deleted `key:` line from an item
    that never had one: only a record can say what the old key was.
    """

    item: Item
    key: str
    source: str
    conflicts: list[tuple[str, str]] = field(default_factory=list)


def _keyed_record_map(entries: Mapping, source: str) -> dict[str, tuple[str, str]]:
    """display id -> (key, source) for a key-keyed record map.

    Seals and membership entries adopt the §5 shape (record id is the
    surrogate, `id` inside is the display id) once a project has been
    adopted; legacy display-id-keyed entries carry no key evidence and are
    skipped, exactly like a pre-keys baseline entry in `baseline_identity`.
    """
    records: dict[str, tuple[str, str]] = {}
    for record_id, value in entries.items():
        if not isinstance(value, Mapping):
            continue
        display_id = value.get("id")
        if not isinstance(display_id, str) or not display_id:
            continue
        records.setdefault(display_id, (str(record_id), source))
    return records


def _key_evidence_sources(project: Project) -> list[dict[str, tuple[str, str]]]:
    """Every record map that remembers an item's key, in precedence order.

    Baseline first (the Layer-4 authority), then the seal files, then the
    membership manifest. The first source that records an item's key is the
    one named in the diagnostic; the rest are consulted only to detect a
    disagreement worth telling the user about.
    """
    from . import boards as boards_mod
    from . import lifecycle
    from . import seal as seal_mod

    sources: list[dict[str, tuple[str, str]]] = []

    baseline = lifecycle.latest(lifecycle.list_baselines(project))
    if baseline is not None:
        records: dict[str, tuple[str, str]] = {}
        for record_id, entry in baseline.items.items():
            identity = baseline_identity(record_id, entry)
            if identity is None:
                continue
            old_key, display_id = identity
            records.setdefault(display_id, (old_key, f"baseline {baseline.name!r}"))
        sources.append(records)

    for board in sorted({""} | set(project.boards)):
        path = seal_mod.seal_path(project, board)
        if not os.path.isfile(path):
            continue
        rel = os.path.relpath(path, project.root).replace(os.sep, "/")
        sources.append(_keyed_record_map(seal_mod.load_seals(project, board), f"seal file {rel!r}"))

    manifest = boards_mod.load_manifest(project)
    membership = {}
    membership.update(_keyed_record_map(manifest.get("boards", {}), MANIFEST_SOURCE))
    membership.update(_keyed_record_map(manifest.get("workspaces", {}), MANIFEST_SOURCE))
    sources.append(membership)
    return sources


def deleted_key_records(project: Project) -> list[DeletedKey]:
    """Local items with no key whose key is still recorded elsewhere (§6).

    The display id must match a recorded key, the same rule Layer 4 applies
    before calling a missing key changed or deleted: source position and
    title similarity are never evidence on their own. A key still declared by
    a live item is not evidence of deletion either -- it belongs to that item.
    """
    candidates = [item for item in project.local_items if not item.key and item.id]
    if not candidates:
        return []
    live_keys = {item.key for item in project.local_items if item.key}
    sources = _key_evidence_sources(project)

    found: list[DeletedKey] = []
    for item in candidates:
        evidence = [
            record
            for source in sources
            if (record := source.get(item.id)) is not None
            and record[0] not in live_keys
        ]
        if not evidence:
            continue
        key, source = evidence[0]
        conflicts = [(k, s) for k, s in evidence[1:] if k != key]
        found.append(DeletedKey(item=item, key=key, source=source, conflicts=conflicts))
    return found


def deleted_key_message(record: DeletedKey) -> str:
    """The verbose §6 diagnostic for a hand-deleted key: what was lost,
    where the old key is recorded, and both remedies spelled out."""
    item = record.item
    head = "key deleted"
    if record.source.startswith("baseline "):
        head += f" since {record.source}"
    message = (
        f"{head}: was {record.key!r}, now no key is declared. The old key is "
        f"recorded for {item.id} in {record.source}. A key never disappears "
        f"legitimately: every reference and every baseline entry pointing at "
        f"{record.key!r}, and this item's history, now dangle."
    )
    if record.conflicts:
        disagreement = "; ".join(f"{k!r} in {s}" for k, s in record.conflicts)
        message += (
            f" The records disagree about the old key -- {disagreement} -- so "
            "check which one is right before restoring."
        )
    message += (
        f" Restore it by adding this line back to {item.source_file} at line "
        f"{item.source_line}: `key: {record.key}`. Or, if this really is a "
        "new, different item, give it a new display id so it is not mistaken "
        "for the old one -- a fresh key will then be minted for it."
    )
    return message


def report_deleted_keys(project: Project) -> list[DeletedKey]:
    """Warn at load time about every hand-deleted key (§6, 2026-09-15).

    Minting a replacement would be the destructive thing to do here: it makes
    every reference and history entry to the old key dangle and overwrites
    the evidence, so these items are deliberately left keyless and the build
    reports them.
    """
    records = deleted_key_records(project)
    for record in records:
        project.warn(
            deleted_key_message(record),
            file=record.item.source_file,
            line=record.item.source_line,
            item_id=record.item.id,
        )
    return records


def _validate_latest_baseline(project: Project) -> None:
    """Report §6 Layer 4 against the latest revision or release baseline."""
    from . import lifecycle

    baseline = lifecycle.latest(lifecycle.list_baselines(project))
    if baseline is None:
        return

    by_key = {item.key: item for item in project.local_items if item.key}
    by_display_id = {item.id: item for item in project.local_items}
    for record_id, entry in baseline.items.items():
        identity = baseline_identity(record_id, entry)
        if identity is None:
            continue
        old_key, display_id = identity
        if old_key in by_key:
            continue
        item = by_display_id.get(display_id)
        if item is None:
            continue

        if not item.key:
            # A keyless item is reported by the deleted-key check, which
            # names the record the old key came from and both remedies.
            continue
        message = (
            f"key changed since baseline {baseline.name!r}: was {old_key!r}, "
            f"now {item.key!r}. A key never changes legitimately. Every "
            "reference and every baseline entry pointing at the old key now "
            "dangles. Restore the old key; if the item really is a new one, "
            "delete the key line and let it be re-minted, and give it a new "
            "display id too."
        )
        project.error(
            message,
            file=item.source_file,
            line=item.source_line,
            item_id=item.id,
        )


def audit_historical_baselines(project: Project) -> list[Diagnostic]:
    """Report §6 Layer 5 for keyed entries older than the latest baseline.

    These are informational because a vanished key in old history may simply
    identify an item that was legitimately deleted. The standing Layer-4
    error covers only the latest baseline and is run separately by validate().
    """
    from . import lifecycle

    baselines = lifecycle.list_baselines(project)
    latest = lifecycle.latest(baselines)
    if latest is None:
        return []

    current_keys = {item.key for item in project.local_items if item.key}
    diagnostics: list[Diagnostic] = []
    for baseline in sorted(baselines, key=lambda b: (b.stamped_at, b.name)):
        if baseline is latest:
            continue
        for record_id, entry in sorted(baseline.items.items()):
            identity = baseline_identity(record_id, entry)
            if identity is None:
                continue
            old_key, display_id = identity
            if old_key in current_keys:
                continue
            project.info(
                f"older baseline {baseline.name!r} references key {old_key!r} "
                f"for {display_id}, which no current item declares. The item "
                "may have been deleted legitimately; this is audit information, "
                "not a build error."
            )
            diagnostics.append(project.diagnostics[-1])
    return diagnostics


@dataclass
class MintPlan:
    assignments: list[tuple[Item, str]] = field(default_factory=list)
    rewrites: list[FileRewrite] = field(default_factory=list)
    remaining: int = 0


def adoption_marker_path(project: Project) -> str:
    return os.path.join(project.root, *ADOPTION_MARKER.split("/"))


def is_adopted(project: Project) -> bool:
    """Whether the explicit adoption marker exists and declares adoption."""
    try:
        with open(adoption_marker_path(project), encoding="utf-8") as fh:
            marker = yaml_safe_load(fh)
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(marker, Mapping) and marker.get("adopted") is True


def missing_assignments(project: Project) -> list[tuple[Item, str]]:
    """Mint in-memory assignments for every keyless local or pending item.

    An item whose deleted key is still recorded in a baseline, seal, or
    membership entry is deliberately *not* a candidate: minting a replacement
    would leave every reference and history entry to the old key dangling and
    overwrite the only evidence of what was lost (`deleted_key_records`).
    """
    protected = {id(record.item) for record in deleted_key_records(project)}
    candidates = [item for item in project.pending if not item.key]
    candidates += [
        item
        for item in project.local_items
        if not item.key and id(item) not in protected
    ]
    return [(item, mint()) for item in candidates]


def plan_missing(
    project: Project,
    source_texts: Mapping[str, str] | None = None,
    assignments: list[tuple[Item, str]] | None = None,
) -> MintPlan:
    """Plan key assignments and source rewrites without writing any file.

    ``source_texts`` lets a transaction layer compose link expansion and key
    insertion while preserving the original serialization. Link expansion
    does not change line counts, so parsed source positions remain valid.
    """
    from .revise import FileRewrite

    planned_assignments = (
        missing_assignments(project) if assignments is None else assignments
    )
    candidates = [item for item, _new_key in planned_assignments]
    plan = MintPlan(assignments=list(planned_assignments))
    if not candidates:
        return plan

    by_file: dict[str, list[tuple[Item, str]]] = defaultdict(list)
    for item, new_key in plan.assignments:
        by_file[item.source_file].append((item, new_key))

    failed: set[int] = set()
    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        if source_texts is not None and rel in source_texts:
            text = source_texts[rel]
        else:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        # Bottom-up so earlier line numbers stay valid as keys are inserted --
        # the same discipline ids.allocate() and former_ids.confirm() use for
        # the same reason.
        for item, new_key in sorted(entries, key=lambda e: e[0].source_line, reverse=True):
            if rel.endswith(".md"):
                lines = ids_mod.insert_into_markdown(lines, item.source_line, f"key: {new_key}")
            else:
                updated = ids_mod.insert_into_list(lines, item.source_line, "key", new_key)
                if updated is None:
                    project.error(
                        f"could not write key {new_key} back into the source",
                        file=rel, line=item.source_line,
                    )
                    failed.add(id(item))
                    continue
                lines = updated

        after = newline.join(lines) + newline
        if after != text:
            plan.rewrites.append(FileRewrite(path=path, rel=rel, before=text, after=after))

    plan.assignments = [
        (item, new_key)
        for item, new_key in plan.assignments
        if id(item) not in failed
    ]
    plan.remaining = len(candidates) - len(plan.assignments)
    return plan


def mint_missing(project: Project, write: bool = True) -> list[tuple[Item, str]]:
    """Assign a key to every local item that doesn't have one yet, and write
    it back into the source file.

    Called by `cli._load()` for every command that loads the project (§2):
    minting a key has none of the properties that make id allocation a
    deliberate, separate step -- no ledger, no coordination, nothing burned,
    nobody ever reads it -- so it happens as a side effect of loading, the
    same posture the project already takes with `.refdes/schema.json`.

    A key is independent of whether the item has a display id yet -- a
    pending item (still in `project.pending`) gets one too, same as an item
    already carrying a real id. `write=False` (the global `--no-write` flag)
    skips minting entirely rather than assigning keys that would vanish at
    the end of the run: a key is only durable once persisted, and re-minting
    a fresh one on every read-only run would make the same item resolve to a
    different key from one invocation to the next.
    """
    report_deleted_keys(project)
    assignments = missing_assignments(project)
    if not assignments:
        return []
    if not write:
        _report_missing(project, len(assignments))
        return []

    from .revise import write_rewrites

    plan = plan_missing(project, assignments=assignments)
    write_rewrites(plan.rewrites)
    for item, new_key in plan.assignments:
        item.key = new_key
    if plan.remaining:
        _report_missing(project, plan.remaining)
    return plan.assignments


def _report_missing(project: Project, count: int) -> None:
    """One project-level info line, not one per item (§2). `info`, not
    `warning`: under `--no-write` this is the expected, correct state, and a
    warning that fires on every CI run is a warning people learn to ignore."""
    noun = "item has" if count == 1 else "items have"
    project.info(
        f"{count} {noun} no key yet; the next writable command will mint "
        "them. Run without --no-write, or see docs/design/keys.md."
    )
