"""Board scoping: which board an item belongs to, and drift between builds.

Opt-in. A board is one path segment under `items/`, matched against the
`boards:` registry in refdes.yaml -- the first segment under `item_layout:
flat` (today's `items/<board>/`), the second under `item_layout: workspace`
(`items/<workspace>/<board>/`, see workspaces.py). With no registry, every
function here is a no-op and every item's `board` stays "" -- an existing
project with no `boards:` block must build byte-identical to one from before
this module existed, and that includes staying on `item_layout: flat`.

Board membership is expected to be mostly stable, but a file does sometimes move.
`.refdes/boards.yaml` records which board -- and, once `workspaces:` is in use,
which workspace -- each item was on the last time the project was built, modeled
on `seal.py`'s append-only manifest, except a move is always a warning, never a
build error: unlike editing sealed history, moving a board or workspace is an
ordinary thing to do deliberately.
"""

from __future__ import annotations

import os
from typing import Callable

import yaml

from .ids import split_id
from .model import Item, Project

MANIFEST_FILE = ".refdes/boards.yaml"


# --------------------------------------------------------------------- resolution


def _path_index(project: Project) -> dict[str, str]:
    """items/ path segment -> board key, including any `path:` aliases."""
    return {spec.path_segment: name for name, spec in project.boards.items()}


def path_segments(item: Item) -> list[str]:
    """Every items/ path segment `item` lives under, filename excluded.

    `["board-a"]` for `items/board-a/r.yaml`, `["ws-a", "board-a"]` for
    `items/ws-a/board-a/r.yaml`, `[]` for a file directly in `items/`. Shared
    with workspaces.py, which reads the first element the same way this module
    reads whichever element `item_layout` says is the board's own.
    """
    rel = item.source_file.replace("\\", "/")
    prefix = "items/"
    if not rel.startswith(prefix):
        return []
    remainder = rel[len(prefix) :]
    parts = remainder.split("/")
    return parts[:-1]  # drop the filename


def _board_segment(project: Project, item: Item) -> str:
    """Which path segment names the board, depending on `item_layout`."""
    parts = path_segments(item)
    if project.item_layout == "workspace":
        return parts[1] if len(parts) >= 2 else ""
    return parts[0] if parts else ""


def _derive(project: Project, item: Item) -> str:
    segment = _board_segment(project, item)
    return _path_index(project).get(segment, "") if segment else ""


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
            if not item.board:
                segment = _board_segment(project, item)
                if segment:
                    reason = f"{segment!r} is not in the boards: registry"
                elif project.item_layout == "workspace":
                    reason = (
                        "it has no second items/ path segment to read a board "
                        "from under item_layout: workspace"
                    )
                else:
                    reason = "it sits directly in items/, outside any board folder"
                project.warn(
                    f"no board: {reason} and no board: key was set. Add "
                    f"`board: <name>` to the file's defaults:, or move the file "
                    f"to items/<registered-board>/.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )


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


def load_manifest(project: Project) -> dict[str, dict[str, str]]:
    """`{"boards": {item_id: board_key}, "workspaces": {item_id: workspace_key}}`.

    One file, two independent sections -- loaded and saved together so neither
    verify() pass can clobber the other's half when only one of `boards:` /
    `workspaces:` is actually in use for this project.
    """
    path = manifest_path(project)
    if not os.path.isfile(path):
        return {"boards": {}, "workspaces": {}}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "boards": dict(data.get("boards") or {}),
        "workspaces": dict(data.get("workspaces") or {}),
    }


def save_manifest(project: Project, manifest: dict[str, dict[str, str]]) -> None:
    path = manifest_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Refdes membership drift manifest. Records which board -- and, once\n"
        "# workspaces: is in use, which workspace -- each item was on the last\n"
        "# time the project was built, so a file moving either -- usually a move\n"
        "# to the wrong folder -- is a warning instead of a silent surprise.\n"
    )
    payload: dict[str, dict[str, str]] = {"boards": manifest.get("boards", {})}
    # Omitted entirely for a project that has never used workspaces:, so a
    # boards-only project's manifest stays exactly the shape it always was.
    if project.workspaces or manifest.get("workspaces"):
        payload["workspaces"] = manifest.get("workspaces", {})
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(payload, fh, sort_keys=True, default_flow_style=False)


def _verify_membership(
    project: Project,
    manifest: dict[str, str],
    moves: list[tuple[str, str, str]],
    current: Callable[[Item], str],
    kind: str,
    write: bool,
    accept_move: bool,
) -> bool:
    """One kind's worth of drift-checking (`"board"` or `"workspace"`).

    Same shape either way: compare the resolved value against what was last
    recorded, warn (never error) on a change, and record it in `moves` --
    `--accept-board-move` is the one flag that accepts both kinds, since they
    share this one manifest file and the same "moving this is an ordinary
    thing to do on purpose" posture.
    """
    changed = False
    for item in sorted(project.local_items, key=lambda i: i.id):
        value = current(item)
        recorded = manifest.get(item.id)
        if not value and recorded is None:
            continue  # never assigned -- resolve()'s own diagnostic covers this

        if recorded is None:
            if write:
                manifest[item.id] = value
                changed = True
            continue
        if recorded == value:
            continue

        moves.append((item.id, recorded, value))
        if value:
            accepted = f"was on {kind} {recorded!r}, now on {value!r}"
            warning = (
                f"{item.id} moved from {kind} {recorded!r} to {value!r} since "
                f"the last build. Run 'refdes build --accept-board-move' if "
                f"this is deliberate, or move the file back."
            )
        else:
            accepted = f"was on {kind} {recorded!r}, now resolves to no {kind}"
            warning = (
                f"{item.id} was on {kind} {recorded!r} and now resolves to no "
                f"{kind}. Run 'refdes build --accept-board-move' if this is "
                f"deliberate, or restore the {kind}."
            )
        if accept_move:
            project.warn(
                f"{kind} move accepted: {item.id} {accepted}",
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
            manifest[item.id] = value
            changed = True
        else:
            project.warn(
                warning,
                file=item.source_file, line=item.source_line, item_id=item.id,
            )
    return changed


def verify(project: Project, write: bool = False, accept_move: bool = False) -> None:
    """Compare each item's resolved board and workspace against the manifest."""
    if not project.boards and not project.workspaces:
        return

    manifest = load_manifest(project)
    changed = False

    if project.boards:
        changed = _verify_membership(
            project, manifest["boards"], project.board_moves,
            lambda item: item.board, "board", write, accept_move,
        ) or changed

    if project.workspaces:
        changed = _verify_membership(
            project, manifest["workspaces"], project.workspace_moves,
            lambda item: item.workspace, "workspace", write, accept_move,
        ) or changed

    if write and changed:
        save_manifest(project, manifest)
