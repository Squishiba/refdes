"""Append-only enforcement for design log entries.

An engineering notebook is only worth anything if yesterday's page still says what
it said yesterday. Entries are sealed the first time they are built; after that,
changing one is a build error. Corrections are made by appending a new entry that
`amends` the old one — the same convention as a paper notebook, where you strike
through and initial rather than erase.

Nothing here can *prevent* an edit; it detects one. That is the honest limit of a
file-based tool, and detection is what actually matters.

Seals are stored per board -- "no one works on everything at once", so accepting
an edit on one board's entries (`--reseal <board>`) must never touch another's.
`.refdes/log-seal.yaml` is the base file: it holds seals for items that resolve
to no board (unchanged from before boards existed, and the *only* file used by a
project with no `boards:` registry at all), plus, transitionally, any entry an
older, single-file build sealed for an item that has since come to live on a
board it hasn't been physically migrated out to yet -- see `verify()`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import yaml

from .model import Item, Project

SEAL_FILE = ".refdes/log-seal.yaml"
RESEAL_ALL = "*"  # sentinel: --reseal with no board name means "every board"

_HEADER = (
    "# Refdes append-only seals. Each entry records the content hash of a log\n"
    "# entry at the time it was first built. Editing a sealed entry fails the\n"
    "# build; append a new entry that `amends` it instead.\n"
)


def seal_path(project: Project, board: str = "") -> str:
    """`.refdes/log-seal.yaml` for board `""`; `.refdes/log-seal-<board>.yaml`
    otherwise -- the same `-<board>` suffix convention every other per-board
    report file already uses.
    """
    name = f"log-seal-{board}.yaml" if board else "log-seal.yaml"
    return os.path.join(project.root, ".refdes", name)


SealValue = str | dict[str, object]
Seals = dict[str, SealValue]


def _seal_parts(
    record_id: str, value: SealValue
) -> tuple[str | None, str, str, int | None]:
    """Return key, recorded display id, hash, and format for either shape."""
    if isinstance(value, Mapping):
        entry = dict(value)
        display_id = entry.get("id")
        if isinstance(display_id, str) and display_id:
            key = record_id
        else:
            key = None
            display_id = record_id
        recorded = str(entry.get("hash", ""))
        raw_format = entry.get("hash_format")
        try:
            hash_format = int(raw_format) if raw_format is not None else None
        except (TypeError, ValueError):
            hash_format = -1
        return key, display_id, recorded, hash_format
    return None, record_id, str(value), None


def _find_seal(
    seals: Seals, item: Item
) -> tuple[str, SealValue, str, int | None] | None:
    """Find an item's seal by surrogate first, then by legacy display id."""
    if item.key:
        keyed = seals.get(item.key)
        if keyed is not None:
            key, _display_id, recorded, hash_format = _seal_parts(item.key, keyed)
            if key == item.key:
                return item.key, keyed, recorded, hash_format
    legacy = seals.get(item.id)
    if legacy is None:
        return None
    key, _display_id, recorded, hash_format = _seal_parts(item.id, legacy)
    if key is not None:
        return None
    return item.id, legacy, recorded, hash_format


def _with_seal_hash(value: SealValue, new_hash: str, hash_format: int) -> SealValue:
    if not isinstance(value, Mapping):
        return new_hash
    entry = dict(value)
    entry["hash"] = new_hash
    entry["hash_format"] = hash_format
    return entry


def load_seals(project: Project, board: str = "") -> Seals:
    path = seal_path(project, board)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        str(record_id): dict(value) if isinstance(value, Mapping) else str(value)
        for record_id, value in (data.get("sealed") or {}).items()
    }


def save_seals(project: Project, seals: Seals, board: str = "") -> None:
    path = seal_path(project, board)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_HEADER)
        yaml.safe_dump({"sealed": seals}, fh, sort_keys=True, default_flow_style=False)


def _matches_sealed_hash(
    recorded: str, item: Item, project: Project, hash_format: int | None = None
) -> tuple[bool, str]:
    """Compare a stored seal hash against the item's current hash.

    An explicit per-entry format is authoritative for §5 key-keyed or
    uncomparable entries. A legacy scalar has no marker, so it retains the
    historical current-first, legacy-second detection: a legacy-format match
    is safely carried forward to the current hash, while neither match is a
    real edit.
    """

    from . import build as build_mod

    if hash_format in (None, build_mod.HASH_FORMAT) and recorded == item.content_hash:
        return True, recorded
    if hash_format in (None, 1) and recorded == build_mod.legacy_hash_for(item, project):
        return True, item.content_hash
    return False, recorded


def append_only_items(project: Project, board: str | None = None) -> list[Item]:
    """Local append-only items, optionally narrowed to one board's own ("" included)."""
    items = [
        item
        for item in project.local_items
        if project.types.get(item.type) and project.types[item.type].append_only
    ]
    if board is not None:
        items = [i for i in items if i.board == board]
    return items


def _boards_in_play(project: Project) -> list[str]:
    """Every board key ("" included) at least one append-only item resolves to."""
    return sorted({item.board for item in append_only_items(project)})


def verify(project: Project, write: bool = False, reseal: str | None = None) -> None:
    """Check sealed entries per board, and seal any new ones when `write` is set.

    Both legacy display-id-keyed seals and §5 surrogate-keyed entries are
    accepted, including a mixture in one file. New seals deliberately retain
    the legacy scalar shape until the project runs `refdes keys adopt`.

    Migration from the pre-board single seal file is lazy and lookback-only:
    an item that used to be sealed in the base file and has since moved onto
    a board is still checked there first, then physically moved only on a
    write-enabled build.
    """
    base = load_seals(project, board="")
    base_changed = False

    for board in _boards_in_play(project):
        entries = append_only_items(project, board=board)
        changed = False
        if board:
            seals = load_seals(project, board)
            for item in entries:
                if _find_seal(seals, item) is not None:
                    continue
                inherited = _find_seal(base, item)
                if inherited is None:
                    continue
                record_id, value, _recorded, _hash_format = inherited
                seals[record_id] = value
                changed = True
        else:
            seals = base

        reseal_here = reseal == RESEAL_ALL or reseal == board

        for item in sorted(entries, key=lambda i: i.id):
            found = _find_seal(seals, item)
            if found is None:
                if write:
                    seals[item.id] = item.content_hash
                    changed = True
                continue
            record_id, value, recorded, hash_format = found
            ok, upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if ok:
                if upgraded != recorded and write:
                    seals[record_id] = _with_seal_hash(
                        value, upgraded, hash_format=2
                    )
                    changed = True
                continue

            if reseal_here:
                project.warn(
                    f"resealed after an edit to a sealed entry (was {recorded}, "
                    f"now {item.content_hash}). This is recorded in the audit output.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                seals[record_id] = _with_seal_hash(
                    value, item.content_hash, hash_format=2
                )
                changed = True
            else:
                project.seal_violations.append(item.id)
                hint = f"--reseal {board}" if board else "--reseal"
                project.error(
                    f"{item.id} is append-only and has been modified since it was "
                    f"sealed. Append a new entry with `amends: [{item.id}]` instead, "
                    f"or run with {hint} if the edit is deliberate.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )

        if board:
            if write and changed:
                save_seals(project, seals, board)
            if write:
                for item in entries:
                    inherited = _find_seal(base, item)
                    if inherited is not None:
                        del base[inherited[0]]
                        base_changed = True
        elif changed:
            base_changed = True

    if _report_deleted(project, base, write=write, reseal=reseal):
        base_changed = True

    if write and base_changed:
        save_seals(project, base, board="")


def _report_deleted(
    project: Project, base: Seals, write: bool, reseal: str | None
) -> bool:
    """Report sealed identities that no current item or former id claims."""
    live_ids = {item.id for item in project.local_items}
    live_ids |= set(project.former_ids)
    live_keys = {item.key for item in project.local_items if item.key}

    base_changed = False
    for board in sorted({""} | set(project.boards)):
        seals = base if board == "" else load_seals(project, board)
        orphans = []
        for record_id, value in seals.items():
            key, display_id, _recorded, _hash_format = _seal_parts(record_id, value)
            is_live = key in live_keys if key is not None else display_id in live_ids
            if is_live:
                continue
            orphans.append((record_id, display_id))
        if not orphans:
            continue
        reseal_here = bool(reseal) and (reseal == RESEAL_ALL or reseal == board)
        hint = f"--reseal {board}" if board else "--reseal"
        for record_id, display_id in sorted(orphans, key=lambda pair: pair[1]):
            if reseal_here:
                project.warn(
                    f"{display_id} was sealed as append-only and is no longer in "
                    "the project -- accepting the removal and dropping its seal.",
                    item_id=display_id,
                )
                if write:
                    del seals[record_id]
            else:
                project.error(
                    f"{display_id} is append-only and was sealed, but no item with "
                    "that id is in the project any more. An append-only entry "
                    "is corrected by appending one that `amends` it, never by "
                    f"deleting it -- restore it, or run with {hint} if the removal "
                    "is deliberate.",
                    item_id=display_id,
                )
        if reseal_here and write:
            if board:
                save_seals(project, seals, board)
            else:
                base_changed = True
    return base_changed


def resealed_ids(project: Project) -> list[str]:
    """Entries whose recorded seal no longer matches their current item."""
    base = load_seals(project, board="")
    out: list[str] = []
    for board in _boards_in_play(project):
        seals = load_seals(project, board) if board else base
        for item in append_only_items(project, board=board):
            found = _find_seal(seals, item)
            if found is None and board:
                found = _find_seal(base, item)
            if found is None:
                continue
            _record_id, _value, recorded, hash_format = found
            ok, _upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if not ok:
                out.append(item.id)
    return out
