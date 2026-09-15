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

from typing import Any, Callable

from . import dates
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


def _start_handle(project: Project, start: Item | str, handles: dict[int, str] | None = None) -> str | None:
    """Accept an Item, a `project.items` key/handle, or a display id."""
    h = handles if handles is not None else _handles(project)
    if isinstance(start, Item):
        return h.get(id(start))
    if start in project.items:
        return start
    item = project.item_by_id(start)
    return h.get(id(item)) if item is not None else None

class ChainGraph:
    """The follows graph with per-build memoization for `resolve_current`.

    Instances are created by `build_graph` and passed through the build
    pipeline. They unpack as `(predecessors, successors)` for backward
    compatibility with existing call sites. The cache and component map
    are built lazily on first use and never outlive the graph (one per build).
    """

    __slots__ = (
        "_component_nodes",
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
        # component_id -> list of node handles (computed once per component)
        self._component_nodes: dict[int, list[str]] = {}

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
        comp_nodes: dict[int, list[str]] = {}
        comp_id = 0
        # All nodes that appear anywhere in the graph
        all_nodes = set(self.predecessors) | set(self.successors)
        for node in all_nodes:
            if node in comp:
                continue
            # BFS/DFS to mark the whole component
            nodes_in_component: list[str] = []
            stack = [node]
            comp[node] = comp_id
            nodes_in_component.append(node)
            while stack:
                cur = stack.pop()
                for pred in self.predecessors.get(cur, []):
                    ph = self._handles.get(id(pred))
                    if ph is not None and ph not in comp:
                        comp[ph] = comp_id
                        nodes_in_component.append(ph)
                        stack.append(ph)
                for succ in self.successors.get(cur, []):
                    sh = self._handles.get(id(succ))
                    if sh is not None and sh not in comp:
                        comp[sh] = comp_id
                        nodes_in_component.append(sh)
                        stack.append(sh)
            comp_nodes[comp_id] = nodes_in_component
            comp_id += 1
        self._component_of = comp
        self._component_nodes = comp_nodes

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
    if graph is None:
        graph = build_graph(project)
    # Accept both ChainGraph and the legacy tuple
    predecessors = graph.predecessors if isinstance(graph, ChainGraph) else graph[0]
    successors = graph.successors if isinstance(graph, ChainGraph) else graph[1]
    handles = graph._handles if isinstance(graph, ChainGraph) else None
    handle = _start_handle(project, item, handles=handles)
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
    handles_tips = graph._handles if isinstance(graph, ChainGraph) else None
    handle = _start_handle(project, start, handles=handles_tips)
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
    handles_tips_use = graph._handles if isinstance(graph, ChainGraph) else _handles(project)
    items_tips_use = (graph._items if isinstance(graph, ChainGraph) else project.items)
    return _tips_from(handle, succs, handles_tips_use, items_tips_use)


def _graph_view(graph, project: Project):
    """`(predecessors, successors, handles, items, cg)` for either graph shape.

    A `ChainGraph` carries the handle map and item map built once for the
    build, so a fold over it never pays for `_handles(project)` again; the
    legacy `(predecessors, successors)` tuple still works and rebuilds them
    per call, which is what it always cost.
    """
    if isinstance(graph, ChainGraph):
        return graph.predecessors, graph.successors, graph._handles, graph._items, graph
    if graph is None:
        built = build_graph(project)
        return built.predecessors, built.successors, built._handles, built._items, built
    predecessors, successors = graph
    return predecessors, successors, _handles(project), project.items, None


def _component(
    handle: str,
    predecessors: dict[str, list[Item]],
    successors: dict[str, list[Item]],
    handles: dict[int, str],
) -> set[str]:
    """Every node reachable from `handle` in *either* direction along
    `follows:` — the connected component, which is what a thread is (§8)."""
    seen = {handle}
    stack = [handle]
    while stack:
        node = stack.pop()
        for neighbour in predecessors.get(node, []) + successors.get(node, []):
            nxt = handles.get(id(neighbour))
            if nxt is None or nxt in seen:
                continue
            seen.add(nxt)
            stack.append(nxt)
    return seen


def _component_tips(
    handle: str,
    predecessors: dict[str, list[Item]],
    successors: dict[str, list[Item]],
    handles: dict[int, str],
    items: dict[str, Item],
    cg: ChainGraph | None,
) -> frozenset[str]:
    """The handles in `handle`'s component with nothing following them.

    This is the one definition of "has this thread forked?" (§3, §6): one tip
    means the thread is settled and folds, more than one means it is not, and
    the answer is the same whichever entry of the thread it is asked from — a
    fork on a sibling branch is a fork for the whole thread, not only for the
    entry that can see it forward. A component that is entirely a cycle has no
    tip and comes back empty.

    On a `ChainGraph` this is `_compute_component_tips`, computed once per
    component and memoized there; the tuple form recomputes it.
    """
    if cg is not None:
        comp_id = cg.component_id(handle)
        if comp_id is None:
            return frozenset({handle})
        cached = cg.tips_get(comp_id)
        if cached is not None:
            return cached
        tips = _compute_component_tips(
            comp_id, cg, handles, items, successors, predecessors
        )
        cg.tips_set(comp_id, tips)
        return tips
    nodes = _component(handle, predecessors, successors, handles)
    return frozenset(node for node in nodes if not successors.get(node))


def thread_tips(
    project: Project,
    start: Item | str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> list[Item]:
    """Every tip of the whole connected thread containing `start`, oldest
    first — the public form of `_component_tips`.

    `tips()` is the narrower question (what runs forward from one entry) and
    stays that way for callers like the build's fork report; this is what the
    fold and §8's panel ask, so a page can never conclude something its own
    fold would refuse to.
    """
    predecessors, successors, handles, items, cg = _graph_view(graph, project)
    handle = _start_handle(project, start, handles=handles)
    if handle is None:
        return []
    return sorted(
        (
            items[node]
            for node in _component_tips(
                handle, predecessors, successors, handles, items, cg
            )
        ),
        key=lambda item: _order_key(project, item),
    )


def thread_entries(
    project: Project,
    start: Item | str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> list[Item]:
    """Every entry in `start`'s connected thread, oldest first.

    Walks *both* directions along `follows:` (§8's chain view: a thread is the
    connected component, not the forward reach), so an entry mid-chain sees
    the whole of it. Order is (date, source file, source line) — the same
    chronological posture `log.html` takes, with file and line as the
    deterministic tiebreak for entries sharing a date. A lone item with no
    `follows:` in either direction is a thread of one, and returns itself.
    """
    predecessors, successors, handles, items, cg = _graph_view(graph, project)
    handle = _start_handle(project, start, handles=handles)
    if handle is None:
        return []
    if cg is not None:
        comp_id = cg.component_id(handle)
        nodes = (
            set(cg._component_nodes.get(comp_id, []))
            if comp_id is not None
            else {handle}
        )
    else:
        nodes = _component(handle, predecessors, successors, handles)
    return sorted(
        (items[node] for node in nodes), key=lambda item: _order_key(project, item)
    )


def _order_key(project: Project, item: Item) -> tuple:
    """Chronological thread order: `date:`, then source file, then source line."""
    return (_date_ordinal(project, item), item.source_file, item.source_line)


def _date_ordinal(project: Project, item: Item) -> int:
    """Sort key: chronological by `date:`, entries with no parseable date
    last (mirrors `render._date_sort_key`'s posture)."""
    value = item.fields.get("date")
    if value is None or str(value) == "":
        return 2**31 - 1
    try:
        return dates.parse_date(value, project.date_format).toordinal()
    except (TypeError, ValueError):
        return 2**31 - 1


def _declares(item: Item, name: str) -> bool:
    """True when this entry's *own* keys named `name` (a field or a link).

    A value handed down by the file's `defaults:` block is present in
    `item.fields` (and for a link, in `item.links`) but named in
    `item.inherited_fields`, and is not this entry declaring anything: a log
    file defaulting `status: proposed` would otherwise have every silent
    entry in it shadow the `accepted` its head actually wrote.
    """
    return name in item.fields and name not in item.inherited_fields


def _fold(
    project: Project,
    start: Item | str,
    declared_of: Callable[[Item], Any],
    *,
    cache_key: str,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> tuple[Any, Item | None]:
    """The one fold behind `resolve_current` and its with-source variants.

    Ask the whole connected thread for its tips (`_component_tips`); more than
    one (an unmerged fork anywhere in it, §6) is undefined — never "settled" —
    so this returns (None, None). From the single tip, walk backward over
    *all* predecessors (a merge entry has several) breadth-first by distance
    from the tip, and return the value `declared_of` gives for the nearest
    entries that declare it, paired with the one they came from. An entry that
    does not declare it does not clear the value.

    Ambiguity is about *values*, not entries: several entries at the same
    nearest distance agreeing on one value fold to that value — a silent merge
    entry whose two parents both say `accepted` still concludes `accepted` —
    and are attributed to the earliest of them by `_order_key` (date, then
    source file, then source line), so the page does not move between builds.
    Same nearest distance, different values: (None, None).

    `declared_of` returns None for "this entry does not declare it", so a
    caller folding a field whose declared value could be falsy still folds.
    `cache_key` names what is being folded — the field name, or `link:name`
    for a link — for the graph's per-(component, key) memo: every entry of a
    thread shares one component, so a thread costs one fold per key, not one
    per entry. The memo holds the `(value, source)` pair, so the value-only
    and with-source folds of one key share it.
    """
    predecessors, successors, handles, items, cg = _graph_view(graph, project)
    start_handle = _start_handle(project, start, handles=handles)
    if start_handle is None:
        return None, None

    comp_id = cg.component_id(start_handle) if cg is not None else None
    if cg is not None and comp_id is not None:
        found, cached = cg.cache_get(comp_id, cache_key)
        if found:
            return cached

    tips_frozen = _component_tips(
        start_handle, predecessors, successors, handles, items, cg
    )
    if len(tips_frozen) != 1:
        result: tuple[Any, Item | None] = (None, None)
    else:
        result = _fold_from_tip(
            project,
            next(iter(tips_frozen)),
            declared_of,
            predecessors,
            handles,
            items,
        )
    if cg is not None and comp_id is not None:
        cg.cache_set(comp_id, cache_key, result)
    return result


def _fold_from_tip(
    project: Project,
    tip_handle: str,
    declared_of: Callable[[Item], Any],
    predecessors: dict[str, list[Item]],
    handles: dict[int, str],
    items: dict[str, Item],
) -> tuple[Any, Item | None]:
    """`_fold`'s backward walk, from the thread's one tip."""
    frontier = [tip_handle]
    visited = {tip_handle}
    while frontier:
        hits = [
            (items[node], declared_of(items[node])) for node in frontier
        ]
        hits = [(item, value) for item, value in hits if value is not None]
        if hits:
            value = hits[0][1]
            if any(other != value for _item, other in hits[1:]):
                return None, None
            source = min(
                (item for item, _value in hits),
                key=lambda item: _order_key(project, item),
            )
            return value, source
        nxt: list[str] = []
        for node in frontier:
            for predecessor in predecessors.get(node, []):
                ph = handles.get(id(predecessor))
                if ph is None or ph in visited:
                    continue
                visited.add(ph)
                nxt.append(ph)
        frontier = nxt
    return None, None


def resolve_current(
    project: Project,
    start: Item | str,
    field: str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> Any | None:
    """The chain's current value of `field`, per threads.md §3.

    The whole connected thread is asked for its tips; more than one tip (an
    unmerged fork, §6) is undefined — never "settled" — so this returns None.
    From the single tip, walk backward over *all* predecessors (a merge entry
    has several) breadth-first by distance from the tip, and return `field`
    from the nearest entry that declares it. An entry omitting the field does
    not clear it. Two entries at the same nearest distance declaring different
    values is ambiguous: None; declaring the *same* value is agreement, and
    folds to it.

    "Declares it" means the entry's own keys said so — see `_declares`.
    ``graph`` lets repeated resolution in one build reuse the parsed follows
    edges instead of rebuilding them for every entry. When `graph` is a
    `ChainGraph`, results are memoized per (connected component, field),
    including the fork/no-tip cases: a thread of N entries costs one fold per
    field, not N.
    """
    value, _source = resolve_current_with_source(project, start, field, graph=graph)
    return value


def resolve_current_with_source(
    project: Project,
    start: Item | str,
    field: str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
) -> tuple[Any, Item | None]:
    """`resolve_current`'s fold, plus the entry the value came from.

    The rendering side (§8's "currently concludes" panel) has to say *which*
    entry concluded it, which the value-only fold throws away. Several entries
    tying at the nearest distance with the same value are attributed to the
    earliest of them by `_order_key`. (None, None) for the same reasons
    `resolve_current` returns None: forked, ambiguous, or nothing in the
    thread ever declared it.
    """
    return _fold(
        project,
        start,
        lambda item: item.fields[field] if _declares(item, field) else None,
        # Fields keep the bare name as their memo key — the key `resolve_current`
        # has always used — and links namespace themselves so a link can never
        # be handed a field's folded value.
        cache_key=field,
        graph=graph,
    )


def resolve_current_link_with_source(
    project: Project,
    start: Item | str,
    link: str,
    *,
    graph: ChainGraph | tuple[dict[str, list[Item]], dict[str, list[Item]]] | None = None,
    by_key: dict[str, Item] | None = None,
) -> tuple[list[Item], Item | None]:
    """The same fold over a *link* name: (resolved targets, declaring entry).

    The nearest entry walking back from the thread's one tip whose own `links`
    declare `link` — not inherited from `defaults:` — supplies the targets,
    resolved through `build.resolve_link_target` so a composite or bare-key
    spelling resolves the way every other structured link does. A target that
    does not resolve is dropped: `resolve_links` has already reported it. Same
    fork and equal-distance rules as `resolve_current`.

    `by_key` is `build._key_index(project)` when the caller has already built
    it — a page folding several link names shares one index.
    """
    from . import build as build_mod

    if by_key is None:
        by_key = build_mod._key_index(project)

    def declared_of(item: Item) -> Any:
        if link not in item.links or link in item.inherited_fields:
            return None
        targets = [
            target
            for target in (
                build_mod.resolve_link_target(by_key, project, raw)
                for raw in item.links.get(link) or []
            )
            if target is not None
        ]
        return targets or None

    targets, source = _fold(
        project, start, declared_of, cache_key=f"link:{link}", graph=graph
    )
    return (targets or []), source


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
    # Get component node list from cached per-component nodes
    component_nodes = set(cg._component_nodes.get(comp_id, []))

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