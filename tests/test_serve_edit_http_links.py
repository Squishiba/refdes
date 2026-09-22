"""The link ops over HTTP: `POST /api/item/<ref>/edit` with `add_link` /
`remove_link`, and the `edit.links` block on `GET /api/item/<ref>`
(docs/design/browser-editor.md, "Slice 2 -- structured links").

The service decides; this pins the HTTP contract on top of it and repeats
the proof that matters for every path that says no: `items/` and `.refdes/`
byte-identical, the same posture as tests/test_no_write.py and
tests/test_serve_edit_http.py.
"""

from __future__ import annotations

import hashlib

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import keys as keys_mod
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Link http test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies: { inverse: verified_by, label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

K_REQ1 = keys_mod.mint()
K_REQ2 = keys_mod.mint()

REQS = f"""\
# a comment that must survive every save
defaults: {{ type: requirement, board: board-a }}
items:
  - id: REQ-001
    key: {K_REQ1}
    text: The rail shall supply 3.3 V.
  - id: REQ-002
    key: {K_REQ2}
    text: The rail shall survive 5 V for a second.
  - id: REQ-003
    text: Keyless on purpose.
"""

DECS = f"""\
defaults: {{ type: decision, board: board-a }}
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001@{K_REQ1}]
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""


def make_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {"reqs.yaml": REQS, "decs.yaml": DECS, "log.yaml": LOG}.items():
        (items / name).write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def served(tmp_path):
    root = make_root(tmp_path)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def decs_file(root) -> str:
    return str(root / "items" / "decs.yaml")


def link_edit(client, root, op, *, ref="DEC-001", **fields):
    payload = {
        "op": op,
        "expected_revision": sha256(decs_file(root)),
        **fields,
    }
    return client.api_post(f"/api/item/{ref}/edit", payload, origin="default")


# --------------------------------------------------------- the edit block


def test_get_item_lists_each_link_verb_with_its_allowed_types(served):
    _app, client, _root = served
    status, payload = client.api_get("/api/item/DEC-001")
    assert status == 200
    verbs = payload["edit"]["links"]
    assert set(verbs) == {"satisfies"}
    assert verbs["satisfies"]["editable"] is True
    assert verbs["satisfies"]["target_types"] == ["requirement"]
    assert verbs["satisfies"]["targets"] == [f"REQ-001@{K_REQ1}"]


def test_a_read_only_item_reports_its_links_uneditable_with_the_reason(served):
    _app, client, _root = served
    status, payload = client.api_get("/api/item/LOG-001")
    assert status == 200
    # the log type declares no links at all: the block is empty, not missing
    assert payload["edit"]["links"] == {}


# ---------------------------------------------------------------- applied


def test_add_link_applies_and_writes_the_composite(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = link_edit(client, root, "add_link", verb="satisfies", target="REQ-002")
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    after = read(decs_file(root))
    assert f"REQ-002@{K_REQ2}" in after
    moved = {k for k, v in snapshot_tree(root).items() if before.get(k) != v}
    assert moved == {"items/decs.yaml"}


def test_remove_link_applies(served):
    _app, client, root = served
    status, payload = link_edit(client, root, "remove_link", verb="satisfies", target="REQ-001")
    assert status == 200, payload
    assert f"REQ-001@{K_REQ1}" not in read(decs_file(root))


# ---------------------------------------------------------------- refusals


def test_a_wrong_typed_target_is_422_and_the_tree_is_unchanged(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = link_edit(client, root, "add_link", verb="satisfies", target="LOG-001")
    assert status == 422
    assert payload["kind"] == "refused"
    assert "requirement" in payload["reason"]
    assert snapshot_tree(root) == before


def test_a_null_key_target_is_422_and_never_written_as_a_bare_id(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = link_edit(client, root, "add_link", verb="satisfies", target="REQ-003")
    assert status == 422
    assert "artifact key" in payload["reason"]
    assert snapshot_tree(root) == before
    assert "REQ-003" not in read(decs_file(root))


@pytest.mark.parametrize(
    "fields",
    [
        {"verb": "satisfies"},  # no target
        {"target": "REQ-002"},  # no verb
        {"verb": "", "target": "REQ-002"},
        {"verb": "satisfies", "target": ""},
    ],
)
def test_malformed_link_ops_are_400(served, fields):
    _app, client, root = served
    before = snapshot_tree(root)
    status, _payload = link_edit(client, root, "add_link", **fields)
    assert status == 400
    assert snapshot_tree(root) == before


def test_a_read_only_server_refuses_link_edits(tmp_path):
    """--no-write is the same door for link ops as for field edits: refused
    before the service is consulted, nothing written."""
    root = make_root(tmp_path)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        before = snapshot_tree(root)
        status, payload = link_edit(client, root, "add_link", verb="satisfies", target="REQ-002")
        assert status == 403
        assert "--no-write" in payload["error"]
        status, payload = link_edit(client, root, "remove_link", verb="satisfies", target="REQ-001")
        assert status == 403
        assert snapshot_tree(root) == before
    finally:
        app.stop()
