"""Contract tests for `POST /api/navis/archive` and `POST /api/navis/restore`
(design in-prog-logs/navis-design-20261025.md §6, §7.3, §9, §11, and §12's
journal refusal; parity with the CLI verbs -- cli.py `_navis_write_verb`,
which renders the same `navis_ops.apply` Outcome).

Black-box over HTTP: the tests import no module under test -- nothing from
`serve.navis_write`, and `navis_ops` only as the monkeypatch seam of the
unknown-outcome-kind test. They import the fixture machinery (`EditorApp`,
the shipped `cli`, and the public store reader `navis_archive.load_records`)
to seed state and assert the JSON contract the routes must answer with.
`navis_archive.archive_record` / `restore_record` are patched only on the
OSError tests, where the module attribute IS the specified patch target.

Selector rules mirrored from `navis_ops.select` (which cli.py's
`_navi_select` delegates to): the full 11-char key, a unique 6..10-char key
prefix (ambiguous names its candidates), then the Show-all ordinal -- the
list `navis.projection` numbers (active first, then archived, orphans last).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes import keys, navis_archive, navis_ops
from refdes.serve.server import EditorApp

ARCHIVE = "/api/navis/archive"
RESTORE = "/api/navis/restore"

SCHEMA = (
    "site: { title: Navis Write, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

ALPHA_TEXT = "Alpha model worst-case copper temperature."
BETA_TEXT = "Beta recheck decoupling near U14."


def _note(item_id: str, title: str, text: str, key: str = "") -> str:
    return (
        f"---\nid: {item_id}\ntype: note\ntitle: {title}\n---\n"
        f"intro\n<!--navi:{key} {text}-->\n"
    )


def _run_cli(config: str, *args: str) -> int:
    return cli_mod.main(["-c", config, *args])


def _project(tmp_path, files: dict[str, str]) -> str:
    """Write the project, then one writable load (`navis ls`) so the markers
    carry minted keys -- the CLI tests' `_mint` recipe (test_navis_archive_cli)."""
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8", newline="")
    _run_cli(str(config), "navis", "ls")
    return str(config)


_MARKER_KEY = re.compile(r"<!--navi:([0-9a-z]{11}) ")


def _navi_keys(root) -> list[str]:
    """The minted Navi keys, in (file, line) order -- the order `ls`/Show-all
    numbers (navis.projection)."""
    out: list[str] = []
    for name in sorted((root / "items").iterdir()):
        out += _MARKER_KEY.findall(name.read_text(encoding="utf-8"))
    return out


def start(root, **kw) -> EditorApp:
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def serve(tmp_path):
    """Build a Navi project under tmp_path and serve it live. The server is
    started after all CLI seeding, which is what the file-watcher test
    fixtures do everywhere (poll_interval=60 keeps the watcher idle)."""
    apps: list[EditorApp] = []

    def _serve(files: dict[str, str], **kw):
        _project(tmp_path, files)
        app = start(tmp_path, **kw)
        apps.append(app)
        return app, Client(app), tmp_path

    yield _serve
    for app in apps:
        app.stop()


NOTES = {"note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT)}


@pytest.fixture
def served(serve):
    """One project: a single active keyed Navi on NOTE-001."""
    return serve(NOTES)


def _post(client, verb: str, selector):
    return client.api_post(f"/api/navis/{verb}", {"navi": selector})


def _ok(payload, verb: str, key: str, changed: bool) -> None:
    assert payload["kind"] == "ok"
    assert payload["verb"] == verb
    assert payload["key"] == key
    assert payload["changed"] is changed


def _conflict(payload, reason: str) -> None:
    assert payload["kind"] == "conflict"
    assert payload["reason"] == reason
    assert payload["error"]


# ---------------------------------------------------------------------------
# success: the verbs archive and restore exactly the named Navi (§6, §9)
# ---------------------------------------------------------------------------


def test_archive_by_full_key_writes_the_record_and_reports_ok(served):
    _app, client, root = served
    key = _navi_keys(root)[0]
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    _ok(payload, "archive", key, True)
    records, diagnostics = navis_archive.load_records(str(root))
    assert diagnostics == []
    assert [r.navi_key for r in records] == [key]
    record = records[0]
    assert record.text == ALPHA_TEXT
    assert record.source["file"] == "items/note-a.md"
    lines = (root / "items" / "note-a.md").read_text(encoding="utf-8").splitlines()
    assert record.source["line"] == next(
        i for i, ln in enumerate(lines, 1) if "<!--navi:" in ln
    )
    assert record.item_key  # the source item's key, §6


def test_archive_by_unique_prefix_reports_the_full_key(served):
    _app, client, root = served
    key = _navi_keys(root)[0]
    status, payload = _post(client, "archive", key[:6])
    assert status == 200, payload
    _ok(payload, "archive", key, True)


def test_an_integer_ordinal_is_accepted(served):
    _app, client, root = served
    key = _navi_keys(root)[0]
    status, payload = client.api_post(ARCHIVE, {"navi": 1})
    assert status == 200, payload
    _ok(payload, "archive", key, True)


def test_ordinal_selectors_number_the_show_all_list(tmp_path):
    """Ordinals address the same list `refdes navis all` numbers: active
    first, then archived (navis.projection)."""
    config = _project(tmp_path, {
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
        "note-b.md": _note("NOTE-002", "Beta", BETA_TEXT),
    })
    keys = _navi_keys(tmp_path)
    assert _run_cli(config, "navis", "archive", keys[1]) == 0  # Beta archived
    app = start(tmp_path)
    try:
        client = Client(app)
        status, payload = _post(client, "archive", "1")
        assert status == 200, payload
        _ok(payload, "archive", keys[0], True)  # row 1: the active Alpha
        # archiving Alpha leaves [Alpha, Beta] as the archived rows in file
        # order, so row 2 is still the pre-archived Beta -- and archiving it
        # again is the no-op (changed: false, the CLI's exit-0 path).
        status, payload = _post(client, "archive", "2")
        assert status == 200, payload
        _ok(payload, "archive", keys[1], False)
    finally:
        app.stop()


def test_archiving_an_already_archived_navi_changes_no_bytes(served):
    """The CLI no-ops with exit 0; the HTTP analogue is 200 changed:false
    with the record file's bytes untouched (no re-write, no re-stamp, §9)."""
    _app, client, root = served
    key = _navi_keys(root)[0]
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    path = navis_archive.record_path(str(root), key)
    before_bytes = Path(path).read_bytes()
    before_tree = snapshot_tree(root)
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    _ok(payload, "archive", key, False)
    assert Path(path).read_bytes() == before_bytes
    assert snapshot_tree(root) == before_tree


def test_restore_of_an_edited_archived_navi_returns_the_live_text(served):
    """§9 row 4: the live marker text changed under the archive record.
    Restore is the record's removal -- it succeeds (200, changed true) and
    the panel shows the LIVE edited text as an active row (the §9 note says
    the snapshot is never re-stamped; the live marker wins)."""
    _app, client, root = served
    key = _navi_keys(root)[0]
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    source = root / "items" / "note-a.md"
    text = source.read_text(encoding="utf-8")
    assert ALPHA_TEXT in text
    edited = ALPHA_TEXT + " (edited)"
    source.write_text(text.replace(ALPHA_TEXT, edited), encoding="utf-8", newline="")
    status, payload = _post(client, "restore", key)
    assert status == 200, payload
    _ok(payload, "restore", key, True)
    status, panel = client.api_get("/api/navis")
    assert status == 200, panel
    rows = [r for r in panel["navis"] if r["key"] == key]
    assert len(rows) == 1
    assert rows[0]["archived"] is False
    assert rows[0]["text"] == edited


def test_restore_round_trip_returns_the_store_to_its_original_state(served):
    """archive -> restore leaves the whole project tree byte-identical to
    before (the §7.3 invariant, round-tripped)."""
    _app, client, root = served
    key = _navi_keys(root)[0]
    before = snapshot_tree(root)
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    assert Path(navis_archive.record_path(str(root), key)).exists()
    status, payload = _post(client, "restore", key)
    assert status == 200, payload
    _ok(payload, "restore", key, True)
    records, _diags = navis_archive.load_records(str(root))
    assert records == []
    assert snapshot_tree(root) == before


def test_restore_by_prefix_removes_the_record(tmp_path):
    config = _project(tmp_path, NOTES)
    key = _navi_keys(tmp_path)[0]
    assert _run_cli(config, "navis", "archive", key) == 0
    app = start(tmp_path)
    try:
        client = Client(app)
        status, payload = _post(client, "restore", key[:6])
        assert status == 200, payload
        _ok(payload, "restore", key, True)
        assert not (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()
    finally:
        app.stop()


# ---------------------------------------------------------------------------
# §7.3: the write touches ONLY .refdes/navis/
# ---------------------------------------------------------------------------


def test_archive_changes_no_file_outside_the_navis_store(served):
    _app, client, root = served
    key = _navi_keys(root)[0]
    before = snapshot_tree(root)
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    after = snapshot_tree(root)
    assert set(before) - set(after) == set()  # nothing removed
    added = set(after) - set(before)
    assert added and all(rel.startswith(".refdes/navis/") for rel in added)
    for rel, digest in before.items():
        if not rel.startswith(".refdes/navis/"):
            assert after[rel] == digest, f"archive touched {rel}"


def test_restore_changes_no_file_outside_the_navis_store(tmp_path):
    config = _project(tmp_path, NOTES)
    key = _navi_keys(tmp_path)[0]
    assert _run_cli(config, "navis", "archive", key) == 0
    app = start(tmp_path)
    try:
        client = Client(app)
        before = snapshot_tree(tmp_path)
        status, payload = _post(client, "restore", key)
        assert status == 200, payload
        after = snapshot_tree(tmp_path)
        assert set(after) - set(before) == set()  # nothing added
        assert set(before) - set(after) == {f".refdes/navis/{key}.yaml.gz"}
        for rel, digest in before.items():
            if not rel.startswith(".refdes/navis/"):
                assert after[rel] == digest, f"restore touched {rel}"
    finally:
        app.stop()


# ---------------------------------------------------------------------------
# 409 conflicts (§9, §12): not_archived, orphan, keyless, journal_pending
# ---------------------------------------------------------------------------


def test_restore_of_an_active_navi_is_not_archived(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = _post(client, "restore", "1")
    assert status == 409, payload
    _conflict(payload, "not_archived")
    assert snapshot_tree(root) == before


def test_restore_of_an_orphan_refuses_and_keeps_the_record(tmp_path):
    """§9 row 3: the marker is gone, so there is nothing to reactivate;
    the record must stay on disk (restore refuses, it never deletes)."""
    config = _project(tmp_path, NOTES)
    key = _navi_keys(tmp_path)[0]
    assert _run_cli(config, "navis", "archive", key) == 0
    (tmp_path / "items" / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\nintro\n",
        encoding="utf-8",
        newline="",
    )
    app = start(tmp_path)
    try:
        client = Client(app)
        path = navis_archive.record_path(str(tmp_path), key)
        before_bytes = Path(path).read_bytes()
        before = snapshot_tree(tmp_path)
        status, payload = _post(client, "restore", key)
        assert status == 409, payload
        _conflict(payload, "orphan")
        assert Path(path).read_bytes() == before_bytes  # the record stays
        assert snapshot_tree(tmp_path) == before
    finally:
        app.stop()


KEYLESS_PROJECT = {
    # a folded YAML block body cannot be spliced at the marker's source
    # position, so the marker stays keyless (test_navis_archive_cli recipe)
    "entries.yaml": (
        "items:\n  - id: NOTE-100\n    type: note\n    title: L\n"
        "    body: >\n      list body\n      <!--navi: list marker-->\n"
    )
}


@pytest.mark.parametrize("verb", ["archive", "restore"])
def test_a_keyless_navi_is_refused_as_keyless(serve, verb):
    _app, client, root = serve(KEYLESS_PROJECT)
    before = snapshot_tree(root)
    status, payload = _post(client, verb, "1")
    assert status == 409, payload
    _conflict(payload, "keyless")
    assert snapshot_tree(root) == before


@pytest.mark.parametrize("verb", ["archive", "restore"])
def test_a_pending_journal_blocks_every_write(tmp_path, verb):
    """§12: a live `.refdes/editor-transaction/` means the store refuses
    every write. The dir is created by this test; the tree must not change.
    Both selectors name a genuine write on the served snapshot (seeded via
    the CLI before the server starts): A active (the archive write), B
    archived with its marker intact (the restore write)."""
    config = _project(tmp_path, {
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
        "note-b.md": _note("NOTE-002", "Beta", BETA_TEXT),
    })
    keys = _navi_keys(tmp_path)
    assert _run_cli(config, "navis", "archive", keys[1]) == 0
    app = start(tmp_path)
    try:
        client = Client(app)
        journal = tmp_path / ".refdes" / "editor-transaction"
        journal.mkdir(parents=True)
        (journal / "journal.yaml").write_text("stub", encoding="utf-8", newline="")
        before = snapshot_tree(tmp_path)
        status, payload = _post(client, verb, "1" if verb == "archive" else keys[1])
        assert status == 409, payload
        _conflict(payload, "journal_pending")
        assert snapshot_tree(tmp_path) == before
    finally:
        app.stop()


def _key_with_prefix(prefix: str, tail: str) -> str:
    data = prefix + tail
    return data + keys.check_char(data)


AMBIGUOUS_PREFIX = "k7f3q2"
KEY_A = _key_with_prefix(AMBIGUOUS_PREFIX, "zzzz")
KEY_B = _key_with_prefix(AMBIGUOUS_PREFIX, "zyzz")


@pytest.mark.parametrize("verb", ["archive", "restore"])
def test_an_ambiguous_prefix_names_its_candidates(serve, verb):
    """Deterministic by construction: both markers carry valid keys sharing
    the same 6-char prefix (the check chars computed with keys.check_char,
    the fabricated-key recipe of test_navis_archive_cli.py:122)."""
    _app, client, root = serve({
        "amb-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT, key=KEY_A),
        "amb-b.md": _note("NOTE-002", "Beta", BETA_TEXT, key=KEY_B),
    })
    before = snapshot_tree(root)
    status, payload = _post(client, verb, AMBIGUOUS_PREFIX)
    assert status == 409, payload
    assert payload["kind"] == "ambiguous"
    # The contract is the candidate SET, keyed by key -- the spec promises
    # no payload order, so nothing here may assume one.
    by_key = {c["key"]: c for c in payload["candidates"]}
    assert set(by_key) == {KEY_A, KEY_B}
    expected = {KEY_A: (ALPHA_TEXT, "amb-a"), KEY_B: (BETA_TEXT, "amb-b")}
    for key, (text, name) in expected.items():
        cand = by_key[key]
        assert cand["text"] == text
        assert name in cand["file"].replace("\\", "/")
        assert isinstance(cand["line"], int) and cand["line"] > 0
    assert snapshot_tree(root) == before


# ---------------------------------------------------------------------------
# 404: selectors that name nothing (never a 500)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("selector", ["zzzzzz", "0", "9", "nosuchkey"])
def test_a_selector_that_names_nothing_is_not_found(served, selector):
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = _post(client, "archive", selector)
    assert status == 404, payload
    assert payload["kind"] == "not_found"
    assert payload["error"]
    assert snapshot_tree(root) == before


def test_a_giant_digit_selector_never_500s(served):
    """A 4300-digit string is out of range by length alone; int() of it
    raises in CPython, and the guard in `navis_ops.select` (the length-bound
    digit branch) mirrors that -- the route must answer 404/400, never a
    traceback."""
    _app, client, _root = served
    status, payload = _post(client, "archive", "1" * 4300)
    assert status in (400, 404), status
    assert isinstance(payload, dict) and payload["error"]


# ---------------------------------------------------------------------------
# 400: the body must be a JSON object carrying a usable selector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        [{"navi": "1"}],   # a JSON array, not an object
        "navis",           # a JSON string, not an object
        {},                # no navi
        {"navi": None},
        {"navi": 1.5},     # not a string, not an int
        {"navi": True},    # bool is not an int
        {"navi": False},
        {"navi": []},
        {"navi": {}},
        {"navi": ""},      # an empty string names nothing
    ],
)
def test_malformed_bodies_are_bad_requests(served, payload):
    _app, client, _root = served
    status, body = client.api_post(ARCHIVE, payload)
    assert status == 400, body
    assert body["kind"] == "bad_request"
    assert body["error"]


def test_a_missing_body_is_a_bad_request(served):
    _app, client, _root = served
    hdrs = {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{client.port}",
    }
    status, _h, data = client.request("POST", ARCHIVE, token=True, headers=hdrs, body=b"")
    assert status == 400
    assert json.loads(data)["error"]


# ---------------------------------------------------------------------------
# 403 and the token gate
# ---------------------------------------------------------------------------


def test_a_read_only_server_refuses_both_verbs_and_writes_nothing(tmp_path):
    _project(tmp_path, NOTES)
    app = start(tmp_path, read_only=True)
    try:
        client = Client(app)
        before = snapshot_tree(tmp_path)
        for verb in ("archive", "restore"):
            status, payload = _post(client, verb, "1")
            assert status == 403, payload
            assert payload["kind"] == "refused"
            assert "--no-write" in payload["error"]
        assert snapshot_tree(tmp_path) == before  # nothing written
    finally:
        app.stop()


def test_the_write_routes_share_the_items_create_token_gate(served):
    """The gate is route-agnostic (server.py `_api`); these routes must
    answer without the token exactly as /api/items/create does -- compare,
    never hard-code."""
    _app, client, _root = served
    body = json.dumps({"navi": "1"}).encode()
    hdrs = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"}
    ref_status, _rh, ref_data = client.request(
        "POST", "/api/items/create", body=b"{}", headers=hdrs
    )
    assert ref_status == 403  # the gate refuses a tokenless POST
    for path in (ARCHIVE, RESTORE):
        status, _h, data = client.request("POST", path, body=body, headers=hdrs)
        assert (status, data) == (ref_status, ref_data)
        status, _h, data = client.request(
            "POST", path, body=body, headers=dict(hdrs, **{"X-Refdes-Token": "wrong"})
        )
        assert status == 403
        status, _h, data = client.request("POST", path, body=body, headers=hdrs, cookie=True)
        assert status == 403  # the session cookie alone is not enough


# ---------------------------------------------------------------------------
# 405
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [ARCHIVE, RESTORE])
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_the_write_routes_reject_other_methods(served, path, method):
    _app, client, _root = served
    if method == "GET":
        status, payload = client.api_get(path)
        assert status == 405, payload
        assert payload == {"error": "method not allowed"}
    else:
        # PUT/DELETE are answered by the server itself (server.py:656-659);
        # what is pinned is that these routes are not a write surface for
        # them, same posture as test_serve_edit_http's method test.
        status, _h, _b = client.request(method, path, token=True, body=b"{}")
        assert status == 405


# ---------------------------------------------------------------------------
# 500: a store failure is a JSON error, never a traceback
# ---------------------------------------------------------------------------


def _boom(*_args, **_kwargs):
    raise OSError("disk full")


def test_a_store_write_failure_is_a_500_json_error(served, monkeypatch):
    """Patch target: `refdes.navis_archive.archive_record` -- `navis_ops.apply`
    calls it as a module attribute (`navis_archive_mod.archive_record`) and
    the serve handlers reach it through the same call, so patching the module
    attribute is the specified seam."""
    _app, client, root = served
    monkeypatch.setattr(navis_archive, "archive_record", _boom)
    before = snapshot_tree(root)
    status, payload = _post(client, "archive", "1")
    assert status == 500, payload
    assert payload["kind"] == "error"
    assert "disk full" in payload["error"]
    assert snapshot_tree(root) == before
    assert not (root / ".refdes" / "navis").exists()


def test_a_store_remove_failure_is_a_500_json_error(tmp_path, monkeypatch):
    config = _project(tmp_path, NOTES)
    key = _navi_keys(tmp_path)[0]
    assert _run_cli(config, "navis", "archive", key) == 0
    app = start(tmp_path)
    try:
        client = Client(app)
        monkeypatch.setattr(navis_archive, "restore_record", _boom)
        before = snapshot_tree(tmp_path)
        status, payload = _post(client, "restore", key)
        assert status == 500, payload
        assert payload["kind"] == "error"
        assert "disk full" in payload["error"]
        assert snapshot_tree(tmp_path) == before
        assert (tmp_path / ".refdes" / "navis" / f"{key}.yaml.gz").exists()
    finally:
        app.stop()


def test_an_unknown_outcome_kind_is_a_500_json_error(served, monkeypatch):
    """The handler is a renderer: a kind it has never seen (a future
    `navis_ops` addition) must answer 500 JSON naming the kind, never
    raise in the handler thread and drop the connection."""
    _app, client, root = served

    def _fake_apply(*_args, **_kwargs):
        return navis_ops.Outcome("brand_new_kind")

    monkeypatch.setattr(navis_ops, "apply", _fake_apply)
    before = snapshot_tree(root)
    status, payload = _post(client, "archive", "1")
    assert status == 500, payload
    assert payload["kind"] == "error"
    assert "brand_new_kind" in payload["error"]
    assert snapshot_tree(root) == before


# ---------------------------------------------------------------------------
# freshness: the served page reflects the write (the save-then-rebuild path)
# ---------------------------------------------------------------------------


def _preview(client, app, item_id: str) -> str:
    slug = app.state.snapshot.project.item_by_id(item_id).slug
    status, _h, body = client.page(f"/preview/{slug}.html")
    assert status == 200
    return body.decode("utf-8")


def test_the_served_page_shows_archived_after_the_write(served):
    """§11: the panel refreshes on the save-then-rebuild refresh the editor
    already runs -- the write handler rebuilds before it answers, so the
    next GET of the source item's page is current (poll_interval=60 leaves
    the watcher no chance to do it behind the handler's back)."""
    app, client, _root = served
    key = _navi_keys(_root)[0]
    html = _preview(client, app, "NOTE-001")
    assert 'class="refdes-navis"' in html
    assert ALPHA_TEXT in html
    assert "[archived]" not in html
    status, payload = _post(client, "archive", key)
    assert status == 200, payload
    html = _preview(client, app, "NOTE-001")
    assert "Show all" in html
    assert ALPHA_TEXT in html
    assert "[archived]" in html
    status, payload = _post(client, "restore", key)
    assert status == 200, payload
    html = _preview(client, app, "NOTE-001")
    assert ALPHA_TEXT in html  # active again
    assert "[archived]" not in html
