"""Thread workbench W2 (docs/design/thread-workbench.md, "squiggles"): the
preview response carries the build's own author-time signals for the item on
the page -- D3, its own diagnostics in the index page's house markup, and D2,
image provenance (resolved source + content hash on hover) or a visible
marker where the build said the image did not resolve.

Everything here reads data the build already produced; nothing re-resolves.
And like W1's probe and the toolbar, the decoration is response-only: the
generation on disk -- what a publish would look like -- has none of it.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Decoration test"
  assets: [figures-a, figures-b]
id:
  width: 3
boards:
  board-a:
    label: "Board A"
types:
  note:
    prefix: NOTE
    fields:
      title: { type: text, required: true }
"""

NOTES_MD = """\
---
id: NOTE-001
type: note
board: board-a
title: Two good images and two bad ones
---

![Rail](good.png)

![Rail again](good2.png)

![Gone](missing.png)

![Two](two.png)
"""

OTHER_MD = """\
---
id: NOTE-002
type: note
board: board-a
title: A different item with its own broken image
---

![Nope](other-missing.png)
"""

PNG = b"\x89PNG\r\n\x1a\n"

PROVENANCE = re.compile(r'data-refdes-src="([^"]+)" title="([^"]+)"')


@pytest.fixture()
def served(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "notes.md").write_text(NOTES_MD, encoding="utf-8")
    (items / "other.md").write_text(OTHER_MD, encoding="utf-8")
    for d in ("figures-a", "figures-b"):
        (tmp_path / d).mkdir()
    # good.png resolves from one directory; two.png is ambiguous between the
    # two; missing.png and other-missing.png exist nowhere.
    (tmp_path / "figures-a" / "good.png").write_bytes(PNG)
    (tmp_path / "figures-a" / "two.png").write_bytes(PNG)
    # resolves relative to items/notes.md itself, so the build content-hashes
    # it (only `site.assets:` bulk-copy files stay identity-mapped unhashed)
    (items / "good2.png").write_bytes(PNG + b"second")
    (tmp_path / "figures-b" / "two.png").write_bytes(b"\x89PNG\r\n\x1a\nother")
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


# ------------------------------------------------------------------ D3


def test_the_item_page_shows_its_own_diagnostics(served):
    app, client = served
    html = _body(client, app, "NOTE-001")
    assert "refdes-diags" in html
    assert "Diagnostics for this item" in html
    # the missing-image error and the ambiguity error, in the index page's
    # house shape: level — file:line [id]: message
    assert "error — items/notes.md" in html
    assert "missing.png" in html
    assert "ambiguous" in html
    assert "NOTE-001" in html


def test_another_items_diagnostic_stays_off_this_page(served):
    app, client = served
    assert "other-missing.png" not in _body(client, app, "NOTE-001")
    # NOTE-002's page carries its own diagnostic, not NOTE-001's ambiguity.
    html2 = _body(client, app, "NOTE-002")
    assert "other-missing.png" in html2
    assert "ambiguous" not in html2


def test_non_item_pages_get_no_diagnostics_panel(served):
    app, client = served
    status, _h, body = client.page("/preview/index.html")
    assert status == 200
    assert "refdes-diags" not in body.decode("utf-8")


# ------------------------------------------------------------------ D2


def test_a_resolved_image_carries_provenance(served):
    app, client = served
    html = _body(client, app, "NOTE-001")
    provenance = dict(PROVENANCE.findall(html))
    assert provenance["items/good2.png"].startswith("items/good2.png · ")
    # the hash shown is the one the build computed for the copied asset
    digest = provenance["items/good2.png"].split(" · ")[1]
    assert re.fullmatch(r"[0-9a-f]{16}", digest)
    assert f'src="assets/items/good2.{digest}.png"' in html
    # a `site.assets:` file the build identity-maps has no content hash --
    # the decoration shows what the build knows, not more
    assert provenance["figures-a/good.png"] == "figures-a/good.png"


def test_unresolved_images_get_an_inline_marker(served):
    app, client = served
    html = _body(client, app, "NOTE-001")
    assert html.count("refdes-squiggle") == 2
    assert "'missing.png' did not resolve" in html
    assert "'two.png' did not resolve" in html


def test_only_this_items_resolutions_are_decorated(served):
    app, client = served
    html = _body(client, app, "NOTE-001")
    assert html.count("data-refdes-src") == 2
    assert "data-refdes-src" not in _body(client, app, "NOTE-002")


# ------------------------------------------------- response-only boundary


def test_the_decoration_never_reaches_the_rendered_files(served):
    app, _client = served
    on_disk = ""
    for dirpath, _d, names in os.walk(app.preview.current):
        for n in names:
            if n.endswith(".html"):
                with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                    on_disk += fh.read()
    assert "refdes-diags" not in on_disk
    assert "data-refdes-src" not in on_disk
    assert "refdes-squiggle" not in on_disk
    # the resolved image is still the plain rewritten published form
    assert 'src="assets/figures-a/good.' in on_disk
