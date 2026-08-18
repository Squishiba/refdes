"""Workspace scoping: the ownership boundary one level above boards.

Opt-in, same posture as boards.py: with no `workspaces:` registry, every
function here is a no-op and every item's `workspace` stays "" -- an existing
project must build byte-identical to one from before this module existed.

A workspace holds everything used only by that workspace -- the seam along
which a project would later split, so extracting a workspace into its own
project is meant to be a folder move, not a renumbering. `item_layout:
workspace` (docs/workspaces.md) is what makes that seam a real directory
boundary (`items/<workspace>/<board>/`); the `workspace:` override below
works regardless of layout, for a project that wants the lint without a full
directory reorganization.

The cross-workspace reference lint is the payoff: an authored link from one
workspace into another that isn't marked `shared: true` is a hidden
dependency that would make the source workspace harder to extract later. It
walks `item.links` only -- never `item.backlinks` (computed) or any derived
aggregate (coverage, a future parts index) -- so it can only ever fire on
something an author actually typed.
"""

from __future__ import annotations

from . import boards
from .model import ERROR, INFO, WARNING, Item, Project

_SEVERITY_EMITTERS = {ERROR: Project.error, WARNING: Project.warn, INFO: Project.info}


# --------------------------------------------------------------------- resolution


def _path_index(project: Project) -> dict[str, str]:
    """items/ path segment -> workspace key, including any `path:` aliases."""
    return {spec.path_segment: name for name, spec in project.workspaces.items()}


def _derive(project: Project, item: Item) -> str:
    parts = boards.path_segments(item)
    segment = parts[0] if parts else ""
    return _path_index(project).get(segment, "") if segment else ""


def resolve(project: Project) -> None:
    """Assign `item.workspace` for every local item: item override > file
    defaults > path -- the same precedence resolve() in boards.py uses for
    `item.board`, and for the same reason: `item.workspace_hint` already
    reflects item-vs-file-defaults precedence by the time parse.py is done.

    The path fallback only applies under `item_layout: workspace`, since
    that's the only layout with a dedicated workspace directory level to read
    it from -- under `item_layout: flat`, an item with no explicit
    `workspace:` simply has no workspace, silently, the same way it would if
    `workspaces:` were never declared at all.
    """
    if not project.workspaces:
        return
    for item in project.local_items:
        if item.workspace_hint:
            if item.workspace_hint not in project.workspaces:
                project.error(
                    f"workspace: {item.workspace_hint!r} is not declared in "
                    f"refdes.yaml's workspaces: registry",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            item.workspace = item.workspace_hint
        elif project.item_layout == "workspace":
            item.workspace = _derive(project, item)
            if not item.workspace:
                parts = boards.path_segments(item)
                segment = parts[0] if parts else ""
                if segment:
                    reason = f"{segment!r} is not in the workspaces: registry"
                else:
                    reason = "it sits directly in items/, outside any workspace folder"
                project.warn(
                    f"no workspace: {reason} and no workspace: key was set. Add "
                    f"`workspace: <name>` to the file's defaults:, or move the "
                    f"file to items/<registered-workspace>/<board>/.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
        # item_layout: flat, no override -> stays "" silently: nothing in the
        # path names a workspace under this layout, so there's nothing to warn
        # about, unlike the board case above.


# -------------------------------------------------------------------------- lint


def lint_cross_workspace_references(project: Project) -> None:
    """Warn (at `project.cross_workspace_severity`) when a local item links to
    another local item in a different, non-shared workspace.

    Scoped to local items on both ends: an imported item's `workspace` field,
    if it resolves to anything at all, describes the *upstream* project's own
    directory structure, not a dependency inside this one -- imports already
    have their own boundary-crossing story (multi-board.md's "Separate
    projects with imports"), distinct from what this lint is for.

    Iterates `item.links` exclusively -- never `item.backlinks` -- so a
    derived/computed relationship (a backlink, coverage, a future parts
    index) can never trip this: only an edge an author actually declared
    counts as the kind of dependency that makes a workspace hard to extract.
    """
    if not project.workspaces:
        return
    emit = _SEVERITY_EMITTERS.get(project.cross_workspace_severity, Project.warn)

    for item in project.local_items:
        if not item.workspace:
            continue
        for link_name, targets in item.links.items():
            for target_id in targets:
                target = project.items.get(target_id)
                if target is None or target.external:
                    continue
                if not target.workspace or target.workspace == item.workspace:
                    continue
                target_spec = project.workspaces.get(target.workspace)
                if target_spec is not None and target_spec.shared:
                    continue
                emit(
                    project,
                    f"{link_name} points at {target_id}, in workspace "
                    f"{target.workspace!r}, which is not marked shared: true "
                    f"-- workspace {item.workspace!r} would gain a hidden "
                    f"dependency on it",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
