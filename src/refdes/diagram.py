"""The vocabulary diagrams: per-term connection pictures as plain inline SVG.

Finding 38, chunk 3b, rebuilt. The first version drew the whole schema --
every type, all twenty-nine declared edges -- as one auto-laid-out graph.
It was a hairball: rounded rectangles in no particular order, verb text
floating with no arrow to anchor it, labels landing on top of each other,
several edges on identical paths. Nobody could read it, and no amount of
tuning a layout algorithm fixes a picture that answers no question.

These drawings answer one question each. `render_spine_svg(project)` draws
the coverage spine: the three verbs `build._coverage_for` actually counts
-- addresses, satisfies, verifies -- as arrows reading
`decision satisfies [accepted] requirement`, with the status gate each
verb carries written into its label. It is the only whole-schema drawing
this module makes, because it is the only whole-schema question worth
asking; a project with none of the three verbs declared gets nothing.

`render_term_svg(project, type)`
draws one type and only its own connections, in a fixed three-column
layout with no layout algorithm at all:

- **left column**: one box per type that can point *at* this type, its
  arrow running right into the centre box;
- **centre**: this type, one box;
- **right column**: one type this type can point at, its arrow running
  right out of the centre box.

One row per (other type, direction) pair: several verbs connecting the
same pair in the same direction share one arrow and stack their labels on
it, so there is never a second arrow between the same two boxes. A verb
declared with an empty target list (`blocked_by: []`) gets one box
labelled *any type* -- the vocabulary page's own wording, and the same
convention `schema_json.link_json_schema` uses. A verb pointing at the
type's own kind draws a second box of that type in the right column;
there are no self-loops, because a loop that goes nowhere explains
nothing.

Direction reads the way a sentence does: **subject verb object**. A box
on the left means that type's own front matter names this one; a box on
the right means this type's front matter names it.

Text is measured, not guessed: a monospace glyph at 12.5 px is about
7.5 px wide, and every box here is wider than the text inside it. Labels
live in the gutters between the columns, centred on their arrow, and
rows grow to fit stacked labels so a label can never touch the row above
or below.

Three things this deliberately is not:

- **not Mermaid.** Jared's call: the picture is emitted here, not handed
  to a renderer the reader has to run.
- **not a graph library.** There is no layout to run; the columns are the
  layout.
- **not interactive.** No script element, no handler attribute, no
  `foreignObject`. The boxes are ordinary anchors into the vocabulary
  page, the colours are the site's own CSS custom properties with literal
  fallbacks, so the same bytes follow dark mode and print, standalone and
  embedded.

Determinism is the property the committed copies depend on: the docs site
checks in generated markup, and a diff there has to mean the schema
changed. So every iteration is sorted, every coordinate is rounded
through one formatter, and nothing reads a clock, a hash seed or a
filesystem.
"""

from __future__ import annotations

import re
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

# Geometry, in SVG user units; the viewBox scales them, so only the
# proportions matter.
NODE_H = 30
PAD_X = 12
FONT_SIZE = 12.5
CHAR_W = 7.5  # a monospace glyph at FONT_SIZE, measured close enough
LABEL_FONT = 11.0
LABEL_CHAR_W = 6.6  # a monospace glyph at LABEL_FONT
LABEL_H = 16
LABEL_PAD_X = 6
LABEL_GAP_Y = 4  # between stacked labels on one arrow
ROW_GAP_Y = 16  # between rows; labels never reach into it
GUTTER_MIN = 28
MARGIN = 16

# The box label for the synthetic ANY target. The vocabulary page writes
# "any type" for an unrestricted verb; the diagram says the same words.
ANY_LABEL = "any type"


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
    list is a record of the schema that gets compared and cited.
    """
    edges: set[Edge] = set()
    for type_name, spec in project.types.items():
        for verb, targets in spec.links.items():
            for target in targets or [ANY]:
                edges.add(Edge(type_name, verb, target))
    return sorted(edges)


def _n(value: float) -> str:
    """One number, formatted the same way every time. Rounded to a
    decimetre of a pixel and stripped of a trailing `.0`, so the same graph
    never differs by floating-point noise between runs."""
    text = f"{value:.1f}"
    return text.removesuffix(".0")


def _text_w(text: str, char_w: float = CHAR_W) -> float:
    return char_w * len(text)


def _box_w(text: str) -> float:
    """A box that fits `text` with breathing room on both sides."""
    return PAD_X * 2 + _text_w(text)


def _display(peer: str) -> str:
    return ANY_LABEL if peer == ANY else peer


# ---------------------------------------------------------------- the rows


def _inverse_map(project: Project) -> dict[str, str]:
    return {
        lt.inverse: name
        for name, lt in project.link_types.items()
        if lt.inverse
    }


def _term_rows(
    project: Project, type_name: str
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(incoming, outgoing) rows for one type: peer -> the verbs on that row.

    Resolves both declaration spellings the way `vocabulary._verb_facts`
    does: a verb declared under its own name points away from the
    declaring type, and a verb declared under its inverse name points at
    it (`note: {links: {documented_by: [requirement]}}` is
    `requirement --documents--> note`, so it is an incoming row on `note`
    and an outgoing row on `requirement`). An empty target list stands
    for the synthetic any-type peer.
    """
    inverse_to_verb = _inverse_map(project)
    incoming: dict[str, set[str]] = {}
    outgoing: dict[str, set[str]] = {}

    spec = project.types[type_name]
    for key, targets in (spec.links or {}).items():
        listed = list(targets or [])
        if key in project.link_types:
            for target in listed or [ANY]:
                outgoing.setdefault(target, set()).add(key)
        elif key in inverse_to_verb:
            for source in listed or [ANY]:
                incoming.setdefault(source, set()).add(inverse_to_verb[key])

    for other_name, other in project.types.items():
        if other_name == type_name:
            continue
        for key, targets in (other.links or {}).items():
            listed = targets or []
            if key in project.link_types:
                if type_name in listed:
                    incoming.setdefault(other_name, set()).add(key)
            elif key in inverse_to_verb:
                if type_name in listed:
                    outgoing.setdefault(other_name, set()).add(inverse_to_verb[key])

    return incoming, outgoing


# --------------------------------------------------------------- geometry


@dataclass
class _Slot:
    """One row placed: its peer, direction, verbs, centre line and height."""

    peer: str
    direction: str  # "in" or "out"
    verbs: tuple[str, ...]
    cy: float
    height: float


def _stack(rows: list[tuple[str, tuple[str, ...]]], direction: str) -> list[_Slot]:
    """Stack rows top to bottom, growing each row to fit its stacked labels."""
    slots: list[_Slot] = []
    y = float(MARGIN)
    for peer, verbs in rows:
        label_block = len(verbs) * LABEL_H + max(len(verbs) - 1, 0) * LABEL_GAP_Y
        height = max(NODE_H, label_block)
        slots.append(_Slot(peer, direction, verbs, y + height / 2, height))
        y += height + ROW_GAP_Y
    return slots


def _gutter_w(slots: list[_Slot]) -> float:
    """The gutter must hold the widest label that will sit in it."""
    widest = max(
        (_text_w(v, LABEL_CHAR_W) for s in slots for v in s.verbs), default=0.0
    )
    return max(widest + LABEL_PAD_X * 2 + 8, GUTTER_MIN)


# ------------------------------------------------------------------ render


def _marker_defs(marker_id: str) -> str:
    return (
        f'<defs><marker id="{marker_id}" viewBox="0 0 8 8" refX="7" refY="4" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L8,4 L0,8 z" fill="var(--accent, #1f5fbf)"/></marker></defs>'
    )


def _edge_svg(slot: _Slot, x0: float, x1: float, marker_id: str) -> str:
    """One arrow and its stacked labels. The arrow is a horizontal line at
    the row's centre, so no two rows can share a path; labels are centred
    on it in the gutter, painted over the line with an opaque box."""
    cx = (x0 + x1) / 2
    block = len(slot.verbs) * LABEL_H + max(len(slot.verbs) - 1, 0) * LABEL_GAP_Y
    parts = [
        f'<g class="edge" data-peer="{escape(slot.peer)}" '
        f'data-direction="{slot.direction}" '
        f'data-verbs="{escape(",".join(slot.verbs))}">',
        f'<path d="M {_n(x0)} {_n(slot.cy)} L {_n(x1)} {_n(slot.cy)}" fill="none" '
        f'stroke="var(--muted, #666e79)" stroke-width="1" '
        f'marker-end="url(#{marker_id})"/>',
    ]
    y = slot.cy - block / 2
    for verb in slot.verbs:
        w = _text_w(verb, LABEL_CHAR_W) + LABEL_PAD_X * 2
        parts.append(
            f'<rect class="label-box" x="{_n(cx - w / 2)}" y="{_n(y)}" '
            f'width="{_n(w)}" height="{LABEL_H}" rx="3" '
            f'fill="var(--bg, #ffffff)" stroke="var(--line, #e0e4e9)"/>'
            f'<text class="edge-label" x="{_n(cx)}" y="{_n(y + LABEL_H / 2)}" '
            f'font-size="{LABEL_FONT}" text-anchor="middle" '
            f'dominant-baseline="central" fill="var(--accent, #1f5fbf)">'
            f"{escape(verb)}</text>"
        )
        y += LABEL_H + LABEL_GAP_Y
    parts.append("</g>")
    return "".join(parts)


def _node_svg(name: str, x: float, y: float, width: float, height: float) -> str:
    box = (
        f'<rect class="node-box" x="{_n(x)}" y="{_n(y)}" '
        f'width="{_n(width)}" height="{_n(height)}" rx="6" '
        f'fill="var(--panel, #f7f8fa)" stroke="var(--line, #e0e4e9)"/>'
        f'<text class="node-label" x="{_n(x + width / 2)}" y="{_n(y + height / 2)}" '
        f'font-size="{FONT_SIZE}" text-anchor="middle" '
        f'dominant-baseline="central" fill="var(--fg, #16191d)">'
        f"{escape(_display(name))}</text>"
    )
    # The synthetic any box is not a term, so it has no anchor to point
    # at; every real type links to its entry on the vocabulary page.
    body = f'<a href="#term-{escape(name)}">{box}</a>' if name != ANY else box
    return f'<g class="node" data-node="{escape(name)}">{body}</g>'


# ---------------------------------------------------------------- the spine

# The three verbs `build._coverage_for` recognises -- the only verbs that
# move an item along the addressed -> satisfied -> verified pipeline. The
# spine draws nothing else: a picture of coverage that quietly includes
# `part_of` would be the same kind of lie the hairball was.
COVERAGE_VERBS = ("addresses", "satisfies", "verifies")

# Which TypeSpec attribute gates which verb, per `_coverage_for`: a
# satisfies link only closes coverage when the *satisfier's* status is in
# its type's satisfying_statuses; likewise verifies/verifying_statuses.
# addresses has no gate -- being addressed is not a claim about status.
_GATE_ATTR = {"satisfies": "satisfying_statuses", "verifies": "verifying_statuses"}


def _coverage_label(project: Project, verb: str, source: str) -> str:
    """An edge label: the verb plus the source type's status gate, if any.

    `satisfies [accepted]` says exactly what the build enforces: this link
    counts toward coverage when the satisfier's status is accepted. A type
    with no gate configured counts every link -- the label says just the
    verb, because there is nothing to promise.
    """
    attr = _GATE_ATTR.get(verb)
    if attr is None:
        return verb
    spec = project.types.get(source)
    allowed = getattr(spec, attr, None) if spec is not None else None
    if not allowed:
        return verb
    return f"{verb} [{', '.join(allowed)}]"


def _spine_rows(project: Project) -> list[tuple[str, str, tuple[str, ...]]]:
    """(source, target, labels) for every coverage link the schema declares.

    Both declaration spellings resolve to the forward direction, exactly as
    `_term_rows` does; a verb declared from both ends is still one row, and
    an empty target list is the synthetic any-type peer.
    """
    pairs: dict[tuple[str, str], set[str]] = {}
    for verb in COVERAGE_VERBS:
        lt = project.link_types.get(verb)
        if lt is None:
            continue
        for type_name in sorted(project.types):
            spec = project.types[type_name]
            for key, targets in (spec.links or {}).items():
                listed = list(targets or [])
                if key == verb:
                    for target in listed or [ANY]:
                        pairs.setdefault((type_name, target), set()).add(
                            _coverage_label(project, verb, type_name)
                        )
                elif lt.inverse and key == lt.inverse:
                    for source in listed or [ANY]:
                        pairs.setdefault((source, type_name), set()).add(
                            _coverage_label(project, verb, source)
                        )
    return [
        (source, target, tuple(sorted(labels)))
        for (source, target), labels in sorted(pairs.items())
    ]


def render_spine_svg(project: Project) -> str:
    """The project's coverage spine as a standalone `<svg>` element.

    One row per (source, target) pair the three coverage verbs connect --
    an arrow reading `decision satisfies [accepted] requirement` -- with
    subjects down the left and objects down the right. It is the answer to
    "how does work close coverage here?", and it is the only whole-schema
    drawing this module makes, because it is the only one that answers a
    question. A project whose schema declares none of the three coverage
    verbs gets the empty string: no drawing, no empty frame.
    """
    rows = _spine_rows(project)
    if not rows:
        return ""

    heights = [
        max(NODE_H, len(labels) * LABEL_H + (len(labels) - 1) * LABEL_GAP_Y)
        for _s, _t, labels in rows
    ]
    cys: list[float] = []
    y = float(MARGIN)
    for h in heights:
        cys.append(y + h / 2)
        y += h + ROW_GAP_Y

    left_w = max(_box_w(source) for source, _t, _l in rows)
    right_w = max(_box_w(_display(target)) for _s, target, _l in rows)
    gutter = max(
        (_text_w(label, LABEL_CHAR_W) for _s, _t, labels in rows for label in labels),
        default=0.0,
    )
    gutter = max(gutter + LABEL_PAD_X * 2 + 8, GUTTER_MIN)

    x_left = float(MARGIN)
    x_arrow0 = x_left + left_w
    x_right = x_arrow0 + gutter
    width = x_right + right_w + MARGIN
    height = y - ROW_GAP_Y + MARGIN

    marker_id = "refdes-arrow-spine"
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_n(width)} {_n(height)}" '
            f'width="100%" height="{_n(height)}" role="img" '
            f'font-family="var(--mono, ui-monospace, monospace)" '
            f'font-size="{FONT_SIZE}">'
        ),
        "<title>coverage spine</title>",
        _marker_defs(marker_id),
    ]

    for (source, target, labels), cy in zip(rows, cys):
        parts.append(
            _spine_edge_svg(source, target, labels, x_arrow0, x_right, cy, marker_id)
        )
    # Same rule as the term diagrams: uniform column widths, so every
    # arrow starts at its own box's right edge and ends at its own box's
    # left edge, with no gap and no ragged column.
    for (source, target, _labels), cy in zip(rows, cys):
        parts.append(_node_svg(source, x_left, cy - NODE_H / 2, left_w, NODE_H))
        parts.append(_node_svg(target, x_right, cy - NODE_H / 2, right_w, NODE_H))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _spine_edge_svg(
    source: str,
    target: str,
    labels: tuple[str, ...],
    x0: float,
    x1: float,
    cy: float,
    marker_id: str,
) -> str:
    """One spine arrow: same construction as a term row -- a horizontal
    line no other row can share, labels centred on it over opaque boxes --
    but attributed by the pair it connects, not by a centre type."""
    cx = (x0 + x1) / 2
    block = len(labels) * LABEL_H + max(len(labels) - 1, 0) * LABEL_GAP_Y
    parts = [
        f'<g class="edge" data-source="{escape(source)}" '
        f'data-target="{escape(target)}" '
        f'data-verbs="{escape("|".join(labels))}">',
        f'<path d="M {_n(x0)} {_n(cy)} L {_n(x1)} {_n(cy)}" fill="none" '
        f'stroke="var(--muted, #666e79)" stroke-width="1" '
        f'marker-end="url(#{marker_id})"/>',
    ]
    y = cy - block / 2
    for label in labels:
        w = _text_w(label, LABEL_CHAR_W) + LABEL_PAD_X * 2
        parts.append(
            f'<rect class="label-box" x="{_n(cx - w / 2)}" y="{_n(y)}" '
            f'width="{_n(w)}" height="{LABEL_H}" rx="3" '
            f'fill="var(--bg, #ffffff)" stroke="var(--line, #e0e4e9)"/>'
            f'<text class="edge-label" x="{_n(cx)}" y="{_n(y + LABEL_H / 2)}" '
            f'font-size="{LABEL_FONT}" text-anchor="middle" '
            f'dominant-baseline="central" fill="var(--accent, #1f5fbf)">'
            f"{escape(label)}</text>"
        )
        y += LABEL_H + LABEL_GAP_Y
    parts.append("</g>")
    return "".join(parts)


def render_term_svg(project: Project, type_name: str) -> str:
    """One type's connections as a standalone `<svg>` element.

    Presentation lives in attributes, using the site's CSS custom
    properties with literal fallbacks: inside a built page the theme's
    values win (so dark mode and print come free), and standalone --
    `refdes schema --graph TYPE` -- the fallbacks render.
    """
    incoming, outgoing = _term_rows(project, type_name)
    left = _stack([(peer, tuple(sorted(verbs))) for peer, verbs in sorted(incoming.items())], "in")
    right = _stack([(peer, tuple(sorted(verbs))) for peer, verbs in sorted(outgoing.items())], "out")

    left_w = max((_box_w(_display(s.peer)) for s in left), default=0.0)
    right_w = max((_box_w(_display(s.peer)) for s in right), default=0.0)
    gutter_l = _gutter_w(left)
    gutter_r = _gutter_w(right)
    centre_w = _box_w(type_name)

    def _column_h(slots: list[_Slot]) -> float:
        if not slots:
            return 0.0
        return slots[-1].cy + slots[-1].height / 2 - MARGIN

    centre_h = max(NODE_H, _column_h(left), _column_h(right))

    x_left = float(MARGIN)
    x_centre = x_left + left_w + gutter_l
    x_right = x_centre + centre_w + gutter_r
    width = x_right + right_w + MARGIN
    height = MARGIN + centre_h + MARGIN

    marker_id = f"refdes-arrow-{re.sub(r'[^A-Za-z0-9_-]', '-', type_name)}"
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_n(width)} {_n(height)}" '
            f'width="100%" height="{_n(height)}" role="img" '
            f'font-family="var(--mono, ui-monospace, monospace)" '
            f'font-size="{FONT_SIZE}">'
        ),
        f"<title>{escape(_display(type_name))} connections</title>",
        _marker_defs(marker_id),
    ]

    # Edges first; nodes paint over them, and each label box punches the
    # line behind it.
    for slot in left:
        parts.append(_edge_svg(slot, x_left + left_w, x_centre, marker_id))
    for slot in right:
        parts.append(_edge_svg(slot, x_centre + centre_w, x_right, marker_id))

    # Column boxes are uniform: every box in a column is as wide as the
    # column's widest label. Sized to their own text, a narrow box's right
    # edge would fall short of the shared x the arrows start from, and the
    # arrow would hang in mid-air -- the owner's measurement: `log` ending
    # at 62.5 with its arrow starting at 122.5. One width per column makes
    # every arrow start exactly at its own box's edge, and lines the
    # columns up while it is at it.
    for slot in left:
        parts.append(_node_svg(slot.peer, x_left, slot.cy - NODE_H / 2, left_w, NODE_H))
    parts.append(_node_svg(type_name, x_centre, MARGIN, centre_w, centre_h))
    for slot in right:
        parts.append(_node_svg(slot.peer, x_right, slot.cy - NODE_H / 2, right_w, NODE_H))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
