"""The per-term vocabulary diagrams (finding 38, chunk 3b rebuilt).

The whole-schema hairball was rejected: one auto-laid-out graph of all
twenty-nine edges produced overlapping labels, duplicate paths and text
wider than its box. What replaced it is one small fixed-layout drawing
per type, and these tests are the acceptance criteria -- run over every
type of every bundled standard (hardware v1, v2, v3), on the rendered SVG
itself, never on a private helper that could drift from it:

1. no two label boxes overlap;
2. no label box overlaps any node box;
3. every text string fits inside its own box;
4. no two arrows share an identical path string;
5. every verb the type declares, and every verb declared pointing at it,
   appears exactly once;
6. rendering twice gives byte-identical output.

Plus the standing constraints from the module docstring: deterministic
output, plain inline SVG, no script, no foreignObject, site CSS custom
properties with literal fallbacks, nodes are anchors into the vocabulary
page.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import write_project_config
from helpers import REPO

from refdes import diagram, parse, vocabulary
from refdes.schema import load_project

STANDARD_SCHEMA = """\
site: {{ title: "Standard Diagram", out: _site }}
id: {{ width: 3 }}
standard: {{ base: hardware, version: {version}, presets: [] }}
"""

DIAGRAM_SCHEMA = """\
site: { title: "Diagram Test", out: _site }
id: { width: 3 }
link_types:
  satisfies:   { inverse: satisfied_by,  label: Satisfies }
  documents:   { inverse: documented_by, label: Documents }
  tracks:      { inverse: tracked_by,    label: Tracks }
types:
  requirement:
    prefix: REQ
    label: Requirement
    links: {}
  decision:
    prefix: DEC
    label: Decision
    links:
      satisfies: [requirement]
  note:
    prefix: NOT
    label: Note
    links:
      documented_by: [requirement]
      tracks: []
"""

STACK_SCHEMA = """\
site: { title: Stack, out: _site }
id: { width: 3 }
link_types:
  alpha: { inverse: alpha_of }
  beta:  { inverse: beta_of }
types:
  gadget: { prefix: GAD, links: {} }
  widget:
    prefix: WID
    links:
      alpha: [gadget]
      beta: [gadget]
"""

PRESET_ON = """\
site: { title: "Preset Diagram", out: _site }
id: { width: 3 }
standard: { base: hardware, version: 3, presets: [design-debate] }
"""

PRESET_OFF = """\
site: { title: "Preset Diagram", out: _site }
id: { width: 3 }
standard: { base: hardware, version: 3, presets: [] }
"""


# --------------------------------------------------------------- fixtures


@pytest.fixture(params=[1, 2, 3], ids=["v1", "v2", "v3"])
def standard_project(request, tmp_path):
    """A bare project pinned to each bundled standard, no overlay."""
    write_project_config(tmp_path, STANDARD_SCHEMA.format(version=request.param))
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


@pytest.fixture()
def diagram_root(tmp_path):
    write_project_config(tmp_path, DIAGRAM_SCHEMA)
    return tmp_path


@pytest.fixture()
def diagram_project(diagram_root):
    return load_project(config_path=str(diagram_root / "refdes-project.yaml"))


@pytest.fixture()
def stack_project(tmp_path):
    write_project_config(tmp_path, STACK_SCHEMA)
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


@pytest.fixture(scope="module")
def repo_project():
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    parse.load_items(project)
    return project


# ----------------------------------------- SVG parsing: the only geometry
# oracle. Boxes are computed from the emitted SVG, not from a helper.

RECT_RE = re.compile(
    r'<rect class="(node-box|label-box)" x="(-?[\d.]+)" y="(-?[\d.]+)"'
    r' width="([\d.]+)" height="([\d.]+)"'
)
TEXT_RE = re.compile(
    r'<text class="(node-label|edge-label)" x="(-?[\d.]+)" y="(-?[\d.]+)"'
    r' font-size="([\d.]+)"[^>]*>([^<]*)</text>'
)
EDGE_RE = re.compile(
    r'<g class="edge" data-peer="([^"]*)" data-direction="([^"]*)"'
    r' data-verbs="([^"]*)">'
)
ARROW_PATH_RE = re.compile(r'<g class="edge"[^>]*>.*?<path d="([^"]*)"')

# An independent monospace estimate: no real monospace font renders a
# glyph narrower than about 0.6 em, so 0.62 is a fair lower bound on what
# the text actually occupies. The rejected diagram measured at ~0.50
# (6.3 px per character at 12.5 px) and this catches that class of bug.
GLYPH_W_EM = 0.62
GLYPH_H_EM = 0.6


def _boxes(svg: str, cls: str) -> list[tuple[float, float, float, float]]:
    return [
        (float(x), float(y), float(w), float(h))
        for kind, x, y, w, h in RECT_RE.findall(svg)
        if kind == cls
    ]


def _texts(svg: str, cls: str):
    return [
        (float(x), float(y), float(size), text)
        for kind, x, y, size, text in TEXT_RE.findall(svg)
        if kind == cls
    ]


def _overlaps(a, b) -> bool:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    eps = 1e-6
    return (
        ax0 < bx0 + bw - eps
        and bx0 < ax0 + aw - eps
        and ay0 < by0 + bh - eps
        and by0 < ay0 + ah - eps
    )


def _expected_rows(project, type_name: str) -> dict[tuple[str, str], set[str]]:
    """(peer, direction) -> verbs, computed from the schema here in the
    test -- deliberately not `diagram._term_rows`, so the two cannot
    drift together."""
    inverse = {
        lt.inverse: name for name, lt in project.link_types.items() if lt.inverse
    }
    rows: dict[tuple[str, str], set[str]] = {}

    def add(peer, direction, verb):
        rows.setdefault((peer, direction), set()).add(verb)

    spec = project.types[type_name]
    for key, targets in (spec.links or {}).items():
        listed = list(targets or [])
        if key in project.link_types:
            for target in listed or [diagram.ANY]:
                add(target, "out", key)
        elif key in inverse:
            for source in listed or [diagram.ANY]:
                add(source, "in", inverse[key])
    for other, other_spec in project.types.items():
        if other == type_name:
            continue
        for key, targets in (other_spec.links or {}).items():
            listed = targets or []
            if key in project.link_types and type_name in listed:
                add(other, "in", key)
            elif key in inverse and type_name in listed:
                add(other, "out", inverse[key])
    return rows


def _drawn_rows(svg: str) -> dict[tuple[str, str], list[str]]:
    return {
        (peer, direction): verbs.split(",") if verbs else []
        for peer, direction, verbs in EDGE_RE.findall(svg)
    }


def _arrow_paths(svg: str) -> list[str]:
    return ARROW_PATH_RE.findall(svg)


def _check_invariants(project, type_name: str) -> None:
    """All six, for one type of one project."""
    svg = diagram.render_term_svg(project, type_name)
    labels = _boxes(svg, "label-box")
    nodes = _boxes(svg, "node-box")

    # 1. no two label boxes overlap
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            assert not _overlaps(a, b), f"{type_name}: labels overlap: {a} {b}"
    # 2. no label box overlaps a node box
    for label in labels:
        for node in nodes:
            assert not _overlaps(label, node), (
                f"{type_name}: label {label} overlaps node {node}"
            )
    # 3. every text fits its own box
    for text_cls, box_cls in (("node-label", "node-box"), ("edge-label", "label-box")):
        texts = _texts(svg, text_cls)
        boxes = _boxes(svg, box_cls)
        assert len(texts) == len(boxes), (
            f"{type_name}: {text_cls} count != {box_cls} count"
        )
        for (x, y, size, text), (bx, by, bw, bh) in zip(texts, boxes):
            tw = GLYPH_W_EM * size * len(text)
            th = GLYPH_H_EM * size
            assert bx <= x - tw / 2, f"{type_name}: '{text}' overflows left"
            assert x + tw / 2 <= bx + bw, f"{type_name}: '{text}' overflows right"
            assert by <= y - th / 2, f"{type_name}: '{text}' overflows top"
            assert y + th / 2 <= by + bh, f"{type_name}: '{text}' overflows bottom"
    # 4. no two arrows share an identical path string
    paths = _arrow_paths(svg)
    assert len(paths) == len(set(paths)), (
        f"{type_name}: duplicate arrow path strings"
    )
    # 5. every declared verb, in and out, exactly once
    expected = _expected_rows(project, type_name)
    drawn = _drawn_rows(svg)
    assert {(p, d): set(v) for (p, d), v in drawn.items()} == expected
    for (peer, direction), verbs in drawn.items():
        assert len(verbs) == len(set(verbs)), (
            f"{type_name}: verb repeated on the {direction} arrow at {peer}"
        )
    # 6. byte-identical re-render
    assert svg == diagram.render_term_svg(project, type_name)


# ------------------------------------------- the six invariants, per type


def test_v1_every_type_passes_the_six_invariants(standard_project):
    for type_name in sorted(standard_project.types):
        _check_invariants(standard_project, type_name)


def test_a_fresh_load_renders_identically(diagram_root):
    first = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(first)
    second = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(second)
    for name in sorted(first.types):
        assert diagram.render_term_svg(first, name) == diagram.render_term_svg(
            second, name
        )


def test_the_repo_project_passes_the_six_invariants(repo_project):
    """The repo's own overlay is part of the surface too."""
    for type_name in sorted(repo_project.types):
        _check_invariants(repo_project, type_name)


# ------------------------------------------------------- arrow flushness
#
# The owner's bug: boxes sized to their own text while the arrows started
# from the column's widest right edge, so a narrow box's arrow hung in
# mid-air -- `log` ending at 62.5 with its arrow starting at 122.5. These
# tests parse the emitted rects and paths and demand zero gap, not
# "close enough".

NODE_GROUP_RE = re.compile(r'<g class="node" data-node="([^"]*)">(.*?)</g>')
NODE_RECT_RE = re.compile(
    r'<rect class="node-box" x="(-?[\d.]+)" y="(-?[\d.]+)"'
    r' width="([\d.]+)" height="([\d.]+)"'
)
ARROW_D_RE = re.compile(
    r'<path d="M (-?[\d.]+) (-?[\d.]+) L (-?[\d.]+) (-?[\d.]+)"'
)
TERM_EDGE_FULL_RE = re.compile(
    r'<g class="edge" data-peer="([^"]*)" data-direction="(in|out)"'
    r' data-verbs="[^"]*">' + ARROW_D_RE.pattern
)
SPINE_EDGE_FULL_RE = re.compile(
    r'<g class="edge" data-source="([^"]*)" data-target="([^"]*)"'
    r' data-verbs="[^"]*">' + ARROW_D_RE.pattern
)

EPS = 1e-6


def _node_boxes(svg: str):
    """(name, x, y, w, h) for every node box, in document order."""
    boxes = []
    for name, body in NODE_GROUP_RE.findall(svg):
        r = NODE_RECT_RE.search(body)
        boxes.append((name, *(float(v) for v in r.groups())))
    return boxes


def _centred_on(boxes, cy):
    return [b for b in boxes if abs(b[2] + b[4] / 2 - cy) < EPS]


def _covering(boxes, cy):
    return [b for b in boxes if b[2] - EPS <= cy <= b[2] + b[4] + EPS]


def _check_term_flushness(svg: str, type_name: str) -> None:
    boxes = _node_boxes(svg)
    arrows = TERM_EDGE_FULL_RE.findall(svg)
    assert arrows
    for peer, direction, x0, y0, x1, _y1 in arrows:
        x0, y0, x1 = float(x0), float(y0), float(x1)
        assert y0 == float(_y1), "arrow is not horizontal"
        if direction == "in":
            own = [b for b in _centred_on(boxes, y0) if b[0] == peer and b[1] < x0]
            assert own, f"{type_name}: no {peer} box on the in-arrow at y={y0}"
            assert abs(own[0][1] + own[0][3] - x0) < EPS, (
                f"{type_name}: in-arrow starts at x={x0} but the {peer} box "
                f"ends at {own[0][1] + own[0][3]} -- gap {x0 - own[0][1] - own[0][3]}"
            )
            centre = [
                b
                for b in _covering(boxes, y0)
                if b[0] == type_name and abs(b[1] - x1) < EPS
            ]
            assert centre, f"{type_name}: in-arrow does not end on the centre box"
        else:
            own = [b for b in _centred_on(boxes, y0) if b[0] == peer and b[1] > x1 - EPS]
            assert own, f"{type_name}: no {peer} box on the out-arrow at y={y0}"
            assert abs(own[0][1] - x1) < EPS, (
                f"{type_name}: out-arrow ends at x={x1} but the {peer} box "
                f"starts at {own[0][1]} -- gap {own[0][1] - x1}"
            )
            centre = [
                b
                for b in _covering(boxes, y0)
                if b[0] == type_name and abs(b[1] + b[3] - x0) < EPS
            ]
            assert centre, f"{type_name}: out-arrow does not start on the centre box"


def _check_spine_flushness(svg: str) -> None:
    boxes = _node_boxes(svg)
    arrows = SPINE_EDGE_FULL_RE.findall(svg)
    assert arrows
    for source, target, x0, y0, x1, _y1 in arrows:
        x0, y0, x1 = float(x0), float(y0), float(x1)
        src = [b for b in _centred_on(boxes, y0) if b[0] == source and b[1] < x0]
        assert src, f"spine: no {source} box on the arrow at y={y0}"
        assert abs(src[0][1] + src[0][3] - x0) < EPS, (
            f"spine: arrow starts at x={x0}, {source} box ends at "
            f"{src[0][1] + src[0][3]} -- gap {x0 - src[0][1] - src[0][3]}"
        )
        tgt = [b for b in _centred_on(boxes, y0) if b[0] == target and b[1] > x1 - EPS]
        assert tgt, f"spine: no {target} box on the arrow at y={y0}"
        assert abs(tgt[0][1] - x1) < EPS, (
            f"spine: arrow ends at x={x1}, {target} box starts at "
            f"{tgt[0][1]} -- gap {tgt[0][1] - x1}"
        )


def _check_uniform_columns(svg: str, what: str) -> None:
    """Every node box sharing a column's x is the same width: no ragged
    right edges, and one shared edge for the column's arrows."""
    by_x: dict[float, set[float]] = {}
    for _name, x, _y, w, _h in _node_boxes(svg):
        by_x.setdefault(round(x, 3), set()).add(round(w, 3))
    for x, widths in by_x.items():
        assert len(widths) == 1, f"{what}: column at x={x} has widths {sorted(widths)}"


def test_arrows_are_flush_with_their_own_boxes(standard_project):
    """The named regression test for the floating-arrow bug: every
    incoming arrow's start x equals the right edge of the box in its own
    row, every outgoing arrow's end x equals the left edge of the box in
    its own row -- zero gap -- and every column is one uniform width."""
    for type_name in sorted(standard_project.types):
        svg = diagram.render_term_svg(standard_project, type_name)
        _check_term_flushness(svg, type_name)
        _check_uniform_columns(svg, type_name)
    spine = diagram.render_spine_svg(standard_project)
    if spine:
        _check_spine_flushness(spine)
        _check_uniform_columns(spine, "spine")


def test_arrows_are_flush_in_the_repo_project_and_its_spine(repo_project):
    for type_name in sorted(repo_project.types):
        _check_term_flushness(diagram.render_term_svg(repo_project, type_name), type_name)
    _check_spine_flushness(diagram.render_spine_svg(repo_project))


# -------------------------------------------------------------- semantics


def test_an_unrestricted_verb_draws_one_any_type_box(diagram_project):
    svg = diagram.render_term_svg(diagram_project, "note")
    assert _drawn_rows(svg) == {
        ("requirement", "in"): ["documents"],
        (diagram.ANY, "out"): ["tracks"],
    }
    assert ">any type<" in svg
    assert svg.count('data-node="any"') == 1
    assert ">any item<" not in svg


def test_a_verb_declared_by_its_inverse_name_points_the_right_way(diagram_project):
    """`note: {links: {documented_by: [requirement]}}` is requirement
    --documents--> note: an incoming row on note, an outgoing row on
    requirement, the verb in its forward form on both."""
    note_svg = diagram.render_term_svg(diagram_project, "note")
    assert _drawn_rows(note_svg) == {
        ("requirement", "in"): ["documents"],
        (diagram.ANY, "out"): ["tracks"],
    }
    req_svg = diagram.render_term_svg(diagram_project, "requirement")
    assert _drawn_rows(req_svg) == {
        ("decision", "in"): ["satisfies"],
        ("note", "out"): ["documents"],
    }


def test_a_self_verb_draws_a_second_box_not_a_loop(repo_project):
    """`decision: {links: {supersedes: [decision]}}` puts a second decision
    box in the right column; there is no loop path anywhere."""
    svg = diagram.render_term_svg(repo_project, "decision")
    assert _drawn_rows(svg)[("decision", "out")] == ["supersedes"]
    assert svg.count('data-node="decision"') == 2  # centre + right column
    assert "c 30" not in svg  # the old self-loop cubic is gone


def test_stacked_labels_share_one_arrow(stack_project):
    """Two verbs, same pair, same direction: one arrow, two labels."""
    svg = diagram.render_term_svg(stack_project, "widget")
    assert _drawn_rows(svg) == {("gadget", "out"): ["alpha", "beta"]}
    assert len(_arrow_paths(svg)) == 1
    assert len(_boxes(svg, "label-box")) == 2


def test_a_preset_is_drawn_only_when_the_project_enables_it(tmp_path):
    """`claim` and `raises` come from the design-debate preset, so they are
    in the diagrams of a project that turns it on and nowhere in one that
    does not -- the picture cannot advertise a verb the build rejects."""
    svg_on = _render_all(tmp_path / "on", PRESET_ON)
    svg_off = _render_all(tmp_path / "off", PRESET_OFF)
    assert 'data-node="claim"' in svg_on
    assert 'data-verbs="raises"' in svg_on
    assert 'data-node="claim"' not in svg_off
    assert 'data-verbs="raises"' not in svg_off


def _render_all(directory, config_text: str) -> str:
    os.makedirs(str(directory), exist_ok=True)
    write_project_config(directory, config_text)
    project = load_project(config_path=str(directory / "refdes-project.yaml"))
    return "".join(
        diagram.render_term_svg(project, name) for name in sorted(project.types)
    )


# -------------------------------------------------------------- staticity


def test_the_svg_has_no_script_and_no_handler(diagram_project):
    svg = diagram.render_term_svg(diagram_project, "decision")
    lowered = svg.lower()
    assert "<script" not in lowered
    assert "onload" not in lowered
    assert "onclick" not in lowered
    assert "javascript:" not in lowered
    assert "<foreignobject" not in lowered


def test_colours_come_from_the_site_tokens(diagram_project):
    svg = diagram.render_term_svg(diagram_project, "decision")
    assert "var(--fg" in svg
    assert "var(--line" in svg
    assert "var(--accent" in svg


def test_both_drawings_use_the_shared_monospace_font_stack(diagram_project):
    """The width math assumes monospace, so the stack must end in the
    generic and must be identical in both drawings; and it must name real
    fonts, not just ui-monospace which resolves to nothing on Windows."""
    term = diagram.render_term_svg(diagram_project, "decision")
    spine = diagram.render_spine_svg(diagram_project)
    assert spine, "fixture should have coverage verbs"
    for svg in (term, spine):
        assert f'font-family="{diagram.FONT_STACK}"' in svg
    assert diagram.FONT_STACK.startswith("var(--mono, ")
    assert diagram.FONT_STACK.rstrip(")").endswith("monospace")
    assert "'Cascadia Code'" in diagram.FONT_STACK
    assert "Consolas" in diagram.FONT_STACK
    assert "ui-monospace" not in diagram.FONT_STACK


def test_the_svg_is_a_whole_document_fragment(diagram_project):
    svg = diagram.render_term_svg(diagram_project, "note")
    assert svg.startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert svg.rstrip().endswith("</svg>")
    assert 'viewBox="' in svg


def test_the_svg_parses_as_xml(diagram_project):
    for name in sorted(diagram_project.types):
        ET.fromstring(diagram.render_term_svg(diagram_project, name))


def test_nodes_link_to_the_vocabulary_anchors(diagram_project):
    svg = diagram.render_term_svg(diagram_project, "decision")
    assert '<a href="#term-requirement"' in svg
    assert '<a href="#term-decision"' in svg
    # the synthetic any box is not a term, so it carries no anchor
    note_svg = diagram.render_term_svg(diagram_project, "note")
    any_node = re.search(r'<g class="node" data-node="any">.*?</g>', note_svg)
    assert any_node and "<a " not in any_node.group(0)


# ------------------------------------------------------- the vocabulary page


def test_the_vocabulary_page_embeds_one_diagram_per_type(diagram_project):
    html = vocabulary.render_html(diagram_project)
    for name in sorted(diagram_project.types):
        term = _term_slice(html, name)
        assert "<svg" in term, f"{name}: no diagram beside the term"
        # the diagram sits under the heading, not above it
        assert term.index("<h3>") < term.index("<svg")


def _term_slice(html: str, name: str) -> str:
    start = html.index(f'id="term-{name}"')
    nxt = html.find('<div class="vocab-term"', start + 1)
    end = html.find("</section>", start)
    stops = [e for e in (nxt, end) if e != -1]
    return html[start: min(stops)]


def test_the_only_drawing_above_the_index_is_the_spine(diagram_project):
    """The hairball is gone. What sits above the index is the coverage
    spine and nothing else, and the markdown carries no diagram reference
    either."""
    html = vocabulary.render_html(diagram_project)
    index_at = html.index('class="vocab-index"')
    above = html[:index_at]
    assert above.count("<svg") == 1
    assert "<title>coverage spine</title>" in above
    md = vocabulary.render_markdown(diagram_project)
    assert "svg" not in md.lower()
    assert "graph" not in md.lower()


def test_the_built_page_still_carries_no_script_of_its_own(diagram_root):
    from refdes import build as build_mod
    from refdes import render

    items = diagram_root / "items"
    items.mkdir(exist_ok=True)
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\n---\n\nOne requirement.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    render.render_site(project)
    with open(
        os.path.join(str(diagram_root), "_site", "vocabulary.html"), encoding="utf-8"
    ) as fh:
        page = fh.read()
    assert "<svg" in page
    # base.html.j2 carries exactly two script tags of its own; the diagrams
    # add none.
    assert page.lower().count("<script") == 2


# --------------------------------------------------------------- schema CLI


def test_cli_schema_graph_prints_every_term_diagram(diagram_root, capsys):
    from refdes import cli

    status = cli.main(
        ["-c", str(diagram_root / "refdes-project.yaml"), "schema", "--graph"]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert out.count("<svg") == 4  # the spine, then requirement, decision, note
    assert out.rstrip().endswith("</svg>")
    assert "mermaid" not in out.lower()
    assert 'data-verbs="satisfies"' in out
    # the spine comes first: overview, then the per-type detail
    assert out.index("<title>coverage spine</title>") < out.index("connections</title>")


def test_cli_schema_graph_prints_one_type(diagram_root, capsys):
    from refdes import cli

    status = cli.main(
        [
            "-c",
            str(diagram_root / "refdes-project.yaml"),
            "schema",
            "--graph",
            "decision",
        ]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert out.count("<svg") == 1
    assert "<title>decision connections</title>" in out


def test_cli_schema_graph_unknown_type_names_the_known_ones(diagram_root, capsys):
    from refdes import cli

    status = cli.main(
        ["-c", str(diagram_root / "refdes-project.yaml"), "schema", "--graph", "bogus"]
    )
    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    for name in ("decision", "note", "requirement"):
        assert name in captured.err


# ------------------------------------------------------------ the spine

SPINE_EDGE_RE = re.compile(
    r'<g class="edge" data-source="([^"]*)" data-target="([^"]*)"'
    r' data-verbs="([^"]*)">'
)


def _expected_spine(project) -> dict[tuple[str, str], set[str]]:
    """(source, target) -> labels, recomputed here from the schema the way
    `build._coverage_for` reads it: the three coverage verbs only, in the
    forward direction whichever end declared them, each label carrying the
    source type's status gate."""
    gate_attr = {"satisfies": "satisfying_statuses", "verifies": "verifying_statuses"}
    rows: dict[tuple[str, str], set[str]] = {}
    for verb in ("addresses", "satisfies", "verifies"):
        lt = project.link_types.get(verb)
        if lt is None:
            continue
        for type_name in sorted(project.types):
            spec = project.types[type_name]
            for key, targets in (spec.links or {}).items():
                listed = list(targets or [])
                if key == verb:
                    pairs = [(type_name, t) for t in (listed or ["any"])]
                elif lt.inverse and key == lt.inverse:
                    pairs = [(s, type_name) for s in (listed or ["any"])]
                else:
                    continue
                for source, target in pairs:
                    attr = gate_attr.get(verb)
                    allowed = None
                    if attr and source in project.types:
                        allowed = getattr(project.types[source], attr, None)
                    label = verb if not allowed else f"{verb} [{', '.join(allowed)}]"
                    rows.setdefault((source, target), set()).add(label)
    return rows


def _drawn_spine(svg: str) -> dict[tuple[str, str], set[str]]:
    return {
        (source, target): set(labels.split("|")) if labels else set()
        for source, target, labels in SPINE_EDGE_RE.findall(svg)
    }


def _check_spine(project) -> str:
    """The six invariants, for one project's spine."""
    svg = diagram.render_spine_svg(project)
    assert svg, "expected a spine for a schema with coverage verbs"

    labels = _boxes(svg, "label-box")
    nodes = _boxes(svg, "node-box")
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            assert not _overlaps(a, b), f"spine labels overlap: {a} {b}"
    for label in labels:
        for node in nodes:
            assert not _overlaps(label, node), f"spine label {label} hits node {node}"
    for text_cls, box_cls in (("node-label", "node-box"), ("edge-label", "label-box")):
        texts = _texts(svg, text_cls)
        boxes = _boxes(svg, box_cls)
        assert len(texts) == len(boxes)
        for (x, y, size, text), (bx, by, bw, bh) in zip(texts, boxes):
            tw = GLYPH_W_EM * size * len(text)
            th = GLYPH_H_EM * size
            assert bx <= x - tw / 2 and x + tw / 2 <= bx + bw, f"'{text}' overflows"
            assert by <= y - th / 2 and y + th / 2 <= by + bh, f"'{text}' overflows"
    paths = _arrow_paths(svg)
    assert paths and len(paths) == len(set(paths)), "spine arrows share a path"
    assert _drawn_spine(svg) == _expected_spine(project)
    assert svg == diagram.render_spine_svg(project)
    return svg


def test_spine_passes_the_six_invariants_for_every_standard(standard_project):
    _check_spine(standard_project)


def test_spine_passes_the_six_invariants_for_the_repo_project(repo_project):
    _check_spine(repo_project)


@pytest.mark.parametrize("standard_version", [1, 2, 3])
def test_spine_labels_carry_the_status_gate(standard_version, tmp_path):
    """The gate `_coverage_for` enforces is the gate the spine advertises:
    a satisfier's satisfying_statuses, a verifier's verifying_statuses,
    and nothing on addresses."""
    write_project_config(tmp_path, STANDARD_SCHEMA.format(version=standard_version))
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    svg = diagram.render_spine_svg(project)
    saw_gate = False
    for (source, _target), labels in _drawn_spine(svg).items():
        for label in labels:
            verb = label.split(" [")[0]
            if verb == "addresses":
                assert "[" not in label, f"addresses carries a gate: {label}"
                continue
            attr = (
                "satisfying_statuses"
                if verb == "satisfies"
                else "verifying_statuses"
            )
            allowed = getattr(project.types[source], attr, None)
            expected = verb if not allowed else f"{verb} [{', '.join(allowed)}]"
            assert label == expected, (
                f"{source} gate mislabelled: {label!r}, schema says {expected!r}"
            )
            saw_gate = saw_gate or bool(allowed)
    assert saw_gate, "bundled standards configure a status gate"


def test_spine_renders_nothing_without_coverage_verbs(stack_project):
    """alpha/beta are not coverage verbs: no drawing, not an empty frame."""
    assert diagram.render_spine_svg(stack_project) == ""


def test_spine_resolves_inverse_declarations(stack_project):
    """A coverage verb declared under its inverse name still points
    forward: `requirement: {links: {satisfied_by: [widget]}}` is
    widget --satisfies--> requirement."""
    import textwrap

    config = textwrap.dedent(
        """\
        site: { title: Spine, out: _site }
        id: { width: 3 }
        link_types:
          satisfies: { inverse: satisfied_by }
        types:
          widget:
            prefix: WID
            links: {}
          requirement:
            prefix: REQ
            links:
              satisfied_by: [widget]
        """
    )
    root = stack_project.root
    sub = os.path.join(str(root), "inv")
    os.makedirs(sub, exist_ok=True)
    write_project_config(sub, config)
    project = load_project(config_path=os.path.join(sub, "refdes-project.yaml"))
    svg = diagram.render_spine_svg(project)
    assert _drawn_spine(svg) == {("widget", "requirement"): {"satisfies"}}


def test_spine_nodes_are_anchors_and_the_svg_is_plain(diagram_project):
    svg = diagram.render_spine_svg(diagram_project)
    assert '<a href="#term-decision"' in svg
    assert "<script" not in svg.lower()
    assert "foreignObject" not in svg
    ET.fromstring(svg)
