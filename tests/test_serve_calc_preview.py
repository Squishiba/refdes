"""The live editor's calc-preview route: `POST /api/item/<ref>/calc`
(in-prog-logs/inline-calc-live-editor-design-20261020.md §3.3, slice A/B3).

The `serve_support.Client` live-`EditorApp` posture of
`test_serve_edit_http.py`: a real server, real tokens and Origin checks,
and -- the proof that matters for a route the editor fires on every pause
-- `snapshot_tree` byte-identity: a preview request must leave every file
in the project byte-for-byte as it found it. The response's `revision` is
pinned to the item's file revision (the form's revision space, §3.6), not
the project-wide `/api/revision` revision. The fidelity pin is the oracle
test: the same text through `loader.load_readonly(overlay=...)` -- a real
full build of the same snapshot -- reports exactly what the route reported.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, snapshot_tree

from refdes import build as build_mod
from refdes import loader
from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Calc preview http test"
id:
  width: 3
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

DECS = """\
defaults: { type: decision }
items:
  - id: DEC-001
    title: Use the buck regulator.
    body: |
      Baseline prose.
"""

LOG = """\
defaults: { type: log }
items:
  - id: LOG-001
    summary: Started the rail work.
"""

CALC_PATH = "/api/item/DEC-001/calc"

# One body line with the panel's three live states.
DRAFT = (
    "Rail `Vout := 2.218 V * 2 = 4.436 V` stale `Vbad := 2 V * 2 = 5 V` "
    "half `Vhalf := 3 V *`\n"
)


def make_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {"decs.yaml": DECS, "log.yaml": LOG}.items():
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


def decs_file(root) -> str:
    return str(root / "items" / "decs.yaml")


def calc(client, *, ref="DEC-001", **payload):
    return client.api_post(f"/api/item/{ref}/calc", payload)


# ---------------------------------------------------------------- the shape


def test_the_response_shape_is_the_contract(served):
    _app, client, _root = served
    status, payload = calc(client, text=DRAFT)
    assert status == 200, payload
    assert set(payload) == {"revision", "spans"}, payload  # no cut: no `truncated` key
    assert payload["spans"] == [
        {
            "line": 0, "start": 6, "end": 35, "result_start": 28, "result_end": 35,
            "name": "Vout", "status": "ok", "computed": "4.436 V", "message": "",
        },
        {
            "line": 0, "start": 44, "end": 65, "result_start": 62, "result_end": 65,
            "name": "Vbad", "status": "stale", "computed": "4 V",
            "message": "inline calc Vbad: stored result says 5 V, now computes 4 V",
        },
        {
            "line": 0, "start": 73, "end": 87,
            "name": "Vhalf := 3 V *", "status": "error", "computed": "",
            "message": "inline calc Vhalf := 3 V *: stored result missing; write '= <quantity>'",
        },
    ]


def test_the_route_is_registered_beside_the_edit_branch(served):
    _app, client, _root = served
    status, payload = client.api_get(CALC_PATH)
    assert status == 405, payload
    # ...and the edit route is undisturbed
    status, _payload = client.api_post("/api/item/DEC-001/edit", {"op": "bogus"})
    assert status in (400, 422)


# ---------------------------------------------------------------- guards


def test_missing_text_is_400(served):
    _app, client, _root = served
    status, payload = client.api_post(CALC_PATH, {})
    assert status == 400
    assert payload == {"error": "text is required: the draft body as one string"}
    status, payload = client.api_post(CALC_PATH, {"text": 5})
    assert status == 400, payload
    status, payload = client.api_post(CALC_PATH, {"text": ["not", "a", "string"]})
    assert status == 400, payload
    # a JSON body that is not an object at all
    status, payload = client.api_post(CALC_PATH, "just a string")
    assert status == 400, payload


def test_a_non_object_fields_bag_is_400(served):
    _app, client, _root = served
    status, payload = client.api_post(CALC_PATH, {"text": DRAFT, "fields": [1, 2]})
    assert status == 400, payload
    assert "fields" in payload["error"]
    status, _payload = client.api_post(CALC_PATH, {"text": DRAFT, "fields": 5})
    assert status == 400


def test_a_fields_bag_is_validated_carried_and_ignored(served):
    _app, client, _root = served
    status, plain = calc(client, text=DRAFT)
    assert status == 200
    status, with_fields = calc(client, text=DRAFT, fields={"anything": 5, "n": None})
    assert status == 200, with_fields
    assert with_fields["spans"] == plain["spans"]
    status, empty = calc(client, text=DRAFT, fields={})
    assert status == 200 and empty["spans"] == plain["spans"]


def test_unknown_request_keys_are_ignored(served):
    # §3.3 forward-compat: the route extracts exactly its known keys, the
    # `_apply_edit` posture. Today's `fields` was once an unknown key too.
    _app, client, _root = served
    status, plain = calc(client, text=DRAFT)
    status, grown = client.api_post(
        CALC_PATH,
        {"text": DRAFT, "field_reference_mode": "on", "token_budget": 99},
    )
    assert status == 200, grown
    assert grown["spans"] == plain["spans"]


def test_an_unknown_item_is_404(served):
    _app, client, _root = served
    status, payload = calc(client, ref="DEC-999", text=DRAFT)
    assert status == 404
    assert "no item matches" in payload["error"]


def test_a_sealed_log_and_an_imported_item_are_403(tmp_path):
    # The write affordance rules answer here too: a body the author cannot
    # save is a body the preview does not evaluate ("stop the false
    # affordance", §3.3 / editor.js:45-53).
    root = make_root(tmp_path)
    project = _build_at(root)
    build_mod.build(project, seal_write=True)
    assert list((root / ".refdes").glob("log-seal*.yaml")), "the fixture did not seal"
    upstream = {
        "title": "Platform",
        "version": "1.0",
        "items": [
            {
                "id": "IFC-001",
                "type": "decision",
                "fields": {"title": "Imported decision."},
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    (root / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    with (root / "refdes-project.yaml").open("a", encoding="utf-8") as fh:
        fh.write("\nimports:\n  - name: platform\n    items: upstream.json\n")
    app = start(root)
    try:
        client = Client(app)
        _status, view = client.api_get("/api/item/IFC-001")
        assert view["external"] is True
        # the 400 shape guard runs before the 403 affordance guard, on a
        # body this route would refuse outright:
        status, payload = client.api_post("/api/item/LOG-001/calc", {})
        assert status == 400, (status, payload)  # missing text, not 403
        for ref, reason in (
            ("LOG-001", "sealed"),
            ("IFC-001", "imported"),
        ):
            status, payload = calc(client, ref=ref, text=DRAFT)
            assert status == 403, (ref, payload)
            assert reason in payload["error"], payload
            assert set(payload) == {"error"}
    finally:
        app.stop()


# ----------------------------------------------------------- inertness


def test_preview_requests_change_nothing_on_disk(served):
    _app, client, root = served
    before = snapshot_tree(root)
    for body in (
        {"text": DRAFT},
        {"text": DRAFT, "fields": {"title": "drafted"}},
        {"text": '`P := source("a.csv", "k") | W = 1 W`\n'},
        {"text": "`V := NOWHERE-001.V = 1 V`\n"},
        {"text": ""},
    ):
        status, payload = client.api_post(CALC_PATH, body)
        assert status == 200, (body, payload)
    assert snapshot_tree(root) == before, "a preview request wrote to the project"


# ------------------------------------------------------------- revision


def test_the_revision_is_the_items_file_revision_not_the_projects(served):
    _app, client, root = served
    status, payload = calc(client, text=DRAFT)
    assert status == 200
    # The string the form holds (`GET /api/item/<ref>` -> edit.file_revision,
    # api.py:825) and sends as `expected_revision` -- the §3.6 guard's space.
    _status, view = client.api_get("/api/item/DEC-001")
    assert payload["revision"] == view["edit"]["file_revision"]
    assert payload["revision"] == sha256(decs_file(root))
    # Not the project-wide `/api/revision` revision (state.py:305): a
    # string space the form never holds.
    _status, project_wide = client.api_get("/api/revision")
    assert payload["revision"] != project_wide["revision"]


def test_the_revision_moves_when_the_file_moves(served):
    app, client, root = served
    _status, first = calc(client, text=DRAFT)
    assert first["revision"] == sha256(decs_file(root))
    # Someone else saves the file (the CLI, a second tab): the snapshot
    # rebuilds, and both the form's and the preview's revision follow.
    with open(decs_file(root), "w", encoding="utf-8") as fh:
        fh.write(DECS.replace("Baseline prose.", "Rail `Vout := 1 V = 1 V`."))
    assert app.state.refresh() is True, "the fixture did not rebuild the model"
    _status, second = calc(client, text=DRAFT)
    assert second["revision"] == sha256(decs_file(root))
    assert second["revision"] != first["revision"]
    _status, view = client.api_get("/api/item/DEC-001")
    assert second["revision"] == view["edit"]["file_revision"]


# ------------------------------------------------------------- the cap


def test_the_cap_truncates_at_the_span_limit(served):
    # Exactly the limit: no `truncated`, all rows. One over: `truncated`,
    # the first 200 rows in source order.
    _app, client, _root = served
    status, payload = calc(
        client, text="".join(f"`A{i} := 1 V = 1 V`\n" for i in range(200))
    )
    assert status == 200 and len(payload["spans"]) == 200
    assert "truncated" not in payload, payload
    status, payload = calc(
        client, text="".join(f"`A{i} := 1 V = 1 V`\n" for i in range(201))
    )
    assert status == 200
    assert payload["truncated"] is True
    assert len(payload["spans"]) == 200
    assert payload["spans"][0]["name"] == "A0" and payload["spans"][-1]["name"] == "A199"
    status, payload = calc(client, text=DRAFT)
    assert "truncated" not in payload, payload  # omitted, not false


def test_the_guards_run_in_a_fixed_order(served):
    # 400 shape before 404 target: a malformed request is rejected on its
    # body, not its ref (the api.py order: text -> fields -> _find_item ->
    # edit_state).
    _app, client, _root = served
    status, payload = client.api_post("/api/item/DEC-999/calc", {"text": 5})
    assert status == 400, (status, payload)
    assert "text is required" in payload["error"]
    # 404 target before 403 affordance: unknown refs answer 404 even
    # though the write path's 403 space (sealed/imported) is what a known
    # sealed item would answer.
    status, payload = client.api_post("/api/item/NOPE-001/calc", {"text": DRAFT})
    assert status == 404, (status, payload)


# ---------------------------------------------------------------- oracle


def test_the_route_and_a_full_overlay_build_agree_on_every_status(served):
    # The fidelity pin (§5): `loader.load_readonly(overlay=...)` is a real
    # full build of the drafted text. The narrow pass may not drift from it
    # -- the panel's rows must be the build's own verdicts, verbatim.
    _app, client, root = served
    status, payload = calc(client, text=DRAFT)
    assert status == 200
    overlay = DECS.replace("      Baseline prose.\n", "      " + DRAFT.rstrip() + "\n")
    assert overlay != DECS
    built = loader.load_readonly(
        str(root / "refdes-project.yaml"),
        overlay={decs_file(root): overlay},
    )
    item = next(i for i in built.local_items if i.id == "DEC-001")
    diags = [
        (d.level, d.message)
        for d in built.diagnostics
        if d.item_id == "DEC-001" and d.message.startswith("inline calc")
    ]
    assert [r["message"] for r in payload["spans"] if r["message"]] == [
        message for _level, message in diags
    ]
    by_name = {r["name"]: r for r in payload["spans"]}
    assert by_name["Vbad"]["computed"] == item.calc_values["Vbad"]
    assert by_name["Vout"]["computed"] == item.calc_values["Vout"]
    # the real build agrees on the statuses it owns (error is import-fatal
    # in the narrow pass's posture; the build reports it as a diagnostic)
    assert by_name["Vout"]["status"] == "ok"
    assert by_name["Vbad"]["status"] == "stale"
