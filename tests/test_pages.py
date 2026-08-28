"""pages.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

from helpers import _build_at

from refdes import render


def test_pages_render_without_being_items(paged_project):
    project = _build_at(paged_project)
    assert not project.errors
    assert {p.slug for p in project.pages} == {"index", "power"}
    # A page is not an item: no ID, no coverage obligations.
    assert "index" not in project.items
    assert len(project.items) == 1


def test_page_titles_come_from_the_h1(paged_project):
    project = _build_at(paged_project)
    titles = {p.slug: p.title for p in project.pages}
    assert titles["index"] == "Board overview"
    assert titles["power"] == "Power"


def test_pages_sort_by_explicit_nav_then_order(paged_project):
    """front-matter `order: 5` beats the default 100."""
    project = _build_at(paged_project)
    assert [p.slug for p in project.pages] == ["power", "index"]


def test_page_to_page_links_are_rewritten_to_html(paged_project):
    project = _build_at(paged_project)
    index = next(p for p in project.pages if p.slug == "index")
    assert 'href="power.html"' in index.body_html
    assert ".md" not in index.body_html


def test_pages_can_reference_items_and_get_previews(paged_project):
    project = _build_at(paged_project)
    power = next(p for p in project.pages if p.slug == "power")
    assert 'data-ref="REQ-001"' in power.body_html


def test_page_headings_get_anchors(paged_project):
    project = _build_at(paged_project)
    power = next(p for p in project.pages if p.slug == "power")
    assert [text for _lvl, text, _a in power.headings] == ["Rails", "Budget"]
    assert '<h2 id="rails">' in power.body_html


def test_page_colliding_with_a_generated_report_is_an_error(paged_project):
    """A page called coverage.md must not silently clobber the coverage report."""
    (paged_project / "pages" / "coverage.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(paged_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)
    # The report survives; the page is skipped rather than overwriting it.
    out = os.path.join(paged_project, "_site", "coverage.html")
    assert "Nope" not in open(out, encoding="utf-8").read()


def test_pages_only_project_may_use_report_names_freely(tmp_path):
    """With no items there are no generated reports, so coverage.md is fine."""
    (tmp_path / "refdes.yaml").write_text(
        "site:\n  title: Docs\n  out: _site\n  pages: pages\n"
        "types:\n  note:\n    prefix: NOTE\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "coverage.md").write_text("# Coverage guide\n", encoding="utf-8")
    project = _build_at(tmp_path)
    out = render.render_site(project)
    assert not project.errors
    assert "Coverage guide" in open(
        os.path.join(out, "coverage.html"), encoding="utf-8"
    ).read()


def test_docs_site_builds_with_no_items_at_all(tmp_path):
    """A pages-only project is a plain website; nothing item-shaped is required."""
    (tmp_path / "refdes.yaml").write_text(
        'site:\n  title: Docs\n  out: _site\n  pages: pages\n'
        "types:\n  note:\n    prefix: NOTE\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text("# Hello\n\nSome prose.\n", encoding="utf-8")

    project = _build_at(tmp_path)
    out = render.render_site(project)
    assert not project.errors
    assert os.path.isfile(os.path.join(out, "index.html"))
    assert os.path.isdir(os.path.join(out, "assets"))
    # No items means no item machinery in the output.
    assert not os.path.exists(os.path.join(out, "coverage.html"))
