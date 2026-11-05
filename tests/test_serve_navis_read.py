"""Contract tests for the editor server's read endpoint `GET /api/navis`.

The contract (design in-prog-logs/navis-design-20261025.md §11, carried out
in the N5a spec): `GET /api/navis` (HEAD allowed), behind the same
token/Host/Origin gate as every `/api/*` route, answers 200 with
`{"navis": [rows...], "counts": {"active": int, "archived": int}}` --
ALL rows, active first then archived, in `navis.projection(project)` order
(the same order as `refdes navis all`), each row the published-site panel's
row shape (`navis_panel.panel_model`) PLUS the full `key` ("" for a keyless
marker). A Navi-free project is a 200 with empty rows and zero counts; a
non-GET/HEAD is a 405; the route is read-only under `--no-write`; an
archive made on disk is visible on the next GET; the GET itself changes
nothing on disk; marker text is data, not HTML.

Written from that spec, NOT from an implementation: the row expectations are
derived from the two functions the contract names -- `navis.projection`
(order, keys) and `navis_panel.panel_model` (row shape) -- so the
implementer can reuse exactly what the spec says they will reuse. The route
does not exist yet, so every test that asks the endpoint a question is red
on its 200/status assertion (the gate-parity tests are comparisons against
`/api/items` and pin the gate by construction).
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree
from test_navis_site_panel import ACTIVE_TEXT, SCHEMA, _navi_project

from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import loader, navis, navis_panel
from refdes.serve.server import EditorApp

ROW_FIELDS = {
    "key", "key6", "text", "item", "href", "file", "line",
    "archived", "changed", "orphan",
}

KEYLESS_TEXT = "A marker nobody minted."
HOSTILE_TEXT = 'Dirty <script>alert("x")</script> & "quoted" bit'


def _contract_rows(config: str) -> list[dict]:
    """The rows the endpoint must return, built the way the contract says:
    `navis_panel.panel_model` over `navis.projection`, plus `key` (the
    projection's None for a keyless marker is the API's ""). The read-only
    load is what serve's state is built from, so this derives the served
    answer without writing anything."""
    project = loader.load_readonly(config)
    assert not project.errors, [str(d) for d in project.errors]
    rows = navis.projection(project)
    model = navis_panel.panel_model(project, rows)
    expected = []
    for row, source in zip(model["rows"] if model else [], rows):
        item = dict(row)
        item["key"] = source["key"] or ""
        expected.append(item)
    return expected


@pytest.fixture
def served(tmp_path):
    """The Navi fixture (one active marker, one archived-and-edited marker,
    one archived-then-hand-deleted marker) on a writable editor server."""
    config = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, Client(app), tmp_path, config
    finally:
        app.stop()


def _marker_project(tmp_path, marker_lines: list[str]) -> str:
    items = tmp_path / "items"
    items.mkdir()
    (items / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\nintro\n"
        + "".join(line + "\n" for line in marker_lines),
        encoding="utf-8",
        newline="",
    )
    return str(write_project_config(tmp_path, SCHEMA))


@pytest.fixture
def served_read_only(tmp_path):
    """A project with an un-minted (keyless) marker and a hostile-text
    marker, served with read_only=True -- the `--no-write` posture, where
    the loader cannot mint and the keyless marker stays keyless."""
    config = _marker_project(
        tmp_path,
        [f"<!--navi:{keys_mod.mint()} {HOSTILE_TEXT}-->", f"<!--navi: {KEYLESS_TEXT}-->"],
    )
    app = EditorApp(config, poll_interval=60, read_only=True)
    app.start()
    try:
        yield app, Client(app), tmp_path, config
    finally:
        app.stop()


# --------------------------------------------------------------------- shape


def test_the_rows_are_the_panel_model_plus_the_key(served):
    _app, client, _root, config = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    assert set(payload) == {"navis", "counts"}
    assert set(payload["counts"]) == {"active", "archived"}
    rows = payload["navis"]
    for row in rows:
        assert set(row) == ROW_FIELDS
    expected = _contract_rows(config)
    assert len(rows) == len(expected)  # fail loud, field by field below
    for row, want in zip(rows, expected):
        assert row == want
    assert [row["key6"] for row in rows] == [row["key"][:6] for row in rows]


def test_rows_are_active_first_then_archived_in_projection_order(served):
    _app, client, _root, config = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    flags = [row["archived"] for row in payload["navis"]]
    assert flags[0] is False
    assert all(flag is True for flag in flags[1:])
    assert [row["key"] for row in payload["navis"]] == [
        row["key"] for row in _contract_rows(config)
    ]


def test_the_fixture_rows_are_active_changed_and_orphan(served):
    """The row flags the §9 table says the fixture exercises: live marker,
    archived marker whose text moved, archived record whose marker is gone
    (whose stored item key still names a live item, so it links)."""
    _app, client, _root, _config = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    by_text = {row["text"]: row for row in payload["navis"]}
    active = by_text[ACTIVE_TEXT]
    assert active["archived"] is False
    assert active["changed"] is False and active["orphan"] is False
    assert active["item"] == "NOTE-001" and active["href"] == "note-001.html"
    archived = by_text["Gamma before the edit"]
    assert archived["archived"] is True and archived["changed"] is True
    assert archived["item"] == "NOTE-003"
    orphan = by_text["Beta archived then deleted"]
    assert orphan["archived"] is True and orphan["orphan"] is True
    assert orphan["item"] == "NOTE-002" and orphan["href"] == "note-002.html"


def test_counts_are_the_archived_tallies_of_the_rows(served):
    _app, client, _root, _config = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    rows = payload["navis"]
    assert payload["counts"] == {
        "active": sum(1 for row in rows if not row["archived"]),
        "archived": sum(1 for row in rows if row["archived"]),
    }
    assert payload["counts"] == {"active": 1, "archived": 2}


# ------------------------------------------------------------------ no Navis


def test_navis_free_project_returns_empty_rows(tmp_path):
    config = str(write_project_config(tmp_path, SCHEMA))
    items = tmp_path / "items"
    items.mkdir()
    (items / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Plain\n---\nplain body.\n",
        encoding="utf-8",
        newline="",
    )
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        status, payload = Client(app).api_get("/api/navis")
        assert status == 200, payload
        assert payload == {"navis": [], "counts": {"active": 0, "archived": 0}}
    finally:
        app.stop()


# ---------------------------------------------------------- methods and gate


def test_head_is_answered(served):
    _app, client, _root, _config = served
    status, _headers, body = client.request("HEAD", "/api/navis", token=True)
    assert status == 200, status
    assert body == b""


def test_post_is_method_not_allowed(served):
    _app, client, _root, _config = served
    status, payload = client.api_post("/api/navis", {})
    assert status == 405, payload
    assert payload == {"error": "method not allowed"}


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_writing_methods_answer_exactly_like_the_items_route(served, method):
    """PUT/DELETE never reach `api.handle` (the server refuses them at the
    transport, body included) -- the contract for the new route is that it
    is indistinguishable from `/api/items` for them, so compare, don't
    hard-code."""
    _app, client, _root, _config = served
    navis_answer = client.request(method, "/api/navis")
    items_answer = client.request(method, "/api/items")
    assert (navis_answer[0], navis_answer[2]) == (items_answer[0], items_answer[2])
    assert navis_answer[0] == 405  # today's refusal; the comparison pins it


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"headers": {"X-Refdes-Token": "wrong"}},
        {"cookie": True},  # the session cookie alone is not enough for /api/
    ],
)
def test_the_route_is_behind_the_items_token_gate(served, kwargs):
    """Same gate as `/api/items`, asserted by comparison (the spec: do not
    hard-code the number)."""
    _app, client, _root, _config = served
    navis_answer = client.request("GET", "/api/navis", **kwargs)
    items_answer = client.request("GET", "/api/items", **kwargs)
    assert (navis_answer[0], navis_answer[2]) == (items_answer[0], items_answer[2])
    assert items_answer[0] >= 400  # the comparison refused a success


# ------------------------------------------------------------ read-only + IO


def test_get_works_on_a_read_only_server(served_read_only):
    _app, client, _root, config = served_read_only
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    assert payload["navis"] == _contract_rows(config)


def test_get_changes_nothing_on_disk(served):
    _app, client, root, _config = served
    before = snapshot_tree(root)
    status, _payload = client.api_get("/api/navis")
    assert status == 200, _payload
    assert snapshot_tree(root) == before


# -------------------------------------------------------------- freshness


def test_archive_on_disk_is_visible_on_the_next_get(served):
    app, client, _root, config = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    active = [row for row in payload["navis"] if not row["archived"]]
    assert [row["text"] for row in active] == [ACTIVE_TEXT]
    key = active[0]["key"]
    assert len(key) == 11

    assert cli_mod.main(["-c", config, "navis", "archive", key]) == 0
    app.state.refresh()  # the rebuild the poller runs; the record is read at
    # request time, so the next GET merges it in either way

    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    row = next(row for row in payload["navis"] if row["key"] == key)
    assert row["archived"] is True
    assert row["text"] == ACTIVE_TEXT  # the record's snapshot
    assert row["changed"] is False and row["orphan"] is False
    assert row["item"] == "NOTE-001" and row["href"] == "note-001.html"
    assert payload["counts"] == {"active": 0, "archived": 3}
    assert all(row["archived"] for row in payload["navis"])


# ------------------------------------------------------------- keyless, hostile


def test_keyless_marker_rows_have_empty_key_fields(served_read_only):
    _app, client, _root, _config = served_read_only
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    keyless = next(row for row in payload["navis"] if row["text"] == KEYLESS_TEXT)
    assert keyless["key"] == "" and keyless["key6"] == ""
    assert keyless["archived"] is False
    assert keyless["item"] == "NOTE-001" and keyless["href"] == "note-001.html"


def test_hostile_marker_text_comes_back_as_exact_json(served_read_only):
    _app, client, _root, _config = served_read_only
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    hostile = next(row for row in payload["navis"] if HOSTILE_TEXT[:20] in row["text"])
    assert hostile["text"] == HOSTILE_TEXT  # data, not HTML: unescaped
    _status, _headers, data = client.request("GET", "/api/navis", token=True)
    assert b"<script>alert(" in data  # no escaping on the wire either
