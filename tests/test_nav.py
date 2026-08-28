"""nav.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import REPO, _build_at

from refdes import nav as nav_mod
from refdes import render

# ------------------------------------------------------------------------ nav


@pytest.fixture
def unboarded_project(tmp_path):
    """A project with no `boards:` registry at all -- a dedicated fixture, not
    `paged_project` (which copies this repo's own config, and this repo now
    registers boards -- see test_real_project_registers_boards_and_renders_
    board_pages)."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site, pages: pages }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text("# Overview\n\nSome prose.\n", encoding="utf-8")
    return tmp_path


def test_nav_tree_is_flat_with_no_boards_registered(unboarded_project):
    """No boards: registry -- nav degrades to the same flat list as before."""
    project = _build_at(unboarded_project)
    tree = nav_mod.build_nav(project, dashboard_href="items.html")
    assert [n.label for n in tree] == [
        "Overview", "Summary", "Items", "Coverage", "Full record", "JSON",
    ]
    assert all(n.href and not n.children for n in tree)


def test_navnode_contains_checks_self_and_descendants_at_any_depth():
    """Findings 5 and 7's shared plumbing: a group node must recognize a page
    living inside a nested descendant, not just its own direct href or
    immediate children -- board.py's own nesting (workspace > board > page)
    goes at least two levels deep."""
    leaf = nav_mod.NavNode("Coverage", "coverage-board-a.html")
    board_group = nav_mod.NavNode("Board A", children=[leaf])
    workspace_group = nav_mod.NavNode("Platform", children=[board_group])

    assert leaf.contains("coverage-board-a.html")
    assert board_group.contains("coverage-board-a.html")
    assert workspace_group.contains("coverage-board-a.html")
    assert not workspace_group.contains("coverage-board-b.html")
    assert not leaf.contains("")


def test_rendered_page_marks_current_page_with_aria_current(board_project):
    """Finding 5: the sidebar link for whatever page is actually being
    rendered gets aria-current="page" -- and no other link on that same page
    does, including the same-labeled link ("Coverage") in a sibling board's
    own group."""
    project = _build_at(board_project)
    out = render.render_site(project)
    coverage_a = open(os.path.join(out, "coverage-board-a.html"), encoding="utf-8").read()
    assert '<a href="coverage-board-a.html" aria-current="page">Coverage</a>' in coverage_a
    without_it = coverage_a.replace(
        '<a href="coverage-board-a.html" aria-current="page">Coverage</a>', ""
    )
    assert "aria-current" not in without_it


def test_sidebar_group_containing_current_page_is_pre_expanded(board_project):
    """Finding 7: the board group the reader is already standing inside opens
    pre-expanded (no click needed to see where you are); a sibling group with
    nothing to do with the current page stays collapsed."""
    project = _build_at(board_project)
    out = render.render_site(project)
    doc_a = open(os.path.join(out, "document-board-a.html"), encoding="utf-8").read()
    sidenav = doc_a.split('<div class="content">')[0]
    assert "<details open>\n      <summary>Board A</summary>" in sidenav
    assert "<details>\n      <summary>Board B</summary>" in sidenav


def test_sidebar_has_a_mobile_collapse_toggle_with_no_javascript(board_project):
    """Finding 7's narrow-viewport handling: the whole nav tree sits behind a
    checkbox-driven toggle (not a <details> wrapper -- verified directly
    against a real browser that a closed <details>'s non-summary content
    can't be forced open by CSS alone, since current browsers hide it via an
    internal, unstyleable mechanism) so a phone doesn't get several hundred
    pixels of expanded navigation before any real content. No <script> tag
    is involved in driving it -- the label/checkbox association is native
    HTML."""
    project = _build_at(board_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    sidenav = html.split('<div class="content">')[0]
    assert '<input type="checkbox" id="sidenav-toggle"' in sidenav
    assert '<label for="sidenav-toggle"' in sidenav
    app_js = open(
        os.path.join(REPO, "src", "refdes", "templates", "assets", "app.js"), encoding="utf-8"
    ).read()
    assert "sidenav" not in app_js  # native label/checkbox, no script drives it


def test_nav_tree_groups_pages_and_reports_under_their_board(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "power.md").write_text(
        "---\nboard: board-a\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    tree = nav_mod.build_nav(project, dashboard_href="items.html")

    groups = {n.label: n for n in tree if not n.href}
    assert set(groups) == {"Board A", "Board B"}

    a_children = [c.label for c in groups["Board A"].children]
    assert a_children == ["Power overview", "Summary", "Coverage", "Full record"]
    # A board with no page of its own still gets a group -- just its reports.
    assert [c.label for c in groups["Board B"].children] == ["Summary", "Coverage", "Full record"]

    # The board-tagged page is not duplicated at the top level.
    root_labels = [n.label for n in tree if n.href]
    assert "Power overview" not in root_labels


def test_nav_group_appears_for_a_page_only_board_with_no_items(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site, pages: pages }\n"
        "boards:\n  power: { label: Power }\n"
        "types:\n  note: { prefix: NOTE }\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "overview.md").write_text(
        "---\nboard: power\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(tmp_path)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")
    groups = {n.label: n for n in tree if not n.href}
    assert set(groups) == {"Power"}
    assert [c.label for c in groups["Power"].children] == ["Power overview"]


def test_page_board_tag_must_be_registered(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "bad.md").write_text(
        "---\nboard: nonexistent\n---\n\n# Bad\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    assert any(
        "nonexistent" in d.message and "not declared" in d.message
        for d in project.errors
    )
    page = next(p for p in project.pages if p.slug == "bad")
    assert page.board == ""


def test_rendered_nav_shows_board_groups(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "power.md").write_text(
        "---\nboard: board-a\n---\n\n# Power overview\n", encoding="utf-8"
    )
    project = _build_at(board_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert "<summary>Board A</summary>" in html
    assert 'href="power.html"' in html
    assert 'href="summary-board-a.html"' in html
    assert 'href="coverage-board-b.html"' in html


def test_rendered_nav_has_no_groups_without_boards_registered(unboarded_project):
    """Finding 7's explicit requirement: a project with no boards/workspaces
    registered must degrade to a flat list of links, not an empty rail or a
    single lonely disclosure -- nav.py's build_nav() already returns a flat
    root list with nothing to group in this case, so there is nothing for
    the sidebar to wrap in <details> at all."""
    project = _build_at(unboarded_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert "<details" not in html.split('<div class="content">')[0]
    assert '<a href="summary.html"' in html
