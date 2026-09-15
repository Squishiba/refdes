"""`follows:` chain walk: tips, the per-field fold, fork and cycle diagnostics.

See docs/design/threads.md §3 ("A lazy walk, not a persistent registry",
"Branching's effect on current") and §6 ("Two entries claiming the same
predecessor", "Merging", "Cycles"). Same role for `follows:` that
`blocked.py` plays for `blocked_by:` — a dedicated walk pass with cycle
detection and diagnostics, run as a build step after link resolution.

The graph is built here from raw `follows:` targets resolved through
`build.resolve_link_target`, rather than read from `backlinks`/
`resolved_links`: those derived maps are for ordinary graph consumers,
while this module needs the durable `project.items` handles to implement
chain-specific walks. Nodes are therefore identified by the surrogate key
or provisional handle, and named in diagnostics by display id or key.

Phase 3a perf: per-graph memoization of `resolve_current` by (component, field).
The `ChainGraph` class wraps the (predecessors, successors) pair and caches
connected-component ids and fold results so a thread of N entries costs O(N),
not O(N²).
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


class ChainGraph:
    """The follows graph with per-build memoization for `resolve_current`.

    Instances are created by `build_graph` and passed through the build
    pipeline. They unpack as `(predecessors, successors)` for backward
    compatibility with existing call sites. The cache and component map
    are built lazily on first use and never outlive the graph (one per build).
    """

    __slots__ = (
        "_component_of",
        "_component_tips",
        "_handles",
        "_items",
        "_resolve_cache",
        "predecessors",
        "successors",
    )

    def __init__(
        self,
        predecessors: dict[str, list[Item]],
        successors: dict[str, list[Item]],
        handles: dict[int, str],
        items: dict[str, Item],
    ):
        self.predecessors = predecessors
        self.successors = successors
        self._handles = handles
        self._items = items
        # Populated lazily by _ensure_components()
        self._component_of: dict[str, int] | None = None
        # (component_id, field) -> resolved value (or a sentinel for None)
        self._resolve_cache: dict[tuple[int, str], Any] = {}
        # component_id -> frozenset of tip handles (computed once per component)
        self._component_tips: dict[int, frozenset[str]] = {}

    def __iter__(self):
        """Unpack as (predecessors, successors) for backward compatibility."""
        return iter((self.predecessors, self.successors))

    def __eq__(self, other):
        """Compare equal to (predecessors, successors) tuple for backward compatibility."""
        if isinstance(other, tuple) and len(other) == 2:
            return (self.predecessors, self.successors) == other
        return NotImplemented

    def _ensure_components(self) -> None:
        """Compute connected-component id for every node in the graph.

        Two nodes are in the same component iff they are connected by any
        path of follows edges (forward or backward). This is exactly the set
        of nodes that share the same `resolve_current` result for any field.
        """
        if self._component_of is not None:
            return
        comp: dict[str, int] = {}
        comp_id = 0
        # All nodes that appear anywhere in the graph
        all_nodes = set(self.predecessors) | set(self.successors)
        for node in all_nodes:
            if node in comp:
                continue
            # BFS/DFS to mark the whole component
            stack = [node]
            comp[node] = comp_id
            while stack:
                cur = stack.pop()
                for pred in self.predecessors.get(cur, []):
                    ph = self._handles.get(id(pred))
                    if ph is not None and ph not in comp:
                        comp[ph] = comp_id
                        stack.append(ph)
                for succ in self.successors.get(cur, []):
                    sh = self._handles.get(id(succ))
                    if sh is not None and sh not in comp:
                        comp[sh] = comp_id
                        stack.append(sh)
            comp_id += 1
        self._component_of = comp

    def component_id(self, handle: str) -> int | None:
        """Return the component id for `handle`, or None if not in graph."""
        self._ensure_components()
        return self._component_of.get(handle)

    def cache_get(self, component_id: int, field: str) -> tuple[bool, Any]:
        """Check cache for (component_id, field). Returns (found, value)."""
        key = (component_id, field)
        if key in self._resolve_cache:
            return True, self._resolve_cache[key]
        return False, None

    def cache_set(self, component_id: int, field: str, value: Any) -> None:
        """Store resolved value for (component_id, field)."""
        self._resolve_cache[(component_id, field)] = value

    def tips_get(self, component_id: int) -> frozenset[str] | None:
        """Get cached tips for component, or None if not computed yet."""
        return self._component_tips.get(component_id)

    def tips_set(self, component_id: int, tips: frozenset[str]) -> None:
        """Cache tips for component."""
        self._component_tips[component_id] = tips


def build_graph(
    project: Project, *, frozen_only: bool = False
) -> ChainGraph:
    """Build the follows graph, returning a `ChainGraph` with memoization.

    ``frozen_only`` excludes bare display-ID references so a write-back pass
    can resolve new entries against the existing durable chain rather than
    accidentally selecting an unfrozen entry as its own tip.

    A target that does not resolve is simply not an edge — `resolve_links`
    has already reported it as its own error, and this pass adds nothing to
    say about it. A project with no `follows:` anywhere gets an empty graph.

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
            if frozen_only and "@" not in raw and not build_mod._is_well_formed_bare_key(raw):
                continue
            target = build_mod.resolve_link_target(by_key, project, raw)
            if target is None:
                continue
            target_handle = handles.get(id(target))
            if target_handle is None or target_handle in seen:
                continue
            seen.add(target_handle)
            predecessors.setdefault(handle, []).append(target)
            successors.setdefault(target_handle, []).append(item)
    return ChainGraph(predecessors, successors, handles, project.items)


def is_threaded(
    project: Project,
    item: Item,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> bool:
    """Whether `item` participates in at least one resolved follows edge."""
    if graph is None:
        graph = build_graph(project)
    # Accept both ChainGraph and the legacy tuple
    predecessors = graph.predecessors if isinstance(graph, ChainGraph) else graph[0]
    successors = graph.successors if isinstance(graph, ChainGraph) else graph[1]
    handle = _start_handle(project, item)
    return handle is not None and (handle in predecessors or handle in successors)


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


def tips(
    project: Project,
    start: Item | str,
    *,
    successors: dict[str, list[Item]] | None = None,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> list[Item]:
    """Every entry reachable forward from ``start`` with no successors.

    ``successors`` lets a caller add a small, in-memory prospective edge set
    while retaining this module's one traversal implementation. ``graph``
    reuses a precomputed `(predecessors, successors)` pair for callers that
    need many walks during one build.
    """
    handle = _start_handle(project, start)
    if handle is None:
        return []
    if isinstance(graph, ChainGraph):
        succs = graph.successors
    elif graph is not None:
        succs = graph[1]
    else:
        succs = build_graph(project).successors
    if successors is not None:
        succs = successors
    return _tips_from(handle, succs, _handles(project), project.items)


def resolve_current(
    project: Project,
    start: Item | str,
    field: str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> Any | None:
    """The chain's current value of `field`, per threads.md §3.

    Walk forward to the reachable tips; more than one tip (an unmerged fork,
    §6) is undefined — never "settled" — so this returns None. From the
    single tip, walk backward over *all* predecessors (a merge entry has
    several) breadth-first by distance from the tip, and return `field` from
    the nearest entry that declares it. An entry omitting the field does not
    clear it. Two entries at the same nearest distance declaring different
    values is ambiguous: None.

    "Declares it" means the entry's own keys said so. A value handed down by
    the file's `defaults:` block is present in `item.fields` but named in
    `item.inherited_fields`, and is not this entry declaring anything: a log
    file defaulting `status: proposed` would otherwise have every silent
    entry in it shadow the `accepted` its head actually wrote.
    ``graph`` lets repeated resolution in one build reuse the parsed follows
    edges instead of rebuilding them for every entry. When `graph` is a
    `ChainGraph`, results are memoized per (connected component, field),
    including the fork/no-tip cases. The component's tips are computed once
    over the ENTIRE component (all nodes with no successors), so every entry
    in the component gets the same result.
    """
    if isinstance(graph, ChainGraph):
        cg = graph
        predecessors, successors = cg.predecessors, cg.successors
        handles = cg._handles
        items = cg._items
    else:
        if graph is None:
            predecessors, successors = build_graph(project)
        else:
            predecessors, successors = graph
        handles = _handles(project)
        items = project.items

    start_handle = _start_handle(project, start)
    if start_handle is None:
        return None

    # If we have a ChainGraph, check cache FIRST using component from start_handle
    if isinstance(graph, ChainGraph):
        comp_id = cg.component_id(start_handle)
        if comp_id is not None:
            found, cached = cg.cache_get(comp_id, field)
            if found:
                return cached
    else:
        comp_id = None

    # For ChainGraph, get or compute the component's tips (all nodes with no successors in the component)
    if isinstance(graph, ChainGraph) and comp_id is not None:
        # Check if we already cached tips for this component
        cached_tips = cg.tips_get(comp_id)
        if cached_tips is not None:
            tips_frozen = cached_tips
        else:
            # Compute ALL tips in the component: nodes in this component with no successors
            tips_frozen = _compute_component_tips(comp_id, cg, handles, items, successors, predecessors)
            cg.tips_set(comp_id, tips_frozen)
    else:
        # Without ChainGraph, compute component tips from scratch each time
        # (still per-component semantics, just not memoized)
        # First find all nodes in the component by walking from start
        component_nodes: set[str] = set()
        stack = [start_handle]
        seen = {start_handle}
        while stack:
            node = stack.pop()
            component_nodes.add(node)
            # Walk backwards
            for predecessor in predecessors.get(node, []):
                prev = handles.get(id(predecessor))
                if prev is not None and prev not in seen:
                    seen.add(prev)
                    stack.append(prev)
            # Walk forwards
            for successor in successors.get(node, []):
                succ_handle = handles.get(id(successor))
                if succ_handle is not None and succ_handle not in seen:
                    seen.add(succ_handle)
                    stack.append(succ_handle)

        # Find all tips in this component (nodes with no internal successors)
        tips_frozen = frozenset(
            node
            for node in component_nodes
            if not any(
                handles.get(id(succ)) in component_nodes
                for succ in successors.get(node, [])
            )
        )

    if len(tips_frozen) != 1:
        # Fork or no tip - cache None result
        if isinstance(graph, ChainGraph) and comp_id is not None:
            cg.cache_set(comp_id, field, None)
        return None

    tip_handle = next(iter(tips_frozen))

    # Perform the fold
    frontier = [tip_handle]
    visited = {tip_handle}
    while frontier:
        declared = [
            items[node].fields[field]
            for node in frontier
            if field in items[node].fields
            and field not in items[node].inherited_fields
        ]
        if declared:
            first = declared[0]
            result = first if all(value == first for value in declared) else None
            # Cache the result if we have a ChainGraph
            if isinstance(graph, ChainGraph) and comp_id is not None:
                cg.cache_set(comp_id, field, result)
            return result
        nxt: list[str] = []
        for node in frontier:
            for predecessor in predecessors.get(node, []):
                ph = handles.get(id(predecessor))
                if ph is None or ph in visited:
                    continue
                visited.add(ph)
                nxt.append(ph)
        frontier = nxt
    result = None
    if isinstance(graph, ChainGraph) and comp_id is not None:
        cg.cache_set(comp_id, field, result)
    return None


def _compute_component_tips(
    comp_id: int,
    cg: ChainGraph,
    handles: dict[int, str],
    items: dict[str, Item],
    successors: dict[str, list[Item]],
    predecessors: dict[str, list[Item]],
) -> frozenset[str]:
    """Compute ALL tips in a connected component.

    A tip is a node in the component that has no successors (within the component).
    """
    # Get all nodes in this component
    component_nodes = {node for node, cid in cg._component_of.items() if cid == comp_id}

    # Find all nodes in the component that have no successors within the component
    tips: set[str] = set()
    for node in component_nodes:
        node_successors = successors.get(node, [])
        # Check if any successor is in the same component
        has_internal_successor = False
        for succ in node_successors:
            succ_handle = handles.get(id(succ))
            if succ_handle is not None and succ_handle in component_nodes:
                has_internal_successor = True
                break
        if not has_internal_successor:
            tips.add(node)

    return frozenset(tips)


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


def resolve(
    project: Project,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> None:
    """Fork `info` and cycle `error` for `follows:` chains (threads.md §6).

    Runs after `resolve_links`, mirroring `blocked_mod.resolve`: the graph
    is only trustworthy once targets resolve. A cycle is a hard error
    reported once for the whole cycle; a fork is `info`, not even a warning
    — two people editing concurrently is a normal, recoverable outcome, not
    a mistake. ``graph`` reuses a build-wide precomputed graph.
    """
    if isinstance(graph, ChainGraph):
        predecessors, successors = graph.predecessors, graph.successors
    elif graph is not None:
        predecessors, successors = graph
    else:
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