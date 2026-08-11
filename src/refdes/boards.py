"""Board scoping: which board an item belongs to, and drift between builds.

Opt-in. A board is the first path segment under `items/`, matched against the
`boards:` registry in refdes.yaml. With no registry, every function here is a
no-op and every item's `board` stays "" -- an existing project with no `boards:`
block must build byte-identical to one from before this module existed.

Board membership is expected to be mostly stable, but a file does sometimes move.
`.refdes/boards.yaml` records which board each item was on the last time the
project was built, modeled on `seal.py`'s append-only manifest, except a board
move is always a warning, never a build error: unlike editing sealed history,
moving a board is an ordinary thing to do deliberately.
"""

from __future__ import annotations

import os

import yaml

from .ids import split_id
from .model import Item, Project

MANIFEST_FILE = ".refdes/boards.yaml"


# --------------------------------------------------------------------- resolution


def _path_index(project: Project) -> dict[str, str]:
    """items/ path segment -> board key, including any `path:` aliases."""
    return {spec.path_segment: name for name, spec in project.boards.items()}


def _derive(project: Project, item: Item) -> str:
    rel = item.source_file.replace("\\", "/")
    prefix = "items/"
    if not rel.startswith(prefix):
        return ""
    remainder = rel[len(prefix) :]
    if "/" not in remainder:
        return ""  # file sits directly in items/, no board segment
    segment = remainder.split("/", 1)[0]
    return _path_index(project).get(segment, "")


def resolve(project: Project) -> None:
    """Assign `item.board` for every local item: item override > file defaults > path.

    The override precedence between an item's own `board:` and its file's
    `defaults:` is already resolved by the time `item.board_hint` is set --
    parse.py merges `defaults:` under each item before the item-level value can
    win, the same way it already does for `prefix:`. This only adds the path
    fallback for items that set neither.
    """
    if not project.boards:
        return
    for item in project.local_items:
        if item.board_hint:
            if item.board_hint not in project.boards:
                project.error(
                    f"board: {item.board_hint!r} is not declared in refdes.yaml's "
                    f"boards: registry",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            item.board = item.board_hint
        else:
            item.board = _derive(project, item)


def lint_tokens(project: Project) -> None:
    """Warn when an item's id prefix does not contain its board's declared token.

    Only checked for boards that declare a `token:` -- ID prefixes stay
    independent of boards otherwise, so this is advisory, never automatic.
    """
    if not project.boards:
        return
    for item in project.local_items:
        if not item.board or not item.id:
            continue
        spec = project.boards.get(item.board)
        if not spec or not spec.token:
            continue
        parsed = split_id(item.id)
        prefix = parsed[0] if parsed else item.id
        if spec.token not in prefix.split("-"):
            project.warn(
                f"item is on board {item.board!r} (token {spec.token!r}), but its "
                f"id prefix {prefix!r} does not contain that token",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )


# ------------------------------------------------------------------------- drift


def manifest_path(project: Project) -> str:
    return os.path.join(project.root, MANIFEST_FILE)


def load_manifest(project: Project) -> dict[str, str]:
    path = manifest_path(project)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data.get("boards") or {})


def save_manifest(project: Project, manifest: dict[str, str]) -> None:
    path = manifest_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes board drift manifest. Records which board each item was on the\n"
        "# last time the project was built, so a file moving boards -- usually a\n"
        "# move to the wrong folder -- is a warning instead of a silent surprise.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(
            {"boards": manifest}, fh, sort_keys=True, default_flow_style=False
        )


def verify(project: Project, write: bool = False, accept_move: bool = False) -> None:
    """Compare each item's resolved board against the last recorded manifest."""
    if not project.boards:
        return

    manifest = load_manifest(project)
    changed = False

    for item in sorted(project.local_items, key=lambda i: i.id):
        if not item.board:
            continue
        recorded = manifest.get(item.id)
        if recorded is None:
            if write:
                manifest[item.id] = item.board
                changed = True
            continue
        if recorded == item.board:
            continue

        project.board_moves.append((item.id, recorded, item.board))
        if accept_move:
            project.warn(
                f"board move accepted: {item.id} was on {recorded!r}, now on "
                f"{item.board!r}",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            manifest[item.id] = item.board
            changed = True
        else:
            project.warn(
                f"{item.id} moved from board {recorded!r} to {item.board!r} since "
                f"the last build. Run 'refdes build --accept-board-move' if this "
                f"is deliberate, or move the file back.",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )

    if write and changed:
        save_manifest(project, manifest)
