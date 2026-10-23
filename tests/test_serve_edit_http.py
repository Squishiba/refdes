"""The editor's write route: `POST /api/item/<ref>/edit` and the editability
flags on `GET /api/item/<ref>` (docs/design/browser-editor.md, "Editing
fields", "Validation, conflicts, and transactions").

The service (`serve/edit.py`) owns the decision; this module pins the HTTP
contract on top of it: who may post, what each of the four results costs in
status codes, and -- the proof that matters -- that every path which says no
leaves `items/` and `.refdes/` byte-identical, the same posture as
tests/test_no_write.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, make_project, snapshot_tree

from refdes import build as build_mod
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Edit http test"
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
      tags: { type: list }
      status: { type: enum, choices: [draft, approved] }
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

REQS = """\
# a comment that must survive every save
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.   # trailing comment
    tags: [power, rail]
    status: approved
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
    satisfies: [REQ-001]
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""

EDIT_PATH = "/api/item/REQ-001/edit"


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


def reqs_file(root) -> str:
    return str(root / "items" / "reqs.yaml")


def edit(client, *, ref="REQ-001", revision=None, root=None, op="set_field", origin="default", **fields):
    payload = {"op": op}
    if revision is not None:
        payload["expected_revision"] = revision
    elif root is not None:
        payload["expected_revision"] = sha256(reqs_file(root))
    payload.update(fields)
    return client.api_post(f"/api/item/{ref}/edit", payload, origin=origin)


# ---------------------------------------------------------------- the gate


def test_edit_requires_the_token_header(served):
    _app, client, root = served
    body = json.dumps({"op": "set_field", "field": "status", "value": "draft",
                       "expected_revision": sha256(reqs_file(root))}).encode()
    hdrs = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"}
    status, _h, _b = client.request("POST", EDIT_PATH, body=body, headers=hdrs)
    assert status == 403
    status, _h, _b = client.request(
        "POST", EDIT_PATH, body=body, headers=dict(hdrs, **{"X-Refdes-Token": "wrong"})
    )
    assert status == 403
    # the session cookie alone is not enough
    status, _h, _b = client.request("POST", EDIT_PATH, body=body, headers=hdrs, cookie=True)
    assert status == 403


def test_edit_rejects_a_foreign_host(served):
    _app, client, root = served
    status, _h, _b = client.request(
        "POST", EDIT_PATH, token=True, host="evil.example",
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"},
        body=b"{}",
    )
    assert status == 403


@pytest.mark.parametrize("origin", [None, "http://evil.example", "null"])
def test_edit_requires_a_matching_origin(served, origin):
    _app, client, root = served
    status, payload = edit(client, root=root, field="status", value="draft", origin=origin)
    assert status == 403


def test_edit_requires_json_content(served):
    _app, client, root = served
    status, _h, _b = client.request(
        "POST", EDIT_PATH, token=True,
        headers={
            "Content-Type": "text/plain",
            "Origin": f"http://127.0.0.1:{client.port}",
        },
        body=b"hello",
    )
    assert status == 415


def test_edit_bodies_are_size_bounded(served):
    """A declared body over the limit is refused before it is read: the request
    is written header-only on a raw socket, so a server that tried to read the
    body would hang the test rather than pass it."""
    _app, client, root = served
    conn = socket.create_connection(("127.0.0.1", client.port), timeout=10)
    try:
        request = (
            f"POST {EDIT_PATH} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{client.port}\r\n"
            f"X-Refdes-Token: {client.app.token}\r\n"
            f"Origin: http://127.0.0.1:{client.port}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 99999999\r\n"
            "\r\n"
        ).encode("ascii")
        conn.sendall(request)
        conn.settimeout(10)
        head = conn.recv(200)
    finally:
        conn.close()
    assert head.startswith(b"HTTP/1.0 413") or head.startswith(b"HTTP/1.1 413")


def test_edit_route_rejects_other_methods(served):
    _app, client, _root = served
    status, _h, _b = client.request(
        "GET", EDIT_PATH, token=True, headers={"Origin": f"http://127.0.0.1:{client.port}"}
    )
    assert status == 405
    status, _h, _b = client.request("PUT", EDIT_PATH, token=True, body=b"{}")
    assert status == 405


def test_a_read_only_server_refuses_edits(tmp_path):
    root = make_root(tmp_path)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        status, payload = edit(client, root=root, field="status", value="draft")
        assert status == 403
        assert "--no-write" in payload["error"]
    finally:
        app.stop()


# ------------------------------------------------------------- bad requests


@pytest.mark.parametrize(
    "payload",
    [
        {"op": "set_field", "field": "status", "value": "draft"},  # no expected_revision
        {"op": "spin", "field": "status", "value": "draft", "expected_revision": "x"},
        {"op": "set_field", "value": "draft", "expected_revision": "x"},  # no field
        {"op": "set_field", "field": "tags", "value": ["a"], "expected_revision": "x"},
        {"op": "set_body", "expected_revision": "x"},  # no text
        {"op": "set_body", "text": 7, "expected_revision": "x"},
    ],
)
def test_malformed_edit_requests_are_400(served, payload):
    _app, client, _root = served
    status, body = client.api_post(EDIT_PATH, payload)
    assert status == 400
    assert "error" in body


# --------------------------------------------------------------- applied


def test_a_saved_field_edit_changes_one_line_and_returns_a_usable_revision(served):
    _app, client, root = served
    path = reqs_file(root)
    before = read(path)
    before_tree = snapshot_tree(root)

    status, payload = edit(client, root=root, field="status", value="draft")

    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    assert payload["path"].endswith("items/reqs.yaml")
    assert not os.path.isabs(payload["path"])
    after = read(path)
    changed = [
        (b, a) for b, a in zip(before.splitlines(), after.splitlines()) if b != a
    ]
    assert changed == [("    status: approved", "    status: draft")]
    assert "# a comment that must survive every save" in after
    assert "# trailing comment" in after
    # only the one file moved
    after_tree = snapshot_tree(root)
    assert {k for k, v in after_tree.items() if before_tree.get(k) != v} == {"items/reqs.yaml"}
    # the returned revision is the file's new content hash, and the next edit accepts it
    assert payload["revision"] == sha256(path)
    status, second = edit(client, revision=payload["revision"], field="text",
                          value="The rail shall supply 5 V.")
    assert status == 200, second
    assert payload["revision"] != sha256(path)


def test_a_saved_edit_refreshes_the_model_and_the_preview(served):
    app, client, root = served
    _status, before = client.api_get("/api/item/REQ-001")
    assert before["fields"]["status"] == "approved"
    serial_before = client.api_get("/api/revision")[1]["serial"]
    with app.preview.open_file([before["page"]]) as fh:
        before_html = fh.read()
    assert b"approved" in before_html

    status, payload = edit(client, root=root, field="status", value="draft")
    assert status == 200

    _status, after = client.api_get("/api/item/REQ-001")
    assert after["fields"]["status"] == "draft"
    assert after["edit"]["file_revision"] == payload["revision"]
    # the snapshot was rebuilt, not merely re-read: its serial moved
    assert client.api_get("/api/revision")[1]["serial"] > serial_before
    # and the preview was rebuilt from the saved bytes: the same page path now
    # serves different content
    page = app.preview.open_file([before["page"]])
    assert page is not None
    with page:
        after_html = page.read()
    assert after_html != before_html
    assert b"draft" in after_html and b"approved" not in after_html


def test_a_saved_body_edit_replaces_the_body(served):
    _app, client, root = served
    path = reqs_file(root)
    status, payload = edit(
        client, root=root, op="set_body", text="Rewritten prose.\n", ref="REQ-001"
    )
    assert status == 200, payload
    assert "Rewritten prose." in read(path)


# --------------------------------------------------------------- conflict


def test_a_stale_revision_is_409_with_diff_and_changes_nothing(served):
    _app, client, root = served
    path = reqs_file(root)
    stale = sha256(path)
    # someone else moves the file first
    moved = read(path).replace("3.3 V", "5.0 V")
    with open(path, "wb") as fh:
        fh.write(moved.encode("utf-8"))
    before_tree = snapshot_tree(root)

    status, payload = edit(client, revision=stale, field="status", value="draft")

    assert status == 409, payload
    assert payload["kind"] == "conflict" and payload["ok"] is False
    assert payload["expected_revision"] == stale
    assert payload["current_revision"] == sha256(path)
    assert payload["current_text"] is not None
    assert "---" in payload["diff"] and "5.0 V" in payload["diff"]
    assert snapshot_tree(root) == before_tree


# ---------------------------------------------------------------- refused


def test_a_sealed_item_is_422_and_changes_nothing(tmp_path):
    root = make_root(tmp_path)
    project = _build_at(root)
    build_mod.build(project, seal_write=True)
    assert list((root / ".refdes").glob("log-seal*.yaml")), "the fixture did not seal"
    app = start(root)
    try:
        client = Client(app)
        path = str(root / "items" / "log.yaml")
        before_tree = snapshot_tree(root)
        status, payload = edit(
            client, ref="LOG-001", revision=sha256(path), field="summary", value="rewritten"
        )
        assert status == 422, payload
        assert payload["kind"] == "refused"
        assert "sealed" in payload["reason"]
        assert snapshot_tree(root) == before_tree
        # and the view says so without being asked
        _status, item = client.api_get("/api/item/LOG-001")
        assert item["edit"]["editable"] is False
        assert "sealed" in item["edit"]["reason"]
        assert all(f["editable"] is False for f in item["edit"]["fields"].values())
        assert item["edit"]["body"]["editable"] is False
    finally:
        app.stop()


def test_an_identity_field_is_422_and_changes_nothing(served):
    _app, client, root = served
    before_tree = snapshot_tree(root)
    status, payload = edit(client, root=root, field="id", value="REQ-999")
    assert status == 422
    assert payload["kind"] == "refused"
    assert snapshot_tree(root) == before_tree


def test_an_unknown_item_is_422_and_changes_nothing(served):
    _app, client, root = served
    before_tree = snapshot_tree(root)
    status, payload = edit(
        client, ref="REQ-999", revision=sha256(reqs_file(root)), field="text", value="x"
    )
    assert status == 422
    assert payload["kind"] == "refused"
    assert snapshot_tree(root) == before_tree


# ---------------------------------------------------------------- invalid


def test_an_invalid_enum_value_is_422_with_diagnostics_and_changes_nothing(served):
    _app, client, root = served
    before_tree = snapshot_tree(root)
    status, payload = edit(client, root=root, field="status", value="not-a-choice")
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert payload["diagnostics"], "the gate must say which error it blocked"
    assert any("not one of" in d["message"] for d in payload["diagnostics"])
    assert snapshot_tree(root) == before_tree


# ------------------------------------------- every refusal leaves no trace


def test_every_refusing_path_leaves_the_project_byte_identical(served):
    """The test_no_write posture applied to the editor's own write route: a
    long list of ways to be told no, and one assertion that none of them wrote."""
    _app, client, root = served
    path = reqs_file(root)
    stale = sha256(path)
    before_tree = snapshot_tree(root)

    attempts = [
        {"op": "set_field", "field": "id", "value": "REQ-999", "expected_revision": sha256(path)},
        {"op": "set_field", "field": "text", "value": "x", "expected_revision": "0" * 64},
        {"op": "set_field", "field": "status", "value": "not-a-choice", "expected_revision": sha256(path)},
        {"op": "set_field", "field": "tags", "value": "power", "expected_revision": sha256(path)},
        {"op": "set_body", "text": "nope", "expected_revision": "0" * 64},
        {"op": "nonsense", "expected_revision": sha256(path)},
    ]
    for payload in attempts:
        status, _body = client.api_post(EDIT_PATH, payload)
        assert status in (400, 409, 422), payload

    # an item that does not exist, and a foreign ref spelling
    status, _body = edit(client, ref="NOPE-1", revision=stale, field="text", value="x")
    assert status == 422

    assert snapshot_tree(root) == before_tree
    assert sorted(os.listdir(root / "items")) == ["decs.yaml", "log.yaml", "reqs.yaml"]


# ------------------------------------------------------ editability on the view


def test_the_item_view_names_what_is_editable_and_why_the_rest_is_not(served):
    _app, client, root = served
    status, item = client.api_get("/api/item/REQ-001")
    assert status == 200
    edit_info = item["edit"]
    assert edit_info["editable"] is True and edit_info["reason"] is None
    assert edit_info["file_revision"] == sha256(reqs_file(root))
    assert edit_info["body"]["editable"] is True

    fields = edit_info["fields"]
    assert fields["text"]["editable"] is True
    assert fields["text"]["control"] == "text"
    assert fields["text"]["required"] is True
    assert fields["text"]["value_type"] == "string"
    # an enum arrives with its choices, so the form builds a select
    assert fields["status"]["editable"] is True
    assert fields["status"]["control"] == "select"
    assert fields["status"]["choices"] == ["draft", "approved"]
    # a collection is read-only, with the reason spelled out
    assert fields["tags"]["editable"] is False
    assert "scalar" in fields["tags"]["reason"]
    # identity is read-only even though it is not in `fields`
    for name in ("id", "key", "type"):
        assert fields[name]["editable"] is False
        assert "identity" in fields[name]["reason"]


def test_the_edit_route_is_not_a_get_surface(served):
    _app, client, _root = served
    status, _payload = client.api_get("/api/item/REQ-001/edit")
    assert status == 405


# ----------------------------------------------------------------- keyed
#
# A project that a writable `refdes check` has minted is the state a real
# author's editor runs against: every `/api/items` row then carries the item's
# surrogate key as its `handle`, and `editor.js` posts that exact spelling
# back to this route (EDIT-01). The read route has always resolved it -- the
# items dict is keyed by it -- and the write route resolves it there too;
# what it must not do is hand the raw spelling to the patcher and refuse
# because the file spells the item by its id. The item is one identity with
# two spellings, and the file carries both.


@pytest.fixture
def served_minted(tmp_path):
    """The shared fixture project after keys were minted (serve_support's
    `make_project` runs one ordinary writable check), served live."""
    config = make_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def handle_for(client, item_id: str) -> str:
    """The `handle` the shipped list gives the browser for `item_id` -- the
    exact spelling `editor.js` puts into the edit URL."""
    status, listing = client.api_get("/api/items")
    assert status == 200
    for row in listing["items"]:
        if row["id"] == item_id:
            return row["handle"]
    raise AssertionError(f"no row for {item_id}")


def test_the_keyed_handle_from_the_row_saves_the_yaml_item(served_minted):
    _app, client, root = served_minted
    path = reqs_file(root)
    handle = handle_for(client, "REQ-001")
    assert handle != "REQ-001" and "-" not in handle

    status, item = client.api_get(f"/api/item/{handle}")
    assert status == 200 and item["edit"]["editable"] is True

    status, payload = client.api_post(
        f"/api/item/{handle}/edit",
        {
            "op": "set_field",
            "field": "text",
            "value": "The rail shall supply 5 V.",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert payload["revision"] == sha256(path)
    text = read(path)
    assert "The rail shall supply 5 V." in text
    # the identity lines and the comments outside the span survive untouched
    assert "id: REQ-001" in text and f"key: {handle}" in text
    assert "This comment must survive edits." in text and "# a comment between items" in text


def test_the_keyed_handle_saves_a_markdown_front_matter_field(served_minted):
    """The front-matter shape, end to end: minting put a `key:` line inside
    the `---` block of items/notes.md, and the row hands out that key as the
    handle. (Body edits on this fixture's notes.md are refused by the
    patcher's `---` rule -- the fixture body carries a horizontal rule --
    so the front-matter field is the shape driven here; clean-body Markdown
    body edits are covered in test_patcher.py.)"""
    _app, client, root = served_minted
    handle = handle_for(client, "REQ-010")
    notes = str(root / "items" / "notes.md")

    status, item = client.api_get(f"/api/item/{handle}")
    assert status == 200 and item["edit"]["editable"] is True

    status, payload = client.api_post(
        f"/api/item/{handle}/edit",
        {
            "op": "set_field",
            "field": "text",
            "value": "A rewritten markdown requirement.",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 200, payload
    assert "A rewritten markdown requirement." in read(notes)
    assert f"key: {handle}" in read(notes)


def test_the_display_id_still_saves_on_a_keyed_project(served_minted):
    _app, client, root = served_minted
    status, payload = edit(client, root=root, field="status", value="draft")
    assert status == 200, payload
    assert "status: draft" in read(reqs_file(root))


def test_a_stale_revision_by_key_handle_is_a_conflict_with_a_real_diff(served_minted):
    """The conflict's draft is planned against the request's own spelling: a
    route that cannot find the item by it produces a 409 with no text to show."""
    _app, client, root = served_minted
    path = reqs_file(root)
    handle = handle_for(client, "REQ-001")
    stale = sha256(path)
    moved = read(path).replace("3.3 V", "5.0 V")
    with open(path, "wb") as fh:
        fh.write(moved.encode("utf-8"))
    before_tree = snapshot_tree(root)

    status, payload = edit(client, ref=handle, revision=stale, field="status", value="draft")
    assert status == 409, payload
    assert payload["current_text"] is not None
    assert "5.0 V" in payload["diff"]
    assert snapshot_tree(root) == before_tree


def test_the_keyed_handle_refuses_identity_with_the_identity_words(served_minted):
    _app, client, root = served_minted
    handle = handle_for(client, "REQ-001")
    before_tree = snapshot_tree(root)
    status, payload = edit(
        client, ref=handle, revision=sha256(reqs_file(root)), field="id", value="REQ-999"
    )
    assert status == 422 and payload["kind"] == "refused"
    assert "identity" in payload["reason"]
    assert snapshot_tree(root) == before_tree


def test_the_keyed_handle_is_blocked_by_the_gate_not_a_find_failure(served_minted):
    """An enum the schema rejects must come back as the gate's `invalid` with
    diagnostics -- not the patcher's `refused`, which would say the save
    never found the item it was asked to edit."""
    _app, client, root = served_minted
    handle = handle_for(client, "REQ-001")
    before_tree = snapshot_tree(root)
    status, payload = edit(
        client, ref=handle, revision=sha256(reqs_file(root)), field="status", value="not-a-choice"
    )
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert payload["diagnostics"]
    assert snapshot_tree(root) == before_tree


def test_the_keyless_provisional_handle_saves_like_the_display_id(served):
    """The keyless project's rows carry the item's provisional `~` handle,
    a view address rather than a spelling the file holds. The browser posts
    exactly that handle, so the write route plans the save against the item's
    display id (F13-2); it used to refuse it with a 422 on every save."""
    _app, client, root = served
    handle = handle_for(client, "REQ-001")
    assert handle.startswith("~")
    status, payload = edit(
        client, ref=handle, revision=sha256(reqs_file(root)), field="status", value="draft"
    )
    assert status == 200, payload
    assert "status: draft" in read(reqs_file(root))
