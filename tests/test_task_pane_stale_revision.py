"""The pane's save revision must describe the bytes its rows were built from.

The interactive preview pane is assembled from two sources that can come
apart (the lead's browser probe on a writable serve, 2026-11): the task
ROWS come from the app's last completed build/load of the project (the
in-memory snapshot), while `data-refdes-revision` was `edit.file_revision`
of the tip's source file read at RESPONSE time -- the disk. An external
edit that changes a task (T-probe open -> dropped) between the snapshot
and the render produced a page pairing the NEW file's sha256 with the OLD
rows: the author sees (and drafts against) the old list, the save carries
the revision of bytes they never saw, and `continue_thread`'s revision
check passes -- the save silently succeeds against a change nobody was
shown, and the conflict panel's "the file has ..." column is stale.

The fix (docs, in-prog-logs/stale-pane-revision.md): the page's revision
is the per-file hash the SNAPSHOT recorded when the model behind the rows
was built (`serve.state.content_hashes`, the same sha256 spelling as
`file_revision`), so the revision labels exactly the bytes the rows were
folded from. A page built from old bytes names the old revision, and a
save against it is a 409 Conflict, never a silent apply. The poller
rebuilds the snapshot as usual, so after the rebuild the page names the
new revision again (that half is pinned in test_task_pane_tick_context.py
-- this file must not undo it).

Each test drives a real `EditorApp` on an ephemeral port with
`poll_interval=60`: the poller's first pass is a full minute away, so the
disk edit below lands while the served snapshot provably has not rebuilt.
"""

from __future__ import annotations

import hashlib
import os
import re

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import cli as cli_mod
from refdes.serve import edit as edit_mod
from refdes.serve.server import EditorApp

TIP_KEY_ATTR = "data-refdes-tip-key"
REVISION_ATTR = "data-refdes-revision"

# The one-tip thread of test_task_pane_tick_context.py: LOG-002 is the tip,
# items/log.yaml is the file every save against this thread compares.
ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model the copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
)

PANEL_TAG = re.compile(r'<div class="refdes-taskpane-panel"[^>]*>')
ATTR_PAIR = re.compile(r'([\w-]+)="([^"]*)"')
ROW_STATE = re.compile(
    r'data-refdes-task="([^"]+)" data-refdes-task-state="([^"]+)"'
)


def _serve_warm(tmp_path):
    """Write the project, warm it with one ordinary writable load (that is
    what mints every item's key), then serve it with a poll interval no
    test outlives: the served snapshot never rebuilds on its own."""
    write_project_config(
        tmp_path,
        "site: { title: Stale Revision, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_bytes(ONE_TIP.encode("utf-8"))
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


@pytest.fixture
def served(tmp_path):
    yield from _serve_warm(tmp_path)


def _panel_of(body: str) -> dict:
    (tag,) = PANEL_TAG.findall(body)
    return dict(ATTR_PAIR.findall(tag))


def _row_states(body: str) -> dict:
    return {task: state for task, state in ROW_STATE.findall(body)}


def _sha(path: str) -> str:
    """sha256 of the file's bytes, computed HERE: the definition
    `file_revision` documents, independent of any refdes helper."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _page(client, app) -> str:
    slug = app.state.snapshot.project.item_by_id("LOG-002").slug + ".html"
    status, _headers, body = client.page(f"/preview/{slug}")
    assert status == 200
    return body.decode("utf-8")


def _edit_task_state_on_disk(log_path: str) -> None:
    """An external author flips T-thermal-model open -> done on disk -- a
    change the pane SHOWS, made while the served snapshot does not rebuild
    (poll_interval=60). Written as bytes: no newline renormalisation."""
    with open(log_path, "rb") as fh:
        text = fh.read().decode("utf-8")
    edited = text.replace(
        "{id: T-thermal-model, text: Model the copper temperature., state: open}",
        "{id: T-thermal-model, text: Model the copper temperature., state: done}",
        1,
    )
    assert edited != text, "the fixture's task row moved: the edit proved nothing"
    with open(log_path, "wb") as fh:
        fh.write(edited.encode("utf-8"))


def test_a_disk_change_the_rows_never_saw_keeps_the_pages_old_revision(served):
    """The core pair: after an external edit changes a task's state on
    disk, the next page still pairs the OLD revision with the OLD rows --
    the revision labels the bytes the rows were folded from, not the disk.
    The page's revision then feeds the save: posting it must be a 409
    Conflict naming the disk's new sha256, never a silent 200 against
    bytes the author was never shown."""
    app, client = served
    log_path = os.path.join(app.state.snapshot.project.root, "items", "log.yaml")

    page0 = _page(client, app)
    rev0 = _panel_of(page0)[REVISION_ATTR]
    assert rev0 == _sha(log_path)  # the control, up front: fresh pair
    assert _row_states(page0)["T-thermal-model"] == "open"

    _edit_task_state_on_disk(log_path)
    moved = _sha(log_path)
    assert moved != rev0

    page1 = _page(client, app)
    panel1 = _panel_of(page1)
    assert panel1[REVISION_ATTR] == rev0, (
        "the page paired the NEW file revision with rows built from the "
        f"OLD bytes: {panel1[REVISION_ATTR]!r} vs {rev0!r}"
    )
    assert _row_states(page1)["T-thermal-model"] == "open"  # the rows are the snapshot's

    status, payload = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-thermal-model", "open"]], "expected_revision": panel1[REVISION_ATTR]},
    )
    assert status == 409, f"the save applied against bytes the page never showed: {payload}"
    assert payload["kind"] == "conflict"
    assert payload["expected_revision"] == rev0
    assert payload["current_revision"] == moved
    with open(log_path, "rb") as fh:
        assert b"id: LOG-003" not in fh.read()  # nothing was written


def test_with_no_disk_change_the_page_names_the_disk_revision_and_saves(served):
    """The control: with no external edit the snapshot's per-file hash IS
    the disk hash -- the page names `file_revision` of the tip's file
    exactly, and a save drafted from it applies (200). The fix must not
    turn a fresh pane preview-only."""
    app, client = served
    log_path = os.path.join(app.state.snapshot.project.root, "items", "log.yaml")

    page = _page(client, app)
    rev = _panel_of(page)[REVISION_ATTR]
    assert rev == _sha(log_path) == edit_mod.file_revision(log_path)

    status, payload = client.api_post(
        "/api/item/LOG-002/continue",
        {"ticks": [["T-thermal-model", "done"]], "expected_revision": rev},
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    with open(log_path, "rb") as fh:
        assert b"id: LOG-003" in fh.read()
