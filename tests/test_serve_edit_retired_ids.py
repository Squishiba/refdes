"""The editor's write route must resolve retired ids (`former_ids:`) exactly
like the read route does (EDIT-03).

`GET /api/item/{ref}` resolves a retired id through `project.former_ids`
(api._find_item, run-5 finding B5); the write route's `_find_item`
(serve/edit.py) resolves only the live spellings, so a POST addressed by the
id a schematic still names was a 422 "no item" while the very same URL as a
GET returned 200. The two routes share one identity space; this module pins
the write route's retired-id behavior against the read route's, including the
three traps: a retired id that is also someone's live id (the live item
wins), a retired id claimed by two items (the write refuses and the project
loudly reports the ambiguity), and a retired id that exists nowhere (the
ordinary refusal, unchanged).

Contract the fix commits to, beyond "the write lands on the item whose
`former_ids:` names the ref":
- the 200 payload reports the item's CURRENT handle under `"handle"` --
  the same field `GET /api/item/{ref}` hands back (surrogate key when the
  project has keys, display id when it does not), so the browser can
  correct its ref.

The drive layer is `api.handle` itself -- the exact handler the socket
layer dispatches to (server._dispatch), the exact (status, JSON payload)
contract the browser consumes, the same real `ProjectState` with the same
post-save refresh. What it leaves out is the transport: the socket, the
token and the origin gate, which test_serve_edit_http and the upload gate
tests pin. A route's identity resolution must be gradeable on a box with
no spare threads for a live server (RLIMIT_NPROC/pids.max), and threads
buy this module nothing: every assertion is a status code, a payload
field, or file bytes. Two tests at the end break that rule on purpose --
the ticket asked for HTTP-level coverage where the repo has it -- driving
the real `EditorApp` socket for the main path and for the loud refusal;
the direct drives stay as the thread-free spine of the module.

The fixtures are projects of their own (like the retired-id tests in
test_serve_api.py): a `former_ids:` entry burns an id into the ledger, which
the shared fixtures cannot absorb. Each test builds its project afresh, so
no test reads text an earlier test's save edited.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes.serve import api as api_mod
from refdes.serve import state as state_mod
from refdes.serve.server import EditorApp

RETIRE_SCHEMA = """\
site:
  title: "Retired ids edit test"
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

# REQ-001 was renamed: REQ-900 is its retired id, spelled by nobody in this
# project any more. REQ-002 never was, and DEC-001 links nothing yet.
REQS = """\
# a comment that must survive every save
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.
    status: approved
    former_ids: [REQ-900]
  - id: REQ-002
    text: The board shall boot within 2 s.
    status: approved
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
"""

# The collision fixture: REQ-002's `former_ids:` names REQ-001, which is
# still a live item. `ids.collect_former_ids` records that as a build error
# and never puts the spelling into `project.former_ids` -- so on BOTH routes
# the live item wins, and the write must land on REQ-001's own item.
COLLIDE_REQS = """\
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.
    status: approved
"""

COLLIDE_CLAIM = """\
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-002
    text: The board shall boot within 2 s.
    status: approved
    former_ids: [REQ-001]
"""

# The ambiguity fixture: REQ-002 and REQ-003 each claim retired REQ-900.
# A build error on the later-loaded claimant -- files load alphabetically,
# so claim2.yaml (REQ-003) records `REQ-900 -> REQ-003` in
# `project.former_ids` first, and REQ-002 (reqs.yaml) carries the "declared
# by both" error. The write must refuse, never pick one, and the project
# must say why, in the open.
CLAIM_REQS = """\
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.
    status: approved
  - id: REQ-002
    text: The board shall boot within 2 s.
    status: approved
    former_ids: [REQ-900]
"""

CLAIM_CLAIM2 = """\
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-003
    text: Nothing addresses this yet.
    status: approved
    former_ids: [REQ-900]
"""


class Api:
    """A thread-free drive of the API routes: the real `ProjectState`, the
    real `api.handle`, the same (status, payload) the socket layer returns.

    The gate the transport owns -- token, origin, --no-write -- is exercised
    through the real socket in test_serve_edit_http; `read_only` here only
    needs to reach the route's own check, which reads the same attribute the
    server sets."""

    def __init__(self, root, read_only: bool = False):
        self.state = state_mod.ProjectState(str(root / "refdes-project.yaml"))
        self.state.load()
        self.read_only = read_only

    def get(self, path: str):
        return api_mod.handle(self, "GET", path, {}, None)

    def post(self, path: str, payload):
        return api_mod.handle(self, "POST", path, {}, payload)


def make_root(tmp_path, files) -> Path:
    write_project_config(tmp_path, RETIRE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def retired_root(tmp_path):
    return make_root(tmp_path, {"reqs.yaml": REQS, "decs.yaml": DECS})


def serve(root) -> Api:
    return Api(root)


def serve_minted(tmp_path) -> tuple[Api, Path]:
    """The same project after an ordinary writable check minted every key:
    the handle the row hands the browser is then the surrogate key, and that
    is the handle a retired-id save must report back."""
    root = retired_root(tmp_path)
    cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    return Api(root), root


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def reqs_file(root) -> str:
    return str(root / "items" / "reqs.yaml")


def decs_file(root) -> str:
    return str(root / "items" / "decs.yaml")


def edit(client, ref, path, **fields):
    payload = {"op": "set_field", "field": "status", "value": "draft"}
    payload.update(fields)
    payload["expected_revision"] = sha256(path)
    return client.post(f"/api/item/{ref}/edit", payload)


def is_find_refusal(status, payload) -> bool:
    """The write route's *resolution* refusal, in its exact words: "no item
    X in this project". The patcher's own refusal says "in this file", which
    is the resolution succeeding and the patch declining -- a different fact,
    pinned by test_serve_edit_http."""
    return (
        status == 422
        and isinstance(payload, dict)
        and payload.get("kind") == "refused"
        and "in this project" in payload.get("reason", "")
    )


def is_ambiguity_refusal(payload) -> bool:
    """The write route's AMBIGUITY refusal, in the resolver's distinctive
    words: it names the mechanism (`former_ids`), the rule ("exactly one
    item") and the posture ("refuses to pick one"). The generic find refusal
    -- "no item X in this project" -- says none of these, so a regression to
    a plain unknown-ref refusal cannot satisfy a test that checks this."""
    reason = payload.get("reason", "")
    return (
        isinstance(payload, dict)
        and payload.get("kind") == "refused"
        and "no item" not in reason
        and "former_ids" in reason
        and "exactly one item" in reason
        and "refuses to pick one" in reason
    )


# ------------------------------------------------------- the read route's bar
#
# The write route has to match the read route; pin what that route does
# today, so a change to it cannot silently move the goal posts.


def test_the_read_route_answers_a_retired_id(tmp_path):
    client = serve(retired_root(tmp_path))
    status, item = client.get("/api/item/REQ-900")
    assert status == 200, item
    assert item["id"] == "REQ-001"
    assert item["former_ids"] == ["REQ-900"]
    # the handle it hands back is the live identity, never the retired spelling
    assert item["handle"] == "REQ-001"


def test_the_read_route_refuses_a_double_claimed_retired_id(tmp_path):
    """The read-route change this task ships, pinned. A retired id claimed
    by two items used to answer 200 with the FIRST claimant: the read route
    consulted `project.former_ids`, and `ids.collect_former_ids` keeps the
    first claim in that map (the double claim is reported as a build error,
    and only live-id collisions are left out of the map). The shared
    resolver refuses to pick, so the read 404s -- the read-side spelling of
    the write route's 422 naming both claimants."""
    client = serve(make_root(tmp_path, {"reqs.yaml": CLAIM_REQS, "claim2.yaml": CLAIM_CLAIM2}))
    status, _payload = client.get("/api/item/REQ-900")
    assert status == 404


# ------------------------------------------------------------------ happy path


def test_an_edit_addressed_by_a_retired_id_lands_on_the_live_item(tmp_path):
    """The bug verbatim: GET /api/item/REQ-900 is 200, POST /api/item/REQ-900/edit
    was 422 "no item 'REQ-900'". The save resolves exactly like the read,
    lands inside REQ-001's own span (the file spells REQ-001, not REQ-900),
    and leaves REQ-002's status approved standing."""
    client, root = serve(retired_root(tmp_path)), tmp_path
    path = reqs_file(root)
    status, payload = edit(client, "REQ-900", path)
    assert status == 200, payload
    assert payload["kind"] == "applied" and payload["ok"] is True
    text = read(path)
    assert "status: draft" in text
    assert text.count("status: draft") == 1, "the edit landed on exactly one item"
    assert "status: approved" in text, "REQ-002 keeps its status"
    assert "# a comment that must survive every save" in text
    # the model the next GET answers from is the refreshed one
    _status, item = client.get("/api/item/REQ-001")
    assert item["fields"]["status"] == "draft"


def test_the_write_reports_the_current_handle(tmp_path):
    """The browser holding the retired spelling must be able to correct its
    ref: the 200 payload carries the item's current handle -- the same field
    the read view hands back -- and not the retired spelling as an identity."""
    client, root = serve(retired_root(tmp_path)), tmp_path
    status, payload = edit(client, "REQ-900", reqs_file(root))
    assert status == 200, payload
    assert payload["handle"] == "REQ-001"
    _status, view = client.get("/api/item/REQ-900")
    assert payload["handle"] == view["handle"], "one handle, one spelling, both routes"


def test_a_retired_id_conflict_keeps_its_diff(tmp_path):
    """The conflict screen on the retired spelling. A stale expected_revision
    addressed by the retired ref must answer 409 WITH the diff and the
    current span text: the conflict plans the author's draft in order to
    show it, and planning against the RAW retired ref -- which is not in
    the file -- made the plan refuse, so the conflict came back with
    current_text=None and diff="": the screen lost its diff exactly for the
    spelling this task added. The conflict plans against the resolver's
    live handle, like the save itself."""
    client, root = serve(retired_root(tmp_path)), tmp_path
    before_tree = snapshot_tree(root)
    status, payload = client.post(
        "/api/item/REQ-900/edit",
        {"op": "set_field", "field": "status", "value": "draft", "expected_revision": "0" * 64},
    )
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    assert payload["current_text"], payload
    assert payload["diff"], payload
    assert "status: draft" in payload["diff"]
    assert snapshot_tree(root) == before_tree, "a conflict writes nothing"


def test_the_write_reports_the_surrogate_key_handle_on_a_keyed_project(tmp_path):
    """On a project with keys the row's handle is the surrogate key, and a
    retired-id save reports THAT as the handle: it is the spelling the row
    gives every reader. The file keeps both of its identity lines."""
    client, root = serve_minted(tmp_path)
    _status, item = client.get("/api/item/REQ-001")
    key = item["handle"]
    assert key not in ("REQ-001", "REQ-900") and "-" not in key

    status, payload = client.post(
        "/api/item/REQ-900/edit",
        {
            "op": "set_field",
            "field": "text",
            "value": "The rail shall supply 5 V.",
            "expected_revision": item["edit"]["file_revision"],
        },
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert payload["handle"] == key
    text = read(reqs_file(root))
    assert "The rail shall supply 5 V." in text
    assert "id: REQ-001" in text and f"key: {key}" in text


# -------------------------------------------------------------------- the traps


def test_a_retired_id_that_is_a_live_id_writes_the_live_item(tmp_path):
    """REQ-002's `former_ids:` names REQ-001, which is live. The live item
    wins on both routes -- the collision is a build error and never enters
    `project.former_ids`, and the live lookups run first regardless. The
    save addressed by REQ-001 lands on REQ-001; the claimant's file is
    byte-identical."""
    root = make_root(tmp_path, {"reqs.yaml": COLLIDE_REQS, "claim.yaml": COLLIDE_CLAIM})
    client = serve(root)
    _status, item = client.get("/api/item/REQ-001")
    assert _status == 200 and item["id"] == "REQ-001"
    before_tree = snapshot_tree(root)

    status, payload = edit(client, "REQ-001", reqs_file(root))
    assert status == 200, payload
    text = read(reqs_file(root))
    block = text.split("- id: REQ-001", 1)[1].split("- id:", 1)[0]
    assert "status: draft" in block, "the edit landed inside REQ-001's own block"
    assert read(str(root / "items" / "claim.yaml")) == COLLIDE_CLAIM
    moved = {k for k, v in snapshot_tree(root).items() if before_tree.get(k) != v}
    assert moved == {"items/reqs.yaml"}


def test_a_retired_id_claimed_by_two_items_writes_neither(tmp_path):
    """REQ-002 and REQ-003 each record retired REQ-900. The built map is NOT
    the resolver's answer here: `ids.collect_former_ids` keeps the FIRST
    claimant under the contested id (files load alphabetically, so
    project.former_ids holds REQ-900 -> REQ-003 and the second claim is a
    build error on REQ-002) -- a resolver reading that map, like the read
    route used to, would write REQ-003's span. The resolver scans and
    refuses to pick instead: the write is refused, the tree is
    byte-identical -- neither claimant is touched -- the read 404s
    (test_the_read_route_refuses_a_double_claimed_retired_id), and the
    loudness lives where the reader can see it: the project reports the
    double claim as its own build diagnostic."""
    root = make_root(tmp_path, {"reqs.yaml": CLAIM_REQS, "claim2.yaml": CLAIM_CLAIM2})
    client = serve(root)
    before_tree = snapshot_tree(root)

    status, payload = edit(client, "REQ-900", reqs_file(root), field="text", value="x")
    assert status == 422, payload
    assert payload["kind"] != "applied"
    # the refusal is THIS task's ambiguity refusal, not a generic "no item":
    # the resolver's own words, and both claimants named, so a regression to
    # the unknown-ref refusal (or to picking one) cannot pass
    assert is_ambiguity_refusal(payload), payload
    reason = payload["reason"]
    assert "REQ-900" in reason, payload
    assert "REQ-002" in reason and "REQ-003" in reason, (
        f"the refusal must name both claimants: {reason!r}"
    )
    assert snapshot_tree(root) == before_tree, "the first claimant must not absorb the write"

    # the project says out loud why: the claimant the linker reported
    # on (the later-loaded file's item) carries the build error naming
    # both owners -- check both, the loudness is the project's, not one
    # item's.
    for claimant in ("REQ-002", "REQ-003"):
        _status, item = client.get(f"/api/item/{claimant}")
        assert _status == 200
        if any("declared by both" in d["message"] for d in item["diagnostics"]):
            break
    else:
        pytest.fail("the project must report the double claim as a build error")


def test_an_unknown_ref_is_the_same_refusal_as_always(tmp_path):
    """A ref that resolves nowhere keeps the existing refusal, verbatim; the
    retired-id step must not turn 404-energy into anything softer."""
    client, root = serve(retired_root(tmp_path)), tmp_path
    before_tree = snapshot_tree(root)
    status, payload = edit(client, "REQ-999", reqs_file(root), field="text", value="x")
    assert status == 422
    assert payload["kind"] == "refused"
    assert "no item" in payload["reason"] and "REQ-999" in payload["reason"]
    assert client.get("/api/item/REQ-999")[0] == 404
    assert snapshot_tree(root) == before_tree


# ---------------------------------------------------------------------- parity
#
# `_find_item`'s docstring promises "the same ... spellings the read API
# accepts". Pin that as a per-spelling equivalence: every spelling the read
# route answers with 200 must be RESOLVED by the write route -- a
# resolution-stage refusal ("no item X in this project") on a spelling the
# read route accepted is the drift this task forbids. (A spelling the write
# resolves and then the patcher declines -- the keyless project's `~`
# provisional handle, pinned by test_serve_edit_http -- passes: that is the
# patch refusing, not the find.)


def test_both_routes_accept_the_same_spellings_keyless(tmp_path):
    client, root = serve(retired_root(tmp_path)), tmp_path
    path = reqs_file(root)
    status, listing = client.get("/api/items")
    assert status == 200
    provisional = next(
        row["handle"] for row in listing["items"] if row["id"] == "REQ-001"
    )
    assert provisional.startswith("~"), "the keyless row's handle is the provisional one"

    for ref in ("REQ-001", "REQ-900", provisional):
        read_status, item = client.get(f"/api/item/{ref}")
        assert read_status == 200, f"the read route must keep answering {ref}"
        assert item["id"] == "REQ-001"
        write_status, payload = edit(client, ref, path, field="text", value=f"via {ref}")
        assert not is_find_refusal(write_status, payload), (
            f"the read route answers {ref} with 200, so the write route's "
            f"_find_item must resolve it too, not refuse it: {payload}"
        )
        if ref == provisional:
            # The find resolves the provisional handle (it IS the items dict
            # key); the patcher then declines it -- the file spells the item
            # by id, not by `~`-handle. Pinned as the write route's own
            # behavior by test_serve_edit_http; the parity here is that it is
            # the PATCH refusing, not the find.
            assert write_status == 422, (ref, payload)
            assert "in this file" in payload["reason"], payload
            continue
        assert write_status == 200, (ref, payload)
        assert payload["kind"] == "applied"
        # one identity, both routes: the write reports what the read answers
        assert payload["id"] == item["id"] and payload["handle"] == item["handle"]
        text = read(path)
        assert f"via {ref}" in text.split("- id: REQ-001", 1)[1].split("- id:", 1)[0], (
            f"the save under {ref} must land inside REQ-001's own span"
        )


def test_both_routes_accept_the_same_spellings_keyed(tmp_path):
    client, root = serve_minted(tmp_path)
    path = reqs_file(root)
    status, listing = client.get("/api/items")
    assert status == 200
    key = next(row["handle"] for row in listing["items"] if row["id"] == "REQ-001")
    assert key != "REQ-001" and "-" not in key  # minted: the surrogate key

    for ref in ("REQ-001", "REQ-900", key):
        read_status, item = client.get(f"/api/item/{ref}")
        assert read_status == 200, f"the read route must keep answering {ref}"
        assert item["id"] == "REQ-001"
        write_status, payload = edit(client, ref, path, field="text", value=f"via {ref}")
        assert not is_find_refusal(write_status, payload), (
            f"the read route answers {ref} with 200, so the write route's "
            f"_find_item must resolve it too, not refuse it: {payload}"
        )
        assert write_status == 200, (ref, payload)
        assert payload["kind"] == "applied"
        # one identity, both routes: every live spelling reports the same
        # current key-handle, never the retired spelling
        assert payload["id"] == item["id"] and payload["handle"] == item["handle"]
        assert payload["handle"] == key
        text = read(path)
        # minting moved `key:` in front of `id:`, so the block boundaries are
        # the id lines themselves, not the `- id:` list markers
        assert f"via {ref}" in text.split("id: REQ-001", 1)[1].split("id: REQ-002", 1)[0], (
            f"the save under {ref} must land inside REQ-001's own span"
        )


def test_a_link_target_spelled_by_a_retired_id_resolves(tmp_path):
    """The same resolver resolves a link target, not just the URL's ref:
    `add_link` with target REQ-900 resolves to REQ-001 and writes the one
    composite the editor writes, DISPLAY-ID@key. On the base this is a 422
    "no item 'REQ-900' ... to link to" from the very function under fix."""
    client, root = serve_minted(tmp_path)
    _status, dec = client.get("/api/item/DEC-001")
    assert _status == 200
    _status, req = client.get("/api/item/REQ-001")
    key = req["handle"]

    status, payload = client.post(
        "/api/item/DEC-001/edit",
        {
            "op": "add_link",
            "verb": "satisfies",
            "target": "REQ-900",
            "expected_revision": sha256(decs_file(root)),
        },
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    text = read(decs_file(root))
    assert f"REQ-001@{key}" in text, text
    assert "REQ-900" not in text, "the retired spelling is never written into a link"


def test_no_refusing_path_writes_anything(tmp_path):
    """The no-write posture for this task's two refusals, each driven every
    way the write route can be driven: the unknown ref (`REQ-999`, resolved
    nowhere) and the double-claim (`REQ-900`, claimed by REQ-002 and
    REQ-003). For each: set_field, set_body and add_link are all refused,
    the tree is byte-identical after, and no file appears in `items/`."""
    # the two refusals need two projects: one directory per case, the
    # fixtures write the same `items/reqs.yaml`
    unknown_root = tmp_path / "unknown"
    unknown_root.mkdir()
    claim_root = tmp_path / "claim"
    claim_root.mkdir()
    cases = [
        (retired_root(unknown_root), "REQ-999", ["decs.yaml", "reqs.yaml"]),
        (
            make_root(claim_root, {"reqs.yaml": CLAIM_REQS, "claim2.yaml": CLAIM_CLAIM2}),
            "REQ-900",
            ["claim2.yaml", "reqs.yaml"],
        ),
    ]
    for root, ref, item_files in cases:
        client = serve(root)
        path = reqs_file(root)
        before_tree = snapshot_tree(root)
        for payload in (
            {"op": "set_field", "field": "text", "value": "x", "expected_revision": sha256(path)},
            {"op": "set_body", "text": "nope", "expected_revision": sha256(path)},
            {"op": "add_link", "verb": "satisfies", "target": "REQ-001",
             "expected_revision": sha256(path)},
        ):
            status, _body = client.post(f"/api/item/{ref}/edit", payload)
            assert status == 422, (ref, payload, _body)
        assert snapshot_tree(root) == before_tree
        assert sorted(os.listdir(root / "items")) == item_files


# -------------------------------------------------------------- over the socket
#
# The drives above grade the route's resolution; these two pin the same
# contract on the real transport -- the `EditorApp` + `Client` pattern of
# test_serve_edit_http -- because the ticket asked for HTTP-level coverage
# where the repo has it. One for the main path, one for the loud refusal.


def test_over_http_a_retired_id_save_lands_and_reports_the_current_ref(tmp_path):
    app = EditorApp(str(make_root(tmp_path, {"reqs.yaml": REQS, "decs.yaml": DECS}) / "refdes-project.yaml"), poll_interval=60)
    root = tmp_path
    app.start()
    try:
        client = Client(app)
        _status, item = client.api_get("/api/item/REQ-900")
        assert _status == 200 and item["id"] == "REQ-001"
        status, payload = client.api_post(
            "/api/item/REQ-900/edit",
            {
                "op": "set_field",
                "field": "status",
                "value": "draft",
                "expected_revision": item["edit"]["file_revision"],
            },
        )
        assert status == 200, payload
        assert payload["kind"] == "applied"
        # the browser's correction: the CURRENT id and handle, never REQ-900
        assert payload["id"] == "REQ-001" and payload["handle"] == "REQ-001"
        text = read(reqs_file(root))
        assert "status: draft" in text.split("- id: REQ-001", 1)[1].split("- id:", 1)[0]
        assert text.count("status: draft") == 1, "REQ-002's approved status stands"
    finally:
        app.stop()


def test_over_http_a_double_claimed_retired_id_is_the_ambiguity_refusal(tmp_path):
    app = EditorApp(
        str(make_root(tmp_path, {"reqs.yaml": CLAIM_REQS, "claim2.yaml": CLAIM_CLAIM2}) / "refdes-project.yaml"),
        poll_interval=60,
    )
    root = tmp_path
    app.start()
    try:
        client = Client(app)
        before_tree = snapshot_tree(root)
        _status, item = client.api_get("/api/item/REQ-002")
        assert _status == 200
        status, payload = client.api_post(
            "/api/item/REQ-900/edit",
            {
                "op": "set_field",
                "field": "text",
                "value": "x",
                "expected_revision": item["edit"]["file_revision"],
            },
        )
        assert status == 422, payload
        assert is_ambiguity_refusal(payload), payload
        assert "REQ-002" in payload["reason"] and "REQ-003" in payload["reason"], payload
        assert snapshot_tree(root) == before_tree
    finally:
        app.stop()
