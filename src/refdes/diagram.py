"""The vocabulary diagram: the resolved type/link graph as plain inline SVG.

Finding 38, chunk 3b. Three things this deliberately is not:

- **not Mermaid.** Jared's call: the bundled `refdes schema --graph` used to
  print Mermaid source, which pushed the rendering -- and the runtime
  dependency, and the question of whether a reader's viewer runs it -- onto
  whoever looked at it. This emits the picture itself.
- **not a graph library.** graphviz needs a native binary; the pure-Python
  layout packages are heavier than the problem. The graph here is a dozen
  nodes and a few dozen edges, which a layered layout handles in a page of
  code, and a page of code is something `refdes` can explain and a
  distribution cannot trip over.
- **not interactive.** No script element, no handler attribute, no
  `foreignObject`. The nodes are ordinary anchors into the vocabulary page,
  the colours are the site's own CSS custom properties with literal
  fallbacks, so the same bytes follow dark mode and print, standalone and
  embedded.

Determinism is the property the committed copy depends on: the docs site
checks in the generated SVG, and a diff there has to mean the schema
changed. So every iteration is sorted, every coordinate is rounded through
one formatter, and nothing reads a clock, a hash seed or a filesystem.

The layout is Sugiyama-shaped, in the small: break cycles with a DFS,
longest-path layering on what is left, four barycenter sweeps to untangle,
then stack each layer and string the edges as cubic beziers behind the
nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .model import Project

# The synthetic target of a verb declared with an empty target list
# (`links: {blocked_by: []}`): one general edge to one node, not one edge
# per known type -- the same convention `schema_json.link_json_schema` and
# the vocabulary page use.
ANY = "any"

# Layout constants. Sizes are in SVG user units; the viewBox scales them, so
# the picture is resolution-independent and the numbers only ever matter in
# proportion to each other.
NODE_H = 30
NODE_GAP_Y = 34
LAYER_GAP_X = 104
PAD_X = 14
FONT_SIZE = 12.5
CHAR_W = 7.5  # a monospace glyph at FONT_SIZE, measured close enough
EDGE_LANE = 7  # vertical offset between parallel edges sharing a node pair
MARGIN = 16


@dataclass(frozen=True, order=True)
class Edge:
    """One declared link: `source --verb--> target`."""

    source: str
    verb: str
    target: str


def graph(project: Project) -> list[Edge]:
    """Every link the resolved schema declares, deduplicated and sorted.

    Deduplicated because a verb declared from both ends (the schema allows
    it; it is merely redundant) is still one edge, and sorted because this
    list is the input to a layout whose output is checked into a file.
    """
    edges: set[Edge] = set()
    for type_name, spec in project.types.items():
        for verb, targets in spec.links.items():
            for target in targets or [ANY]:
                edges.add(Edge(type_name, verb, target))
    return sorted(edges)


def _nodes(edges: list[Edge], project: Project) -> list[str]:
    """Every type, plus the synthetic any node only when something points
    at it. A type with no links at all still appears: the diagram is of the
    vocabulary, not only of its edges."""
    names = set(project.types)
    for e in edges:
        names.add(e.source)
        names.add(e.target)
    return sorted(names)


def _n(value: float) -> str:
    """One number, formatted the same way every time. Rounded to a
    decimetre of a pixel and stripped of a trailing `.0`, so the same graph
    never differs by floating-point noise between runs."""
    text = f"{value:.1f}"
    return text.removesuffix(".0")


def _width(name: str) -> float:
    return PAD_X * 2 + CHAR_W * len(name)


# ------------------------------------------------------------------- layering


def _layers(nodes: list[str], edges: list[Edge]) -> dict[str, int]:
    """Layer index per node: longest path from a source, after the cycles
    are cut.

    A vocabulary has cycles -- `decision --supersedes--> decision` is a
    self-loop, and two verbs that are each other's inverse can close a
    loop -- and a layered layout needs a DAG. The cut is a DFS in sorted
    order: an edge to a node still on the stack is a back edge and does not
    constrain layering. It is still drawn; it simply flows backwards.
    """
    succ: dict[str, list[str]] = {name: [] for name in nodes}
    for e in edges:
        if e.source != e.target and e.target not in succ[e.source]:
            succ[e.source].append(e.target)
    for targets in succ.values():
        targets.sort()

    back: set[tuple[str, str]] = set()
    state: dict[str, int] = {name: 0 for name in nodes}  # 0 new, 1 open, 2 done
    for root in nodes:
        if state[root]:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            node, children = stack[-1]
            nxt = next(children, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            if state[nxt] == 1:
                back.add((node, nxt))
            elif state[nxt] == 0:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))

    dag = {name: [t for t in succ[name] if (name, t) not in back] for name in nodes}
    indeg = {name: 0 for name in nodes}
    for name in nodes:
        for target in dag[name]:
            indeg[target] += 1

    layer = {name: 0 for name in nodes}
    ready = sorted(n for n in nodes if indeg[n] == 0)
    while ready:
        node = ready.pop(0)
        for target in dag[node]:
            layer[target] = max(layer[target], layer[node] + 1)
            indeg[target] -= 1
            if indeg[target] == 0:
                ready.append(target)
                ready.sort()
    return layer


def _ordering(nodes: list[str], edges: list[Edge], layer: dict[str, int]) -> dict[int, list[str]]:
    """Order within each layer: start alphabetical, then four barycenter
    sweeps -- a node moves toward the average position of the nodes it
    connects to in the layer being held still. Ties break on the name, so
    the sweep is a function of the graph and nothing else."""
    by_layer: dict[int, list[str]] = {}
    for name in nodes:
        by_layer.setdefault(layer[name], []).append(name)
    for members in by_layer.values():
        members.sort()

    neighbours: dict[str, list[str]] = {name: [] for name in nodes}
    for e in edges:
        if e.source == e.target:
            continue
        neighbours[e.source].append(e.target)
        neighbours[e.target].append(e.source)

    top = max(by_layer) if by_layer else 0
    for sweep in range(4):
        indexes = range(1, top + 1) if sweep % 2 == 0 else range(top - 1, -1, -1)
        anchor_layer = (lambda i: i - 1) if sweep % 2 == 0 else (lambda i: i + 1)
        for index in indexes:
            if anchor_layer(index) not in by_layer:
                continue
            position = {
                name: pos for pos, name in enumerate(by_layer[anchor_layer(index)])
            }
            barycenter = {}
            for name in by_layer[index]:
                around = [position[n] for n in neighbours[name] if n in position]
                if around:
                    barycenter[name] = sum(around) / len(around)
            by_layer[index].sort(
                key=lambda name: (barycenter.get(name, float("inf")), name)
            )
    return by_layer


# ----------------------------------------------------------------- geometry


@dataclass
class _Point:
    x: float
    y: float


def _place(by_layer: dict[int, list[str]], layer: dict[str, int]) -> dict[str, _Point]:
    """Assign each node its top-left corner. Layers advance left to right;
    within a layer nodes stack, and a short layer is centred against the
    tallest one so the graph sits around its middle line rather than
    drifting up."""
    tallest = max(
        (len(members) * (NODE_H + NODE_GAP_Y) for members in by_layer.values()),
        default=NODE_H,
    )
    pos: dict[str, _Point] = {}
    x = float(MARGIN)
    for index in sorted(by_layer):
        members = by_layer[index]
        width = max(_width(name) for name in members)
        height = len(members) * (NODE_H + NODE_GAP_Y) - NODE_GAP_Y
        y = MARGIN + (tallest - height) / 2
        for name in members:
            pos[name] = _Point(x, y)
            y += NODE_H + NODE_GAP_Y
        x += width + LAYER_GAP_X
    return pos


def _bezier(p0, p1, p2, p3, t=0.5):
    """The point at `t` on a cubic, used to park an edge label on its line."""
    u = 1 - t
    a, b, c, d = u**3, 3 * u * u * t, 3 * u * t * t, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _edge_path(e: Edge, pos: dict[str, _Point], lane: int) -> tuple[str, tuple[float, float]]:
    """The `d` of one edge and where its label goes.

    Forward edges arc gently from the source's right side to the target's
    left. Backward edges -- a verb that points at a layer the layout put
    behind it, including the two ends of an inverse pair -- take the same
    cubic with the control points thrown wide, so they sweep around the
    nodes rather than through them; they are drawn first, so anything they
    still cross passes behind a node box. A self-loop is a small loop off
    the right edge: it is a real declaration, and dropping it would make
    the diagram lie about the schema.
    """
    src, dst = pos[e.source], pos[e.target]
    offset = lane * EDGE_LANE
    if e.source == e.target:
        sx, sy = src.x + _width(e.source), src.y + NODE_H / 2
        d = (
            f"M {_n(sx)} {_n(sy - 6)} "
            f"c 30 -18, 30 18, 0 12"
        )
        return d, (sx + 26, sy + offset)
    p0 = (src.x + _width(e.source), src.y + NODE_H / 2 + offset)
    p3 = (dst.x, dst.y + NODE_H / 2 + offset)
    dx = p3[0] - p0[0]
    if dx > 0:
        p1 = (p0[0] + dx * 0.5, p0[1])
        p2 = (p3[0] - dx * 0.5, p3[1])
    else:
        p1 = (p0[0] + 70, p0[1])
        p2 = (p3[0] - 70, p3[1])
    d = f"M {_n(p0[0])} {_n(p0[1])} C {_n(p1[0])} {_n(p1[1])}, {_n(p2[0])} {_n(p2[1])}, {_n(p3[0])} {_n(p3[1])}"
    return d, _bezier(p0, p1, p2, p3)


# ------------------------------------------------------------------- render


def render_svg(project: Project) -> str:
    """The whole `<svg>` element, as one string.

    Presentation lives in attributes on the elements, using the site's CSS
    custom properties with literal fallbacks: inside a built page the
    theme's values win (so dark mode and print come free), and standalone
    -- `refdes schema --graph > graph.svg` -- the fallbacks render.
    """
    edges = graph(project)
    nodes = _nodes(edges, project)
    layer = _layers(nodes, edges)
    by_layer = _ordering(nodes, edges, layer)
    pos = _place(by_layer, layer)

    right = max(p.x + _width(name) for name, p in pos.items()) + MARGIN
    bottom = max(p.y for p in pos.values()) + NODE_H + MARGIN

    # Parallel edges -- the same node pair joined by two verbs -- get lanes
    # so their lines and labels separate. Sorted first, so the lane a verb
    # gets depends on the schema and not on a dict.
    lanes: dict[tuple[str, str], int] = {}
    sized = sorted(edges, key=lambda e: (e.source, e.target, e.verb))

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(right)} {_n(bottom)}" '
            f'width="100%" height="{_n(bottom)}" role="img" '
            f'font-family="var(--mono, ui-monospace, monospace)" font-size="{FONT_SIZE}">'
        ),
        f"<title>{escape('Type and link graph')}</title>",
        (
            '<defs><marker id="refdes-arrow" viewBox="0 0 8 8" refX="7" refY="4" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0,0 L8,4 L0,8 z" fill="var(--accent, #1f5fbf)"/></marker></defs>'
        ),
    ]

    # Edges first: nodes paint over them, so a back edge that has to cross
    # the graph reads as passing behind it.
    for e in sized:
        key = (e.source, e.target)
        lane = lanes.get(key, 0)
        lanes[key] = lane + 1
        d, (lx, ly) = _edge_path(e, pos, lane)
        parts.append(
            f'<g class="edge" data-source="{escape(e.source)}" data-verb="{escape(e.verb)}" '
            f'data-target="{escape(e.target)}">'
            f'<path d="{d}" fill="none" stroke="var(--muted, #666e79)" stroke-width="1" '
            f'opacity="0.75" marker-end="url(#refdes-arrow)"/>'
            f'<text x="{_n(lx)}" y="{_n(ly - 3)}" text-anchor="middle" '
            f'fill="var(--accent, #1f5fbf)" font-size="{FONT_SIZE - 1.5}" '
            f'stroke="var(--bg, #ffffff)" stroke-width="3" style="paint-order:stroke">'
            f"{escape(e.verb)}</text></g>"
        )

    for name in nodes:
        p = pos[name]
        width = _width(name)
        box = (
            f'<rect width="{_n(width)}" height="{NODE_H}" rx="6" '
            f'fill="var(--panel, #f7f8fa)" stroke="var(--line, #e0e4e9)"/>'
            f'<text x="{_n(width / 2)}" y="{_n(NODE_H / 2)}" text-anchor="middle" '
            f'dominant-baseline="central" fill="var(--fg, #16191d)">'
            f"{escape('any type' if name == ANY else name)}</text>"
        )
        # The synthetic any node is not a term, so it has no anchor to
        # point at; every real type links to its entry on this page.
        body = f'<a href="#term-{escape(name)}">{box}</a>' if name != ANY else box
        parts.append(
            f'<g class="node" data-node="{escape(name)}" '
            f'transform="translate({_n(p.x)} {_n(p.y)})">{body}</g>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
