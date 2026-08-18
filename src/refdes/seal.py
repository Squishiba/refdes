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
            if recorded == item.content_hash:
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

    if write and base_changed:
        save_seals(project, base, board="")


def resealed_ids(project: Project) -> list[str]:
    """Entries whose recorded seal, on any board, no longer matches their current hash."""
    base = load_seals(project, board="")
    out: list[str] = []
    for board in _boards_in_play(project):
        if board:
            seals = load_seals(project, board)
            for item_id, h in base.items():
                seals.setdefault(item_id, h)
        else:
            seals = base
        out.extend(
            item.id
            for item in append_only_items(project, board=board)
            if item.id in seals and seals[item.id] != item.content_hash
        )
    return out
