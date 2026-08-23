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


def load_seals(project: Project, board: str = "") -> dict[str, str]:
    path = seal_path(project, board)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data.get("sealed") or {})


def save_seals(project: Project, seals: dict[str, str], board: str = "") -> None:
    path = seal_path(project, board)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_HEADER)
        yaml.safe_dump({"sealed": seals}, fh, sort_keys=True, default_flow_style=False)


def _matches_sealed_hash(recorded: str, item: Item, project: Project) -> tuple[bool, str]:
    """Compare a stored seal hash against `item`'s current one, folding in
    the hash-format migration (docs/design/keys.md §5) so a seal written
    before keys existed doesn't read as tampered purely because the hash
    *definition* changed underneath it.

    Returns `(matches, hash_to_store)`. Three outcomes:

    - `recorded == item.content_hash`: unchanged under the current
      (hash_format-2) definition -- the ordinary case for any seal written
      since keys landed. `(True, recorded)`, nothing to do.
    - `recorded` doesn't match the current hash, but does match what the
      item would have hashed to under the *old* (hash_format-1) definition
      (`build.legacy_hash_for`): the content hasn't actually changed since
      this was sealed, only the hash definition has. `(True,
      item.content_hash)` -- the caller upgrades the stored value in place.
      Seals have no per-entry `hash_format` field to persist (unlike
      baselines: a seal is a flat `{id: hash}` map with no room for one) --
      but none is needed, because once the value is upgraded it *is* a
      hash_format-2 hash, indistinguishable from one sealed fresh under the
      current code. The migration is self-describing by construction, not
      by a recorded flag.
    - Neither matches: a real edit since sealing, format aside.
      `(False, recorded)` -- an ordinary violation, exactly as before this
      migration existed.

    A deferred import of `build` avoids a cycle: `build.py` already imports
    `seal` (its own `build()` calls `seal.verify()`), so `seal` importing
    `build` at module level would be circular. By the time this function
    runs, `build` has always finished importing (`compute_hashes`, whose
    output this compares against, already ran), so the deferred import is
    safe and cheap -- Python caches the module after the first import.
    """
    from . import build as build_mod

    if recorded == item.content_hash:
        return True, recorded
    if recorded == build_mod.legacy_hash_for(item, project):
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

    `reseal` is `None`/falsy (verify only), `RESEAL_ALL` (accept edits on every
    board), or one registered board's key (accept edits only for that board's
    own entries -- every other board's still fail as a normal violation).

    Migration from the pre-board single seal file is lazy and lookback-only: an
    item that used to be sealed in the base file and has since come to resolve
    onto a board is still checked against that old hash (never silently treated
    as brand new), by falling back to the base file for any id the board's own
    file doesn't have yet. Only a `write`-enabled run (`build`, never `check`)
    then physically moves that entry into the board's own file and drops it from
    the base one -- so a read-only `check` never mutates seal storage, but still
    catches a real edit against a project that has not been `build`t since
    adopting boards.
    """
    base = load_seals(project, board="")
    base_changed = False

    for board in _boards_in_play(project):
        entries = append_only_items(project, board=board)
        changed = False
        if board:
            seals = load_seals(project, board)
            for item in entries:
                if item.id not in seals and item.id in base:
                    # Pulled in from the legacy file: this board's own file needs
                    # writing even though nothing about the seal itself changed,
                    # or the entry would vanish once it's pruned from `base` below.
                    seals[item.id] = base[item.id]
                    changed = True
        else:
            seals = base

        reseal_here = reseal == RESEAL_ALL or reseal == board

        for item in sorted(entries, key=lambda i: i.id):
            recorded = seals.get(item.id)
            if recorded is None:
                if write:
                    seals[item.id] = item.content_hash
                    changed = True
                continue
            ok, upgraded = _matches_sealed_hash(recorded, item, project)
            if ok:
                if upgraded != recorded and write:
                    # Hash-format migration (docs/design/keys.md §5): content
                    # is unchanged, only the hash definition moved -- upgrade
                    # silently, same posture as the fresh-seal branch above,
                    # not the reseal-with-a-warning branch below (nothing was
                    # actually edited here).
                    seals[item.id] = upgraded
                    changed = True
                continue

            if reseal_here:
                project.warn(
                    f"resealed after an edit to a sealed entry (was {recorded}, "
                    f"now {item.content_hash}). This is recorded in the audit output.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                seals[item.id] = item.content_hash
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
                    if base.pop(item.id, None) is not None:
                        base_changed = True
        elif changed:
            base_changed = True

    if _report_deleted(project, base, write=write, reseal=reseal):
        base_changed = True

    if write and base_changed:
        save_seals(project, base, board="")


def _report_deleted(
    project: Project, base: dict[str, str], write: bool, reseal: str | None
) -> bool:
    """Report every sealed entry that is no longer anywhere in the project.

    Editing a sealed entry was already a build error; deleting one outright
    was not detected at all -- a clean build, a clean `audit`, and an
    orphaned hash left behind in the seal file. That is the louder half of
    the same tamper-evidence question, so it is reported the same way, with
    the same `--reseal` escape hatch for a deliberate removal.

    "No longer anywhere" is deliberately generous: an id that is still live
    under a *different* board (the lazy migration `verify()` performs above),
    or that some item now claims through `former_ids:` after a renumbering,
    is present, not deleted. Only a `write` run can actually drop the
    orphaned entry, so a read-only `check` reports without mutating storage;
    returning True lets the caller know the base file needs rewriting.
    """
    live = {item.id for item in project.local_items}
    live |= set(project.former_ids)

    base_changed = False
    for board in sorted({""} | set(project.boards)):
        seals = base if board == "" else load_seals(project, board)
        orphans = sorted(item_id for item_id in seals if item_id not in live)
        if not orphans:
            continue
        reseal_here = bool(reseal) and (reseal == RESEAL_ALL or reseal == board)
        hint = f"--reseal {board}" if board else "--reseal"
        for item_id in orphans:
            if reseal_here:
                project.warn(
                    f"{item_id} was sealed as append-only and is no longer in the "
                    "project -- accepting the removal and dropping its seal.",
                    item_id=item_id,
                )
                if write:
                    del seals[item_id]
            else:
                project.error(
                    f"{item_id} is append-only and was sealed, but no item with "
                    "that id is in the project any more. An append-only entry is "
                    "corrected by appending one that `amends` it, never by "
                    f"deleting it -- restore it, or run with {hint} if the removal "
                    "is deliberate.",
                    item_id=item_id,
                )
        if reseal_here and write:
            if board:
                save_seals(project, seals, board)
            else:
                base_changed = True
    return base_changed


def resealed_ids(project: Project) -> list[str]:
    """Entries whose recorded seal, on any board, no longer matches their
    current hash -- audit-only, so a read that never writes (`refdes audit`
    doesn't `seal.verify(write=True)` first). Uses the same hash-format-aware
    comparison `verify()` does (_matches_sealed_hash): otherwise, the first
    `audit` run after adopting keys would list every sealed entry in the
    project as "resealed", when nothing was actually touched -- only the
    hash definition moved (docs/design/keys.md §5)."""
    base = load_seals(project, board="")
    out: list[str] = []
    for board in _boards_in_play(project):
        if board:
            seals = load_seals(project, board)
            for item_id, h in base.items():
                seals.setdefault(item_id, h)
        else:
            seals = base
        for item in append_only_items(project, board=board):
            recorded = seals.get(item.id)
            if recorded is None:
                continue
            ok, _upgraded = _matches_sealed_hash(recorded, item, project)
            if not ok:
                out.append(item.id)
    return out
