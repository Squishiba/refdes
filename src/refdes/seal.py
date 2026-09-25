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

from . import keys as keys_mod
from . import textio
from .model import Item, Project
from .parse import yaml_safe_load

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
    seals: Seals, item: Item, live_keys: set[str]
) -> tuple[str, SealValue, str, int | None] | None:
    """Find an item's seal by surrogate, recorded display id, then legacy id.

    The recorded-id pass is corruption-sensitive: if the live item's key was
    changed, the old key-keyed seal still belongs to this display id. It may
    claim that item only when no live local item owns the recorded key; a live
    owner means the seal belongs to that owner and its recorded id is merely
    the pre-rename label. This prevents both laundering and rename-then-reuse
    false positives.
    """
    if item.key:
        keyed = seals.get(item.key)
        if keyed is not None:
            key, _display_id, recorded, hash_format = _seal_parts(item.key, keyed)
            if key == item.key:
                return item.key, keyed, recorded, hash_format
    for record_id, value in seals.items():
        key, display_id, recorded, hash_format = _seal_parts(record_id, value)
        if key is not None and key not in live_keys and display_id == item.id:
            return record_id, value, recorded, hash_format
    legacy = seals.get(item.id)
    if legacy is None:
        return None
    key, _display_id, recorded, hash_format = _seal_parts(item.id, legacy)
    if key is not None:
        return None
    return item.id, legacy, recorded, hash_format


def _seal_key_mismatch(record_id: str, value: SealValue, item: Item) -> str | None:
    recorded_key, _display_id, _hash, _format = _seal_parts(record_id, value)
    if recorded_key is not None and recorded_key != item.key:
        return recorded_key
    return None


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
        data = yaml_safe_load(fh) or {}
    return {
        str(record_id): dict(value) if isinstance(value, Mapping) else str(value)
        for record_id, value in (data.get("sealed") or {}).items()
    }


def format_seals(seals: Seals) -> str:
    """Serialize seals identically for adoption planning and persistence."""
    return _HEADER + yaml.safe_dump(
        {"sealed": seals}, sort_keys=True, default_flow_style=False
    )


def save_seals(project: Project, seals: Seals, board: str = "") -> None:
    path = seal_path(project, board)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.write_text(path, format_seals(seals))


def _matches_sealed_hash(
    recorded: str, item: Item, project: Project, hash_format: int | None = None
) -> tuple[bool, str]:
    """Compare a stored seal hash against `item`'s current one, folding in
    the hash-format migration (docs/design/keys.md §5) so a seal written
    under an earlier hash definition does not read as tampered purely
    because the definition changed underneath it.

    Returns ``(matches, hash_to_store)``. Two outcomes:

    - ``hash_format`` known (a key-keyed entry's own recorded format): the
      recorded hash must match ``keys.hash_in_format(item, project,
      hash_format)`` -- the one shared reconstruction every hash-format
      migration site uses, not a copy of it.
    - ``hash_format`` unknown (a legacy scalar seal, with no field for a
      format marker of its own): try the newest definition first, then each
      older one in turn (docs/design/keys.md §5(c)) -- the first that
      matches identifies an unchanged entry, and a successful write upgrades
      the scalar to the current hash.

    Neither permitted definition matching is a real edit; the original hash
    is returned with ``matches=False``.

    The deferred ``build`` import avoids a cycle: ``build.py`` imports this
    module for ``verify()``, while this comparison needs ``build.HASH_FORMAT``.
    By call time build has finished importing and Python caches the module.
    """
    from . import build as build_mod

    formats = (hash_format,) if hash_format is not None else tuple(range(build_mod.HASH_FORMAT, 0, -1))
    for fmt in formats:
        expected = keys_mod.hash_in_format(item, project, fmt)
        if expected is not None and recorded == expected:
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


def is_sealed(project: Project, item: Item) -> bool:
    """Whether ``item`` already has an append-only seal in any board file.

    Follows freezing happens before board resolution in the normal load path,
    so it must inspect every declared board rather than relying on
    ``item.board``. A legacy base-file seal remains authoritative until a
    writable build migrates it to its board-specific file.
    """
    spec = project.types.get(item.type)
    if spec is None or not spec.append_only:
        return False
    live_keys = {candidate.key for candidate in project.local_items if candidate.key}
    for board in sorted({""} | set(project.boards)):
        if _find_seal(load_seals(project, board), item, live_keys) is not None:
            return True
    return False


def _boards_in_play(project: Project) -> list[str]:
    """Every board key ("" included) at least one append-only item resolves to."""
    return sorted({item.board for item in append_only_items(project)})


def verify(project: Project, write: bool = False, reseal: str | None = None) -> None:
    """Check sealed entries per board, and seal any new ones when requested.

    A new entry with an ERROR diagnostic attributed to it in this build is
    not sealed -- it is reported once and seals on the first later build
    where it is error-free, so fixing what the build complained about never
    collides with a seal made over the broken text.

    ``reseal`` is ``None``/falsy (verify only), ``RESEAL_ALL`` (accept edits
    on every board), or one registered board key (accept edits only for that
    board). A changed surrogate key is corruption, not an ordinary edit, and
    is never accepted by resealing.

    Both legacy display-id-keyed scalars and §5 surrogate-keyed dictionaries
    are accepted, including mixtures in one file. New seals use the keyed
    shape after the project records explicit adoption.

    Pre-board history is migrated lazily and lookback-only: when an item now
    resolves onto a board but its seal remains in the base file, verification
    still checks that old entry rather than treating the item as new. Only a
    write-enabled build moves it into the board file and prunes the base copy;
    read-only ``check`` therefore never mutates seal storage while retaining
    the same tamper detection.
    """
    from . import build as build_mod

    base = load_seals(project, board="")
    base_changed = False
    live_keys = {item.key for item in project.local_items if item.key}
    # An entry this very build flagged with an ERROR is never sealed: the
    # author is told to fix it, and sealing it now would turn that fix into
    # "modified since it was sealed" -- following the error's own instruction
    # would punish them. Per-entry, not per-build: an error elsewhere does
    # not freeze healthy entries out of sealing. Only attributed errors
    # count; project-level diagnostics belong to no entry.
    errored_items = {d.item_id for d in project.errors if d.item_id}

    for board in _boards_in_play(project):
        entries = append_only_items(project, board=board)
        changed = False
        if board:
            seals = load_seals(project, board)
            for item in entries:
                if _find_seal(seals, item, live_keys) is not None:
                    continue
                inherited = _find_seal(base, item, live_keys)
                if inherited is None:
                    continue
                record_id, value, _recorded, _hash_format = inherited
                seals[record_id] = value
                changed = True
        else:
            seals = base

        reseal_here = reseal == RESEAL_ALL or reseal == board
        for item in sorted(entries, key=lambda i: i.id):
            found = _find_seal(seals, item, live_keys)
            if found is None:
                if write:
                    if item.id in errored_items:
                        project.warn(
                            f"{item.id} was not sealed because it has errors; "
                            "it will be sealed on the first clean build",
                            file=item.source_file, line=item.source_line,
                            item_id=item.id,
                        )
                    elif keys_mod.is_adopted(project) and item.key:
                        seals[item.key] = {
                            "id": item.id,
                            "hash": item.content_hash,
                            "hash_format": build_mod.HASH_FORMAT,
                        }
                    else:
                        seals[item.id] = item.content_hash
                    changed = True
                continue
            record_id, value, recorded, hash_format = found
            recorded_key = _seal_key_mismatch(record_id, value, item)
            if recorded_key is not None:
                project.seal_violations.append(item.id)
                if not item.key:
                    # The key was deleted, not changed: the deleted-key report
                    # (§6, 2026-09-15) owns this item and says so with the
                    # remedies. Never re-seal over it either.
                    continue
                project.error(
                    f"{item.id} is append-only and its key changed since it was "
                    f"sealed: was {recorded_key!r}, now {item.key!r}. A key never "
                    "changes legitimately; restore the sealed key from history.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            ok, upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if ok:
                if upgraded != recorded and write:
                    seals[record_id] = _with_seal_hash(
                        value, upgraded, hash_format=build_mod.HASH_FORMAT
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
                    value, item.content_hash, hash_format=build_mod.HASH_FORMAT
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
                    inherited = _find_seal(base, item, live_keys)
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
    """Report every sealed entry whose identity is no longer in the project.

    Editing a sealed entry was already an error; without this pass, deleting
    one outright produced a clean build and left only an orphaned hash. That
    is the louder half of the same tamper-evidence rule and uses the same
    board-scoped reseal escape hatch.

    "No longer anywhere" is deliberately generous. A legacy display id still
    counts when it is live on another board or claimed through ``former_ids``.
    A surrogate-keyed entry first belongs to any live owner of its immutable
    key, regardless of whether its recorded id was later reused. Only when no
    live item owns that key may the recorded display id identify key
    corruption; that case is reported once by ``verify()``, not again and
    misleadingly as a deleted item here. Read-only checks report but never
    remove entries.
    """
    live_ids = {item.id for item in project.local_items}
    live_ids |= set(project.former_ids)
    live_keys = {item.key for item in project.local_items if item.key}

    base_changed = False
    for board in sorted({""} | set(project.boards)):
        seals = base if board == "" else load_seals(project, board)
        orphans = []
        for record_id, value in seals.items():
            key, display_id, _recorded, _hash_format = _seal_parts(record_id, value)
            if key is None:
                is_live = display_id in live_ids
            elif key in live_keys:
                is_live = True
            else:
                is_live = display_id in live_ids
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
    """Return sealed entries whose current content no longer matches.

    Audit is read-only, so it cannot rely on ``verify(write=True)`` having
    upgraded legacy hashes first. It therefore uses the same format-aware
    comparison as verification; otherwise the first audit after adopting keys
    would call every unchanged legacy seal "resealed". A key mismatch is also
    returned as drift even when the content hash itself still matches.
    """
    base = load_seals(project, board="")
    live_keys = {item.key for item in project.local_items if item.key}
    out: list[str] = []
    for board in _boards_in_play(project):
        seals = load_seals(project, board) if board else base
        for item in append_only_items(project, board=board):
            found = _find_seal(seals, item, live_keys)
            if found is None and board:
                found = _find_seal(base, item, live_keys)
            if found is None:
                continue
            _record_id, _value, recorded, hash_format = found
            if _seal_key_mismatch(_record_id, _value, item) is not None:
                out.append(item.id)
                continue
            ok, _upgraded = _matches_sealed_hash(recorded, item, project, hash_format)
            if not ok:
                out.append(item.id)
    return out
