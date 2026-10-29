"""End-to-end: the live inline-calc panel's exact wire loop, over the real
server (in-prog-logs/inline-calc-live-editor-design-20261020.md §5 slice B,
the item the node harness cannot prove: §3.3 + §3.6 + the save round-trip).

What lives in the browser is proven under node in
``test_editor_live_calc.py``; what lives in the route in
``test_serve_calc_preview.py``. This file is the seam between them: the
byte-for-byte loop the panel performs -- GET the item, POST the draft text
to ``/calc``, convert the returned line-relative result ranges to document
offsets, replace the stale spans last-to-first (exactly live-calc.js's
rules, re-implemented against the real payloads), POST ``set_body`` with
the form's own revision, and read the file back. The pins that matter:

- the response ``revision`` equals the form's ``file_revision`` (the guard
  space) and a calc request changes no file;
- auto-fill touches ONLY the stale span: the ok-within-window literal
  ``4.4 V`` (computed ``4.436 V``) survives byte-for-byte (§3.5, D1);
- the save lands on disk with the filled text, and the next full build of
  the saved bytes reports NO "stored result says" diagnostic -- the fill
  made the item true, not just quiet (§5 slice B: "fill, save, check").
"""

from __future__ import annotations

import hashlib

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, snapshot_tree

from refdes.serve.server import EditorApp

SCHEMA = """\
site:
  title: "Live calc e2e"
id:
  width: 3
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
"""

# One body line with the panel's two auto-fill states: `Vout` is ok within
# the rounding window (stored 4.4 V, computes 4.436 V at the default 4
# sigfigs -- D1: NEVER rewritten), `Vbad` is stale (stored 5 V, computes
# 4 V).  The fence above them pins that a real build sees the block and the
# panel's span is on the line it names.
BODY = (
    "```calc\n"
    "V_in = 3.3 V\n"
    "```\n"
    "\n"
    "Rail `Vout := 2.218 V * 2 = 4.4 V` feeds `Vbad := 2 V * 2 = 5 V`.\n"
)

DECS = f"""\
defaults: {{ type: decision }}
items:
  - id: DEC-001
    title: Pick the rail.
    body: |
      {'      '.join(BODY.splitlines(keepends=True))}"""


def make_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    return tmp_path


@pytest.fixture
def served(tmp_path):
    root = make_root(tmp_path)
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60)
    app.start()
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def sha256(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def decs_file(root) -> str:
    return str(root / "items" / "decs.yaml")


# ---- the client-side rules live-calc.js enforces, against REAL payloads:
# line-relative (line, result_start, result_end) -> document offsets, stale
# rows only, last-to-first (live-calc.js `applySpans`/`toOffsets`).


def to_document_offset(text: str, line: int, col: int) -> int:
    lines = text.split("\n")
    return sum(len(part) + 1 for part in lines[:line]) + col


def auto_fill(text: str, spans: list[dict]) -> str:
    targets = [s for s in spans if s["status"] == "stale" and s["computed"]]
    out = text
    for span in sorted(targets, key=lambda s: (s["line"], s["result_start"]), reverse=True):
        start = to_document_offset(out, span["line"], span["result_start"])
        end = to_document_offset(out, span["line"], span["result_end"])
        out = out[:start] + span["computed"] + out[end:]
    return out


# ---------------------------------------------------------------- the loop


def test_the_panel_loop_from_get_to_saved_bytes(served):
    _app, client, root = served
    path = decs_file(root)

    # 1. open: the form holds the body and its own file revision
    _status, view = client.api_get("/api/item/DEC-001")
    body = view["body"]
    assert "Vbad := 2 V * 2 = 5 V" in body, view
    form_revision = view["edit"]["file_revision"]

    # 2. the open flush: a calc request, byte-identity, guard-space revision
    before = snapshot_tree(root)
    status, payload = client.api_post(
        "/api/item/DEC-001/calc", {"text": body, "fields": {}}
    )
    assert status == 200, payload
    assert snapshot_tree(root) == before, "a calc request wrote to the project"
    assert payload["revision"] == form_revision, (
        "the panel's revision guard compares this against the form's own "
        "revision: the two spaces must meet here (§3.6)"
    )

    # 3. the rows the panel would render, on the body as the form holds it
    by_name = {span["name"]: span for span in payload["spans"]}
    assert by_name["Vout"]["status"] == "ok"
    assert by_name["Vout"]["computed"] == "4.436 V"
    assert by_name["Vbad"]["status"] == "stale"
    assert by_name["Vbad"]["computed"] == "4 V"
    assert by_name["Vbad"]["result_start"] is not None

    # 4. apply under the panel's rules: stale rows only, last-to-first
    filled = auto_fill(body, payload["spans"])
    assert "Vbad := 2 V * 2 = 4 V" in filled
    assert "= 5 V" not in filled
    assert "Vout := 2.218 V * 2 = 4.4 V" in filled, (
        "the ok-within-window literal was rewritten by a faithful client: "
        "the auto-fill gate is `stale`, never `computed != stored` (§3.5, D1)"
    )
    assert "```calc\nV_in = 3.3 V\n```" in filled, "the fill disturbed the fence above"

    # 5. the author saves through the normal edit route with the form's revision
    status, saved = client.api_post(
        "/api/item/DEC-001/edit",
        {"op": "set_body", "text": filled, "expected_revision": form_revision},
    )
    assert status == 200, saved
    with open(path, encoding="utf-8") as fh:
        text_on_disk = fh.read()
    assert "Vbad := 2 V * 2 = 4 V" in text_on_disk
    assert "= 5 V" not in text_on_disk
    assert "Vout := 2.218 V * 2 = 4.4 V" in text_on_disk, (
        "the saved bytes disturbed the ok span"
    )
    assert saved["revision"] == sha256(path)

    # 6. the panel re-requests on the post-save text: the guard passes on the
    #    form's ADVANCED revision and the stale row is gone
    _status, view2 = client.api_get("/api/item/DEC-001")
    assert view2["edit"]["file_revision"] == saved["revision"]
    status, payload2 = client.api_post(
        "/api/item/DEC-001/calc", {"text": view2["body"], "fields": {}}
    )
    assert status == 200, payload2
    assert payload2["revision"] == view2["edit"]["file_revision"]
    after = {span["name"]: span for span in payload2["spans"]}
    assert after["Vbad"]["status"] == "ok", payload2
    assert after["Vout"]["status"] == "ok"

    # 7. the truth pin: a full build of the saved bytes reports no stale-
    #    result diagnostic at all -- the fill made the item true, §5 slice B
    built = _build_at(root)
    stale_says = [
        d.message
        for d in built.diagnostics
        if d.item_id == "DEC-001" and "stored result says" in d.message
    ]
    assert stale_says == [], stale_says


def test_the_form_revision_survives_the_save_sequence_of_the_real_editor(served):
    # editor.js posts one op per request and threads the RESPONSE revision
    # into the next expected_revision (postAll); the panel's guard reads the
    # same form variable. Two sequential saves must move both together.
    _app, client, _root = served
    _status, view = client.api_get("/api/item/DEC-001")
    rev = view["edit"]["file_revision"]
    for marker in ("first", "second"):
        status, payload = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "set_body", "text": f"{marker} prose\n", "expected_revision": rev},
        )
        assert status == 200, payload
        rev = payload["revision"]
        status, calc = client.api_post("/api/item/DEC-001/calc", {"text": f"{marker} prose\n"})
        assert status == 200
        assert calc["revision"] == rev, (
            "the calc revision must track the form's revision after each "
            "save: the guard compares them (§3.6)"
        )
