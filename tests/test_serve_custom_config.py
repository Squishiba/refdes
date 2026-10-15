"""EDITOR-API-003: the editor honors a custom project-config path.

A server launched as `refdes -c custom-project.yaml serve` reads through the
configured file (the CLI passes `args.config` to `EditorApp`, and
`ProjectState._build` loads it), so GETs answered 200 while POST edit and
POST create rebuilt `os.path.join(root, 'refdes-project.yaml')` inside
`serve/edit.py` and 422-refused with `the project did not load:
FileNotFoundError` on every write. These tests pin the write routes to the
launch's own settings file, keep the default-marker project working
unchanged as the control, and pin the watcher on the same configured path so
the post-save revalidation and the poller's reload watch the bytes the model
is actually built from (docs/design/browser-editor.md, "Revision and
conflict detection").
"""

from __future__ import annotations

import hashlib
import os

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Custom config test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, approved] }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""

REQS = """\
# a comment that must survive every save
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.
    status: approved
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001]
"""


def make_root(tmp_path, *, settings_name: str):
    """The fixture project, its settings file written under `settings_name`.

    The custom case is the plain one a user reaches: the file the CLI accepts
    via `-c`, named something other than the marker, beside the unchanged
    `refdes-schema.yaml` overlay that `_load_schema_overlay` resolves by its
    fixed name.
    """
    write_project_config(tmp_path, SCHEMA)
    default = tmp_path / "refdes-project.yaml"
    if settings_name != "refdes-project.yaml":
        os.rename(default, tmp_path / settings_name)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "reqs.yaml").write_text(REQS, encoding="utf-8", newline="\n")
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    return tmp_path


def start(root, settings_name: str, **kw):
    app = EditorApp(str(root / settings_name), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture(params=["refdes-project.yaml", "custom-project.yaml"])
def served(tmp_path, request):
    """The same conversation on both spellings of the project's settings
    file: the default marker (the control -- this worked before the fix and
    must keep working) and a custom `-c` path (the finding)."""
    settings_name = request.param
    root = make_root(tmp_path, settings_name=settings_name)
    app = start(root, settings_name)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def reqs_file(root) -> str:
    return str(root / "items" / "reqs.yaml")


def set_field(client, root, *, ref="REQ-001", **fields):
    payload = {"op": "set_field", "expected_revision": sha256(reqs_file(root)), **fields}
    return client.api_post(f"/api/item/{ref}/edit", payload)


# ------------------------------------------------------------------- edit


def test_edit_applies_under_a_custom_config_path(served):
    _app, client, root = served
    status, payload = set_field(client, root, field="status", value="draft")
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert payload["path"] == "items/reqs.yaml"
    with open(reqs_file(root), encoding="utf-8") as fh:
        text = fh.read()
    assert "status: draft" in text
    assert text.startswith("# a comment that must survive every save")
    assert payload["revision"] == sha256(reqs_file(root))


def test_edit_revalidates_cleanly_after_a_custom_config_save(served):
    """The post-save refresh is the design's full rebuild; on a custom path
    it must find the config it is watching, not a missing default marker."""
    _app, client, root = served
    status, payload = set_field(client, root, field="status", value="draft")
    assert status == 200, payload
    status, rev = client.api_get("/api/revision")
    assert status == 200
    assert rev["load_error"] is None
    assert rev["stale"] is False
    assert rev["revision"]  # the revision covers the saved bytes


# ----------------------------------------------------------------- create


def test_create_applies_under_a_custom_config_path(served):
    _app, client, root = served
    status, payload = client.api_post(
        "/api/items/create",
        {"type": "decision", "fields": {"title": "Move to a linear regulator."}},
    )
    assert status == 200, payload
    assert payload["kind"] == "created"
    assert payload["id"] == "DEC-002"
    assert payload["path"] == "items/decs.yaml"
    with open(root / "items" / "decs.yaml", encoding="utf-8") as fh:
        assert "title: Move to a linear regulator." in fh.read()


def test_create_id_sequence_continues_after_a_custom_config_create(served):
    """The id the create reserved came from the project loaded through the
    configured file, so the next preview plans against the same state."""
    _app, client, _root = served
    status, payload = client.api_post(
        "/api/items/create",
        {"type": "decision", "fields": {"title": "First."}},
    )
    assert status == 200, payload
    status, preview = client.api_get("/api/create/preview?type=decision")
    assert status == 200
    assert preview["id"] == "DEC-003"


# ------------------------------------------------- the watcher on the config


def test_poller_watches_the_config_the_server_loaded(tmp_path):
    """A semantic edit to the *configured* settings file is a project change:
    the poller's refresh rebuilds, and `/api/create/schema` answers from the
    new model. Watching the conventional name of a project that lives at a
    custom path watches a file that does not exist, and this edit moves no
    revision at all."""
    settings_name = "custom-project.yaml"
    root = make_root(tmp_path, settings_name=settings_name)
    app = start(root, settings_name)
    try:
        client = Client(app)
        status, before = client.api_get("/api/create/schema")
        assert status == 200
        assert "board-c" not in before["boards"]
        with open(root / settings_name, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace(
            '  board-a:\n    label: "Board A"\n',
            '  board-a:\n    label: "Board A"\n  board-c:\n    label: "Board C"\n',
        )
        with open(root / settings_name, "w", encoding="utf-8") as fh:
            fh.write(text)
        assert app.state.refresh() is True
        status, after = client.api_get("/api/create/schema")
        assert status == 200
        assert "board-c" in after["boards"]
        status, rev = client.api_get("/api/revision")
        assert rev["load_error"] is None
        assert rev["stale"] is False
    finally:
        app.stop()


def test_default_config_watcher_control(tmp_path):
    """The same watcher assertion on the default marker name, so the fix
    cannot pass by swapping one hardcoded name for the other."""
    root = make_root(tmp_path, settings_name="refdes-project.yaml")
    app = start(root, "refdes-project.yaml")
    try:
        client = Client(app)
        _status, before = client.api_get("/api/create/schema")
        assert "board-c" not in before["boards"]
        with open(root / "refdes-project.yaml", encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace(
            '  board-a:\n    label: "Board A"\n',
            '  board-a:\n    label: "Board A"\n  board-c:\n    label: "Board C"\n',
        )
        with open(root / "refdes-project.yaml", "w", encoding="utf-8") as fh:
            fh.write(text)
        assert app.state.refresh() is True
        _status, after = client.api_get("/api/create/schema")
        assert "board-c" in after["boards"]
    finally:
        app.stop()
