"""Contract tests for `POST /api/navis/mint` (Jared's 2026-11-05 decision:
"serve offers a mint" -- the browser surfaces gain a button on a keyless
Navi marker, backed by this route; design in-prog-logs/navis-design-20261025.md
§5 (minted per-marker keys), §7.2 (the mint is a body edit by design), §11
(the panel refreshes on the save-then-rebuild the editor already runs)).

The mint itself is `navis.mint_keys(project, write=True)`: project-wide
(per-marker mint is out of scope), exact-provenance-or-refuse, the splice
`<!--navi:` -> `<!--navi:KEY ` never changing line counts. This file pins
only the HTTP contract the route answers with; the transport rules (token
header, matching Origin, application/json) copy `tests/test_serve_navis_write.py`
exactly -- those gates are route-agnostic (`server.py::_api`), so every
transport test also asserts the tokened POST succeeds, pinning that the
gate is the only thing between the client and a live route.

Black-box over HTTP: the tests import no module under test (neither a
future `serve.navis_mint` nor the route hook in `api.py`). They import the
fixture machinery (`EditorApp`, the shipped `cli`, the public store reader
`navis_archive.load_records`), `keys` for validating minted keys, and
`refdes.revise` ONLY as the monkeypatch seam of the OSError test:
`navis.mint_keys` imports `revise.write_rewrites_verified` inside its body,
so the module attribute IS the specified patch target (the sibling's
`navis_archive.archive_record` posture).

Red before the route exists: `POST /api/navis/mint` falls through
`api.handle` to 404 {"error": "not found"} (a GET there is a 404, not a
405), so every test here fails for the missing route, not for a typo.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes import keys, navis_archive, revise
from refdes.serve.server import EditorApp

MINT = "/api/navis/mint"
ARCHIVE = "/api/navis/archive"
CREATE = "/api/items/create"

SCHEMA = (
    "site: { title: Navis Mint, out: _site }\n"
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
GAMMA_TEXT = "Gamma label the via stitching."

# A valid hand-declared key (keys.mint is the mint itself): the mint must
# leave this marker byte-identical and mint no key equal to it.
HAND_KEY = keys.mint()

_KEYED_RE = re.compile(r"<!--navi:([0-9a-z]{11}) ")
_KEYLESS_RE = re.compile(r"<!--navi:(?![0-9a-z]{11} )")


def _note(item_id: str, title: str, text: str, key: str = "") -> str:
    return (
        f"---\nid: {item_id}\ntype: note\ntitle: {title}\n---\n"
        f"intro\n<!--navi:{key} {text}-->\n"
    )


def _two(item_id: str, title: str, first: str, second: str) -> str:
    """Two keyless markers, written colon-adjacent (no space after
    `<!--navi:`), so the splice's whitespace consumption is exactly
    `key + " "` and the byte-level expectation is computable."""
    return (
        f"---\nid: {item_id}\ntype: note\ntitle: {title}\n---\n"
        f"intro\n<!--navi:{first}-->\nmid\n<!--navi:{second}-->\n"
    )


# a folded list-file `body:` scalar: mint_keys refuses to mint into it
# (test_navis_mint.py's refusal recipe), so this marker must show up in
# `still_keyless` with its file bytes untouched.
FOLDED = (
    "items:\n  - id: NOTE-100\n    type: note\n    title: L\n"
    "    body: >\n      list body\n      <!--navi: list marker-->\n"
)

MIXED = {
    "note-a.md": _two("NOTE-001", "Alpha", ALPHA_TEXT, BETA_TEXT),
    "note-b.md": (
        f"---\nid: NOTE-002\ntype: note\ntitle: Beta\n---\n"
        f"keyless\n<!--navi:{GAMMA_TEXT}-->\n"
        f"hand\n<!--navi:{HAND_KEY} Hand keyed one-->\n"
    ),
}

SIMPLE = {"note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT)}

KEYED_ONLY = {"note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT, key=HAND_KEY)}


def _write(root, files: dict[str, str]) -> str:
    config = write_project_config(root, SCHEMA)
    items = root / "items"
    items.mkdir()
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8", newline="")
    return str(config)


def _run_cli(config: str, *args: str) -> int:
    return cli_mod.main(["-c", config, *args])


def _text(root, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", newline="")


def _unsplice(text: str, minted_keys: list[str]) -> str:
    """Reverse every reported splice; the result must be the file's exact
    original text, which is the byte-level proof that the mint changed
    nothing but the keys."""
    for key in minted_keys:
        marker = f"<!--navi:{key} "
        assert text.count(marker) == 1, key
        text = text.replace(marker, "<!--navi:", 1)
    return text


def start(root, **kw) -> EditorApp:
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


@pytest.fixture
def serve(tmp_path):
    """Write a keyless-marker project under tmp_path and serve it live. No
    CLI mint seed (the sibling's `_project` runs `navis ls` to key markers;
    here the keyless markers are the fixture): the served snapshot is built
    read-only, so nothing mints behind the tests' back. poll_interval=60
    keeps the watcher idle."""
    apps: list[EditorApp] = []

    def _serve(files: dict[str, str], **kw):
        _write(tmp_path, files)
        app = start(tmp_path, **kw)
        apps.append(app)
        return app, Client(app), tmp_path

    yield _serve
    for app in apps:
        app.stop()


@pytest.fixture
def served(serve):
    """One project: a single keyless marker on NOTE-001 (writable server)."""
    return serve(SIMPLE)


def _preview(client, app, item_id: str) -> str:
    slug = app.state.snapshot.project.item_by_id(item_id).slug
    status, _h, body = client.page(f"/preview/{slug}.html")
    assert status == 200
    return body.decode("utf-8")


def _ok_mint(payload, changed: bool) -> None:
    assert payload["kind"] == "ok"
    assert payload["changed"] is changed


# ---------------------------------------------------------------------------
# success: the mint is project-wide and reports every minted marker
# ---------------------------------------------------------------------------


def test_the_mint_mints_every_keyless_marker_and_reports_them(serve):
    _app, client, _root = serve(MIXED)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)
    minted = payload["minted"]
    assert payload["still_keyless"] == 0
    assert len(minted) == 3  # every keyless marker, project-wide
    by_file: dict[str, list[str]] = {}
    for entry in minted:
        assert set(entry) >= {"key", "key6", "item", "file"}
        assert keys.malformed_key_message(entry["key"]) is None  # valid per keys.py
        assert entry["key6"] == entry["key"][:6]
        assert entry["file"].startswith("items/note-")
        by_file.setdefault(entry["file"], []).append(entry["key"])
    assert set(by_file) == {"items/note-a.md", "items/note-b.md"}  # repo-relative posix
    assert len(by_file["items/note-a.md"]) == 2
    assert len(by_file["items/note-b.md"]) == 1
    assert {e["item"] for e in minted} == {"NOTE-001", "NOTE-002"}
    all_keys = [e["key"] for e in minted]
    assert len(set(all_keys)) == 3  # unique across the project
    assert HAND_KEY not in all_keys  # ... including the already-declared key


def test_the_mint_splices_only_the_keys_and_touches_nothing_else(serve):
    _app, client, root = serve(MIXED)
    rels = ["items/note-a.md", "items/note-b.md"]
    before = {rel: _text(root, rel) for rel in rels}
    tree_before = snapshot_tree(root)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    keys_by_file: dict[str, list[str]] = {}
    for entry in payload["minted"]:
        keys_by_file.setdefault(entry["file"], []).append(entry["key"])
    for rel in rels:
        after = _text(root, rel)
        # every byte except the spliced keys is the original text
        assert _unsplice(after, keys_by_file[rel]) == before[rel]
        assert len(after.splitlines()) == len(before[rel].splitlines())
        assert after.count("<!--navi:") == before[rel].count("<!--navi:")
    # the hand-keyed marker is untouched, byte for byte
    assert f"<!--navi:{HAND_KEY} Hand keyed one-->" in _text(root, "items/note-b.md")
    after_tree = snapshot_tree(root)
    assert set(after_tree) == set(tree_before)  # nothing added, nothing removed
    changed = {rel for rel in tree_before if after_tree[rel] != tree_before[rel]}
    assert changed == set(rels)  # the minted files and nothing else
    assert not [rel for rel in after_tree if rel.startswith(".refdes/navis/")]


def test_a_second_mint_changes_nothing(serve):
    _app, client, root = serve(MIXED)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    tree = snapshot_tree(root)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, False)
    assert payload["minted"] == []
    assert payload["still_keyless"] == 0
    assert snapshot_tree(root) == tree  # idempotent: no re-write, no re-stamp


def test_a_project_with_nothing_keyless_is_a_noop(serve):
    _app, client, root = serve(KEYED_ONLY)
    path = root / "items" / "note-a.md"
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    tree = snapshot_tree(root)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, False)
    assert payload["minted"] == []
    assert payload["still_keyless"] == 0
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime  # not even opened for writing
    assert snapshot_tree(root) == tree


def test_extra_body_keys_are_ignored(served):
    _app, client, _root = served
    status, payload = client.api_post(MINT, {"force": True, "navi": "zzzzzz", "junk": [1, 2]})
    assert status == 200, payload
    _ok_mint(payload, True)
    assert len(payload["minted"]) == 1


# ---------------------------------------------------------------------------
# 400: the body must be a JSON object; the raw-JSON refusals are the server
# gate's own (the sibling's missing-body posture: 400 with an `error`, the
# gate answers before any route runs, so kind is not promised there)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        [{"key": "x"}],  # a JSON array, not an object
        "navis",         # a JSON string, not an object
        7,               # a JSON number, not an object
        7.5,
        True,            # a JSON bool, not an object
    ],
)
def test_a_non_object_body_is_a_bad_request(served, payload):
    _app, client, _root = served
    status, body = client.api_post(MINT, payload)
    assert status == 400, body
    assert body["kind"] == "bad_request"
    assert body["error"]


@pytest.mark.parametrize("raw", [b"{oops", b""])
def test_invalid_json_bodies_are_bad_requests(served, raw):
    """Mirror the sibling's `test_a_missing_body_is_a_bad_request`: the
    server gate answers invalid JSON with 400 + `error` before the route
    runs (the spec's `kind: bad_request` is the handler's answer for a
    parsed non-object; the raw-JSON 400 is pinned as the sibling pins it).
    The trailing mint pins the route exists -- the gate is not the contract
    under test here."""
    _app, client, _root = served
    hdrs = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"}
    status, _h, data = client.request("POST", MINT, token=True, headers=hdrs, body=raw)
    assert status == 400
    assert json.loads(data)["error"]
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)


# ---------------------------------------------------------------------------
# 403 and the gates (gate-first, exactly like the sibling write routes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},              # the valid mint body on a writable server
        "navis",         # a JSON string, not an object
        [1],             # a JSON array, not an object
        {"force": True}, # extra keys -- a no-op body on a writable server
    ],
)
def test_a_read_only_server_refuses_before_validating_the_body(tmp_path, payload):
    """§11/§13's unqualified "403 under --no-write": the gate is consulted
    FIRST, so a probe with an incomplete body gets the refusal, not a 400
    that leaks the body rules of a server that cannot write. The mint is
    the most write-y navis verb there is, and it obeys the same gate."""
    _write(tmp_path, MIXED)
    app = start(tmp_path, read_only=True)
    try:
        client = Client(app)
        before = snapshot_tree(tmp_path)
        status, body = client.api_post(MINT, payload)
        assert status == 403, body
        assert body["kind"] == "refused"
        assert "--no-write" in body["error"]
        assert snapshot_tree(tmp_path) == before  # nothing written
    finally:
        app.stop()


def test_the_mint_route_shares_the_write_routes_token_gate(served):
    """The gate is route-agnostic (server.py `_api`); the mint must answer
    without the token exactly as /api/items/create does -- compare, never
    hard-code -- and the identical request WITH the token mints."""
    _app, client, _root = served
    body = json.dumps({}).encode()
    hdrs = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{client.port}"}
    ref_status, _rh, ref_data = client.request("POST", CREATE, body=b"{}", headers=hdrs)
    assert ref_status == 403  # the gate refuses a tokenless POST
    status, _h, data = client.request("POST", MINT, body=body, headers=hdrs)
    assert (status, data) == (ref_status, ref_data)
    status, _h, data = client.request(
        "POST", MINT, body=body, headers=dict(hdrs, **{"X-Refdes-Token": "wrong"})
    )
    assert status == 403
    status, _h, data = client.request("POST", MINT, body=body, headers=hdrs, cookie=True)
    assert status == 403  # the session cookie alone is not enough
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)


def test_the_mint_route_refuses_a_mismatched_origin(served):
    """Same Origin rule as the sibling routes, compared against the
    archive route's answer on the same request rather than hard-coded."""
    _app, client, _root = served
    ref_status, ref_data = client.api_post(ARCHIVE, {}, origin="http://evil.example")
    assert ref_status == 403
    status, body = client.api_post(MINT, {}, origin="http://evil.example")
    assert (status, body) == (ref_status, ref_data)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)


def test_the_mint_route_requires_application_json(served):
    """The sibling routes' 415 posture, compared -- and the JSON-typed
    request mints."""
    _app, client, _root = served
    hdrs = {"Content-Type": "text/plain", "Origin": f"http://127.0.0.1:{client.port}"}
    ref_status, _rh, ref_data = client.request(
        "POST", ARCHIVE, token=True, headers=hdrs, body=b"{}"
    )
    assert ref_status == 415
    status, _h, data = client.request("POST", MINT, token=True, headers=hdrs, body=b"{}")
    assert (status, data) == (ref_status, ref_data)
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)


# ---------------------------------------------------------------------------
# 405
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_the_mint_route_is_post_only(served, method):
    _app, client, _root = served
    if method == "GET":
        status, payload = client.api_get(MINT)
        assert status == 405, payload
        assert payload == {"error": "method not allowed"}
    else:
        # PUT/DELETE are answered by the server itself (server.py:656-659);
        # what is pinned is that this path is not a write surface for them,
        # same posture as the sibling's method test.
        status, _h, _b = client.request(method, MINT, token=True, body=b"{}")
        assert status == 405
    status, payload = client.api_post(MINT, {})  # ... and is one for POST
    assert status == 200, payload
    _ok_mint(payload, True)


# ---------------------------------------------------------------------------
# refusals: mint_keys refuses to mint into some markers; the route reports
# them in still_keyless and the minted ones land alongside (200, not an error)
# ---------------------------------------------------------------------------


def test_a_refused_marker_stays_keyless_and_is_counted(serve):
    _app, client, root = serve({"note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
                                "entries.yaml": FOLDED})
    yaml_path = root / "items" / "entries.yaml"
    before = yaml_path.read_bytes()
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)
    assert [e["file"] for e in payload["minted"]] == ["items/note-a.md"]
    assert payload["still_keyless"] == 1
    assert yaml_path.read_bytes() == before  # the refused file is untouched
    status, panel = client.api_get("/api/navis")
    assert status == 200, panel
    row = next(r for r in panel["navis"] if r["item"] == "NOTE-100")
    assert row["key"] == ""  # the panel agrees: still keyless


def test_a_file_edited_after_the_snapshot_keeps_its_bytes(serve):
    """The exact-provenance rule made visible over HTTP: a file edited on
    disk after the served snapshot was built is refused mint-by-mint (the
    user's bytes win, never a clobber), while an untouched file still
    mints in the same call."""
    _app, client, root = serve({
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
        "note-b.md": _note("NOTE-002", "Beta", BETA_TEXT),
    })
    source = root / "items" / "note-a.md"
    edited_text = ALPHA_TEXT + " (hand edit)"
    source.write_text(
        source.read_text(encoding="utf-8").replace(ALPHA_TEXT, edited_text),
        encoding="utf-8",
        newline="",
    )
    edited_bytes = source.read_bytes()
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    _ok_mint(payload, True)
    assert [e["file"] for e in payload["minted"]] == ["items/note-b.md"]
    assert [e["item"] for e in payload["minted"]] == ["NOTE-002"]
    assert payload["still_keyless"] == 1
    assert source.read_bytes() == edited_bytes  # the edit survives, byte for byte
    status, panel = client.api_get("/api/navis")
    assert status == 200, panel
    row = next(r for r in panel["navis"] if r["item"] == "NOTE-001")
    assert row["key"] == ""
    assert row["text"] == edited_text  # the rebuilt panel shows the user's text


# ---------------------------------------------------------------------------
# freshness: the forced rebuild lands before the response (design §11)
# ---------------------------------------------------------------------------


def test_the_panel_and_the_served_page_show_the_minted_keys_after_the_write(serve):
    """Mirror of the sibling's test_the_served_page_shows_archived_after_the_write:
    the write handler rebuilds before it answers (poll_interval=60 leaves
    the watcher no chance to do it behind the handler's back), so the next
    GET of /api/navis carries the keys and the preview page renders key6."""
    app, client, _root = serve(SIMPLE)
    status, panel = client.api_get("/api/navis")
    assert status == 200, panel
    assert len(panel["navis"]) == 1
    assert panel["navis"][0]["key"] == ""  # keyless on the served snapshot
    html = _preview(client, app, "NOTE-001")
    assert ALPHA_TEXT in html
    assert '<span class="mono"></span>' in html  # the keyless row renders no key
    status, payload = client.api_post(MINT, {})
    assert status == 200, payload
    key = payload["minted"][0]["key"]
    status, panel = client.api_get("/api/navis")
    assert status == 200, panel
    rows = panel["navis"]
    assert [r["key"] for r in rows] == [key]
    assert len(rows[0]["key6"]) == 6
    assert rows[0]["key6"] == key[:6]
    html = _preview(client, app, "NOTE-001")
    assert f'<span class="mono">{key[:6]}</span>' in html
    assert ALPHA_TEXT in html


# ---------------------------------------------------------------------------
# locking: the write lock serializes mints (the sibling routes' posture --
# plan under the lock, so the second request plans against what the first
# committed; no corruption, no double splice, no deadlock)
# ---------------------------------------------------------------------------


def test_two_simultaneous_mints_mint_each_marker_exactly_once(serve):
    app, _client, root = serve(MIXED)
    rels = ["items/note-a.md", "items/note-b.md"]
    lines_before = {rel: len(_text(root, rel).splitlines()) for rel in rels}
    barrier = threading.Barrier(2)
    results: list = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait(timeout=30)
        outcome = Client(app).api_post(MINT, {})
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive()  # no deadlock: the lock is released

    assert len(results) == 2
    assert [status for status, _payload in results] == [200, 200]
    payloads = [payload for _status, payload in results]
    assert sorted(p["changed"] for p in payloads) == [False, True]
    winner = next(p for p in payloads if p["changed"])
    loser = next(p for p in payloads if not p["changed"])
    assert len(winner["minted"]) == 3
    assert loser["minted"] == []  # it planned against the committed state
    keys_in_files = [
        k for rel in rels for k in _KEYED_RE.findall(_text(root, rel)) if k != HAND_KEY
    ]
    assert sorted(keys_in_files) == sorted(e["key"] for e in winner["minted"])
    for rel in rels:
        text = _text(root, rel)
        assert len(_KEYLESS_RE.findall(text)) == 0  # every marker keyed, splices intact
        assert len(text.splitlines()) == lines_before[rel]


# ---------------------------------------------------------------------------
# 500: a write failure is a JSON error, never a traceback
# ---------------------------------------------------------------------------


def _boom(*_args, **_kwargs):
    raise OSError("disk full")


def test_a_write_failure_is_a_500_json_error(served, monkeypatch):
    """Patch target: `refdes.revise.write_rewrites_verified` -- the writer
    `navis.mint_keys` imports (inside its body, at call time) and calls as
    the module attribute, so patching it is the specified seam (the
    sibling's `navis_archive.archive_record` posture)."""
    _app, client, root = served
    monkeypatch.setattr(revise, "write_rewrites_verified", _boom)
    before = snapshot_tree(root)
    status, payload = client.api_post(MINT, {})
    assert status == 500, payload
    assert payload["kind"] == "error"
    assert "disk full" in payload["error"]
    assert snapshot_tree(root) == before


# ---------------------------------------------------------------------------
# scope: the mint writes marker bytes in item files and nothing else --
# the archive store is not part of this route's contract at all
# ---------------------------------------------------------------------------


def test_the_mint_never_touches_the_archive_store(tmp_path):
    config = _write(tmp_path, {"note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT, key=HAND_KEY)})
    assert _run_cli(config, "navis", "archive", HAND_KEY) == 0
    record = Path(navis_archive.record_path(str(tmp_path), HAND_KEY))
    record_bytes = record.read_bytes()
    # a keyless marker added after the archive seeding: the mint's target
    (tmp_path / "items" / "note-b.md").write_text(
        _note("NOTE-002", "Beta", GAMMA_TEXT), encoding="utf-8", newline=""
    )
    app = start(tmp_path)
    try:
        client = Client(app)
        status, payload = client.api_post(MINT, {})
        assert status == 200, payload
        _ok_mint(payload, True)
        assert [e["file"] for e in payload["minted"]] == ["items/note-b.md"]
        assert record.read_bytes() == record_bytes  # the record is untouched
        records, _diags = navis_archive.load_records(str(tmp_path))
        assert [r.navi_key for r in records] == [HAND_KEY]  # and still loads
        store = tmp_path / ".refdes" / "navis"
        assert sorted(p.name for p in store.iterdir()) == [f"{HAND_KEY}.yaml.gz"]
    finally:
        app.stop()
