"""One author session, end to end, against a live server.

The slices each landed with their own contract tests -- `test_serve_edit_http`
for field edits, `test_serve_edit_http_links` for link ops, `test_serve_create`
for creation -- and each of those is right in isolation. What none of them
proves is that the pieces compose the way a person actually uses them: create
an item, then edit *that* item using the revision the create handed back, then
link it to something that already existed, then collide with another edit, then
bump into a sealed entry -- one continuous session, no fixture reset between
steps.

So this module is a story, not a grid. Every step asserts both halves of the
promise: the HTTP response the browser sees, and the FILE state behind it.
Between steps the whole project tree is hashed, in the `test_no_write.py`
posture: the only files allowed to differ are the exact ones that step was
supposed to touch. The second test replays the same session against a
`--no-write` server, where every operation must be a 403 and the tree must not
move a byte.

The fixture is a temp project; nothing here touches this repo's own `items/`.
"""

from __future__ import annotations

import difflib
import hashlib
import threading

import pytest
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, snapshot_tree

from refdes import build as build_mod
from refdes import keys as keys_mod
from refdes.serve.server import EditorApp

# Keys are minted at import so the fixture text can name them: the composite
# a link write is supposed to produce (`REQ-001@<key>`) is only assertable if
# the fixture knows the target's key up front.
K_REQ1 = keys_mod.mint()
K_DEC1 = keys_mod.mint()
K_LOG1 = keys_mod.mint()

SCHEMA = """\
site:
  title: "Editor e2e"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  amends: { inverse: amended_by, label: Amends }
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
      status: { type: enum, choices: [proposed, accepted] }
    links:
      satisfies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
    links:
      amends: [log]
"""

REQS = f"""\
# the list comment: must survive every step of this scenario
defaults: {{ type: requirement, board: board-a }}
items:
  - id: REQ-001
    key: {K_REQ1}
    text: The rail shall supply 3.3 V.   # trailing comment, likewise
    status: approved
  - id: REQ-002
    text: The board shall boot within 2 s.
"""

DECS = f"""\
defaults: {{ type: decision, board: board-a }}
items:
  - id: DEC-001
    key: {K_DEC1}
    title: Use the buck regulator.
    status: accepted
    satisfies: [REQ-001@{K_REQ1}]
"""

LOG = f"""\
defaults: {{ type: log, board: board-a }}
items:
  - id: LOG-001
    key: {K_LOG1}
    summary: Started the rail work.
"""


def make_root(tmp_path):
    """The fixture project, already in the state a real one is in: keys
    present, the clean log entry sealed by an ordinary writable build."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {"reqs.yaml": REQS, "decs.yaml": DECS, "log.yaml": LOG}.items():
        (items / name).write_text(text, encoding="utf-8", newline="\n")
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)
    assert list((tmp_path / ".refdes").glob("log-seal*.yaml")), "the fixture did not seal"
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


def changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    """Every path whose bytes differ, including appearances and disappearances."""
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def spans(before: str, after: str) -> list[tuple[str, str, str]]:
    """The regions that differ, as (kind, old_text, new_text) over whole lines.

    The byte-fidelity probe: an edit that disturbs more than its own span -- a
    reflowed quote, a reordered key, a comment eaten by the round trip -- shows
    up here as an extra region, or a region wider than the edit asked for.
    """
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new)
    return [
        (tag, "".join(old[i1:i2]), "".join(new[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


# --------------------------------------------------------------- the scenario


def test_a_full_author_session(served):
    """Create -> edit -> link -> conflict -> sealed refusal, one session."""
    _app, client, root = served
    decs = str(root / "items" / "decs.yaml")
    reqs = str(root / "items" / "reqs.yaml")
    log = str(root / "items" / "log.yaml")
    ledger = root / ".refdes" / "ids.yaml"

    reqs_at_start = read(reqs)
    log_at_start = read(log)
    tree = snapshot_tree(root)

    # -- Step 0: the sealed entry is sealed, and the view says so unprompted.
    _status, sealed_view = client.api_get("/api/item/LOG-001")
    assert sealed_view["edit"]["editable"] is False
    assert "sealed" in sealed_view["edit"]["reason"]

    # -- Step 1: create a decision. The preview promises an id; the create
    #    delivers exactly that id, with a minted key and a usable revision.
    _status, preview = client.api_get("/api/create/preview?type=decision")
    assert preview["id"] == "DEC-002"
    assert not ledger.exists(), "a preview must reserve nothing"

    status, created = client.api_post(
        "/api/items/create",
        {
            "type": "decision",
            "fields": {"title": "Use a synchronous buck.", "status": "proposed"},
            "destination": "items/decs.yaml",
        },
    )
    assert status == 200, created
    assert created["kind"] == "created" and created["id"] == preview["id"]
    assert len(created["key"]) == 11
    assert created["path"] == "items/decs.yaml"
    assert created["revision"] == sha256(decs)

    after_create = read(decs)
    # a pure append: every byte that was there before is still there, in order
    assert after_create.startswith(DECS)
    assert "id: DEC-002" in after_create and f"key: {created['key']}" in after_create
    assert "DEC-002" in ledger.read_text(encoding="utf-8")
    # the model refreshed: the new item is addressable without a restart
    status, view = client.api_get("/api/item/DEC-002")
    assert status == 200 and view["fields"]["title"] == "Use a synchronous buck."

    step1 = changed(tree, snapshot_tree(root))
    assert step1 == {"items/decs.yaml", ".refdes/ids.yaml"}, step1
    tree = snapshot_tree(root)

    # -- Step 2: edit a field on the item created in step 1, using the
    #    revision step 1 handed back. One line moves, and it is the new
    #    item's line -- nothing else in the file, comments included.
    status, applied = client.api_post(
        "/api/item/DEC-002/edit",
        {
            "op": "set_field",
            "field": "status",
            "value": "accepted",
            "expected_revision": created["revision"],
        },
    )
    assert status == 200, applied
    assert applied["kind"] == "applied" and applied["revision"] == sha256(decs)
    assert applied["revision"] != created["revision"]

    after_edit = read(decs)
    diff2 = spans(after_create, after_edit)
    assert diff2 == [("replace", "    status: proposed\n", "    status: accepted\n")], diff2
    # the change sits inside the block created in step 1, not DEC-001's
    assert after_edit.rindex("    status: accepted") > after_edit.index("id: DEC-002")
    assert "Use the buck regulator." in after_edit and f"REQ-001@{K_REQ1}" in after_edit
    # the files this session has no business with are still the fixture's bytes
    assert read(reqs) == reqs_at_start and read(log) == log_at_start

    step2 = changed(tree, snapshot_tree(root))
    assert step2 == {"items/decs.yaml"}, step2
    tree = snapshot_tree(root)

    # -- Step 3: link the new decision to a requirement that already existed.
    #    The client sends a bare id; the server writes the composite.
    status, linked = client.api_post(
        "/api/item/DEC-002/edit",
        {
            "op": "add_link",
            "verb": "satisfies",
            "target": "REQ-001",
            "expected_revision": applied["revision"],
        },
    )
    assert status == 200, linked
    assert linked["kind"] == "applied"

    after_link = read(decs)
    composite = f"REQ-001@{K_REQ1}"
    dec002_block = after_link.split("- id: DEC-002", 1)[1]
    # the server wrote the composite, not the bare id the client sent; the
    # flow-list spelling is the patcher's choice, not the client's
    assert f"satisfies: [{composite}]" in dec002_block or f"satisfies: {composite}" in dec002_block
    assert "satisfies: REQ-001\n" not in dec002_block
    # DEC-001's own link line is untouched: the composite now appears twice
    assert after_link.count(composite) == 2
    diff3 = spans(after_edit, after_link)
    assert len(diff3) == 1 and diff3[0][0] in ("insert", "replace"), diff3
    assert composite in diff3[0][2]

    step3 = changed(tree, snapshot_tree(root))
    assert step3 == {"items/decs.yaml"}, step3
    tree = snapshot_tree(root)

    # -- Step 4: two edits race on the same item with the same stale revision.
    #    Exactly one applies; the other is a 409 carrying the diff, and the
    #    file reflects only the winner.
    stale = sha256(decs)
    results: list[tuple[int, dict]] = []
    barrier = threading.Barrier(2)

    def race(value: str):
        barrier.wait()
        results.append(
            client.api_post(
                "/api/item/DEC-002/edit",
                {
                    "op": "set_field",
                    "field": "title",
                    "value": value,
                    "expected_revision": stale,
                },
            )
        )

    threads = [
        threading.Thread(target=race, args=("Use a synchronous buck (revised).",)),
        threading.Thread(target=race, args=("Use a multiphase buck.",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    by_status = {s: b for s, b in results}
    assert sorted(by_status) == [200, 409], results
    winner, loser = by_status[200], by_status[409]
    assert winner["kind"] == "applied" and winner["revision"] == sha256(decs)
    assert loser["kind"] == "conflict" and loser["ok"] is False
    assert loser["expected_revision"] == stale
    assert loser["current_revision"] == sha256(decs)
    assert loser["current_text"] is not None
    assert "---" in loser["diff"] and "buck" in loser["diff"]

    after_race = read(decs)
    won = "Use a synchronous buck (revised)." in after_race
    lost = "Use a multiphase buck." in after_race
    assert won != lost, "exactly one racing edit may reach the file"
    # the loser's value is nowhere in the file, not even partially
    assert ("multiphase" in after_race) == lost
    # the link written in step 3 survived the race untouched
    assert composite in after_race.split("- id: DEC-002", 1)[1]

    step4 = changed(tree, snapshot_tree(root))
    assert step4 == {"items/decs.yaml"}, step4
    tree = snapshot_tree(root)

    # -- Step 5: the author tries to rewrite the sealed log entry anyway.
    #    Refused with the sealed reason, and not one byte of the log moves.
    status, refused = client.api_post(
        "/api/item/LOG-001/edit",
        {
            "op": "set_field",
            "field": "summary",
            "value": "Rewritten after the fact.",
            "expected_revision": sha256(log),
        },
    )
    assert status == 422, refused
    assert refused["kind"] == "refused" and "sealed" in refused["reason"]
    assert read(log) == log_at_start

    step5 = changed(tree, snapshot_tree(root))
    assert step5 == set(), step5

    # -- Coda: across the whole session, exactly two files ever moved.
    moved = changed(snapshot_tree(root), tree)
    assert moved <= {".refdes/ids.yaml", "items/decs.yaml"}, moved
    assert read(reqs) == reqs_at_start, "the requirements file was never part of this session"
    assert read(log) == log_at_start, "the sealed log entry was never touched"


# ------------------------------------------------- the same session, read-only


def test_the_same_session_against_a_no_write_server(tmp_path):
    """Every operation from the scenario above, replayed against `--no-write`:
    each one a 403 that says why, and the tree byte-identical at the end."""
    root = make_root(tmp_path)
    before = snapshot_tree(root)
    app = start(root, read_only=True)
    try:
        client = Client(app)

        # step 1's create
        status, body = client.api_post(
            "/api/items/create",
            {
                "type": "decision",
                "fields": {"title": "Use a synchronous buck."},
                "destination": "items/decs.yaml",
            },
        )
        assert status == 403 and "--no-write" in body["error"]

        # step 2's field edit (a bogus revision must not change the answer:
        # the gate runs before the service, so it never reaches the revision check)
        status, body = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "set_field", "field": "status", "value": "proposed", "expected_revision": "0" * 64},
        )
        assert status == 403 and "--no-write" in body["error"]

        # step 3's link op
        status, body = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "add_link", "verb": "satisfies", "target": "REQ-002", "expected_revision": "0" * 64},
        )
        assert status == 403 and "--no-write" in body["error"]

        # step 4's racing edit, and step 5's sealed-entry edit
        for ref, field in (("DEC-001", "title"), ("LOG-001", "summary")):
            status, body = client.api_post(
                f"/api/item/{ref}/edit",
                {"op": "set_field", "field": field, "value": "nope", "expected_revision": "0" * 64},
            )
            assert status == 403 and "--no-write" in body["error"]
    finally:
        app.stop()

    after = snapshot_tree(root)
    assert after == before, changed(before, after)
    assert "DEC-002" not in read(root / "items" / "decs.yaml")
