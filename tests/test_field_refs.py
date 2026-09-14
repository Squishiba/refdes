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
