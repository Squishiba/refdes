"""Thread workbench W1 (docs/design/thread-workbench.md, "pin"): the preview
page reloads itself when the project rebuilds.

No browser here, so this pins the two halves the browser wires together:
the served page carries the probe (token meta, serial meta, module script),
and the serial it names tracks the rebuild -- it equals the live
`/api/revision` serial at request time and moves when an external edit is
polled and rebuilt, which is exactly the condition `preview.js` reloads on.
The decoration boundary is pinned too: like the toolbar, the probe exists
only in the HTTP response, never in the rendered generation on disk.
"""

from __future__ import annotations

import os
import re
import time

import pytest
from serve_support import Client, make_project

from refdes.serve.server import EditorApp

SERIAL_META = re.compile(r'name="refdes-serial" content="(\d+)"')


@pytest.fixture()
def served(tmp_path):
    config = make_project(tmp_path)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def _page_of(app, item_id: str) -> str:
    return app.state.snapshot.project.item_by_id(item_id).slug + ".html"


def test_preview_responses_carry_the_reload_probe(served):
    app, client, _root = served
    status, _h, body = client.page(f"/preview/{_page_of(app, 'REQ-001')}")
    assert status == 200
    html = body.decode("utf-8")
    assert 'name="refdes-serial"' in html
    assert 'name="refdes-token"' in html
    assert "/edit/static/preview.js" in html


def test_the_probe_never_reaches_the_rendered_files(served):
    app, _client, _root = served
    on_disk = ""
    for dirpath, _d, names in os.walk(app.preview.current):
        for n in names:
            if n.endswith(".html"):
                with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                    on_disk += fh.read()
    assert "refdes-serial" not in on_disk
    assert "preview.js" not in on_disk


def test_the_injected_serial_is_the_live_revision_serial(served):
    app, client, _root = served
    _status, info = client.api_get("/api/revision")
    _s, _h, body = client.page(f"/preview/{_page_of(app, 'REQ-001')}")
    m = SERIAL_META.search(body.decode("utf-8"))
    assert m is not None
    assert int(m.group(1)) == info["serial"]


def test_an_external_edit_moves_the_serial_the_probe_watches(served):
    app, client, root = served
    page = _page_of(app, "REQ-001")
    _s, _h, before = client.page(f"/preview/{page}")
    serial_before = int(SERIAL_META.search(before.decode("utf-8")).group(1))

    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace("3.3 V", "5.0 V"), encoding="utf-8"
    )

    deadline = time.time() + 10
    while time.time() < deadline:
        _s, info = client.api_get("/api/revision")
        if info["serial"] > serial_before:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the poller never rebuilt after the external edit")

    # The next request is served from the new generation with a newer serial
    # injected -- the exact mismatch preview.js reloads on.
    _s, _h, after = client.page(f"/preview/{page}")
    serial_after = int(SERIAL_META.search(after.decode("utf-8")).group(1))
    assert serial_after > serial_before
    assert "5.0 V" in after.decode("utf-8")
