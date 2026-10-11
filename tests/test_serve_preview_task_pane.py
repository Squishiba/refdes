"""Thread workbench W5a, served half: the task pane in the `refdes serve`
preview (docs/design/thread-workbench.md §7a, "the same pane" sub-decision
6: preview and site show the same thing, so it is rendered in the shared
item template rather than as a W1–W3 style response-only decoration).

Because the pane lives in the template, what the preview serves is the
published page — pane and all — and these tests read that served HTML for
the projection's lines and prove the pane's own assets ride along, while
the project on disk stays untouched: W5a adds no write path (§7's read-only
boundary) and touches no API.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes.serve.server import EditorApp

CONFIG = (
    "site: { title: Pane preview, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

LOG_FILE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "  - id: LOG-006\n"
    "    type: log\n"
    "    summary: A lone entry with no thread.\n"
    "    date: 2026-09-06\n"
)


@pytest.fixture()
def served(tmp_path):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(LOG_FILE, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    cli_mod.main(["-c", config, "check"])  # mint keys, as a real project starts
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def _page_of(app, item_id: str) -> str:
    return app.state.snapshot.project.item_by_id(item_id).slug + ".html"


def _body(client, app, item_id: str) -> str:
    status, _h, body = client.page(f"/preview/{_page_of(app, item_id)}")
    assert status == 200
    return body.decode("utf-8")


def test_the_preview_serves_the_pane_with_the_projection_lines(served):
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    assert 'data-refdes-taskpane="LOG-001"' in html
    assert "viewing LOG-001 · tasks as of tip LOG-002" in html
    assert (
        "Verdict: accepted (LOG-002, 2026-09-02), 1 open task remaining below"
        in html
    )


def test_the_pane_assets_ride_along_in_the_preview(served):
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    assert 'href="assets/taskpane.css"' in html
    assert '<script src="assets/taskpane.js" defer></script>' in html
    for asset in ("taskpane.css", "taskpane.js"):
        status, _h, body = client.page(f"/preview/assets/{asset}")
        assert status == 200, asset
        assert b"refdes-taskpane" in body, asset


def test_a_non_threaded_preview_page_carries_no_pane(served):
    app, client, _tmp = served
    html = _body(client, app, "LOG-006")
    assert "refdes-taskpane" not in html


def test_serving_the_pane_changes_nothing_on_disk(served):
    """The pane is read-only in the strongest sense: serving it never
    writes into the project. (The generation the preview renders into is
    not project content either — snapshot covers the project root.)"""
    app, client, tmp = served
    before = snapshot_tree(tmp)
    _body(client, app, "LOG-001")
    _body(client, app, "LOG-006")
    client.page("/preview/assets/taskpane.js")
    client.page("/preview/assets/taskpane.css")
    assert snapshot_tree(tmp) == before


def test_the_preview_page_has_no_write_control_or_token(served):
    """Read-only half of §7: the served pane page carries no token, no
    API path and no form — the editor chrome that does carry them lives
    on the editor surface, not in the preview."""
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    pane = html[html.find('<aside class="refdes-taskpane"') :]
    pane = pane[: pane.find("</aside>")]
    assert "<input" not in pane
    for needle in ("X-Refdes-Token", "token", "/api/", "<form", "fetch("):
        assert needle not in pane
