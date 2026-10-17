"""Accept: the one operation that writes the item *and* the lockfile
(docs/design/editor-source-picker.md §4 -- Slice B; the Accept half of §10's
test list).

Slice A's file proves the picker reads and writes nothing. This one is the
opposite half of the feature and the only part of it that touches tracked
state, so the assertions are about pairs: a body line and a pin that land
together, and a refusal that leaves **both** files exactly as it found them.
`snapshot_tree` over the whole project is the posture for the refusals, and an
mtime is asserted where nothing was ever written to that file at all: since
§4's pair-landing shape, a refusal inside the gate wrote NOTHING, so a moved
mtime means a write happened that should not have. §4's acknowledged residue is
a crash between the pair's two replaces, not this window.

Everything goes through the real HTTP surface on a real fixture project, in
the shape Slice A's fixture set up: a decision citing `analysis/budget.csv`,
whose `rail_load` key is already in use and whose `eff` key is sitting there
unpicked.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from helpers import _build_at
from serve_support import Client, snapshot_tree
from test_serve_sources import (  # the fixture is the feature's, not one file's
    CSV,
    ITEMS,
    fetch,
    lock,
    lock_bytes,
    make_root,
    start,
)

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes.serve import edit as edit_mod
from refdes.write_lock import project_write_lock

EDIT = "/api/item/DEC-001/edit"
CSV_PATH = "analysis/budget.csv"
RAIL = 'P = source("analysis/budget.csv", "rail_load") | W'
EFF = 'eff = source("analysis/budget.csv", "eff") | 1'


def calc_body(*lines) -> str:
    """An item body of exactly one calc block holding these lines -- the shape
    the fixture's `body: |` parses to, and the shape the browser would post
    after inserting a picked line at the caret."""
    return "```calc\n" + "".join(line + "\n" for line in lines) + "```\n"


def revision(root, rel="items/decisions.yaml") -> str:
    """The file's content revision, spelled the way the client spells it."""
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def pin(key, *, path=CSV_PATH, unit="1", name=None, **extra):
    entry = {"path": path, "key": key, "unit": unit}
    if name is not None:
        entry["name"] = name
    entry.update(extra)
    return entry


def accept(client, root, *, text, pins, ref="DEC-001", rev=None, **overrides):
    payload = {
        "op": "set_body",
        "text": text,
        "pin": pins,
        "expected_revision": rev if rev is not None else revision(root),
    }
    payload.update(overrides)
    return client.api_post(f"/api/item/{ref}/edit", payload)


@pytest.fixture
def served(tmp_path):
    """The fixture project, fetched -- so `rail_load` is pinned and `eff` is
    not, which is the state an accept is made from."""
    root = make_root(tmp_path)
    fetch(root)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def unpinned(tmp_path):
    """The same project nobody has ever fetched: no `.refdes/citations.yaml`."""
    root = make_root(tmp_path)
    assert not (root / ".refdes" / "citations.yaml").exists()
    return root


def pinned_values(root, path=CSV_PATH):
    records = lock(root)["citations"]
    return {k: v["value"] for k, v in (records[path]["values"]).items()}


# ------------------------------------------------------------------ it lands


def test_accept_writes_the_body_and_the_lockfile_together(served):
    _app, client, root = served
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    # the line, in the body, on disk
    assert EFF in (root / "items" / "decisions.yaml").read_text("utf-8")
    # the pin, in the lockfile, on disk -- read by the reader, not by the browser
    assert pinned_values(root) == {"rail_load": "1.85", "eff": "0.93"}
    # and the response says what it pinned, so the panel can say it back
    assert payload["pinned"] == [
        {"path": CSV_PATH, "key": "eff", "reader": "csv", "value": "0.93"}
    ]
    assert payload["revision"] == revision(root)
    assert payload["diagnostics"] == []


def test_an_accepted_value_resolves_with_no_cli_step_in_between(served):
    # The point of §4: pick, accept, and the number is in the build. A plain
    # `refdes fetch` afterwards finds nothing to do -- which is the proof that
    # what accept wrote is a lockfile fetch recognizes as already correct, not
    # an approximation of one that the next command quietly repairs.
    _app, client, root = served
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 200, payload
    before = lock_bytes(root)

    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch"]) == 0
    assert lock_bytes(root) == before, "fetch did not recognize the record accept wrote"

    project = build_mod.build(_build_at(root))
    assert not [d for d in project.diagnostics if d.level == "error"]
    dec = next(i for i in project.local_items if i.id == "DEC-001")
    line = next(line for line in dec.calcs if line.name == "eff")
    assert line.error is None
    assert line.source_path == CSV_PATH and line.source_key == "eff"
    assert line.source_locked == "0.93", "the row is not evaluating the pinned number"


def test_a_picked_value_saves_and_resolves_without_a_cli_step(served):
    """Follow the panel's three reads and its one write through HTTP, then
    inspect the refreshed item and served preview without running fetch."""
    app, client, root = served
    status, listed = client.api_get("/api/item/DEC-001/sources")
    assert status == 200, listed
    path = next(file["path"] for file in listed["files"] if file["browse"] == "rows")
    status, rows = client.api_get(f"/api/item/DEC-001/sources/entries?path={path}&q=eff")
    assert status == 200, rows
    chosen = next(entry for entry in rows["entries"] if entry["key"] == "eff")
    assert chosen["selectable"] and chosen["value"] == "0.93"

    status, initial = client.api_get(
        f"/api/item/DEC-001/sources/propose?path={path}&key={chosen['key']}"
    )
    assert status == 200 and not initial["complete"] and initial["line"] is None
    status, proposal = client.api_get(
        f"/api/item/DEC-001/sources/propose?path={path}&key={chosen['key']}&unit=1&name={initial['name']}"
    )
    assert status == 200 and proposal["complete"], proposal
    status, before = client.api_get("/api/item/DEC-001")
    assert status == 200, before
    body = before["body"].replace("```\n", proposal["line"] + "\n```\n", 1)
    assert proposal["line"] in body

    status, saved = client.api_post(EDIT, {
        "op": "set_body",
        "text": body,
        "expected_revision": before["edit"]["file_revision"],
        "pin": [{
            "path": proposal["path"], "key": proposal["key"],
            "unit": proposal["unit"], "name": proposal["name"],
        }],
    })
    assert status == 200, saved
    assert saved["pinned"][0]["value"] == "0.93"
    status, after = client.api_get("/api/item/DEC-001")
    assert status == 200, after
    assert proposal["line"] in after["body"]
    page = app.preview.open_file([after["page"]])
    assert page is not None
    with page:
        html = page.read().decode("utf-8")
    table = html[html.index('<table class="calc"'):]
    table = table[:table.index("</table>")]
    assert 'class="calc-name">eff' in table
    assert 'class="calc-result">0.93' in table


def test_accept_of_an_unpinned_citation_pins_the_hash_and_the_value_in_one_record(
    tmp_path,
):
    # §4: "A file with no record at all is different and is allowed: fetch pins
    # the hash and extracts in one write, and so does accept." The record has
    # to be the record fetch would have made -- same five keys, same shapes --
    # or the next fetch looks at the file and sees something it did not write.
    root = unpinned(tmp_path)
    app = start(root)
    try:
        status, payload = accept(
            Client(app), root, text=calc_body(RAIL), pins=pin("rail_load", unit="W")
        )
        assert status == 200, payload
    finally:
        app.stop()

    record = lock(root)["citations"][CSV_PATH]
    assert set(record) == {"sha256", "fetched", "kept_copy", "bytes", "values"}
    assert record["sha256"] == hashlib.sha256(CSV.encode("utf-8")).hexdigest()
    assert record["kept_copy"] is False
    assert record["bytes"] == len(CSV.encode("utf-8"))
    assert record["fetched"]
    assert record["values"] == {"rail_load": {"reader": "csv", "value": "1.85"}}


def test_accept_never_replaces_an_existing_value_for_a_different_key(served):
    # `_refresh_pinned_sources` replaces the whole `values` map because a fetch
    # walked every body in the project and knows every key it uses. Accept is
    # being asked for one key from one item, so the keys it was not asked about
    # have to survive being left out -- including a key nothing cites any more,
    # which is exactly the pin a fetch would drop and accept must not.
    _app, client, root = served
    other = 'other_v = source("analysis/budget.csv", "other") | 1'
    status, payload = accept(
        client, root, text=calc_body(RAIL, other), pins=pin("other", name="other_v")
    )
    assert status == 200, payload
    assert pinned_values(root) == {"rail_load": "1.85", "other": "7"}

    status, payload = accept(
        client, root, text=calc_body(RAIL, other, EFF), pins=pin("eff", name="eff")
    )
    assert status == 200, payload
    assert pinned_values(root) == {"rail_load": "1.85", "other": "7", "eff": "0.93"}, (
        "accept rewrote a key it was not asked about"
    )


def test_accept_pins_the_value_the_reader_read_not_the_value_the_browser_sent(served):
    # §5: there is no second parser, and that is not a style rule. A `value` in
    # the request is not trusted, checked, or echoed -- it is not a field the
    # operation has.
    _app, client, root = served
    status, payload = accept(
        client,
        root,
        text=calc_body(RAIL, EFF),
        pins=pin("eff", name="eff", value="999.5"),
    )
    assert status == 200, payload
    assert pinned_values(root)["eff"] == "0.93"
    assert payload["pinned"][0]["value"] == "0.93"


def test_a_re_accept_of_an_already_pinned_key_does_not_touch_the_lockfile(served):
    # Nothing new is pinned, so nothing is written: the staged bytes are the
    # bytes on disk. `fetched` is a timestamp, and a save that changed no value
    # has no business moving it.
    _app, client, root = served
    before_bytes = lock_bytes(root)
    before_stat = os.stat(root / ".refdes" / "citations.yaml")
    status, payload = accept(
        client, root, text=calc_body(RAIL), pins=pin("rail_load", unit="W")
    )
    assert status == 200, payload
    assert lock_bytes(root) == before_bytes
    assert os.stat(root / ".refdes" / "citations.yaml").st_mtime_ns == (
        before_stat.st_mtime_ns
    )


# ------------------------------------------------------------------- it refuses


def test_accept_refuses_a_changed_file_and_directs_fetch_update(served):
    # §4: "The browser never re-pins a changed file." Re-accepting a changed
    # source value is Jared's acceptance gate and stays a deliberate act in a
    # terminal where the `old -> new` diff is printed.
    _app, client, root = served
    (root / CSV_PATH).write_text(
        CSV.replace("eff,0.93", "eff,0.61"), encoding="utf-8", newline=""
    )
    before = snapshot_tree(root)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422
    assert payload["kind"] == "refused"
    assert "changed since it was pinned" in payload["reason"]
    assert f"refdes fetch --update --path {CSV_PATH}" in payload["reason"]
    assert snapshot_tree(root) == before


def test_a_refused_accept_leaves_both_the_item_file_and_the_lockfile_byte_identical(
    served,
):
    # A refusal decided before any write -- here, a body that does not name the
    # key it asks to pin. Neither file is touched, not even its mtime.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    before = snapshot_tree(root)
    item_mtime = os.stat(item_file).st_mtime_ns
    lock_mtime = os.stat(lock_file).st_mtime_ns

    status, payload = accept(
        client, root, text=calc_body(RAIL), pins=pin("eff", name="eff")
    )
    assert status == 422
    assert payload["kind"] == "refused"
    assert "names no source() call" in payload["reason"]
    assert snapshot_tree(root) == before
    assert os.stat(item_file).st_mtime_ns == item_mtime
    assert os.stat(lock_file).st_mtime_ns == lock_mtime, "the refusal wrote the lockfile"


def test_a_diagnostic_gate_refusal_never_writes_the_lockfile(served):
    # §4 step 6, the first two-file transaction the editor performs. The pin
    # is valid and has to be staged before the candidate can be judged -- the
    # in-memory overlay is the only way the new `source()` line resolves --
    # and then the body breaks the build for its own reason. The gate's
    # `Invalid` comes back unchanged, and the lockfile never moves: under §4's
    # pair-landing shape a refusal inside the gate has written nothing, so
    # there is no rollback for it to perform.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    before = snapshot_tree(root)
    item_mtime = os.stat(item_file).st_mtime_ns

    status, payload = accept(
        client,
        root,
        text=calc_body(RAIL, EFF, "eff = 2 | 1"),
        pins=pin("eff", name="eff"),
    )
    assert status == 422, payload
    assert payload["kind"] == "invalid", payload
    assert snapshot_tree(root) == before, "the gate refused but the pin stayed"
    assert os.stat(item_file).st_mtime_ns == item_mtime, "the body was written anyway"


def test_a_failure_inside_the_gate_lands_neither_file(served, monkeypatch):
    # §4's window, read-only: the accept's bytes are staged, and something
    # fails inside the gate. Nothing was ever written, so the refusal leaves
    # the tree byte-for-byte as it was -- the item file never moved (not even
    # its mtime), and the lockfile never appeared.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    before = snapshot_tree(root)
    item_mtime = os.stat(item_file).st_mtime_ns

    real = edit_mod.loader.load_readonly

    def load(config, overlay=None, lockfile_overlay=None):
        if overlay:  # the candidate load, whose gate is read-only now
            raise RuntimeError("simulated failure inside the gate")
        return real(config, overlay=overlay, lockfile_overlay=lockfile_overlay)

    monkeypatch.setattr(edit_mod.loader, "load_readonly", load)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "simulated failure" in payload["reason"]
    assert snapshot_tree(root) == before
    assert os.stat(item_file).st_mtime_ns == item_mtime


OTHER = 'o = source("analysis/budget.csv", "other") | 1'


def test_a_conflicting_accept_does_not_unpin_a_save_that_already_landed(
    served, monkeypatch
):
    # WRITE-CONCUR-001 (the PR #134 review's HIGH): a cooperating server
    # lands its whole accept -- body and pin -- mid-gate, in the window
    # before this accept's late revision check. The old shape's rollback
    # restored the bytes *this* writer had read, deleting that save's pin
    # while its body, which names the pin, sat on disk: `refdes check` then
    # failed the project on a line the loser never wrote. Under §4's
    # pair-landing shape this accept writes nothing before the landing
    # section, the revision check conflicts it there, and the conflict lands
    # nothing -- the winner's pin stands under the body naming it, and the
    # winner's project still checks.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    original_gate = edit_mod._blocking_diagnostics

    def another_accept_lands_midflight(before, after, item, op):
        # Stand in for the other process's *applied* writes, as they exist at
        # this instant: its lockfile, read fresh and extended with its own
        # pin, and its body naming that pin.
        records = citations_mod.load_lockfile(_build_at(root))
        records[CSV_PATH].setdefault("values", {})["other"] = {
            "reader": "csv",
            "value": "7",
        }
        lock_file.write_bytes(
            citations_mod.lockfile_text(records).encode("utf-8")
        )
        text = item_file.read_text("utf-8")
        item_file.write_text(
            text.replace(
                "      " + RAIL + "\n",
                "      " + RAIL + "\n      " + OTHER + "\n",
                1,
            ),
            "utf-8",
        )
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", another_accept_lands_midflight)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    # the winner's body is on disk, and its pin is still what the loser's
    # rollback would have destroyed
    assert OTHER in item_file.read_text("utf-8")
    assert "other" in lock(root)["citations"][CSV_PATH]["values"]
    # the project is not left in the state neither save can fix from the editor
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0


def test_a_refused_accept_of_a_never_fetched_project_leaves_no_lockfile(
    tmp_path, monkeypatch
):
    # A refusal in the gate lands nothing, and the staged bytes of a project
    # with no lockfile at all must not become one: a project that has never
    # been fetched stays a project that has never been fetched.
    root = unpinned(tmp_path)
    app = start(root)
    try:
        real = edit_mod.loader.load_readonly

        def load(config, overlay=None, lockfile_overlay=None):
            if overlay:
                raise RuntimeError("simulated failure inside the gate")
            return real(config, overlay=overlay, lockfile_overlay=lockfile_overlay)

        monkeypatch.setattr(edit_mod.loader, "load_readonly", load)
        status, payload = accept(
            Client(app), root, text=calc_body(RAIL), pins=pin("rail_load", unit="W")
        )
        assert status == 422, payload
    finally:
        app.stop()
    assert not (root / ".refdes" / "citations.yaml").exists()


def test_a_body_line_for_a_key_that_was_not_pinned_is_still_refused(served):
    # Accept is the only way a `source()` line gets a pin, and the ordinary
    # save still refuses the line without one: widening `set_body` did not open
    # a route from a body to an unpinned key.
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = accept(client, root, text=calc_body(RAIL, EFF), pins=[])
    assert status == 422, payload
    assert payload["kind"] == "invalid"
    assert any("no locked value" in d["message"] for d in payload["diagnostics"])
    assert snapshot_tree(root) == before


def test_accept_re_validates_a_key_that_stopped_being_selectable(tmp_path):
    # Between the proposal and the accept the file moved: `eff` is now on two
    # rows, and the reader refuses a duplicated key rather than choosing one.
    # The accept asks for the same key it proposed and is refused by the row --
    # which is why the pick is re-validated under the lock instead of trusted
    # from the earlier request.
    root = make_root(tmp_path)
    app = start(root)
    try:
        client = Client(app)
        status, proposal = client.api_get(
            "/api/item/DEC-001/sources/propose?path=analysis/budget.csv&key=eff&unit=1"
        )
        assert status == 200, proposal
        (root / CSV_PATH).write_text(
            CSV + "eff,0.50,a second row with the same key\n", encoding="utf-8", newline=""
        )
        before = snapshot_tree(root)
        status, payload = accept(
            client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
        )
        assert status == 422, payload
        assert "cannot be picked" in payload["reason"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


# ------------------------------------------------- refusals inherited, not new


def test_a_no_write_server_offers_the_picker_and_refuses_accept(tmp_path):
    root = make_root(tmp_path)
    fetch(root)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        status, payload = client.api_get(
            "/api/item/DEC-001/sources/propose?path=analysis/budget.csv&key=eff&unit=1"
        )
        assert status == 200, payload
        assert payload["line"] == EFF
        before = snapshot_tree(root)
        status, payload = accept(
            client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
        )
        assert status == 403
        assert "--no-write" in payload["error"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


def test_accept_refuses_a_sealed_item_with_the_existing_reason(tmp_path):
    # Slice B adds no refusal code for a sealed entry: the accept rides the
    # `set_body` path, and the path already refuses it. The reason string is the
    # one every other edit to this entry gets, asserted rather than assumed --
    # a second copy of the message is how the two start to disagree.
    root = make_root(tmp_path, items=ITEMS + (
        "  - id: LOG-001\n"
        "    type: log\n"
        "    summary: Recorded the rail budget.\n"
        "    citations:\n"
        "      - path: analysis/budget.csv\n"
    ))
    build_mod.build(_build_at(root), seal_write=True)
    assert list((root / ".refdes").glob("log-seal*.yaml")), "the fixture did not seal"
    app = start(root)
    try:
        client = Client(app)
        before = snapshot_tree(root)
        status, payload = client.api_post(
            "/api/item/LOG-001/edit",
            {
                "op": "set_body",
                "text": calc_body(EFF),
                "pin": pin("eff", name="eff"),
                "expected_revision": revision(root),
            },
        )
        assert status == 422, payload
        assert payload["kind"] == "refused"
        assert "sealed append-only entry" in payload["reason"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


def test_accept_refuses_an_imported_item_with_the_existing_reason(tmp_path):
    upstream = {
        "title": "Platform",
        "version": "1.0",
        "items": [
            {
                "id": "IFC-001",
                "type": "decision",
                "fields": {"citations": [{"path": "analysis/budget.csv"}]},
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    root = make_root(tmp_path)
    (root / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    with (root / "refdes-project.yaml").open("a", encoding="utf-8") as fh:
        fh.write("\nimports:\n  - name: platform\n    items: upstream.json\n")
    app = start(root)
    try:
        client = Client(app)
        before = snapshot_tree(root)
        status, payload = client.api_post(
            "/api/item/IFC-001/edit",
            {
                "op": "set_body",
                "text": calc_body(EFF),
                "pin": pin("eff", name="eff"),
                "expected_revision": revision(root),
            },
        )
        assert status == 422, payload
        assert "imported item; imports are read-only" in payload["reason"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


# ------------------------------------------------------ the request's own shape


@pytest.mark.parametrize(
    "bad",
    [
        {"pin": "analysis/budget.csv"},  # not an object
        {"pin": {"path": CSV_PATH}},  # no key
        {"pin": {"key": "eff"}},  # no path
        {"pin": [{"path": CSV_PATH, "key": "eff", "unit": "1"}, "nope"]},
        {"pin": {"path": CSV_PATH, "key": "eff", "unit": 7}},
    ],
)
def test_a_malformed_pin_is_a_400_not_a_partial_write(served, bad):
    _app, client, root = served
    before = snapshot_tree(root)
    payload = {
        "op": "set_body",
        "text": calc_body(RAIL, EFF),
        "expected_revision": revision(root),
    }
    payload.update(bad)
    status, answer = client.api_post(EDIT, payload)
    assert status == 400, answer
    assert "error" in answer and "reason" not in answer
    assert snapshot_tree(root) == before


def test_a_pin_on_an_op_that_cannot_name_it_is_a_400(served):
    # Not a refusal and not a silent drop: a pin has nowhere to live without a
    # body naming it, and saving the body separately would be exactly the
    # half-commit §4 exists to prevent.
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = client.api_post(
        EDIT,
        {
            "op": "set_field",
            "field": "title",
            "value": "x",
            "pin": pin("eff", name="eff"),
            "expected_revision": revision(root),
        },
    )
    assert status == 400, payload
    assert "only accepted on op 'set_body'" in payload["error"]
    assert snapshot_tree(root) == before


def test_the_op_name_is_still_set_body(served):
    # §10: the picker posts `set_body` and "never a new op name". There is one
    # mutation entry point and widening the request is not adding a door.
    _app, client, root = served
    before = snapshot_tree(root)
    for op in ("accept_source", "pin_source", "source_accept"):
        status, payload = client.api_post(
            EDIT,
            {
                "op": op,
                "text": calc_body(RAIL, EFF),
                "pin": pin("eff", name="eff"),
                "expected_revision": revision(root),
            },
        )
        assert status == 400, (op, payload)
    assert snapshot_tree(root) == before


def test_a_refused_accept_says_nothing_about_the_server_filesystem(served):
    # Slice A's invariant, and Accept is where a new message could break it:
    # the extraction failure and the drift refusal both name a file, and the
    # only name they are allowed is the project-relative one.
    _app, client, root = served
    (root / CSV_PATH).write_text(
        CSV.replace("eff,0.93", "eff,0.61"), encoding="utf-8", newline=""
    )
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422
    text = json.dumps(payload)
    assert str(root) not in text
    assert "analysis/budget.csv" in text


# ----------------------------------------------------------------- #182 family
#
# The shape #182 closed: the accept used to write the lockfile BEFORE the
# gate and restore it on refusal. That put a window both ways -- (a) a
# cooperating accept of the SAME key is an adoption this accept's byte compare
# cannot see (its own write looks like a no-op), so the loser's restore
# erased the winner's adopted pin from under a body naming it; and (b) a
# cooperating accept gating over *this* accept's write could roll back inside
# this accept's gate, deleting the pin from under the body this accept then
# landed. Both left a tree naming an unpinned pair: `refdes check` fails the
# project. The probes below are the net for the pair that now lands in one
# section -- probes 1 and 2 verified RED on the old shape, probe "already
# pinned" verified RED at the first fix's head.

EXTRA = 'x = 2 | 1'


def items_yaml(*lines) -> str:
    """`ITEMS` with DEC-001's body set to exactly these lines -- what a
    cooperating accept's applied save leaves on disk. Derived from `ITEMS`
    so the simulated writer and the fixture cannot drift apart."""
    body = "".join("      " + line + "\n" for line in lines)
    original = "      " + RAIL + "\n"
    assert ITEMS.count(original) == 1, "the fixture's DEC-001 body moved"
    return ITEMS.replace(original, body)


def pin_eff_records(root):
    """The fetched project's records with `eff` pinned -- the bytes a
    same-key accept stages, spelled from the records on disk."""
    records = citations_mod.load_lockfile(_build_at(root))
    records[CSV_PATH].setdefault("values", {})["eff"] = {"reader": "csv", "value": "0.93"}
    return records


def test_a_conflicting_accept_does_not_erase_a_pin_a_same_key_accept_adopted(
    served, monkeypatch
):
    # A cooperating accept of the same key lands mid-gate -- its lockfile
    # byte-identical to this accept's staged bytes, its body naming the pin
    # on disk -- and this accept then conflicts on the body's revision. The
    # old shape's rollback compared the winner's bytes to its own staged
    # bytes, found them equal, judged them its own, and restored the
    # pre-accept file -- erasing the adoption from under the winner's body.
    # This accept now writes nothing before the gate, so the conflict lands
    # nothing and the adoption stands.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    original_gate = edit_mod._blocking_diagnostics

    def same_key_accept_lands_midflight(before, after, item, op):
        # The winner's whole applied state, as it exists at this instant:
        # its lockfile (byte-identical to the bytes this accept staged --
        # the premise the assertion below pins) and its body, which differs
        # from the loser's -- both inside one section of the project lock,
        # as a real applied save lands them.
        with project_write_lock(str(root)):
            lock_file.write_bytes(
                citations_mod.lockfile_text(pin_eff_records(root)).encode("utf-8")
            )
            item_file.write_text(items_yaml(RAIL, EFF, EXTRA), "utf-8")
        return original_gate(before, after, item, op)

    monkeypatch.setattr(
        edit_mod, "_blocking_diagnostics", same_key_accept_lands_midflight
    )
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 409, payload
    assert payload["kind"] == "conflict"
    # the winner's adopted pin stands under the body naming it, and it
    # stands AS the bytes this accept staged -- the scenario's premise,
    # pinned so a silent divergence cannot turn this probe into a test of
    # some other branch
    assert lock_bytes(root) == citations_mod.lockfile_text(
        pin_eff_records(root)
    ).encode("utf-8"), "the writer's bytes were not this accept's staged bytes"
    assert "eff" in lock(root)["citations"][CSV_PATH]["values"]
    assert EFF in item_file.read_text("utf-8")
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0


def test_a_refused_accept_does_not_delete_a_pin_from_under_a_landed_body(
    served, monkeypatch
):
    # The window runs the other way: a cooperating accept of the same key
    # lands mid-gate (its lockfile is byte-identical to this accept's
    # staged bytes), and this accept refuses inside its own gate. The old
    # shape's rollback restored the bytes it read -- a file not pinning the
    # key the landed body names. This accept wrote nothing, so the refusal
    # leaves the landed state standing.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    real = edit_mod.loader.load_readonly

    def load(config, overlay=None, lockfile_overlay=None):
        if overlay:  # the candidate load, after this accept's decision
            with project_write_lock(str(root)):
                lock_file.write_bytes(
                    citations_mod.lockfile_text(pin_eff_records(root)).encode("utf-8")
                )
                item_file.write_text(items_yaml(RAIL, EFF), "utf-8")
            raise RuntimeError("simulated failure inside the gate")
        return real(config, overlay=overlay, lockfile_overlay=lockfile_overlay)

    monkeypatch.setattr(edit_mod.loader, "load_readonly", load)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    # the landed body names `eff`, so `eff` stays pinned -- on exactly the
    # bytes this accept had staged, which is the scenario's premise
    assert lock_bytes(root) == citations_mod.lockfile_text(
        pin_eff_records(root)
    ).encode("utf-8")
    assert "eff" in lock(root)["citations"][CSV_PATH]["values"]
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0


def test_an_accept_survives_a_writer_that_moved_the_lockfile_midgate(
    served, monkeypatch
):
    # A cooperating writer rewrote the lockfile during the gate. The pair
    # this accept brings is not collateral for a compare to skip: the accept
    # re-stages over the writer's records under fetch's own policy and lands
    # both files. The writer's pin survives in the bytes that land.
    _app, client, root = served
    lock_file = root / ".refdes" / "citations.yaml"
    original_gate = edit_mod._blocking_diagnostics

    def a_pin_lands_during_the_gate(before, after, item, op):
        records = citations_mod.load_lockfile(_build_at(root))
        records[CSV_PATH].setdefault("values", {})["other"] = {"reader": "csv", "value": "7"}
        with project_write_lock(str(root)):
            lock_file.write_bytes(citations_mod.lockfile_text(records).encode("utf-8"))
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", a_pin_lands_during_the_gate)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert EFF in (root / "items" / "decisions.yaml").read_text("utf-8")
    values = lock(root)["citations"][CSV_PATH]["values"]
    assert {"eff", "other", "rail_load"} <= set(values)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0


def test_a_writer_that_already_pinned_the_key_lands_its_own_pins_too(
    served, monkeypatch
):
    # The moved-file branch's other half, and the review's regression: the
    # writer's file pins this accept's key AND a key this accept does not
    # carry, and a body naming that other key has landed. This accept's
    # staged bytes predate the writer and lack its pin, so writing them
    # would erase it -- the clobber class this PR exists to close, from the
    # other side. The file stands and only the body lands.
    _app, client, root = served
    lock_file = root / ".refdes" / "citations.yaml"
    extra = root / "items" / "extra.yaml"
    original_gate = edit_mod._blocking_diagnostics

    def a_writer_lands_a_body_and_pins_both(before, after, item, op):
        records = citations_mod.load_lockfile(_build_at(root))
        values = records[CSV_PATH].setdefault("values", {})
        values["eff"] = {"reader": "csv", "value": "0.93"}
        values["other"] = {"reader": "csv", "value": "7"}
        with project_write_lock(str(root)):
            # both inside one section of the project lock, as a real
            # applied save lands them (see the same-key probe above)
            extra.write_text(
                "defaults: { type: decision }\n"
                "items:\n"
                "  - id: DEC-500\n"
                "    citations:\n"
                "      - path: analysis/budget.csv\n"
                "    body: |\n"
                "      ```calc\n"
                '      O = source("analysis/budget.csv", "other") | 1\n'
                "      ```\n",
                "utf-8",
            )
            lock_file.write_bytes(citations_mod.lockfile_text(records).encode("utf-8"))
        return original_gate(before, after, item, op)

    monkeypatch.setattr(
        edit_mod, "_blocking_diagnostics", a_writer_lands_a_body_and_pins_both
    )
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert EFF in (root / "items" / "decisions.yaml").read_text("utf-8")
    values = lock(root)["citations"][CSV_PATH]["values"]
    assert {"eff", "other", "rail_load"} <= set(values), values
    # The tree the pair lands in builds: both bodies name pinned keys.
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 0


def test_a_writer_that_repinned_the_key_during_the_gate_makes_the_accept_refuse(
    served, monkeypatch
):
    # The moved file pins this accept's key, but at a DIFFERENT value than
    # the one this accept read -- a `fetch --update` of a changed source
    # landed during the gate. The gate judged the body's calc line against
    # 0.93. Landing the body over the writer's 0.61 lands a tree whose gate
    # was never judged; overwriting the writer's file with the staged bytes
    # is this PR's own clobber. Neither: the accept refuses, the writer's
    # file stands, and the repair is a fresh accept against it.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    original_gate = edit_mod._blocking_diagnostics

    def the_key_is_repinned(before, after, item, op):
        records = citations_mod.load_lockfile(_build_at(root))
        records[CSV_PATH].setdefault("values", {})["eff"] = {
            "reader": "csv", "value": "0.61",
        }
        with project_write_lock(str(root)):
            lock_file.write_bytes(citations_mod.lockfile_text(records).encode("utf-8"))
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", the_key_is_repinned)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "'0.61'" in payload["reason"], payload
    assert "'0.93'" in payload["reason"], payload
    assert EFF not in item_file.read_text("utf-8"), (
        "the body landed over a pin the gate never judged"
    )
    values = lock(root)["citations"][CSV_PATH]["values"]
    assert values["eff"]["value"] == "0.61", "the accept overwrote the writer's pin"


def test_a_reextraction_reading_a_new_value_during_the_gate_refuses(
    served, monkeypatch
):
    # The merge half of the same hole: a cooperating `fetch --update` lands
    # during the gate -- the source file's bytes move, and the lockfile's
    # record names the NEW bytes, pinning a key this accept does not carry.
    # This accept's key is not pinned, so the landing section re-stages over
    # the writer's records, and the reader now reads 0.61 where the gate was
    # judged on 0.93. The pair is refused, not landed; the writer stands.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    csv_file = root / "analysis" / "budget.csv"
    original_gate = edit_mod._blocking_diagnostics

    def a_fetch_update_lands(before, after, item, op):
        new_csv = (
            "key,value,note\n"
            "rail_load,9.99,recalibrated\n"
            "eff,0.61,datasheet rev F\n"
            "other,7,x\n"
        )
        records = citations_mod.load_lockfile(_build_at(root))
        record = records[CSV_PATH]
        record["sha256"] = hashlib.sha256(new_csv.encode("utf-8")).hexdigest()
        record["bytes"] = len(new_csv.encode("utf-8"))
        record["values"] = {"other": {"reader": "csv", "value": "7"}}
        with project_write_lock(str(root)):
            csv_file.write_text(new_csv, "utf-8", newline="")
            lock_file.write_bytes(citations_mod.lockfile_text(records).encode("utf-8"))
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", a_fetch_update_lands)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "'0.61'" in payload["reason"], payload
    assert "'0.93'" in payload["reason"], payload
    assert EFF not in item_file.read_text("utf-8"), (
        "the body landed on a re-extraction the gate never judged"
    )
    assert "eff" not in lock(root)["citations"][CSV_PATH]["values"], (
        "the accept landed the drifted re-extraction"
    )


def test_a_moved_lockfile_over_a_changed_source_file_is_refused(served, monkeypatch):
    # The landing section's third outcome, which every sibling branch has a
    # probe for and this did not: the file moved, this accept's pair is NOT
    # pinned in it, and the re-stage finds the record's bytes are not the
    # file's bytes anymore. fetch's own refusal fires inside the landing
    # section, points at `refdes fetch --update`, the pair lands nowhere,
    # and the writer's file stands.
    _app, client, root = served
    item_file = root / "items" / "decisions.yaml"
    lock_file = root / ".refdes" / "citations.yaml"
    csv_file = root / "analysis" / "budget.csv"
    original_gate = edit_mod._blocking_diagnostics

    def the_bytes_move_under_the_records(before, after, item, op):
        records = citations_mod.load_lockfile(_build_at(root))
        records[CSV_PATH].setdefault("values", {})["other"] = {"reader": "csv", "value": "7"}
        new_csv = (
            "key,value,note\n"
            "rail_load,1.85,mW budget\n"
            "eff,0.61,datasheet rev F\n"
            "other,7,x\n"
        )
        with project_write_lock(str(root)):
            lock_file.write_bytes(citations_mod.lockfile_text(records).encode("utf-8"))
            csv_file.write_text(new_csv, "utf-8", newline="")
        return original_gate(before, after, item, op)

    monkeypatch.setattr(edit_mod, "_blocking_diagnostics", the_bytes_move_under_the_records)
    status, payload = accept(
        client, root, text=calc_body(RAIL, EFF), pins=pin("eff", name="eff")
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "changed since it was pinned" in payload["reason"], payload
    assert "fetch --update" in payload["reason"], payload
    assert EFF not in item_file.read_text("utf-8")
    assert "eff" not in lock(root)["citations"][CSV_PATH]["values"]
