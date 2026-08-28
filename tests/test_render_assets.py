"""images and assets -- and: site.assets:, figure/caption, pages + images, stale output, figure identity/numbering, explicit reference regression.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from helpers import COVERAGE_SCHEMA, REPO, _build_and_render, _build_at

from refdes import build as build_mod
from refdes import parse, render
from refdes.schema import load_project

# ------------------------------------------------------------- images and assets


def _asset_hash(data: bytes) -> str:
    """Matches build.py's own truncation of the content sha256 for a hashed
    asset filename -- computed here, not hardcoded, so a deliberate change to
    the truncation length doesn't silently rot these tests."""
    return hashlib.sha256(data).hexdigest()[:16]


IMAGE_ITEM = """\
---
id: DEC-A-001
type: decision
title: Has a couple images.
status: accepted
---

![missing](figures/missing.png)

![present](figures/present.png)

![remote](https://example.com/photo.png)
"""


@pytest.fixture
def image_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(IMAGE_ITEM, encoding="utf-8")
    figures = items / "figures"
    figures.mkdir()
    (figures / "present.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_missing_image_src_errors_present_and_remote_do_not(image_project):
    """A dangling image src must fail the build now that a resolving one works."""
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    messages = [d.message for d in project.errors]
    assert any("figures/missing.png" in m for m in messages)
    assert not any("figures/present.png" in m for m in messages)
    assert not any("example.com" in m for m in messages)
    assert not any("figures/missing.png" in d.message for d in project.warnings)


def test_present_local_image_is_registered_and_rewritten(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    assert "items/figures/present.png" in project.assets
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    assert project.assets["items/figures/present.png"] == f"items/figures/present.{digest}.png"
    item = project.items["DEC-A-001"]
    assert f'src="assets/items/figures/present.{digest}.png"' in item.body_html
    # A remote src is never touched or registered.
    assert "assets/https" not in item.body_html
    assert 'src="https://example.com/photo.png"' in item.body_html


def test_local_image_is_copied_into_the_site(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)

    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    copied = os.path.join(out, "assets", "items", "figures", f"present.{digest}.png")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == b"\x89PNG\r\n\x1a\n"


def test_editing_an_image_changes_its_url_and_prunes_the_old_one(image_project):
    """Content-hashed filenames (docs/design/index-blocks.md §10): editing the
    bytes in place must not silently serve stale content from a cache under
    the same URL -- the filename itself has to change, and the old one must
    not linger in _site/."""
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)
    old_digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    old_path = os.path.join(out, "assets", "items", "figures", f"present.{old_digest}.png")
    assert os.path.isfile(old_path)

    new_bytes = b"\x89PNG\r\n\x1a\n\x00extra"
    (image_project / "items" / "figures" / "present.png").write_bytes(new_bytes)

    project2 = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)
    out2 = render.render_site(project2)
    new_digest = _asset_hash(new_bytes)
    assert new_digest != old_digest
    new_path = os.path.join(out2, "assets", "items", "figures", f"present.{new_digest}.png")
    assert os.path.isfile(new_path)
    assert not os.path.isfile(old_path)  # pruned, same as any other stale output


def test_deleting_an_image_reference_prunes_its_copied_asset(image_project):
    project = load_project(config_path=str(image_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    copied = os.path.join(out, "assets", "items", "figures", f"present.{digest}.png")
    assert os.path.isfile(copied)

    text = (image_project / "items" / "dec-a.md").read_text(encoding="utf-8")
    text = text.replace("![present](figures/present.png)\n\n", "")
    (image_project / "items" / "dec-a.md").write_text(text, encoding="utf-8")

    out = _build_and_render(image_project)
    assert not os.path.isfile(copied)


def test_asset_colliding_with_a_template_reserved_name_is_an_error(tmp_path):
    """A site.assets: directory literally named `style.css` must not clobber
    the template's own reserved top-level asset name. An `<img src>` can no
    longer produce this collision now that it is always content-hashed (an
    escaping `../style.css` reference now lands on `style.<hash>.css`); a
    site.assets: mapping stays an identity mapping (docs/design/index-blocks.md
    §10), so it is the one remaining way to hit this."""
    schema = COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        'site: {title: "Coverage Test", out: _site, assets: ["style.css"]}',
    )
    (tmp_path / "refdes.yaml").write_text(schema, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    clobber_dir = tmp_path / "style.css"
    clobber_dir.mkdir()
    (clobber_dir / "logo.png").write_text("SHOULD NOT LAND HERE", encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)

    assert any("would be written to assets/style.css" in d.message for d in project.errors)
    real_style = open(os.path.join(out, "assets", "style.css"), encoding="utf-8").read()
    assert "SHOULD NOT LAND HERE" not in real_style  # the template's own stylesheet survived


# ------------------------------------------------------------- site.assets:

SITE_ASSETS_SCHEMA = COVERAGE_SCHEMA.replace(
    'site: {title: "Coverage Test", out: _site}',
    'site: {title: "Coverage Test", out: _site, assets: [figures]}',
)


@pytest.fixture
def site_assets_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(SITE_ASSETS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: Nothing references figures.\n---\n",
        encoding="utf-8",
    )
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "board.pdf").write_bytes(b"%PDF-1.4 fake")
    return tmp_path


def test_site_assets_directory_is_copied_with_no_reference_needed(site_assets_project):
    out = _build_and_render(site_assets_project)
    copied = os.path.join(out, "assets", "figures", "board.pdf")
    assert os.path.isfile(copied)
    assert open(copied, "rb").read() == b"%PDF-1.4 fake"


def test_site_assets_missing_directory_warns(tmp_path):
    schema = COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        'site: {title: "Coverage Test", out: _site, assets: [nope]}',
    )
    (tmp_path / "refdes.yaml").write_text(schema, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert any("'nope' is not a directory" in d.message for d in project.warnings)


# ------------------------------------------------------------- figure/caption

FIGURE_ITEM = """\
---
id: DEC-A-001
type: decision
title: Has a captioned figure.
status: accepted
---

![the curve](figures/present.png){width=60% caption="Figure 3 — the curve"}

![no caption given](figures/present.png){width=40%}

![plain, no suffix](figures/present.png)
"""


@pytest.fixture
def figure_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(FIGURE_ITEM, encoding="utf-8")
    figures = items / "figures"
    figures.mkdir()
    (figures / "present.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_figure_attrs_wrap_the_image_and_set_width_and_caption(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")

    assert '<figure class="md-figure" style="width: 60%">' in html
    assert "<figcaption>Figure 3 — the curve</figcaption>" in html
    assert f'<img src="assets/items/figures/present.{digest}.png" alt="the curve" />' in html


def test_figure_caption_falls_back_to_alt_when_not_given(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html

    assert '<figure class="md-figure" style="width: 40%">' in html
    assert "<figcaption>no caption given</figcaption>" in html


def test_image_with_no_suffix_is_never_wrapped_in_a_figure(figure_project):
    project = load_project(config_path=str(figure_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    html = project.items["DEC-A-001"].body_html
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")

    assert f'<img src="assets/items/figures/present.{digest}.png" alt="plain, no suffix" />' in html
    # Exactly two images are wrapped (the two with a suffix); the third stands alone.
    assert html.count("<figure") == 2


# ------------------------------------------------------------- pages + images

def test_pages_get_the_same_image_resolution_and_copy(tmp_path):
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Overview\n\n![board photo](img/board.png)\n", encoding="utf-8"
    )
    img_dir = pages / "img"
    img_dir.mkdir()
    (img_dir / "board.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    out = _build_and_render(tmp_path)
    digest = _asset_hash(b"\x89PNG\r\n\x1a\n")
    assert os.path.isfile(os.path.join(out, "assets", "pages", "img", f"board.{digest}.png"))
    index_html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert f'src="assets/pages/img/board.{digest}.png"' in index_html


# -------------------------------------------------------------- stale output


PRUNE_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Stays.
---
""",
    "req-b.md": """\
---
id: REQ-B-001
type: requirement
text: Gets deleted.
---
""",
}


@pytest.fixture
def prune_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in PRUNE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_deleting_an_item_prunes_its_stale_page(prune_project):
    """A deleted item must not leave a live, still-linkable page in _site/ (#1 P1-4)."""
    out_dir = _build_and_render(prune_project)
    stale_page = os.path.join(out_dir, "req-b-001.html")
    assert os.path.isfile(stale_page)

    (prune_project / "items" / "req-b.md").unlink()

    out_dir = _build_and_render(prune_project)
    assert not os.path.isfile(stale_page)
    assert os.path.isfile(os.path.join(out_dir, "req-a-001.html"))


def test_prune_never_touches_files_it_did_not_write(prune_project):
    """Pruning must be scoped to the manifest, never a blanket sweep of out_dir."""
    out_dir = _build_and_render(prune_project)
    hand_written = os.path.join(out_dir, "notes.txt")
    with open(hand_written, "w", encoding="utf-8") as fh:
        fh.write("keep me")

    _build_and_render(prune_project)
    assert os.path.isfile(hand_written)


# --------------------------------------------------------- figure identity/numbering

FIG_SCHEMA = """\
site: {title: "Figures Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  power: {label: Power}
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links: {}
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
    links: {}
"""


FIG_PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def fig_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FIG_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    figures = items / "figures"
    figures.mkdir()
    (figures / "curve.png").write_bytes(FIG_PNG)
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Buck topology.\nboard: power\n---\n\n"
        'See [[fig:fig-curve]] and [[fig:fig-curve|the curve above]].\n'
        'Also [[fig:fig-nope]].\n\n'
        '![the curve](figures/curve.png){id="fig-curve" caption="Efficiency"}\n',
        encoding="utf-8",
    )
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: TPS62913.\nboard: power\n---\n\n"
        "Cross-item: [[fig:fig-curve]].\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Overview\n\nPage ref: [[fig:fig-curve]].\n", encoding="utf-8"
    )
    return tmp_path


def test_figure_id_is_registered_and_gets_an_html_id(fig_project):
    project = _build_at(fig_project)
    assert not project.errors
    assert "fig-curve" in project.figures
    owner, source_file, _line = project.figures["fig-curve"]
    assert owner == "DEC-001"
    assert source_file == "items/dec-001.md"


def test_duplicate_figure_id_is_an_error_naming_both_locations(fig_project):
    (fig_project / "items" / "cmp-002.md").write_text(
        "---\nid: CMP-002\ntype: component\ntitle: Dup.\nboard: power\n---\n\n"
        '![dup](figures/curve.png){id="fig-curve"}\n',
        encoding="utf-8",
    )
    project = _build_at(fig_project)
    # cmp-002.md sorts before dec-001.md, so CMP-002 registers 'fig-curve'
    # first and DEC-001's own use of it is the one that collides.
    msg = next(d.message for d in project.errors if "figure id" in d.message)
    assert "figure id 'fig-curve' is already used by CMP-002" in msg
    assert "items/cmp-002.md" in msg
    assert "Figure ids must be unique across the project" in msg


def test_figure_numbers_per_document_own_item_page(fig_project):
    project = _build_at(fig_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert "<figcaption>Figure 1 — Efficiency</figcaption>" in html
    assert '<a class="ref fig-ref" href="#fig-curve">Figure 1</a>' in html
    assert '<a class="ref fig-ref" href="#fig-curve">the curve above</a>' in html
    assert '<span class="ref ref-missing" title="unknown figure">fig-nope</span>' in html
    assert any(
        "reference to figure 'fig-nope', which does not exist" in d.message
        for d in project.warnings
    )


def test_figure_cross_item_reference_fails_on_the_items_own_page(fig_project):
    out = _build_and_render(fig_project)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert '<span class="ref ref-missing" title="unknown figure">fig-curve</span>' in html


def test_figure_cross_item_reference_resolves_in_the_combined_document(fig_project):
    out = _build_and_render(fig_project)
    html = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert html.count("Figure 1") >= 2  # DEC-001's own figure and CMP-001's cross-ref
    assert '<a class="ref fig-ref" href="#fig-curve">Figure 1</a>' in html


def test_figure_reference_on_a_narrative_page_that_lacks_it_warns(fig_project):
    project = _build_at(fig_project)
    out = render.render_site(project)
    assert any(
        "exists on DEC-001 but is not rendered on this page" in d.message
        for d in project.warnings
    )
    index_html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert '<span class="ref ref-missing" title="unknown figure">fig-curve</span>' in index_html


def test_check_catches_a_dangling_figure_reference_without_rendering(fig_project):
    """`refdes check` never calls render_site, so a dangling [[fig:...]] has
    to be caught by build() itself -- the same way a dangling [[ITEM-ID]]
    already is -- or `check` would silently miss what `build` catches."""
    project = _build_at(fig_project)  # build() only, exactly what `check` runs
    assert any(
        "reference to figure 'fig-nope', which does not exist" in d.message
        for d in project.warnings
    )


def test_build_does_not_double_warn_a_dangling_figure_reference(fig_project):
    """The same project run through build() then render_site() (what `refdes
    build` actually does) must warn about a nonexistent figure id exactly
    once, not once from the eager check and again from every document
    resolve_figures happens to touch."""
    project = _build_at(fig_project)
    render.render_site(project)
    matches = [
        d.message for d in project.warnings
        if "reference to figure 'fig-nope', which does not exist" in d.message
    ]
    assert len(matches) == 1


# -------------------------------------------------- explicit reference regression

def test_explicit_item_reference_does_not_nest_duplicate_links(blocks_project):
    """Regression: _linkify's bare-reference pass used to re-scan its own
    explicit-reference substitutions, turning [[ID]] into nested <a><a>...
    tags because the target id also appears as the link's own text/attrs."""
    (blocks_project / "items" / "req-001.md").write_text(
        "---\nid: REQ-001\ntype: requirement\ntext: Input voltage range.\n---\n\n"
        "See [[CON-001]] for the thermal budget.\n",
        encoding="utf-8",
    )
    project = _build_at(blocks_project)
    html = project.items["REQ-001"].body_html
    assert html.count("<a") == 1
    assert '<a class="ref" href="con-001.html" data-ref="CON-001">CON-001</a>' in html
