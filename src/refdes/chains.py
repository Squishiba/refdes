"""`follows:` chain walk: tips, the per-field fold, fork and cycle diagnostics.

See docs/design/threads.md §3 ("A lazy walk, not a persistent registry",
"Branching's effect on current") and §6 ("Two entries claiming the same
predecessor", "Merging", "Cycles"). Same role for `follows:` that
`blocked.py` plays for `blocked_by:` — a dedicated walk pass with cycle
detection and diagnostics, run as a build step after link resolution.

The graph is built here, from raw `follows:` targets resolved through
`build.resolve_link_target`, rather than read off `backlinks`/
`resolved_links`: those carry *display ids*, which an id-less continuation
entry (threads.md §2) does not have. Nodes are therefore identified by the
`project.items` dict key — the surrogate key when an item has one, its
provisional handle otherwise — and named in diagnostics by display id, or
by key when it has none.
"""

from __future__ import annotations

from typing import Any

from .model import Item, Project

FOLLOWS = "follows"


def _name(item: Item | None) -> str:
    """How an entry is referred to in a message: display id, or key when
    it has no id (threads.md §2's permanently id-less continuation)."""
    if item is None:
        return "?"
    return item.id or item.key or item.slug


def _handles(project: Project) -> dict[int, str]:
    """id(item) -> its `project.items` key, the node identity this module's
    graphs are keyed by (surrogate key, or provisional handle)."""
    return {id(item): handle for handle, item in project.items.items()}


def _start_handle(project: Project, start: Item | str) -> str | None:
    """Accept an Item, a `project.items` key/handle, or a display id."""
    if isinstance(start, Item):
        return _handles(project).get(id(start))
    if start in project.items:
        return start
    item = project.item_by_id(start)
    return _handles(project).get(id(item)) if item is not None else None


def build_graph(project: Project) -> tuple[dict[str, list[Item]], dict[str, list[Item]]]:
    """(predecessors, successors) for every `follows:` edge, keyed by node.

    A target that does not resolve is simply not an edge — `resolve_links`
    has already reported it as its own error, and this pass adds nothing to
    say about it. A project with no `follows:` anywhere gets two empty maps.

    `build` is imported here rather than at module scope: build.py imports
    this module for its own build step, so a top-level import would be a
    cycle.
    """
    from . import build as build_mod

    by_key = build_mod._key_index(project)
    predecessors: dict[str, list[Item]] = {}
    successors: dict[str, list[Item]] = {}
    handles = _handles(project)
    for handle, item in project.items.items():
        targets = item.links.get(FOLLOWS) or []
        if not targets:
            continue
        seen: set[str] = set()
        for raw in targets:
            target = build_mod.resolve_link_target(by_key, project, raw)
            if target is None:
                continue
            target_handle = handles.get(id(target))
            if target_handle is None or target_handle in seen:
                continue
            seen.add(target_handle)
            predecessors.setdefault(handle, []).append(target)
            successors.setdefault(target_handle, []).append(item)
    return predecessors, successors


def _tips_from(
    handle: str,
    successors: dict[str, list[Item]],
    handles: dict[int, str],
    items: dict[str, Item],
) -> list[Item]:
    """`tips()`'s walk, against an already-built graph — so the build step
    pays for `build_graph` once, not once per forked entry."""
    tip_nodes: list[Item] = []
    stack = [handle]
    visited = {handle}
    while stack:
        node = stack.pop()
        following = successors.get(node, [])
        if not following:
            tip_nodes.append(items[node])
        for successor in following:
            nxt = handles.get(id(successor))
            if nxt is None or nxt in visited:
                continue
            visited.add(nxt)
            stack.append(nxt)
    return tip_nodes


def tips(project: Project, start: Item | str) -> list[Item]:
    """Every entry reachable forward from `start` (inclusive) with no
    successors of its own. A start with nothing after it is its own tip."""
    handle = _start_handle(project, start)
    if handle is None:
        return []
    _, successors = build_graph(project)
    return _tips_from(handle, successors, _handles(project), project.items)


def resolve_current(project: Project, start: Item | str, field: str) -> Any | None:
    """The chain's current value of `field`, per threads.md §3.

    Walk forward to the reachable tips; more than one tip (an unmerged fork,
    §6) is undefined — never "settled" — so this returns None. From the
    single tip, walk backward over *all* predecessors (a merge entry has
    several) breadth-first by distance from the tip, and return `field` from
    the nearest entry that declares it. An entry omitting the field does not
    clear it. Two entries at the same nearest distance declaring different
    values is ambiguous: None.
    """
    found = tips(project, start)
    if len(found) != 1:
        return None
    tip = found[0]
    tip_handle = _handles(project).get(id(tip))
    if tip_handle is None:
        return None

    predecessors, _ = build_graph(project)
    handles = _handles(project)
    items = project.items
    frontier = [tip_handle]
    visited = {tip_handle}
    while frontier:
        declared = [
            items[node].fields[field]
            for node in frontier
            if field in items[node].fields
        ]
        if declared:
            first = declared[0]
            return first if all(value == first for value in declared) else None
        nxt: list[str] = []
        for node in frontier:
            for predecessor in predecessors.get(node, []):
                ph = handles.get(id(predecessor))
                if ph is None or ph in visited:
                    continue
                visited.add(ph)
                nxt.append(ph)
        frontier = nxt
    return None


def _find_cycle(project: Project, predecessors: dict[str, list[Item]]) -> list[str] | None:
    """Node handles of one `follows:` cycle, in walk order, closing back on
    the first — or None when the graph is a DAG. Walked backward along
    `follows:`, so `A -> B` in the result reads "A follows B", matching how
    `blocked.py`'s cycle path reads along `blocked_by`.

    Iterative so a long chain can't blow the recursion limit, with the walk
    stack tracked explicitly (a node pushes its own "returning" marker, so
    the path is the true current path, not every node ever seen) and the
    cycle sliced out of it. The last node is the one whose own `follows:`
    declaration closes the loop -- the edge whoever reads this would edit.
    """
    handles = _handles(project)
    state: dict[str, int] = {}  # 0 = on the current path, 1 = fully explored
    for origin in project.items:
        if state.get(origin) == 1:
            continue
        stack: list[tuple[str, bool]] = [(origin, False)]
        path: list[str] = []
        while stack:
            node, returning = stack.pop()
            if returning:
                state[node] = 1
                path.pop()
                continue
            if state.get(node) is not None:
                continue
            state[node] = 0
            path.append(node)
            stack.append((node, True))
            for predecessor in predecessors.get(node, []):
                nxt = handles.get(id(predecessor))
                if nxt is None:
                    continue
                if state.get(nxt) == 0:
                    return path[path.index(nxt):] + [nxt]
                if state.get(nxt) is None:
                    stack.append((nxt, False))
    return None


def resolve(project: Project) -> None:
    """Fork `info` and cycle `error` for `follows:` chains (threads.md §6).

    Runs after `resolve_links`, mirroring `blocked_mod.resolve`: the graph
    is only trustworthy once targets resolve. A cycle is a hard error
    reported once for the whole cycle; a fork is `info`, not even a warning
    — two people editing concurrently is a normal, recoverable outcome, not
    a mistake.
    """
    predecessors, successors = build_graph(project)
    if not predecessors:
        return  # no follows: anywhere -- nothing to report, nothing to walk

    cycle = _find_cycle(project, predecessors)
    if cycle:
        names = " -> ".join(_name(project.items[node]) for node in cycle)
        closer = project.items[cycle[-2]]
        project.error(
            f"follows cycle: {names}",
            file=closer.source_file,
            line=closer.source_line,
            item_id=closer.id,
        )
        return

    handles = _handles(project)
    for handle, following in successors.items():
        if len(following) < 2:
            continue
        # A fork a later merge entry has already reconciled is not an open
        # fork: §6's remedy is "append an entry declaring follows: [both
        # tips]", and a diagnostic that outlives its own remedy is noise. If
        # everything downstream of this entry reconverges on one tip, the
        # thread has concluded again -- report only while it hasn't.
        if len(_tips_from(handle, successors, handles, project.items)) < 2:
            continue
        entry = project.items[handle]
        names = ", ".join(_name(successor) for successor in following)
        quantifier = "both" if len(following) == 2 else "all"
        project.info(
            f"this thread has forked: {names} {quantifier} declare follows: [{_name(entry)}]. "
            "Coverage and checks treat an unmerged fork as unsettled -- append an "
            "entry declaring follows: [both tips] to reconcile it, or leave the "
            "fork if the two continuations are genuinely independent.",
            file=entry.source_file,
            line=entry.source_line,
            item_id=entry.id,
        )
