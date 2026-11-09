"""The continuation endpoint: `POST /api/item/<ref>/continue` (docs/design/
thread-workbench-w5b-plan.md §4 W5b.2, plan lines 257-277).

W5b.2 is the HTTP face of the W5b.1 operation (`serve.edit.continue_thread`,
merged in #448; tests/test_serve_continue.py pins the operation). The plan's
W5b.2 "Adds" (lines 259-263) is one dispatcher entry in `serve/api.py` mapping
the four results to statuses "exactly as `_apply_edit` and `_create_item` do"
-- this module pins that mapping with the same fixtures `tests/
test_serve_edit_http.py` uses (live `EditorApp` on port 0, `serve_support.
Client`), and the same "every refusal leaves the project byte-identical"
posture. Ratified defaults this file depends on: Q2's door (iii) -- one new
endpoint, riding the same token + Origin checks (plan lines 456-458, 147-149)
and the same `Applied/Conflict/Refused/Invalid` mapping (Q2 ratified
2026-11-06, plan lines 479-482); Q10's (a) -- no CLI in W5b, so no CLI test
here (plan lines 632-633). The permission seam's three rules the W5b.2 title
names (plan line 257, spelled at plan lines 147-151): every `/api/` call
requires the launch token (pinned by test_continue_requires_the_launch_token),
every POST requires a matching Origin (test_continue_requires_a_matching_
origin), and the write-capable surface stays a same-origin module -- W5b.2
"deliberately does not do" any new CSP allowance, content type, or body-cap
(plan lines 273-274), so the route's only content type is the neighbours' JSON
(pinned by test_continue_requires_json_content and the applied test's
`application/json`).

The request body this file pins (the implementer follows it):

    POST /api/item/<ref>/continue
    {
      "ticks": [["T-a", "done"], ...],   # (task id, wanted state) pairs, in order
      "expected_revision": "<sha256>"    # file_revision of the thread's file
    }

`ticks` is a list of 2-element lists: the operation's request field is a
tuple of pairs, not a mapping (tests/test_serve_continue.py docstring, plan
line 243 refuses a duplicate id, which an object cannot express), and JSON
spells a pair as a 2-element array. `expected_revision` copies the key name
`_apply_edit` requires (api.py:1173-1175) -- same word for the same fact (the
target file's content revision), so the conflict screen's client code is one
spelling. A malformed body is a 400 with "error" (api.py:1170-1175's split:
shape is the route's, authoring outcomes are the service's).

The response shapes copy the neighbours verbatim (api.py:1230-1279): Applied
200 {kind: "applied", ok, message, path, revision, describe, id, handle,
diagnostics}; Conflict 409 {kind: "conflict", ok, message, path,
expected_revision, current_revision, current_text, diff}; Refused 422 {kind:
"refused", ok, message, reason, path}; Invalid 422 {kind: "invalid", ok,
message, reason, path, diagnostics}. `who` is "local", as on /edit
(api.py:1214).
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import build as build_mod
from refdes import keys, parse
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Continue http test"
date_format: DD/MM/YYYY
id:
  width: 3
link_types:
  follows: { inverse: followed_by, label: Follows, trace: false }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      date: { type: date }
      summary: { type: text, required: true }
      tasks: { type: tasks, on_change: timeline }
    links:
      follows: [log]
  note:
    prefix: NOTE
    fields:
      title: { type: text, required: true }
"""

# The same thread shape tests/test_serve_continue.py runs the operation over:
# a settled thread whose tip declares the complete list.
LOG = """\
defaults:
  type: log
  prefix: LOG-SYS

items:
  - id: LOG-SYS-001
    summary: Rail work opens.
    date: 30/08/2026
  - id: LOG-SYS-002
    summary: Rail work continues.
    date: 01/09/2026
    follows: [LOG-SYS-001]
    tasks:
      - {id: T-rail, text: Settle the rail budget., state: open}
      - {id: T-bom, text: Freeze the BOM., state: done}
      - {id: T-probe, text: Probe the SWD pins., state: open}
"""

NOTES = """\
defaults: { type: note }
items:
  - id: NOTE-001
    title: Not a thread entry.
"""

CONTINUE_PATH = "/api/item/LOG-SYS-002/continue"


def _write(root, name, text):
    with open(os.path.join(str(root), name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def mint_keys(root):
    """Keys minted the way any writable command leaves them -- the composite
    `follows:` needs the tip's key (tests/test_serve_continue.py's fixture)."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project, write=True)


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def served(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(tmp_path, "items/log.yaml", LOG)
    _write(tmp_path, "items/notes.yaml", NOTES)
    mint_keys(tmp_path)
    app = start(tmp_path)
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


def sha256_of(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def log_file(root) -> str:
    return str(root / "items" / "log.yaml")


def read_bytes(path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def continue_post(client, *, ref="LOG-SYS-002", root=None, revision=None, ticks=None, path=None):
    payload = {
        "ticks": [["T-rail", "done"]] if ticks is None else ticks,
        "expected_revision": (
            sha256_of(log_file(root)) if revision is None else revision
        ),
    }
    return client.api_post(path if path is not None else f"/api/item/{ref}/continue", payload)


def served_from(tmp_path, files: dict[str, str], *, seal: bool = False, schema: str = SCHEMA):
    """A served project written from `files`, keys minted -- the folded-posture
    fixtures (ambiguous/undeclared/cleared/gate) each need their own thread."""
    write_project_config(tmp_path, schema)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    for name, text in files.items():
        _write(tmp_path, os.path.join("items", name), text)
    mint_keys(tmp_path)
    if seal:
        project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
        parse.load_items(project)
        build_mod.build(project, seal_write=True, reseal=False)
    app = start(tmp_path)
    return app, Client(app), tmp_path


# ------------------------------------------------------------------ the gate
#
# The plan's W5b.2 "Verified against" (plan lines 268-271): "No token -> 403;
# wrong Origin -> 403; a refusal is a status + a message + 'nothing changed',
# never a 500; --no-write -> 403 naming the reason; a request that lies about
# the revision -> Conflict with the current list, and no write." Header setup
# copied from tests/test_serve_edit_http.py's gate section.


def test_continue_requires_the_launch_token(served):
    _app, client, root = served
    body = b'{"ticks": [["T-rail", "done"]], "expected_revision": "' + sha256_of(log_file(root)).encode() + b'"}'
    hdrs = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"}
    status, _h, _b = client.request("POST", CONTINUE_PATH, body=body, headers=hdrs)
    assert status == 403
    status, _h, _b = client.request(
        "POST", CONTINUE_PATH, body=body, headers=dict(hdrs, **{"X-Refdes-Token": "wrong"})
    )
    assert status == 403
    status, _h, _b = client.request("POST", CONTINUE_PATH, body=body, headers=hdrs, cookie=True)
    assert status == 403


def test_continue_rejects_a_foreign_host(served):
    _app, client, _root = served
    status, _h, _b = client.request(
        "POST",
        CONTINUE_PATH,
        token=True,
        host="evil.example",
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"},
        body=b"{}",
    )
    assert status == 403


@pytest.mark.parametrize("origin", [None, "http://evil.example", "null"])
def test_continue_requires_a_matching_origin(served, origin):
    _app, client, root = served
    status, _payload = client.api_post(
        CONTINUE_PATH,
        {"ticks": [["T-rail", "done"]], "expected_revision": sha256_of(log_file(root))},
        origin=origin,
    )
    assert status == 403


def test_a_read_only_server_refuses_continuations(tmp_path):
    """W5b.2 "Verified against" (plan line 270): `--no-write` -> 403 naming
    the reason, spelled the neighbours' way (api.py:1168-1169: the route's
    own top check, "this server was started with --no-write", before the
    body is even interpreted)."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(tmp_path, "items/log.yaml", LOG)
    mint_keys(tmp_path)
    app = start(tmp_path, read_only=True)
    try:
        client = Client(app)
        before = snapshot_tree(root=tmp_path)
        status, payload = continue_post(client, root=tmp_path)
        assert status == 403, payload
        assert "--no-write" in payload["error"]
        assert snapshot_tree(root=tmp_path) == before
    finally:
        app.stop()


def test_the_continue_route_is_not_a_get_surface(served):
    _app, client, _root = served
    status, _h, _b = client.request(
        "GET", CONTINUE_PATH, token=True, headers={"Origin": f"http://127.0.0.1:{client.port}"}
    )
    assert status == 405
    status, _h, _b = client.request("PUT", CONTINUE_PATH, token=True, body=b"{}")
    assert status == 405


def test_continue_requires_json_content(served):
    _app, client, _root = served
    status, _h, body = client.request(
        "POST",
        CONTINUE_PATH,
        token=True,
        headers={"Content-Type": "text/plain", "Origin": f"http://127.0.0.1:{client.port}"},
        body=b"hello",
    )
    assert status == 415
    assert b"application/json" in body


# ---------------------------------------------------------------- applied


def test_a_continuation_applies_with_the_new_entry_id_handle_and_revision(served):
    """W5b.2 maps `Applied` to 200 with the new entry's id/handle/revision,
    the same body `_apply_edit` returns (api.py:1230-1252); the thread file
    gains exactly one entry and every pre-existing byte (the tip's included,
    R2, plan lines 369-372) stays put as a pure prefix."""
    _app, client, root = served
    path = log_file(root)
    before = read_bytes(path)
    before_tree = snapshot_tree(root)

    status, payload = continue_post(client, root=root)

    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    assert payload["id"] == "LOG-SYS-003"  # the file's own defaults.prefix series
    assert payload["handle"] and payload["handle"] != payload["id"]  # the minted key
    assert payload["path"] == "items/log.yaml"  # shown(): project-relative (api.py:1222-1228)
    assert not os.path.isabs(payload["path"])
    assert payload["revision"] == sha256_of(path)
    assert "LOG-SYS-003" in payload["message"]
    assert "1 tick" in payload["describe"]
    assert isinstance(payload["diagnostics"], list)

    after = read_bytes(path)
    assert after.startswith(before)  # pure suffix: the tip bytes unchanged
    assert after.count(b"- id: ") == before.count(b"- id: ") + 1  # exactly one entry
    # only the thread file, the id ledger, and the capture's history files
    # moved. W5b.5: the continuation save captures the predecessor -- one
    # `followed` event + its snapshot object, both under .refdes/history.
    moved = {k for k, v in snapshot_tree(root).items() if before_tree.get(k) != v}
    history_moved = {k for k in moved if k.startswith(".refdes/history/")}
    assert moved - history_moved == {"items/log.yaml", ".refdes/ids.yaml"}
    assert sum(k.startswith(".refdes/history/events/") for k in history_moved) == 1
    assert sum(k.startswith(".refdes/history/objects/") for k in history_moved) == 1

    # the snapshot refreshed the way a save refreshes (api.py:1234): the new
    # entry is addressable immediately
    status, item = client.api_get(f"/api/item/{payload['id']}")
    assert status == 200
    assert item["id"] == "LOG-SYS-003"


# --------------------------------------------------------------- conflict


def test_a_stale_revision_is_409_with_the_current_list_and_changes_nothing(served):
    """Q3(a) as ratified (plan lines 508-510): a request that lies about the
    revision -> `Conflict` with the current list, and no write (plan
    lines 270-271). The neighbours' 409 shape (api.py:1253-1263): the current
    revision, the current text, the diff -- and nothing merged."""
    _app, client, root = served
    path = log_file(root)
    stale = sha256_of(path)
    # a concurrent author moves the tip's file through the ordinary edit route
    status, edited = client.api_post(
        "/api/item/LOG-SYS-002/edit",
        {
            "op": "set_field",
            "field": "summary",
            "value": "Rail work, re-scoped.",
            "expected_revision": stale,
        },
    )
    assert status == 200, edited
    before_tree = snapshot_tree(root)

    status, payload = continue_post(client, root=root, revision=stale)

    assert status == 409, payload
    assert payload["kind"] == "conflict" and payload["ok"] is False
    assert payload["expected_revision"] == stale
    assert payload["current_revision"] == sha256_of(path)
    assert payload["current_text"] is not None
    # "with the current list": the carried disk text shows the rows as they
    # are now -- the ticked row is still open on disk
    assert "T-rail" in payload["current_text"]
    assert "state: open" in payload["current_text"]
    assert "LOG-SYS-003" in payload["diff"]  # what the save would have appended
    assert snapshot_tree(root) == before_tree
    assert b"LOG-SYS-003" not in read_bytes(path)


# --------------------------------------------------------- refusals, "no"


FOLD_CASES = [
    pytest.param(
        "ambiguous",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-C, summary: Left., date: 01/09/2026, tasks: [{id: T-l, text: Left., state: open}]}\n"
        "  - {id: LOG-D, summary: Right., date: 01/09/2026, tasks: [{id: T-r, text: Right., state: open}]}\n"
        "  - {id: LOG-E, summary: Merge., date: 02/09/2026, follows: [LOG-C, LOG-D]}\n",
        "LOG-E",
        [["T-l", "done"]],
        "ambiguous",
        id="ambiguous",
    ),
    pytest.param(
        "undeclared",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026}\n"
        "  - {id: LOG-B, summary: Silent., date: 02/09/2026, follows: [LOG-A]}\n",
        "LOG-B",
        [["T-a", "done"]],
        "undeclared",
        id="undeclared",
    ),
    pytest.param(
        "cleared",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026, tasks: [{id: T-a, text: A., state: open}]}\n"
        "  - {id: LOG-B, summary: Cleared., date: 02/09/2026, follows: [LOG-A], tasks: []}\n",
        "LOG-B",
        [["T-a", "done"]],
        "cleared",
        id="cleared",
    ),
]


@pytest.mark.parametrize("_name, log_text, ref, ticks, needle", FOLD_CASES)
def test_the_fold_postures_are_422_refused_and_change_nothing(tmp_path, _name, log_text, ref, ticks, needle):
    """Plan line 242 (via W5b.1): a fold that is `ambiguous`, `undeclared`, or
    `cleared` carries no list to copy -- Refused, 422 with the neighbours'
    refusal body, and the tree byte-identical."""
    app, client, root = served_from(tmp_path, {"log.yaml": log_text})
    try:
        before = snapshot_tree(root)
        status, payload = continue_post(client, ref=ref, root=root, ticks=ticks)
        assert status == 422, payload
        assert payload["kind"] == "refused" and payload["ok"] is False
        assert needle in payload["reason"]
        assert payload["message"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


TICK_CASES = [
    pytest.param("LOG-SYS-002", [["T-nope", "done"]], "T-nope", id="unknown-task-id"),
    pytest.param("LOG-SYS-002", [["T-rail", "closed"]], "closed", id="state-outside-vocabulary"),
    pytest.param(
        "LOG-SYS-002",
        [["T-rail", "done"], ["T-rail", "dropped"]],
        "ticked twice",
        id="duplicate-tick",
    ),
    pytest.param("LOG-SYS-002", [["T-rail", 7]], "vocabulary", id="non-string-state"),
    pytest.param("LOG-SYS-999", [["T-rail", "done"]], "no item", id="unknown-ref"),
    pytest.param("NOTE-001", [["T-rail", "done"]], "undeclared", id="note-entry-declares-no-tasks"),
]


@pytest.mark.parametrize("ref, ticks, needle", TICK_CASES)
def test_the_refusal_postures_are_422_with_a_message_and_change_nothing(served, ref, ticks, needle):
    """Every Refused posture the W5b.1 operation has -- unknown task id, a
    state outside TASK_STATES, a second tick for one id, an unknown ref, a
    ref that is not a thread entry (plan lines 242-243) -- is the neighbours'
    422 refused (api.py:1273-1279): a status + a message + nothing changed,
    never a 500 (plan line 269)."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = continue_post(client, ref=ref, root=root, ticks=ticks)
    assert status == 422, payload
    assert payload["kind"] == "refused" and payload["ok"] is False
    assert needle in payload["reason"]
    assert payload["message"]
    assert snapshot_tree(root) == before


def test_a_sealed_tip_is_422_refused_and_untouched(tmp_path):
    """Plan line 243 (sealed target, via W5b.1): the sealed tip is refused the
    same way `apply_edit` refuses it (tests/test_serve_edit_http.py:400-425
    pins /edit's spelling) -- 422, the word "sealed", bytes identical."""
    app, client, root = served_from(tmp_path, {"log.yaml": LOG}, seal=True)
    try:
        before = snapshot_tree(root)
        status, payload = continue_post(client, root=root)
        assert status == 422, payload
        assert payload["kind"] == "refused"
        assert "sealed" in payload["reason"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


def test_the_delta_gate_blocks_with_422_invalid_and_writes_nothing(tmp_path):
    """The Invalid posture (W5b.1's delta-diagnostic gate, plan line 233): a
    tip whose list already carries a row outside the vocabulary is copied
    verbatim, which attributes the same error to the NEW entry -- an error the
    gate blocks. The neighbours' invalid body (api.py:1264-1272): 422, kind
    "invalid", the blocking diagnostics."""
    app, client, root = served_from(
        tmp_path,
        {
            "log.yaml": "defaults: { type: log }\n"
            "items:\n"
            "  - {id: LOG-A, summary: Opens., date: 01/09/2026, tasks: "
            "[{id: T-a, text: A., state: open}, {id: T-b, text: B., state: closed}]}\n"
        },
    )
    try:
        before = snapshot_tree(root)
        status, payload = continue_post(client, ref="LOG-A", root=root, ticks=[["T-a", "done"]])
        assert status == 422, payload
        assert payload["kind"] == "invalid" and payload["ok"] is False
        assert payload["diagnostics"], "the gate must say which error it blocked"
        assert any("closed" in d["message"] for d in payload["diagnostics"])
        assert snapshot_tree(root) == before
    finally:
        app.stop()


# ---------------------------------------------------------- malformed body


MALFORMED = [
    pytest.param([1, 2], id="not-an-object-list"),
    pytest.param("ticks!", id="not-an-object-string"),
    pytest.param(None, id="not-an-object-null"),
    pytest.param({"ticks": [["T-rail", "done"]]}, id="missing-revision"),
    pytest.param({"ticks": [["T-rail", "done"]], "expected_revision": ""}, id="empty-revision"),
    pytest.param({"ticks": [["T-rail", "done"]], "expected_revision": 7}, id="revision-not-a-string"),
    pytest.param({"expected_revision": "0" * 64}, id="ticks-missing"),
    pytest.param({"ticks": "nope", "expected_revision": "0" * 64}, id="ticks-not-a-list"),
    pytest.param({"ticks": [["T-rail"]], "expected_revision": "0" * 64}, id="tick-not-a-pair"),
    pytest.param({"ticks": [["T-rail", "done", "x"]], "expected_revision": "0" * 64}, id="tick-too-long"),
    pytest.param({"ticks": ["T-rail"], "expected_revision": "0" * 64}, id="tick-a-bare-string"),
]


@pytest.mark.parametrize("payload", MALFORMED)
def test_a_malformed_body_is_400_and_changes_nothing(served, payload):
    """The neighbours' split (api.py:1165-1175, "A malformed request -- not an
    authoring outcome -- is a 400"; _create_item's shape gates at api.py:1375-
    1401 refuse what could not be a request at all, in the same 400-with-
    "error" shape): not an object, a missing/blank/non-string revision, ticks
    that are not a list of 2-element pairs."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, body = client.api_post(CONTINUE_PATH, payload)
    assert status == 400, body
    assert "error" in body
    assert snapshot_tree(root) == before


# ------------------------------------------------------------------- the ref


def test_a_percent_encoded_ref_is_decoded_like_the_neighbours(served):
    """The dispatcher unquotes the ref exactly as the /edit route does
    (api.py:54-57: `urllib.parse.unquote(path[len("/api/item/"):-len(...)])`,
    on the path `_dispatch` has already unquoted once, server.py:673). A ref
    percent-encoded at the wire decodes to the display id and resolves."""
    _app, client, root = served
    status, payload = continue_post(client, root=root, path="/api/item/LOG%2DSYS%2D002/continue")
    assert status == 200, payload
    assert payload["id"] == "LOG-SYS-003"


HOSTILE_REFS = [
    pytest.param("/api/item/%2e%2e%2f%2e%2e%2fsecret/continue", id="path-traversal"),
    pytest.param("/api/item/a%00b/continue", id="nul-byte"),
    pytest.param("/api/item/" + "L" * 300 + "/continue", id="very-long-ref"),
]


@pytest.mark.parametrize("path", HOSTILE_REFS)
def test_a_hostile_ref_is_refused_cleanly_and_never_500s(served, path):
    """A ref that decodes to path traversal, a NUL, or 300 chars reaches the
    operation's ref resolution (edit._continue_locked's `resolve_ref` ->
    `no item ... in this project`) and lands as the neighbours' 422 refusal
    for an unknown item (tests/test_serve_edit_http.py:436-444): a status, a
    message, nothing changed -- never a 500 (plan line 269)."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = continue_post(client, root=root, path=path)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "no item" in payload["reason"]
    assert snapshot_tree(root) == before


def test_the_response_echoes_request_text_only_as_the_neighbours_do(served):
    """The neighbours echo a rejected ref as Python's repr inside a JSON
    string (`f"no item {ref!r} in this project"`, edit.py:2418), and the whole
    payload passes the write routes' choke point `_write_outcome` ->
    `_relative_paths` (api.py:754-760), which scrubs path-shaped text; the
    continue route shares both. So a hostile task id comes back as the
    repr-in-JSON echo, JSON-escaped by `json.dumps` (server.py:634), under
    `application/json` -- no second content type, no new CSP allowance (plan
    lines 273-274). Nothing is written."""
    _app, client, root = served
    before = snapshot_tree(root)
    hostile = '"><img src=x onerror=alert(1)>'
    body = json.dumps(
        {"ticks": [[hostile, "done"]], "expected_revision": sha256_of(log_file(root))}
    ).encode("utf-8")
    status, headers, data = client.request(
        "POST",
        CONTINUE_PATH,
        token=True,
        body=body,
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"},
    )
    assert status == 422
    assert headers["content-type"].startswith("application/json")
    text = data.decode("utf-8")
    assert f"task {hostile!r}".replace('"', '\\"') in text  # the repr echo, JSON-escaped
    assert "is not in the task list at the tip" in text
    assert snapshot_tree(root) == before


# ------------------------------------------------------- the permission seam


def test_who_reaches_the_operation_as_it_does_for_edit(served, monkeypatch):
    """The seam's `who` (edit.py:160-163): the /edit route passes the literal
    "local" (api.py:1214, "today every caller is the same local author, and
    the seam lives in the service"), and W5b.2's "Adds" says the operation
    "carries `who` like every other request" (plan line 263). Pin the call
    the route makes: who="local", the URL-decoded ref, the body's ticks pairs
    in order, the body's revision."""
    _app, client, root = served
    captured: list = []
    real = edit_mod.continue_thread

    def spy(project_root, request, config_path=None, *, read_only=False):
        captured.append(request)
        return real(project_root, request, config_path, read_only=read_only)

    monkeypatch.setattr(edit_mod, "continue_thread", spy)
    revision = sha256_of(log_file(root))
    status, payload = continue_post(client, root=root, revision=revision)
    assert status == 200, payload
    assert len(captured) == 1
    request = captured[0]
    assert request.who == "local"
    assert request.ref == "LOG-SYS-002"
    assert request.expected_revision == revision
    assert [list(tick) for tick in request.ticks] == [["T-rail", "done"]]
