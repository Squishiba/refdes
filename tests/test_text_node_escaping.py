"""Text-node XSS regression (backlog finding 31).

The two existing escaping tests pin the attribute-context breakout
(`test_citation_page_value_is_html_escaped`) and the preview-data JSON payload
(`test_preview_data_escapes_script_close`). Nothing exercised the plain text
node — `{{ item.title }}` in `index.html.j2` and `coverage.html.j2` — where a
future `| safe` addition would silently reopen an escaping hole with no
failing test to catch it. This module renders an evil-titled item into both
pages and asserts the escaped entity form is present and the raw `<script>`
is not.
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_and_render

EVIL_TITLE = "T<script>alert(1)</script>"

# A coverable requirement type carrying a real `title` field, so one item
# lands on both sinks: the index by_type table (index.html.j2:54,81) and the
# coverage table (coverage.html.j2:48).
TEXT_NODE_SCHEMA = """\
site: {title: "Text-node escaping", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      title: { type: text, required: true }
    links: {}
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""


def _evil_project(tmp_path):
    write_project_config(tmp_path, TEXT_NODE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-001.md").write_text(
        "---\n"
        "id: REQ-001\n"
        "type: requirement\n"
        f"title: '{EVIL_TITLE}'\n"
        "---\n",
        encoding="utf-8",
    )
    return tmp_path


def _assert_title_escaped(out, page):
    html = open(os.path.join(out, page), encoding="utf-8").read()
    # Autoescaping turns `{{ item.title }}` into the entity form...
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # ...and the raw tag never reaches the page anywhere.
    assert "<script>alert(1)</script>" not in html


def test_evil_title_is_escaped_on_index_page(tmp_path):
    out = _build_and_render(_evil_project(tmp_path))
    _assert_title_escaped(out, "index.html")


def test_evil_title_is_escaped_on_coverage_page(tmp_path):
    out = _build_and_render(_evil_project(tmp_path))
    _assert_title_escaped(out, "coverage.html")
