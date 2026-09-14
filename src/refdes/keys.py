"""Surrogate keys: opaque, immutable per-item identity (docs/design/keys.md).

Implements key minting plus the context-free portions of the corruption lint:
well-formedness and uniqueness within one resolution scope. Link-target
resolution diagnostics live in build.py, beside the resolver they replace.

An item's key, once minted, is never regenerated and never rewritten. Nothing
here ever changes an existing `item.key`.
"""

from __future__ import annotations

import os
import secrets
from collections import defaultdict

from . import ids as ids_mod
from .model import Item, Project

ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32 -- i, l, o, u excluded
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
    """Report §6 Layers 1-2 for every item in this resolution scope.

    Pending items participate too: they already own durable keys even though
    they do not yet have display ids and cannot be linked to until allocation.
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
        item_loc = f"{item.source_file}:{item.source_line}"
        owner_loc = f"{owner.source_file}:{owner.source_line}"
        project.error(
            f"key {item.key!r} on {item_name} ({item_loc}) is already used by "
            f"{owner_name} ({owner_loc}). A key is unique by construction; two "
            "items sharing one means a line was duplicated. Delete the key "
            "from one of them and rebuild — it will be re-minted.",
            file=item.source_file,
            line=item.source_line,
            item_id=item.id or None,
        )


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
    candidates = [item for item in project.pending if not item.key]
    candidates += [item for item in project.local_items if not item.key]
    if not candidates:
        return []

    if not write:
        _report_missing(project, len(candidates))
        return []

    assignments = [(item, mint()) for item in candidates]

    by_file: dict[str, list[tuple[Item, str]]] = defaultdict(list)
    for item, new_key in assignments:
        by_file[item.source_file].append((item, new_key))

    failed: set[int] = set()

    for rel, entries in by_file.items():
        path = os.path.join(project.root, rel)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()

        # Bottom-up so earlier line numbers stay valid as we insert -- same
        # discipline ids.allocate() and former_ids.confirm() use for the
        # same reason.
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

        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(newline.join(lines) + newline)

    written = [(item, new_key) for item, new_key in assignments if id(item) not in failed]
    for item, new_key in written:
        item.key = new_key

    still_missing = len(candidates) - len(written)
    if still_missing:
        _report_missing(project, still_missing)

    return written


def _report_missing(project: Project, count: int) -> None:
    """One project-level info line, not one per item (§2). `info`, not
    `warning`: under `--no-write` this is the expected, correct state, and a
    warning that fires on every CI run is a warning people learn to ignore."""
    noun = "item has" if count == 1 else "items have"
    project.info(
        f"{count} {noun} no key yet; the next writable command will mint "
        "them. Run without --no-write, or see docs/design/keys.md."
    )
