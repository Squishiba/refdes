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

import re

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes import threads
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
    "      - not even a mapping\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
    "  - id: LOG-003\n"
    "    summary: Fork head.\n"
    "    date: 2026-09-03\n"
    "  - id: LOG-004\n"
    "    summary: Left branch.\n"
    "    date: 2026-09-04\n"
    "    follows: LOG-003\n"
    "    tasks: [{id: T-left, text: Left branch task., state: open}]\n"
    "  - id: LOG-005\n"
    "    summary: Right branch.\n"
    "    date: 2026-09-05\n"
    "    follows: LOG-003\n"
    "    tasks: [{id: T-right, text: Right branch task., state: open}]\n"
    "  - id: LOG-006\n"
    "    type: log\n"
    "    summary: A lone entry with no thread.\n"
    "    date: 2026-09-06\n"
)


def _write_project(tmp_path) -> str:
    """The served project, on disk, unloaded: threaded log + a fork + a
    malformed row. Returns the config path. Split out of the fixture so the
    "changes nothing on disk" test can snapshot BEFORE the app starts
    (PR #197 review C4)."""
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(LOG_FILE, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    # A warm check: it mints keys, freezes the bare `follows:` edges -- and
    # reports the malformed task row, which is exactly the point: serve
    # shows the pane next to a project that has an error.
    cli_mod.main(["-c", config, "check"])
    # The writable path freezes a bare `follows:` to the target's CURRENT
    # tip, so the two siblings froze into a chain. The spelled-out frozen
    # edge is how an author asks for a branch (tests/test_thread_cli.py
    # ::_fork_from_bare), so LOG-005's edge is rewritten to name LOG-003's
    # key -- and the freeze leaves a composite edge alone on every later
    # load.
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    (head_key,) = re.findall(r"- key: (\S+)\n    id: LOG-003", text)
    blocks = re.split(r"(?=  - key: )", text)
    text = "".join(
        re.sub(r"follows: LOG-\d+@\S+", f"follows: LOG-003@{head_key}", block)
        if re.match(r"  - key: \S+\n    id: LOG-005", block)
        else block
        for block in blocks
    )
    path.write_text(text, encoding="utf-8")
    return config


@pytest.fixture()
def served(tmp_path):
    config = _write_project(tmp_path)
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
    # B3 (PR #197 review round 2): the expectation is the shared composer's
    # output for the served project's own verdict, not a re-typed literal.
    view = next(
        view
        for view in threads.threads_projection(app.state.snapshot.project)
        if "LOG-001" in view["entries"]
    )
    branch = view["branches"][0]
    open_count = sum(
        1 for row in branch["tasks"]["rows"] if row["state"] == "open"
    )
    line = threads.verdict_line(branch["verdict"], open_count)
    assert line in html
    assert line.startswith("Verdict: accepted (")


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


def test_serving_the_pane_changes_nothing_on_disk(tmp_path):
    """The pane is read-only in the strongest sense: starting the server and
    serving pane pages never writes into the project. (The generation the
    preview renders into is not project content either — snapshot covers the
    project root.)

    C4 (PR #197 review round 2): the snapshot is taken BEFORE `app.start()`
    -- the old version snapshotted inside the already-started fixture, so a
    write during startup would have been invisible. Dedicated test (it needs
    the app's whole lifetime) built on the fixture's own setup helper."""
    config = _write_project(tmp_path)
    before = snapshot_tree(tmp_path)
    app = EditorApp(config, poll_interval=0.05)
    app.start()
    try:
        client = Client(app)
        _body(client, app, "LOG-001")
        _body(client, app, "LOG-006")
        client.page("/preview/assets/taskpane.js")
        client.page("/preview/assets/taskpane.css")
        assert snapshot_tree(tmp_path) == before
    finally:
        app.stop()
    assert snapshot_tree(tmp_path) == before  # and stopping wrote nothing either


def test_the_preview_page_has_no_write_control_or_token(served):
    """Read-only half of §7: the served pane page carries no token, no
    API path and no form — the editor chrome that does carry them lives
    on the editor surface, not in the preview. (T1, PR #197 review: pin
    the marker first, so an absent pane can never pass this vacuously.)"""
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    start = html.find('<aside class="refdes-taskpane"')
    assert start != -1, "the preview page must carry the pane at all"
    pane = html[start:]
    end = pane.find("</aside>")
    assert end != -1
    pane = pane[:end]
    # Round-5 nit: the scan is case-insensitive -- HTML and JS carry no
    # reason for a write control's spelling to arrive lowercase.
    pane = pane.lower()
    assert "<input" not in pane
    for needle in ("x-refdes-token", "token", "/api/", "<form", "fetch("):
        assert needle not in pane


# ------------------ PR #197 review T3: forks and malformed rows in preview


def test_the_preview_renders_malformed_rows_as_count_plus_valid_row(served):
    """B1 through the serve template path: the count rides the heading and
    the valid row still prints."""
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    assert (
        f"{threads.task_heading('', single_tip=True)} "
        f"{threads.task_malformed_note(1)}"
    ) in html
    assert "T-thermal-model" in html
    assert "Model worst-case copper temperature." in html


def test_the_preview_renders_fork_tabs_never_unioned(served):
    """B1's sibling through the serve template path (review T3): a fork
    gets one tab per tip, each panel carrying only its own list."""
    app, client, _tmp = served
    html = _body(client, app, "LOG-003")
    assert ">LOG-004</button>" in html and ">LOG-005</button>" in html
    assert "Tasks at LOG-004:" in html and "Tasks at LOG-005:" in html
    first = html[html.find('data-refdes-panel="1"') :]
    first = first[: first.find('data-refdes-panel="2"')]
    second = html[html.find('data-refdes-panel="2"') :]
    derived_at = second.find("<details")
    if derived_at != -1:  # this fixture's second tip carries no derived block
        second = second[:derived_at]
    # exactly one task per panel, each panel a different one -- a union
    # would put both in both
    assert ("T-left" in first) != ("T-right" in first)
    assert ("T-left" in second) != ("T-right" in second)
    assert ("T-left" in first) != ("T-left" in second)


# ----------------- PR #197 review B2: the pane clears the serve toolbar


def test_the_preview_offsets_the_toggle_above_the_bar(served):
    """Both halves of the collision fix on the served page: the bar's
    stylesheet loads after `taskpane.css` (so its later rules win), and
    the bar's own CSS carries the pane offsets -- response-only, the
    published site never sees it."""
    app, client, _tmp = served
    html = _body(client, app, "LOG-001")
    assert "refdes-serve-bar" in html  # the bar is on this page
    # C4 (PR #197 review round 2): presence FIRST -- `find` returns -1 for a
    # missing needle, so `find(a) < find(b)` once passed vacuously on a page
    # carrying neither stylesheet (or only the bar's).
    assert 'href="assets/taskpane.css"' in html
    assert "/edit/static/bar.css" in html
    assert html.find("assets/taskpane.css") < html.find("/edit/static/bar.css")
    status, _h, css = client.page("/edit/static/bar.css")
    assert status == 200
    text = css.decode("utf-8")
    # The pane's offsets, read back OUT OF bar.css (C4: the old assertion
    # was `12 + (6 + 13 * 1.4 + 6) < 50 < 87` -- pure literals that can
    # never fail. Every number below comes from the fetched file.)
    # Round-5 nit: `\s` matches newlines too, so a rule re-wrapped over
    # several lines is still read (the old single-line patterns would
    # silently report "no offsets" on a reformatted bar.css).
    toggle = re.search(r"\.refdes-taskpane-toggle \{\s*bottom: (\d+)px;\s*\}", text)
    panel = re.search(r"\.refdes-taskpane \{\s*bottom: (\d+)px;\s*\}", text)
    assert toggle and panel, "bar.css carries no task-pane offsets at all"
    toggle_at, panel_at = int(toggle.group(1)), int(panel.group(1))
    bar = re.search(r"\.refdes-serve-bar \{[^}]*\}", text)
    assert bar, "bar.css carries no .refdes-serve-bar rule"
    bar = bar.group(0)
    bottom = re.search(r"bottom: (\d+)px", bar)
    pad_v = re.search(r"padding: (\d+)px", bar)
    font = re.search(r"font: (\d+)px/([\d.]+)", bar)
    assert bottom and pad_v and font, f"bar.css rule lost its metrics: {bar!r}"
    font_px, leading = font.groups()
    bottom, pad_v = int(bottom.group(1)), int(pad_v.group(1))
    # The bar's own top edge, above the viewport bottom: its bottom offset
    # plus its height (vertical padding x2 over the font's line box).
    bar_top = bottom + 2 * pad_v + int(font_px) * float(leading)
    assert bar_top < toggle_at, "the toggle must clear the bar's top edge"
    assert toggle_at < panel_at, "the panel must sit above the toggle"
