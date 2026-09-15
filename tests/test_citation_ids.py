"""Citation identity: a declared `id:` on a citation entry, and the
`[[cite:id]]` reference form that links to it (docs/design/backlog.md
finding 19 Part B).

A citation reference is a link to that citation's own row on the page of the
item that declares it -- it never inlines anything, exactly the way
`[[fig:id]]` links to a figure and `[[ID#field]]` links to a field's row
(finding 19 Part A, tests/test_field_refs.py).
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_and_render, _build_at

CITATION_SCHEMA = """\
site: {title: "Citation Identity Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
"""


def _project(tmp_path, cmp_citations, dec_body="Plain body."):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "cmp-001.md").write_text(
        "---\nid: CMP-001\ntype: component\ntitle: TPS62913.\n"
        f"datasheets:\n{cmp_citations}\n---\n",
        encoding="utf-8",
    )
    (items / "dec-001.md").write_text(
        f"---\nid: DEC-001\ntype: decision\ntitle: Pick the converter.\n---\n\n{dec_body}\n",
        encoding="utf-8",
    )
    return tmp_path


ONE_CITATION_WITH_ID = (
    "  - path: https://example.com/ds.pdf\n"
    "    rev: C\n"
    "    id: ds-main\n"
)

ONE_CITATION_NO_ID = "  - path: https://example.com/ds.pdf\n    rev: C\n"


def test_cite_ref_renders_an_anchored_link_to_the_owning_item_page(tmp_path):
    out = _build_and_render(
        _project(tmp_path, ONE_CITATION_WITH_ID, "See [[cite:ds-main]] for detail.")
    )
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert 'class="ref cite-ref" href="cmp-001.html#cite-ds-main">ds-main</a>' in html
    assert "[[cite:ds-main]]" not in html


def test_cite_ref_label_overrides_the_link_text(tmp_path):
    out = _build_and_render(
        _project(
            tmp_path, ONE_CITATION_WITH_ID, "See [[cite:ds-main|the datasheet]] for detail."
        )
    )
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert 'href="cmp-001.html#cite-ds-main">the datasheet</a>' in html
    assert "[[cite:ds-main|the datasheet]]" not in html


def test_citation_row_carries_the_matching_id_exactly_once(tmp_path):
    out = _build_and_render(_project(tmp_path, ONE_CITATION_WITH_ID))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert html.count('id="cite-ds-main"') == 1
    assert '<tr id="cite-ds-main">' in html


def test_citation_without_id_still_renders_exactly_as_before(tmp_path):
    """Regression: a citation with no `id:` keeps rendering its row with no
    id attribute at all -- the whole feature is additive."""
    out = _build_and_render(_project(tmp_path, ONE_CITATION_NO_ID))
    html = open(os.path.join(out, "cmp-001.html"), encoding="utf-8").read()
    assert "<h2>Citations</h2>" in html
    assert "https://example.com/ds.pdf" in html
    assert "cite-" not in html
    assert "<tr>" in html


def test_unknown_cite_id_is_a_diagnostic_and_renders_missing_ref_span(tmp_path):
    project_root = _project(tmp_path, ONE_CITATION_NO_ID, "See [[cite:nope]] for detail.")
    project = _build_at(project_root)
    msg = next(d.message for d in project.warnings if "nope" in d.message)
    assert "does not exist" in msg

    out = _build_and_render(project_root)
    html = open(os.path.join(out, "dec-001.html"), encoding="utf-8").read()
    assert '<span class="ref ref-missing" title="unknown citation">nope</span>' in html
    assert "[[cite:nope]]" not in html


def test_cite_ref_fragment_warns(tmp_path):
    """Citations are addressed by id, not by field -- a `#fragment` on one is
    author error, reported exactly like it is on a figure reference."""
    project = _build_at(
        _project(tmp_path, ONE_CITATION_WITH_ID, "See [[cite:ds-main#page]] for detail.")
    )
    msg = next(d.message for d in project.warnings if "ds-main" in d.message)
    assert "fragment" in msg


def test_duplicate_citation_id_across_two_items_is_an_error_naming_both(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n"
        "  - id: CMP-001\n    title: A\n"
        "    datasheets:\n      - path: https://example.com/a.pdf\n        id: shared\n"
        "  - id: CMP-002\n    title: B\n"
        "    datasheets:\n      - path: https://example.com/b.pdf\n        id: shared\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    msg = next(d for d in project.errors if "shared" in d.message)
    assert "already used by CMP-001" in msg.message
    assert msg.item_id == "CMP-002"


def test_invalid_citation_id_format_is_an_error(tmp_path):
    write_project_config(tmp_path, CITATION_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "cmp.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n"
        "  - id: CMP-001\n    title: A\n"
        "    datasheets:\n      - path: https://example.com/a.pdf\n        id: \"not a valid id!\"\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert any("not a valid citation id" in d.message for d in project.errors)
