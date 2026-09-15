"""`[[ID#field]]` fragment references (docs/design/backlog.md finding 19 Part A).

A fragment reference is a *link* to one field's row on the target item's page
-- it never inlines the field's value, exactly the way `[[fig:id]]` links to a
figure instead of embedding it.
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_and_render, _build_at

FRAG_SCHEMA = """\
site: {title: "Fragment Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
      part_number: { type: text }
      vendor: { type: text }
    links: {}
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links: {}
"""


def _project(tmp_path, dec_body):
    write_project_config(tmp_path, FRAG_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    # `vendor` is declared on the type but left empty here.
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: TPS62913.\npart_number: TPS62913\n---\n",
        encoding="utf-8",
    )
    (items / "dec-001.md").write_text(
        f"---\nid: DEC-001\ntype: decision\ntitle: Pick the converter.\n---\n\n{dec_body}\n",
        encoding="utf-8",
    )
    return tmp_path


SECTION_SCHEMA = """\
site: {title: "Section Anchors", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  bound:
    prefix: BND
    fields:
      title: { type: text, required: true }
      limit: { type: text }
    links: {}
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
      options: { type: options }
      checks: { type: checks }
    links: {}
"""


def _options_project(tmp_path):
    """DEC-002 has options (its own section); DEC-004 declares the field but
    has none, so no section renders."""
    write_project_config(tmp_path, SECTION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-002.md").write_text(
        "---\nid: DEC-002\ntype: decision\ntitle: Two ways.\n"
        "options:\n"
        "  - name: Buck\n    verdict: chosen\n    because: Efficient.\n"
        "  - name: LDO\n    verdict: rejected\n    because: Hot.\n---\n",
        encoding="utf-8",
    )
    (items / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: No options listed.\n---\n",
        encoding="utf-8",
    )
    return tmp_path


CITATION_SCHEMA = """\
site: {title: "Citation Anchors", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
"""

CITATION_ITEM = """\
defaults:
  type: component
items:
  - id: CMP-001
    title: Buck converter
    datasheets:
      - path: https://example.com/ds.pdf
        rev: C
"""


def _checks_project(tmp_path):
    write_project_config(tmp_path, SECTION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bnd-001.md").write_text(
        "---\nid: BND-001\ntype: bound\ntitle: Efficiency floor.\nlimit: '>= 90 %'\n---\n",
        encoding="utf-8",
    )
    (items / "dec-003.md").write_text(
        "---\nid: DEC-003\ntype: decision\ntitle: Checked.\n"
        "checks:\n  - value: eff\n    against: BND-001\n---\n\n"
        "```calc\neff : % = 93 %\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_field_fragment_renders_a_link_to_the_field_anchor(tmp_path):
    """The whole point: `[[CMP-001#part_number]]` is a link to that row, not
    literal `[[...]]` text and not the field's value inlined."""
    out = _build_and_render(_project(tmp_path, "See [[CMP-001#part_number]]."))
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert 'href="cmp-001.html#field-part_number"' in html
    assert "[[CMP-001#part_number]]" not in html


def test_field_fragment_label_overrides_the_link_text(tmp_path):
    out = _build_and_render(_project(tmp_path, "See [[CMP-001#part_number|the MPN]]."))
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert 'href="cmp-001.html#field-part_number"' in html
    assert ">the MPN</a>" in html
    assert "[[CMP-001#part_number|the MPN]]" not in html


def test_item_page_carries_the_field_anchor_id(tmp_path):
    """The href is only worth following if the target page has the id."""
    out = _build_and_render(_project(tmp_path, "Plain body."))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'id="field-part_number"' in html


def test_declared_but_empty_field_still_has_an_anchor(tmp_path):
    """`vendor` is declared on `component` but empty on CMP-001. The row is
    not rendered for an empty value, so the anchor has to exist some other
    way -- a reference to it must never land on a missing id."""
    out = _build_and_render(_project(tmp_path, "See [[CMP-001#vendor]]."))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert 'id="field-vendor"' in html
    project = _build_at(_project(tmp_path, "See [[CMP-001#vendor]]."))
    assert not [d for d in project.warnings if "vendor" in d.message]


def test_empty_field_anchor_keeps_a_layout_box(tmp_path):
    """A `hidden` element has no layout box, and a browser will not scroll to
    one -- the placeholder has to be an empty row with a cell, collapsed by
    CSS, or the link navigates nowhere."""
    out = _build_and_render(_project(tmp_path, "See [[CMP-001#vendor]]."))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert '<tr id="field-vendor" class="field-anchor"><td' in html
    assert 'hidden' not in html.split('id="field-vendor"')[1].split('</tr>')[0]


def test_a_field_rendered_in_its_own_section_anchors_on_the_section(tmp_path):
    """`options` is skipped by the fields table because it renders in its own
    section, so that section -- not a placeholder row -- has to carry the
    anchor, exactly once."""
    out = _build_and_render(_options_project(tmp_path))
    html = open(os.path.join(out, "dec-002.html"), encoding="utf-8").read()
    assert html.count('id="field-options"') == 1
    assert '<section class="options" id="field-options">' in html
    assert '<tr id="field-options"' not in html


def test_a_field_rendered_in_its_checks_section_anchors_there(tmp_path):
    out = _build_and_render(_checks_project(tmp_path))
    html = open(os.path.join(out, "dec-003.html"), encoding="utf-8").read()
    assert html.count('id="field-checks"') == 1
    assert '<section class="checks" id="field-checks">' in html
    assert '<tr id="field-checks"' not in html


def test_a_citations_field_anchors_on_the_citations_section(tmp_path):
    """The citations-typed field is skipped by the fields table by *type*, and
    its name is the project's own, so the section takes that name."""
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(CITATION_ITEM, encoding="utf-8")
    out = _build_and_render(tmp_path)
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert html.count('id="field-datasheets"') == 1
    assert '<section class="citations" id="field-datasheets">' in html
    assert '<tr id="field-datasheets"' not in html


def test_an_empty_section_field_falls_back_to_the_placeholder_row(tmp_path):
    """DEC-004 declares `options` but has none: no section renders, so the
    anchor has to be the placeholder row -- and still exactly one of them."""
    out = _build_and_render(_options_project(tmp_path))
    html = open(os.path.join(out, "dec-004.html"), encoding="utf-8").read()
    assert html.count('id="field-options"') == 1
    assert '<section class="options"' not in html
    assert '<tr id="field-options" class="field-anchor"><td' in html


def test_undeclared_field_is_a_diagnostic_naming_item_field_and_type(tmp_path):
    project = _build_at(_project(tmp_path, "See [[CMP-001#no_such_field]]."))
    msg = next(d.message for d in project.warnings if "no_such_field" in d.message)
    assert "CMP-001" in msg
    assert "no_such_field" in msg
    assert "component" in msg


def test_undeclared_field_does_not_render_a_link(tmp_path):
    out = _build_and_render(_project(tmp_path, "See [[CMP-001#no_such_field]]."))
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert "#field-no_such_field" not in html
    assert "[[" not in html


def test_unknown_item_with_a_fragment_warns_like_a_plain_unknown_item(tmp_path):
    """The fragment must not change or swallow the existing diagnostic."""
    with_fragment = _build_at(_project(tmp_path, "See [[REQ-999#part_number]]."))
    plain = _build_at(_project(tmp_path, "See [[REQ-999]]."))
    got = [d.message for d in with_fragment.warnings if "REQ-999" in d.message]
    want = [d.message for d in plain.warnings if "REQ-999" in d.message]
    assert got == want
    assert any("does not exist" in m for m in got)


def test_a_fragment_on_a_figure_reference_warns(tmp_path):
    """Figures are addressed by id, so `#something` on one is author error --
    it must be reported, not silently dropped from the link."""
    project = _build_at(_project(tmp_path, "See [[fig:fig-curve#title]]."))
    msg = next(d.message for d in project.warnings if "fig-curve" in d.message)
    assert "fragment" in msg


def test_plain_labeled_and_figure_references_are_unchanged(tmp_path):
    """Regression: widening the regex must not disturb the forms that work today."""
    write_project_config(tmp_path, FRAG_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    figures = items / "figures"
    figures.mkdir()
    (figures / "curve.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: TPS62913.\npart_number: TPS62913\n---\n",
        encoding="utf-8",
    )
    # The figure lives in the same item as the references to it: a cross-item
    # [[fig:...]] deliberately does not resolve on a standalone item page.
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Pick the converter.\n---\n\n"
        "Bare CMP-001 here, explicit [[CMP-001]] there, labeled "
        "[[CMP-001|the converter]], figure [[fig:fig-curve]] and "
        "[[fig:fig-curve|the curve]].\n\n"
        '![the curve](figures/curve.png){id="fig-curve" caption="Efficiency"}\n',
        encoding="utf-8",
    )
    out = _build_and_render(tmp_path)
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert 'href="cmp-001.html" data-ref="CMP-001">CMP-001</a>' in html
    assert 'href="cmp-001.html" data-ref="CMP-001">the converter</a>' in html
    assert '<a class="ref fig-ref" href="#fig-curve">Figure 1</a>' in html
    assert '<a class="ref fig-ref" href="#fig-curve">the curve</a>' in html
    assert "[[" not in html
