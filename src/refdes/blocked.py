"""`blocked_by:` cycle detection, transitive root resolution, and the
stale-blocker diagnostic. See docs/design/standard-library.md §9.

The declared edge is direct (an item names only its immediate blocker); the
report resolves transitively to the structural root, because naming the root
cause is the entire value of building this at all. "Root" is structural, not
status-based: the walk follows `blocked_by` edges until it reaches an item
declaring none of its own, regardless of what any item along the way now has
for a status -- see the separate, per-edge stale check below for that.

Reuses `blocks.walk_cascade()` for cycle detection (`on_cycle="error"`)
rather than a second traversal -- the seam that primitive was built with.
Root resolution itself, once the graph is known acyclic, is a plain
recursive walk with no cycle machinery of its own to write.
"""

from __future__ import annotations

from . import blocks as blocks_mod
from .model import BlockedChain, Project


def _is_settled(target_ref: str, project: Project) -> bool:
    """A blocker counts as settled when its own type declares
    `satisfying_statuses` (or, for a verifier-shaped type,
    `verifying_statuses`) and its current status is in that list. A type
    that declares neither never triggers this check -- the same
    "unconfigured means nothing special happens" default `compute_coverage`
    already uses for the same two flags."""
    target = project.item_by_ref(target_ref)
    if target is None:
        return False
    spec = project.types.get(target.type)
    if spec is None:
        return False
    allowed = (
        spec.satisfying_statuses
        if spec.satisfying_statuses is not None
        else spec.verifying_statuses
    )
    if allowed is None:
        return False
    return target.fields.get("status") in allowed


def _paths_to_roots(project: Project, node_id: str, guard: int) -> list[list[str]]:
    """Every root-terminated path starting at `node_id`, following
    `blocked_by` edges -- a node with no `blocked_by` of its own is itself a
    root. A node with several direct blockers contributes one path per
    branch, so a fan-out is never silently collapsed to one arbitrary
    chain. `guard` is a depth backstop only; `resolve()` already runs the
    cycle check first, so this is never expected to actually hit it."""
    if guard <= 0:
        return [[node_id]]
    node = project.item_by_ref(node_id)
    # resolved links carry display ids where available and keys otherwise;
    # item_by_ref() preserves both id-bearing and id-less graph nodes.
    targets = node.resolved_links.get("blocked_by", []) if node else []
    if not targets:
        return [[node_id]]
    paths: list[list[str]] = []
    for target_id in targets:
        for sub in _paths_to_roots(project, target_id, guard - 1):
            paths.append([node_id] + sub)
    return paths


def resolve(project: Project) -> None:
    """Cycle-check every declared `blocked_by` edge, then resolve each
    direct edge to its structural root(s) and flag any that have gone
    stale.

    Must run after `resolve_links` (needs `links`/`backlinks` populated) and
    before `compute_coverage` (which reads `project.blocked_chains` to
    annotate claimed-but-unsettled requirements). A cycle is a hard,
    build-stopping `error` -- reported once, at the file:line of the edge
    that closes the loop, not some arbitrary node the walk happened to
    start from -- after which the graph can't be trusted, so this returns
    immediately without populating `project.blocked_chains` at all.
    """
    project.blocked_chains = []
    max_depth = len(project.items) + 1  # enough hops to reach any real root

    for item in project.local_items:
        if not item.links.get("blocked_by"):
            continue
        try:
            item_ref = item.id or item.key
            blocks_mod.walk_cascade(
                project, item_ref, "up", {"blocked_by"}, max_depth, on_cycle="error"
            )
        except blocks_mod.CascadeCycleError as exc:
            # exc.path ends [..., closer ref, target ref already in path] --
            # the closer's own declaration is the concrete edge whoever reads
            # this error would actually edit.
            closer_ref = exc.path[-2]
            closer = project.item_by_ref(closer_ref)
            project.error(
                f"blocked_by cycle: {' -> '.join(exc.path)}",
                file=closer.source_file if closer else None,
                line=closer.source_line if closer else None,
                item_id=closer.id if closer else closer_ref,
            )
            return

    for item in project.local_items:
        for target_id in item.resolved_links.get("blocked_by", []):
            stale = _is_settled(target_id, project)
            if stale:
                target = project.item_by_ref(target_id)
                display_ref = (target.id or target.key) if target else target_id
                project.info(
                    f"blocked_by {display_ref}, which is now "
                    f"{target.fields.get('status')!r} -- is it still blocked? "
                    "Remove the edge if resolved, or say in 'rationale' why it "
                    "still applies.",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
            for sub_path in _paths_to_roots(project, target_id, max_depth):
                item_ref = item.id or item.key
                path = [item_ref] + sub_path
                root_id = path[-1]
                root = project.item_by_ref(root_id)
                project.blocked_chains.append(
                    BlockedChain(
                        item_id=item_ref,
                        path=path,
                        root_id=root_id,
                        root_status=root.fields.get("status") if root else None,
                        stale=stale,
                    )
                )


def by_item(project: Project) -> dict[str, list[BlockedChain]]:
    """`project.blocked_chains` grouped by the declaring item -- the shape
    every consumer (item page, coverage, audit) actually wants."""
    grouped: dict[str, list[BlockedChain]] = {}
    for chain in project.blocked_chains:
        grouped.setdefault(chain.item_id, []).append(chain)
    return grouped
