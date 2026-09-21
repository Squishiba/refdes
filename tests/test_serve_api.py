"""The editor's read-side JSON API (docs/design/browser-editor.md, Filtering
and "Server and refresh architecture"): `/api/items` answers a filtered list
from the *built* project, `/api/item/<ref>` returns one item's view. Filter
semantics, facet counts, URL round-trip, and the token/Host/Origin gate on
the new routes."""

from __future__ import annotations

import pytest
from serve_support import Client, make_filter_project, make_project

from refdes.serve.server import EditorApp


@pytest.fixture
def served(tmp_path):
    config = make_filter_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, Client(app)
    finally:
        app.stop()


def _ids(payload):
    return sorted(row["id"] for row in payload["items"])


# --------------------------------------------------------------- single filters

@pytest.mark.parametrize(
    "query,expected",
    [
        ({}, ["BND-001", "BND-002", "DEC-001", "DEC-002", "DEC-003", "LOG-001",
              "REQ-001", "REQ-002", "REQ-003", "TST-001"]),
        ({"type": "requirement"}, ["REQ-001", "REQ-002", "REQ-003"]),
        ({"board": "board-b"}, ["BND-002", "REQ-002"]),
        ({"workspace": "product-a"}, ["BND-002", "REQ-002"]),
        ({"tag": "power"}, ["REQ-001"]),
        # tag matching is the `refdes ls` rule: case-insensitive substring
        ({"tag": "POW"}, ["REQ-001"]),
        ({"file": "items/reqs.yaml"}, ["REQ-001", "REQ-002", "REQ-003"]),
        ({"stage": "open"}, ["REQ-003"]),
        ({"stage": "verified"}, ["REQ-001"]),
        ({"stage": "satisfied"}, ["REQ-002"]),
        ({"check": "pass"}, ["DEC-001"]),
        ({"check": "fail"}, ["DEC-002"]),
        ({"check": "none"}, ["BND-001", "BND-002", "DEC-003", "LOG-001",
                             "REQ-001", "REQ-002", "REQ-003", "TST-001"]),
        ({"blocked": "yes"}, ["DEC-003"]),
        ({"blocked": "no"}, ["BND-001", "BND-002", "DEC-001", "DEC-002",
                             "LOG-001", "REQ-001", "REQ-002", "REQ-003", "TST-001"]),
        # link relationships, by display id
        ({"links_to": "REQ-001"}, ["DEC-001", "TST-001"]),
        ({"linked_from": "DEC-001"}, ["REQ-001"]),
        ({"missing_verb": "satisfies"}, ["DEC-003"]),
        ({"q": "boot"}, ["DEC-002", "BND-002", "REQ-002"]),
    ],
)
def test_each_filter_alone(served, query, expected):
    _app, client = served
    status, payload = client.api_get(
        "/api/items?" + "&".join(f"{k}={v}" for k, v in query.items())
    )
    assert status == 200
    assert _ids(payload) == sorted(expected)
    assert payload["total"] == len(expected)


# ------------------------------------------------------------------ combined

def test_filters_and_together(served):
    _app, client = served
    status, payload = client.api_get("/api/items?type=requirement&board=board-a")
    assert status == 200
    assert _ids(payload) == ["REQ-001", "REQ-003"]


def test_three_way_combination(served):
    _app, client = served
    status, payload = client.api_get(
        "/api/items?type=decision&blocked=yes&missing_verb=satisfies"
    )
    assert status == 200
    assert _ids(payload) == ["DEC-003"]


def test_contradictory_combination_is_empty_not_wrong(served):
    _app, client = served
    status, payload = client.api_get("/api/items?stage=open&stage-ignored=1&check=fail")
    assert status == 200
    assert _ids(payload) == []
    assert payload["total"] == 0


# --------------------------------------------------------------------- counts

def test_facet_counts_match_a_full_scan(served):
    _app, client = served
    status, payload = client.api_get("/api/items")
    assert status == 200
    rows = payload["items"]
    row_keys = {"file": "source_file"}
    for facet in ("type", "board", "workspace", "file", "stage", "check", "blocked"):
        tally: dict[str, int] = {}
        for row in rows:
            value = row[row_keys.get(facet, facet)]
            if facet == "blocked":
                value = "yes" if value else "no"
            if value is None:
                continue  # a non-coverable item has no stage at all
            tally[value] = tally.get(value, 0) + 1
        assert payload["facets"][facet] == tally, facet
    # every item has a type/board/check/blocked value; only coverable items
    # have a stage, and only tagged items a tag
    assert sum(payload["facets"]["type"].values()) == payload["total"]
    assert sum(payload["facets"]["stage"].values()) == 3
    assert sum(payload["facets"]["tag"].values()) == 3
    assert payload["facets"]["type"] == {
        "requirement": 3, "decision": 3, "bound": 2, "test": 1, "log": 1
    }
    assert payload["facets"]["blocked"] == {"no": 9, "yes": 1}
    assert payload["facets"]["stage"] == {"verified": 1, "satisfied": 1, "open": 1}
    assert payload["facets"]["check"] == {"none": 8, "pass": 1, "fail": 1}


def test_facet_counts_are_cross_filtered(served):
    """A facet's counts ignore only its own filter: with stage=open active,
    the type facet still counts every stage (that is what a sidebar needs to
    show what clicking another value would do), but the board facet reflects
    stage=open."""
    _app, client = served
    status, payload = client.api_get("/api/items?stage=open")
    assert status == 200
    assert payload["facets"]["stage"] == {"verified": 1, "satisfied": 1, "open": 1}
    assert payload["facets"]["type"] == {"requirement": 1}
    assert payload["facets"]["board"] == {"board-a": 1}


def test_facet_totals_report_the_other_filters_applied(served):
    _app, client = served
    status, payload = client.api_get("/api/items?type=decision")
    assert status == 200
    # the board facet's total is "decisions, any board" = 3
    assert payload["facet_totals"]["board"] == 3
    # its own facet ignores its own filter too: type total is everything
    assert payload["facet_totals"]["type"] == 10


# ---------------------------------------------------------------- url round-trip

def test_filter_state_round_trips_through_the_url(served):
    """The `filters` echo, re-encoded as a query string, reproduces the same
    parsed state and the same answer — the property the editor's address bar
    depends on."""
    from urllib.parse import urlencode

    _app, client = served
    query = {
        "type": ["decision"], "board": ["board-a"], "check": ["none"],
        "blocked": ["yes"], "missing_verb": ["satisfies"], "q": ["blocked"],
    }
    status, first = client.api_get("/api/items?" + urlencode(query, doseq=True))
    assert status == 200
    assert first["filters"] == {k: v[0] for k, v in query.items()}
    again = "/api/items?" + urlencode(first["filters"])
    status2, second = client.api_get(again)
    assert status2 == 200
    assert second["filters"] == first["filters"]
    assert _ids(second) == _ids(first) == ["DEC-003"]


def test_tag_with_spaces_and_symbols_round_trips(served):
    from urllib.parse import quote, urlencode
    _app, client = served
    status, payload = client.api_get("/api/items?" + urlencode({"tag": "power"}))
    assert status == 200 and _ids(payload) == ["REQ-001"]
    status, payload = client.api_get("/api/items?q=" + quote("3.3 V"))
    assert status == 200 and _ids(payload) == ["REQ-001"]


# ---------------------------------------------------------------- bad queries

@pytest.mark.parametrize(
    "query",
    [
        "stage=banana",
        "check=maybe",
        "blocked=perhaps",
        "missing_verb=no_such_verb",
        "links_to=NOPE-999",
        "linked_from=k0000000000",
        "limit=0",
        "limit=-3",
        "limit=lots",
    ],
)
def test_bad_filter_values_are_400_not_empty(served, query):
    _app, client = served
    status, payload = client.api_get(f"/api/items?{query}")
    assert status == 400
    assert "error" in payload


def test_unknown_params_are_ignored(served):
    _app, client = served
    status, payload = client.api_get("/api/items?whatever=1")
    assert status == 200
    assert payload["filters"] == {}


def test_limit_bounds_the_rows_but_not_the_total(served):
    _app, client = served
    status, payload = client.api_get("/api/items?limit=2")
    assert status == 200
    assert len(payload["items"]) == 2
    assert payload["total"] == 10


# ----------------------------------------------------------------- item view

def test_item_view_returns_fields_body_links_coverage_diagnostics(served):
    _app, client = served
    status, item = client.api_get("/api/item/REQ-001")
    assert status == 200
    assert item["id"] == "REQ-001" and item["type"] == "requirement"
    assert item["fields"]["text"] == "The rail shall supply 3.3 V."
    assert item["tags"] == ["power", "rail"]
    assert item["links"]["incoming"]["satisfied_by"] == ["DEC-001"]
    assert item["links"]["incoming"]["verified_by"] == ["TST-001"]
    assert item["links"]["outgoing"] == {}
    assert item["coverage"]["stage"] == "verified"
    assert item["coverage"]["satisfied_by"] == ["DEC-001"]
    assert item["coverage"]["verified_by"] == ["TST-001"]
    assert item["source_file"] == "items/reqs.yaml"
    assert item["page"] == "req-001.html"
    assert item["revision"]


def test_item_view_links_both_directions_and_diagnostics(served):
    _app, client = served
    status, item = client.api_get("/api/item/DEC-002")
    assert status == 200
    assert item["links"]["outgoing"]["satisfies"] == ["REQ-002"]
    assert item["check"] == "fail"
    assert item["checks"][0]["ok"] is False
    assert item["checks"][0]["against"] == "BND-002"
    # the failing check is an attributed diagnostic on the item
    assert any(d["level"] == "error" and "I_boot" in d["message"] for d in item["diagnostics"])
    assert all(d.get("file") == "items/decs.yaml" for d in item["diagnostics"])
    assert "I_boot = 3 A" in item["body"]


def test_item_view_seal_state(served):
    _app, client = served
    status, item = client.api_get("/api/item/LOG-001")
    assert status == 200
    assert item["append_only"] is True
    # a read-only load never seals: the fixture has no seal record
    assert item["sealed"] is False


def test_item_view_addressed_by_the_row_handle(served):
    """The list hands out `handle`; the view must accept exactly that, which
    is the only way a keyless item (provisional handle, no key, no dict path)
    stays addressable."""
    _app, client = served
    status, payload = client.api_get("/api/items?type=log")
    assert status == 200
    handle = payload["items"][0]["handle"]
    status, item = client.api_get(f"/api/item/{handle}")
    assert status == 200
    assert item["id"] == "LOG-001" and item["handle"] == handle


def test_item_view_unknown_ref_is_404(served):
    _app, client = served
    status, payload = client.api_get("/api/item/NOPE-999")
    assert status == 404
    assert "error" in payload


# ------------------------------------------------------------------ the gate

@pytest.mark.parametrize("path", ["/api/items", "/api/item/REQ-001"])
def test_api_reads_require_the_token_header(served, path):
    _app, client = served
    status, _h, _b = client.request("GET", path)
    assert status == 403
    status, _h, _b = client.request("GET", path, headers={"X-Refdes-Token": "wrong"})
    assert status == 403
    # the session cookie alone is not enough for /api/ either
    status, _h, _b = client.request("GET", path, cookie=True)
    assert status == 403


@pytest.mark.parametrize("path", ["/api/items", "/api/item/REQ-001"])
def test_bad_host_is_rejected_before_routing(served, path):
    _app, client = served
    status, _h, _b = client.request(
        "GET", path, token=True, host=f"127.0.0.1:{client.port + 1}"
    )
    assert status == 403
    status, _h, _b = client.request("GET", path, token=True, host="evil.example")
    assert status == 403


@pytest.mark.parametrize("path", ["/api/items", "/api/item/REQ-001"])
def test_cross_origin_get_is_rejected(served, path):
    _app, client = served
    status, _h, _b = client.request(
        "GET", path, token=True, headers={"Origin": "http://evil.example"}
    )
    assert status == 403


@pytest.mark.parametrize("path", ["/api/items", "/api/item/REQ-001"])
def test_reads_reject_writing_methods(served, path):
    _app, client = served
    status, _payload = client.api_post(path, {})
    assert status == 405


def test_the_original_fixture_project_serves_too(tmp_path):
    """The read side works on the plain fixture as well (keyless items after
    a minted-key load), not only on the filter fixture."""
    config = make_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        client = Client(app)
        status, payload = client.api_get("/api/items")
        assert status == 200 and payload["total"] >= 6
        status, item = client.api_get("/api/item/REQ-001")
        assert status == 200 and item["key"]  # keys were minted by the fixture
    finally:
        app.stop()
