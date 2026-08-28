"""parts indexing and equivalence.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import COVERAGE_SCHEMA, PARTS_SCHEMA, _build_at

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import nav as nav_mod
from refdes import parse, render
from refdes import workspaces as workspaces_mod
from refdes.schema import load_project

PARTS_ITEMS = {
    ("alpha", "main", "cmp-001.md"): """\
---
id: CMP-001
type: component
title: Main MCU.
part_number: STM32G474
workspace: alpha
board: main
---
""",
    ("beta", "main", "cmp-002.md"): """\
---
id: CMP-002
type: component
title: Also uses the same MCU, different workspace.
part_number: STM32G474
workspace: beta
board: main
---
""",
    ("alpha", "main", "cmp-003.md"): """\
---
id: CMP-003
type: component
title: A near-miss part number, deliberately different.
part_number: STM32G474RET6
workspace: alpha
board: main
---
""",
    ("alpha", "main", "cmp-004.md"): """\
---
id: CMP-004
type: component
title: Cited a datasheet for a part never made into a component.
workspace: alpha
board: main
datasheets:
  - url: "https://example.com/opamp.pdf"
    part_number: LM358
---
""",
}


@pytest.fixture
def parts_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(PARTS_SCHEMA, encoding="utf-8")
    for (workspace, board, name), text in PARTS_ITEMS.items():
        d = tmp_path / "items" / workspace / board
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    return tmp_path


def _parts_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_by_part_number_exact_string_near_miss_stays_separate(parts_project):
    project = _parts_build(parts_project)
    assert not project.errors
    parts = citations_mod.by_part_number(project)
    assert set(parts) == {"STM32G474", "STM32G474RET6", "LM358"}
    g474 = parts["STM32G474"]
    assert sorted(c.id for c in g474.components) == ["CMP-001", "CMP-002"]
    g474ret6 = parts["STM32G474RET6"]
    assert [c.id for c in g474ret6.components] == ["CMP-003"]
    # Sharing a component list would be the exact bug exact-string indexing
    # exists to prevent.
    assert g474.components != g474ret6.components


def test_by_part_number_covers_citation_only_parts(parts_project):
    project = _parts_build(parts_project)
    parts = citations_mod.by_part_number(project)
    lm358 = parts["LM358"]
    assert lm358.components == []
    assert [item.id for item, _status in lm358.citers] == ["CMP-004"]


def test_by_part_number_board_and_workspace_scoping(parts_project):
    project = _parts_build(parts_project)
    alpha_parts = citations_mod.by_part_number(project, workspace="alpha")
    assert "STM32G474" in alpha_parts
    assert [c.id for c in alpha_parts["STM32G474"].components] == ["CMP-001"]

    beta_parts = citations_mod.by_part_number(project, workspace="beta")
    assert [c.id for c in beta_parts["STM32G474"].components] == ["CMP-002"]

    board_parts = citations_mod.by_part_number(project, board="main")
    assert sorted(c.id for c in board_parts["STM32G474"].components) == ["CMP-001", "CMP-002"]


def test_part_usage_boards_property(parts_project):
    project = _parts_build(parts_project)
    usage = citations_mod.by_part_number(project)["STM32G474"]
    assert usage.boards == ["main"]


def test_cross_workspace_lint_does_not_fire_on_shared_part_numbers(parts_project):
    """The whole point of the parts page: it's a derived view, not an
    authored link. Two workspaces' components sharing a part_number is a
    coincidence of the BOM, never a declared dependency, so the lint built
    in an earlier step -- which walks item.links exclusively -- must never
    fire on it. CMP-001 (alpha) and CMP-002 (beta) share STM32G474 and
    declare no links to each other at all."""
    project = _parts_build(parts_project)
    project.cross_workspace_severity = "error"  # maximize the chance of catching a false positive
    workspaces_mod.lint_cross_workspace_references(project)
    assert not project.errors
    assert not project.warnings


def test_parts_pages_render_global_board_and_workspace_scoped(parts_project):
    project = _parts_build(parts_project)
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "parts.html"))
    assert os.path.isfile(os.path.join(out, "parts-main.html"))
    assert os.path.isfile(os.path.join(out, "parts-alpha.html"))
    assert os.path.isfile(os.path.join(out, "parts-beta.html"))

    global_html = open(os.path.join(out, "parts.html"), encoding="utf-8").read()
    assert "STM32G474" in global_html
    assert "STM32G474RET6" in global_html
    assert "LM358" in global_html

    alpha_html = open(os.path.join(out, "parts-alpha.html"), encoding="utf-8").read()
    assert 'data-ref="CMP-001"' in alpha_html
    # Different workspace -- previews_json legitimately embeds every item's
    # data regardless of page, so check the actual rendered table content.
    assert 'data-ref="CMP-002"' not in alpha_html


def test_a_page_named_parts_collides_with_the_report(parts_project):
    pages = parts_project / "pages"
    pages.mkdir()
    (pages / "parts.md").write_text("# Hand-written page\n", encoding="utf-8")
    project = _parts_build(parts_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)


def test_component_page_links_to_also_used_elsewhere(parts_project):
    project = _parts_build(parts_project)
    out = render.render_site(project)
    cmp001 = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'href="parts.html#part-stm32g474">also used elsewhere</a>' in cmp001
    # CMP-003's part number is used by no one else.
    cmp003 = open(os.path.join(out, "cmp-003.html"), encoding="utf-8").read()
    assert "also used elsewhere" not in cmp003


def test_audit_reports_a_parts_section(parts_project, capsys):
    cli_mod.main(["-c", str(parts_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Parts:" in out
    assert "STM32G474" in out
    assert "used by CMP-001, CMP-002 (components)" in out
    assert "LM358" in out
    assert "used by CMP-004 (citation)" in out


def test_audit_parts_section_breaks_out_workspaces(parts_project, capsys):
    """CMP-001 (alpha) and CMP-002 (beta) share STM32G474 -- a project with a
    workspaces: registry should see that split named, the same way boards
    already are."""
    cli_mod.main(["-c", str(parts_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "— workspaces: alpha, beta" in out


def test_audit_parts_section_omits_workspace_line_for_a_flat_project(tmp_path, capsys):
    """A project with no workspaces: registry never populates item.workspace
    at all, so the line must not appear -- not even empty -- rather than
    growing a confusing always-blank row."""
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "boards:\n  power: {label: Power}\n"
        "types:\n"
        "  component:\n"
        "    prefix: CMP\n"
        "    fields:\n"
        "      title: {type: text, required: true}\n"
        "      part_number: {type: text}\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: t.\n"
        "part_number: TPS62913\nboard: power\n---\n",
        encoding="utf-8",
    )
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "— board: power" in out
    assert "workspace" not in out


def test_nav_parts_link_present_when_parts_exist(parts_project):
    project = _parts_build(parts_project)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")

    def flatten(nodes):
        for n in nodes:
            yield n
            yield from flatten(n.children)

    hrefs = {n.href for n in flatten(tree)}
    assert "parts.html" in hrefs


def test_nav_parts_link_absent_with_no_part_numbers(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = _build_at(tmp_path)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")

    def flatten(nodes):
        for n in nodes:
            yield n
            yield from flatten(n.children)

    hrefs = {n.href for n in flatten(tree)}
    assert "parts.html" not in hrefs


def test_equivalent_rationale_is_optional(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Drop-in second source.\n"
        "workspace: alpha\nboard: main\nequivalent: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert not project.errors


def test_alternate_requires_rationale(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close, not drop-in.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert any(
        "'rationale' is required" in d.message and "alternate" in d.message
        for d in project.errors
    )


def test_alternate_with_rationale_passes(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close, not drop-in.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance; verify before substituting.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert not project.errors


def test_self_inverse_link_merges_both_directions_on_the_declaring_side(parts_project):
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    declaring = open(os.path.join(out, "cmp-005.html"), encoding="utf-8").read()
    assert 'class="tight self-inverse"' in declaring
    assert 'data-ref="CMP-001"' in declaring.split('class="tight self-inverse"')[1].split("</ul>")[0]


def test_self_inverse_link_appears_once_on_the_backlink_side_only(parts_project):
    """CMP-005 declares alternate: [CMP-001]; CMP-001 never declares it back.
    CMP-001's own page must still show the relationship (via the computed
    backlink), exactly once, not duplicated or missing."""
    (parts_project / "items" / "alpha" / "main" / "cmp-005.md").write_text(
        "---\nid: CMP-005\ntype: component\ntitle: Functionally close.\n"
        "workspace: alpha\nboard: main\nalternate: [CMP-001]\n"
        "rationale: Different tolerance.\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    receiving = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    block = receiving.split('class="tight self-inverse"')[1].split("</ul>")[0]
    assert block.count('data-ref="CMP-005"') == 1


def test_self_inverse_redundant_double_declaration_still_renders_once(parts_project):
    """Both sides separately, redundantly declaring the same equivalence is
    harmless -- the merge de-duplicates rather than showing it twice."""
    (parts_project / "items" / "alpha" / "main" / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: Main MCU.\n"
        "part_number: STM32G474\nworkspace: alpha\nboard: main\n"
        "equivalent: [CMP-002]\n---\n",
        encoding="utf-8",
    )
    (parts_project / "items" / "beta" / "main" / "cmp-002.md").write_text(
        "---\nid: CMP-002\ntype: component\ntitle: Also uses the same MCU.\n"
        "part_number: STM32G474\nworkspace: beta\nboard: main\n"
        "equivalent: [CMP-001]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    block = html.split('class="tight self-inverse"')[1].split("</ul>")[0]
    assert block.count('data-ref="CMP-002"') == 1


def test_equivalent_and_alternate_are_ordinary_authored_links_for_the_lint(parts_project):
    """Unlike shared part_number usage, equivalent/alternate ARE declared
    item.links -- a genuine authored claim -- so the cross-workspace lint
    correctly still fires on those, distinguishing an authored dependency
    from a derived coincidence of the BOM."""
    (parts_project / "items" / "alpha" / "main" / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: Main MCU.\n"
        "part_number: STM32G474\nworkspace: alpha\nboard: main\n"
        "equivalent: [CMP-002]\n---\n",
        encoding="utf-8",
    )
    project = _parts_build(parts_project)
    assert any(
        "equivalent points at CMP-002" in d.message and "workspace 'beta'" in d.message
        for d in project.warnings
    )
