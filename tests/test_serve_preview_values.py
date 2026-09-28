"""Thread workbench W3 (docs/design/thread-workbench.md, "values"): D1 inline
calc values, pane-only per §7.1. The published page already renders every
`{{name}}` prose reference as its evaluated value -- a bare <code> span with
the name destroyed. The served preview puts the name back beside the value
(name + owning block, from `item.calc_values` and `CalcLine.block`), and
each calc table gains a show-values toggle.

Everything here reads strings the build already formatted; nothing is
evaluated or re-evaluated. And like W1's probe, W2's squiggles and the
toolbar, the decoration is response-only: the generation on disk -- what a
publish would look like -- has none of it, byte for byte.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, snapshot_tree

from refdes import render
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Values test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
  note:
    prefix: NOTE
    fields:
      title: { type: text, required: true }
"""

NAMED_MD = """\
---
id: DEC-001
type: decision
board: board-a
title: Supply and losses
---

Prose cites {{V_in}} and {{V_in | mV}} and a bare code span `not-a-value`.

```calc id="supply"
V_in = 12 V
I_in = 0.5 A
```

```calc id="losses"
P_diss = V_in * I_in * 0.049
```

A dotted prose mention DEC-001.V_in is not prose syntax and stays untouched.
"""

UNNAMED_MD = """\
---
id: DEC-002
type: decision
board: board-a
title: One unnamed block
---

```calc
Q = 3 W
```

Cites {{Q}}.
"""

TABLE_ONLY_MD = """\
---
id: DEC-003
type: decision
board: board-a
title: A block nobody cites in prose
---

```calc id="lone"
R_load = 47 ohm
```

The table stands on its own; no `{{...}}` reference names it anywhere.
"""

PLAIN_MD = """\
---
id: NOTE-001
type: note
board: board-a
title: No calcs at all
---

Nothing computes here, so nothing is attributed.
"""


@pytest.fixture()
def served(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "named.md").write_text(NAMED_MD, encoding="utf-8")
    (items / "unnamed.md").write_text(UNNAMED_MD, encoding="utf-8")
    (items / "table-only.md").write_text(TABLE_ONLY_MD, encoding="utf-8")
    (items / "plain.md").write_text(PLAIN_MD, encoding="utf-8")
    app = EditorApp(str(tmp_path / "refdes-project.yaml"), poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


def _page_of(app, item_id: str) -> str:
    return app.state.snapshot.project.item_by_id(item_id).slug + ".html"


def _body(client, app, item_id: str) -> str:
    status, _h, body = client.page(f"/preview/{_page_of(app, item_id)}")
    assert status == 200
    return body.decode("utf-8")


# ------------------------------------------------------- D1 inline values


def test_an_inline_value_gains_its_name_and_block(served):
    app, client = served
    html = _body(client, app, "DEC-001")
    assert (
        '<code data-refdes-calc="V_in" title="V_in = 12 V (block: supply)">12 V</code>'
        in html
    )
    assert '<span class="refdes-calc-attr">V_in · supply</span>' in html


def test_an_unnamed_blocks_value_gains_only_its_name(served):
    app, client = served
    html = _body(client, app, "DEC-002")
    assert '<code data-refdes-calc="Q" title="Q = 3 W">3 W</code>' in html
    badge = re.search(r'<span class="refdes-calc-attr">([^<]*)</span>', html)
    assert badge is not None and badge.group(1) == "Q"


def test_a_unit_converted_reference_is_not_decorated(served):
    # `{{V_in | mV}}` renders the build's converted string, which is stored
    # nowhere; recomputing it would be re-evaluation, so the pane leaves it.
    app, client = served
    html = _body(client, app, "DEC-001")
    assert "<code>12000 mV</code>" in html


def test_an_authors_own_code_span_is_left_alone(served):
    app, client = served
    html = _body(client, app, "DEC-001")
    assert "<code>not-a-value</code>" in html


def test_a_dotted_prose_mention_stays_undecorated(served):
    # refdes-2's veto: dotted ITEM.NAME is not prose syntax; decorating it
    # would imply meaning the site does not have (§3.3).
    app, client = served
    html = _body(client, app, "DEC-001")
    assert "</a>.V_in is not prose syntax" in html
    # the only badges on this page are the one inline attribution
    assert html.count("refdes-calc-attr") == 1


def test_a_calc_table_nobody_cites_in_prose_gets_no_toggle(served):
    # The toggle controls the values the pane *adds*. With no inline
    # attribution on the page there is nothing for it to hide, so a table
    # alone gains no button -- the reading recorded in
    # in-prog-logs/wb-w3-values.md, pinned here.
    app, client = served
    html = _body(client, app, "DEC-003")
    assert '<table class="calc"' in html
    assert "refdes-values-toggle" not in html
    assert "refdes-calc-attr" not in html


def test_an_item_without_calc_values_gets_nothing(served):
    app, client = served
    html = _body(client, app, "NOTE-001")
    assert "refdes-calc-attr" not in html
    assert "refdes-values-toggle" not in html
    assert "data-refdes-calc" not in html


# ------------------------------------------------------ show-values toggle


def test_each_calc_table_carries_one_toggle(served):
    app, client = served
    assert _body(client, app, "DEC-001").count("refdes-values-toggle") == 2


def test_an_unnamed_table_gains_a_caption_carrying_the_toggle(served):
    app, client = served
    html = _body(client, app, "DEC-002")
    assert '<caption class="calc-caption refdes-only">' in html
    assert 'aria-pressed="true"' in html


# ------------------------------------------------- response-only boundary


def test_the_published_output_is_byte_identical(served):
    app, client = served
    before = snapshot_tree(app.preview.current)
    html = _body(client, app, "DEC-001")
    assert "refdes-calc-attr" in html  # the response really was decorated
    _ = _body(client, app, "DEC-002")
    after = snapshot_tree(app.preview.current)
    assert before == after  # serving changed not one byte on disk


def test_the_decoration_never_reaches_the_rendered_files(served):
    app, _client = served
    on_disk = ""
    for dirpath, _d, names in os.walk(app.preview.current):
        for n in names:
            if n.endswith(".html"):
                with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                    on_disk += fh.read()
    assert "refdes-calc-attr" not in on_disk
    assert "refdes-values-toggle" not in on_disk
    assert "data-refdes-calc" not in on_disk
    # the inline value is still the plain published form
    assert "<code>12 V</code>" in on_disk


def test_a_real_publish_of_the_same_project_shows_none_of_it(tmp_path, served):
    """§4's "Never touches `_site/`" checked at the publish boundary rather
    than the serve one: the same sources on disk, run through the build's own
    `render_site`, produce a site with none of the workbench's markers and
    the plain published form of the value. The decoration exists only in
    `serve/server.py::_decorate`, so this is structural, not luck."""
    app, client = served
    decorated = _body(client, app, "DEC-001")
    assert "refdes-calc-attr" in decorated and "refdes-values-toggle" in decorated

    out = render.render_site(_build_at(tmp_path))
    pages = 0
    for dirpath, _d, names in os.walk(out):
        for n in names:
            if not n.endswith(".html"):
                continue
            pages += 1
            with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                text = fh.read()
            for marker in (
                "refdes-calc-attr",
                "refdes-values-toggle",
                "data-refdes-calc",
                "refdes-serve-bar",
            ):
                assert marker not in text, f"{marker} leaked into {n}"
    assert pages > 1
    with open(os.path.join(out, "dec-001.html"), encoding="utf-8") as fh:
        published = fh.read()
    # the value is published, the attribution is not
    assert "<code>12 V</code>" in published
    assert "V_in" not in published.partition("<table")[0]
