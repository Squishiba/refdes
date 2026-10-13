"""Page-level uniqueness of calc-block DOM anchors (RENDER-ANCHOR-001/002/003).

Block names are unique per item, not per project (docs/design/named-
calc-blocks.md §11.2), so two items can both own a block `losses` — and the
merged documents (document.html and its board/workspace copies) render every
item's body into one DOM. That made `id="calc-losses"` appear twice on one
page. The anchor strategy here: the owner's own page keeps the bare
`id="calc-<name>"` (which is what `[[ID#calc:name]]` links to, so every
cross-reference keeps working), and on any page that would render the same
calc anchor twice, the later occurrence is renamed with a `-2`/`-3`… suffix
that is guaranteed not to collide with any id already on that page.

Sabotage-style: each test fails if the duplicate ships, if the rename lands
on the FIRST occurrence (moving the bare anchor away from what `#calc:` links
resolve to), if the renamed candidate can collide with a real block name
(`losses-2`), or if `block=""` is allowed to match the unnamed fence.
"""

from __future__ import annotations

import re

from conftest import write_project_config
from helpers import _build_at

from refdes import render as render_mod

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)

LOSSES_A = (
    "---\nid: DEC-001\ntype: decision\n---\n\n"
    '```calc id="losses"\nP_a = 2 W\n```\n\n'
    "See [[DEC-002#calc:losses]] and [[DEC-001#calc:losses|my own losses]].\n"
)

LOSSES_B = (
    "---\nid: DEC-002\ntype: decision\n---\n\n"
    '```calc id="losses"\nP_b = 3 W\n```\n\n'
    "```calc\nQ_diss = 0.5 W\n```\n"
)


def _project(tmp_path, items: dict[str, str], pages: dict[str, str] | None = None):
    write_project_config(tmp_path, CONFIG)
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    for name, text in items.items():
        (items_dir / name).write_text(text, encoding="utf-8")
    if pages:
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        for name, text in pages.items():
            (pages_dir / name).write_text(text, encoding="utf-8")
    return _build_at(tmp_path)


def _site(tmp_path, items, pages=None):
    project = _project(tmp_path, items, pages)
    out_dir = render_mod.render_site(project)
    return project, out_dir


def _read(out_dir, name):
    with open(f"{out_dir}/{name}", encoding="utf-8") as fh:
        return fh.read()


def _calc_anchors(html: str) -> list[str]:
    return re.findall(r'<table class="calc" id="(calc-[^"]*)"', html)


# --------------------------------------------------- merged document pages


def test_document_html_calc_anchor_unique_across_items(tmp_path):
    """RENDER-ANCHOR-001: two items both naming a block `losses` must not
    put `id="calc-losses"` on document.html twice.

    Sabotage: dropping the per-page uniqueness pass ships two identical
    anchors; renaming the FIRST occurrence instead of the later ones moves
    the bare anchor away from what `dec-*.html#calc-losses` resolves to.
    """
    project, out_dir = _site(tmp_path, {"a.md": LOSSES_A, "b.md": LOSSES_B})
    assert not project.errors, project.errors

    document = _read(out_dir, "document.html")
    anchors = _calc_anchors(document)
    assert len(anchors) == len(set(anchors)), anchors
    # First occurrence in reading order keeps the bare anchor; the later
    # one moves to the suffixed form.
    assert anchors == ["calc-losses", "calc-losses-2"], anchors


def test_item_pages_keep_bare_anchor_and_cross_refs(tmp_path):
    """The other half of the strategy: the standalone pages are untouched.

    Each item's own page keeps `id="calc-losses"` — that is the anchor
    `[[ID#calc:name]]` resolves to (§5.3), and the reference hrefs carry the
    target's page name, so they resolve there from any page, merged included.
    Sabotage: prefixing the anchor at emission breaks every published
    `#calc:` deep link and these assertions.
    """
    project, out_dir = _site(tmp_path, {"a.md": LOSSES_A, "b.md": LOSSES_B})
    assert not project.errors, project.errors

    for name in ("dec-001.html", "dec-002.html"):
        html = _read(out_dir, name)
        assert html.count('<table class="calc" id="calc-losses">') == 1, name

    dec001 = _read(out_dir, "dec-001.html")
    assert 'href="dec-002.html#calc-losses"' in dec001
    assert 'href="dec-001.html#calc-losses"' in dec001
    # document.html must not anchorize a fragment href into the merged DOM —
    # the link goes to the owner's page, where the bare anchor lives.
    document = _read(out_dir, "document.html")
    assert 'href="dec-002.html#calc-losses"' in document
    assert 'href="#calc-losses"' not in document


def test_renamed_anchor_never_collides_with_a_real_block_name(tmp_path):
    """A block can genuinely be named `losses-2`; the suffix must route
    around ids already on the page, not land on one.

    Sabotage: a rename that picks `f"{anchor}-2"` without checking what the
    page already carries puts `id="calc-losses-2"` on two tables.
    """
    losses_2 = (
        "---\nid: DEC-003\ntype: decision\n---\n\n"
        '```calc id="losses-2"\nP_c = 4 W\n```\n'
    )
    project, out_dir = _site(
        tmp_path, {"a.md": LOSSES_A, "b.md": LOSSES_B, "c.md": losses_2}
    )
    assert not project.errors, project.errors

    document = _read(out_dir, "document.html")
    anchors = _calc_anchors(document)
    assert anchors == ["calc-losses", "calc-losses-3", "calc-losses-2"], anchors
    assert len(anchors) == len(set(anchors)), anchors


# ------------------------------------------------------------- calcblock pages


def test_calcblock_page_dupes_get_unique_anchors(tmp_path):
    """RENDER-ANCHOR-003: two `{{calcblock}}` directives naming the same
    block of two different items must not emit `id="calc-losses"` twice on
    one page.

    Sabotage: the pre-fix renderer emits two identical anchors; dropping
    the second table instead of renaming its anchor loses a directive's
    content.
    """
    page = (
        "# Two losses\n\n"
        '{{calcblock item="DEC-001" block="losses"}}\n\n'
        '{{calcblock item="DEC-002" block="losses"}}\n'
    )
    project, out_dir = _site(
        tmp_path, {"a.md": LOSSES_A, "b.md": LOSSES_B}, {"two.md": page}
    )
    assert not project.errors, project.errors

    html = _read(out_dir, "two.html")
    anchors = _calc_anchors(html)
    assert anchors == ["calc-losses", "calc-losses-2"], anchors
    # Both directives still render their tables.
    assert html.count('<tr class="calc-row">') == 2


# --------------------------------------------------------- the unnamed fence


def test_calcblock_empty_block_is_a_build_error(tmp_path):
    """RENDER-ANCHOR-002: `block=""` must not match the item's unnamed
    fence — the parameter names a NAMED block (docs/design/
    named-calc-blocks.md §5.4: "A **named** calc block … Must exist").

    Sabotage: `line.block == block` matching the empty string renders the
    unnamed rows with no anchor and a caption ending in a dangling ` / `.
    """
    page = (
        "# Empty\n\n" '{{calcblock item="DEC-002" block=""}}\n'
    )
    project, page_obj = _page(tmp_path, {"b.md": LOSSES_B}, {"empty.md": page})

    assert len(project.errors) == 1, project.errors
    assert project.errors[0].message == (
        '{{calcblock item="DEC-002" block=""}} — block="" is not a calc '
        "block name -- calcblock renders a named ```calc block. "
        "DEC-002 names: losses."
    )
    assert '<p class="block-error">' in page_obj.body_html
    # The unnamed block's rows are NOT rendered here.
    assert "Q_diss" not in page_obj.body_html
    assert '<table class="calc"' not in page_obj.body_html


def _page(tmp_path, items, pages):
    project = _project(tmp_path, items, pages)
    return project, next(p for p in project.pages if p.slug == "empty")
