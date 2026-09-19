"""The generated vocabulary diagram (finding 38, chunk 3b).

One hand-rolled layered layout, emitted as plain inline SVG: no graph
library, no Mermaid, no reader-side JavaScript. The contract these tests
hold:

- the diagram is the *resolved* schema: every declared link-verb target is
  an edge, a project's own overlay type appears in its own diagram, and
  the bundled standard's `group` node and `part_of` edges are there;
- same input, same bytes: two renders are identical, so a diff in a
  committed diagram means the schema changed and nothing else;
- nodes are links to the vocabulary page's anchors, and colours come from
  the site's CSS tokens, so dark mode and print work for free;
- it is not a script: no `script` element, no handler attribute, nothing
  that runs.
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest
from conftest import write_project_config
from helpers import REPO

from refdes import diagram, parse, vocabulary
from refdes.schema import load_project

GEN_PATH = os.path.join(REPO, "docs-site", "gen_examples.py")
SVG_PATH = os.path.join(REPO, "docs-site", "images", "vocabulary-graph.svg")

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

ITEMS = "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A requirement.\n"

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


@pytest.fixture()
def diagram_root(tmp_path):
    write_project_config(tmp_path, DIAGRAM_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(ITEMS, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def diagram_project(diagram_root):
    project = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


@pytest.fixture(scope="module")
def repo_project():
    """The repo's own project: the bundled standard at its pin, plus the
    repo's overlay. This is the graph the diagram must actually be legible
    for -- about a dozen nodes and a few dozen edges."""
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    parse.load_items(project)
    return project


def _declared_edges(project) -> set[tuple[str, str, str]]:
    """Every (source, verb, target) the resolved schema declares, with an
    empty target list standing for the synthetic any-type node."""
    edges = set()
    for type_name, spec in project.types.items():
        for verb, targets in spec.links.items():
            for target in targets or [diagram.ANY]:
                edges.add((type_name, verb, target))
    return edges


def _svg_edges(svg: str) -> set[tuple[str, str, str]]:
    return {
        (m.group(1), m.group(2), m.group(3))
        for m in re.finditer(
            r'<g class="edge" data-source="([^"]+)" data-verb="([^"]+)" data-target="([^"]+)"',
            svg,
        )
    }


# ------------------------------------------------------------------ the graph


def test_every_declared_target_is_an_edge(diagram_project):
    """The diagram is not a selection: one edge per declared (type, verb,
    target), counted against the schema itself."""
    assert _svg_edges(diagram.render_svg(diagram_project)) == _declared_edges(
        diagram_project
    )


def test_an_unrestricted_verb_draws_one_edge_to_the_any_node(diagram_project):
    edges = _svg_edges(diagram.render_svg(diagram_project))
    assert ("note", "tracks", diagram.ANY) in edges
    assert not [e for e in edges if e[0] == "note" and e[2] in {"decision"}]


def test_a_verb_declared_by_its_inverse_name_is_an_edge(diagram_project):
    """`note: {links: {documented_by: [requirement]}}` is requirement
    --documents--> note; the diagram draws what the declaration says."""
    edges = _svg_edges(diagram.render_svg(diagram_project))
    assert ("note", "documented_by", "requirement") in edges


def test_the_bundled_standard_has_a_group_node_and_part_of_edges(repo_project):
    svg = diagram.render_svg(repo_project)
    assert 'data-node="group"' in svg
    part_of = [e for e in _svg_edges(svg) if e[1] == "part_of"]
    assert part_of, "the bundled standard declares part_of edges"
    assert all(e[2] == "group" for e in part_of)


def test_an_overlay_type_appears_in_its_own_diagram(diagram_project):
    svg = diagram.render_svg(diagram_project)
    assert 'data-node="note"' in svg
    assert ">note<" in svg


def test_a_preset_is_drawn_only_when_the_project_enables_it(tmp_path):
    """`claim` and `raises` come from the design-debate preset, so they are
    in the diagram of a project that turns it on and nowhere in one that
    does not -- the picture cannot advertise a verb the build rejects."""
    svg_on = _render_at(tmp_path / "on", PRESET_ON)
    svg_off = _render_at(tmp_path / "off", PRESET_OFF)
    assert 'data-node="claim"' in svg_on
    assert 'data-verb="raises"' in svg_on
    assert 'data-node="claim"' not in svg_off
    assert 'data-verb="raises"' not in svg_off


def _render_at(directory, config_text: str) -> str:
    directory.mkdir()
    write_project_config(directory, config_text)
    return diagram.render_svg(
        load_project(config_path=str(directory / "refdes-project.yaml"))
    )


# --------------------------------------------------------------- determinism


def test_two_renders_are_identical(diagram_project):
    assert diagram.render_svg(diagram_project) == diagram.render_svg(diagram_project)


def test_a_fresh_load_renders_identically(diagram_root):
    first = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(first)
    second = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(second)
    assert diagram.render_svg(first) == diagram.render_svg(second)


def test_the_repo_diagram_is_deterministic(repo_project):
    assert diagram.render_svg(repo_project) == diagram.render_svg(repo_project)


# ------------------------------------------------------------------ the nodes


def test_nodes_link_to_the_vocabulary_anchors(diagram_project):
    svg = diagram.render_svg(diagram_project)
    for name in diagram_project.types:
        assert f'<a href="#term-{name}"' in svg


# ------------------------------------------------------------------- staticity


def test_the_svg_has_no_script_and_no_handler(diagram_project):
    svg = diagram.render_svg(diagram_project)
    lowered = svg.lower()
    assert "<script" not in lowered
    assert "onload" not in lowered
    assert "onclick" not in lowered
    assert "javascript:" not in lowered
    assert "<foreignobject" not in lowered


def test_colours_come_from_the_site_tokens(diagram_project):
    """CSS custom properties with literal fallbacks: inside a built site the
    page's tokens win, so dark mode and print follow the theme; standalone
    (piped to a file by `refdes schema --graph`) the fallbacks render."""
    svg = diagram.render_svg(diagram_project)
    assert "var(--fg" in svg
    assert "var(--line" in svg
    assert "var(--accent" in svg


def test_the_svg_is_a_whole_document_fragment(diagram_project):
    svg = diagram.render_svg(diagram_project)
    assert svg.startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert svg.rstrip().endswith("</svg>")
    assert 'viewBox="' in svg


def test_the_svg_parses_as_xml(diagram_project):
    """The docs site checks this picture in as a file a browser opens, so the
    bytes have to be well-formed XML, not merely HTML-shaped strings."""
    import xml.etree.ElementTree as ET

    ET.fromstring(diagram.render_svg(diagram_project))


# ------------------------------------------------------- the vocabulary page


def test_the_vocabulary_page_leads_with_the_diagram(diagram_project):
    html = vocabulary.render_html(diagram_project)
    assert '<svg' in html
    assert html.index("<svg") < html.index('class="vocab-term"')


def test_the_built_page_still_carries_no_script_of_its_own(diagram_root):
    from refdes import build as build_mod
    from refdes import render

    project = load_project(config_path=str(diagram_root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    render.render_site(project)
    with open(
        os.path.join(str(diagram_root), "_site", "vocabulary.html"), encoding="utf-8"
    ) as fh:
        page = fh.read()
    assert "<svg" in page
    # base.html.j2 carries exactly two script tags of its own; the diagram
    # adds none.
    assert page.lower().count("<script") == 2


# --------------------------------------------------------------- schema graph


def test_cli_schema_graph_emits_svg(diagram_root, capsys):
    from refdes import cli

    status = cli.main(
        ["-c", str(diagram_root / "refdes-project.yaml"), "schema", "--graph"]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert out.startswith("<svg")
    assert "mermaid" not in out.lower()
    assert 'data-verb="satisfies"' in out


# ---------------------------------------------------------------- docs site


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_examples_diagram", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_site_diagram_file_is_current(gen):
    """The docs site cannot inline SVG -- its markdown renders with html
    disabled -- so the diagram is a checked-in asset, and a checked-in
    generated file has to be provably generated."""
    with open(SVG_PATH, encoding="utf-8") as fh:
        assert fh.read() == gen.render_diagram_svg()


def test_docs_site_vocabulary_page_references_the_diagram():
    with open(os.path.join(REPO, "docs", "vocabulary.md"), encoding="utf-8") as fh:
        page = fh.read()
    assert "vocabulary-graph.svg" in page


def test_docs_site_check_accepts_the_committed_diagram(gen):
    assert gen.main(["--check"]) == 0
