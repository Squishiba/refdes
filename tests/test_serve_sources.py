"""The source-read endpoints (docs/design/editor-source-picker.md §2, §5, §6,
§7 -- Slice A, "the service reads"; the endpoint half of §10).

Through the real HTTP surface against a real fixture project, in the posture
`test_serve_edit_http.py` uses: one `served` fixture, a real `EditorApp`, and
for the refusals one `snapshot_tree` comparison proving the whole project --
the item file, the CSV, and the citation lockfile alike -- came out byte for
byte as it went in. These routes read a cited file, so the tests that matter
most are the ones that try to make them read a file the item has not cited.

Nothing here writes. Accept (Slice B) and the panel (Slice C) are not in this
slice, and the absence of a lockfile write is asserted rather than assumed.
"""

from __future__ import annotations

import json
import os

import pytest
import yaml
from conftest import write_project_config
from helpers import _build_at
from serve_support import Client, snapshot_tree

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes.serve.server import EditorApp

CONFIG = """\
site: { title: Source picker, out: _site }
types:
  decision:
    prefix: DEC
    fields:
      citations: { type: citations, on_change: invalidate }
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
      citations: { type: citations, on_change: invalidate }
"""

CSV = "key,value,note\nrail_load,1.85,mW budget\neff,0.93,datasheet rev E\nother,7,x\n"
BROKEN_CSV = (
    "key,value,note\n"
    "rail_load,1.85,mW budget\n"
    "dup,1,a\n"
    "dup,2,b\n"
    "not_a_number,abc,c\n"
)
NO_READER = "key,value\nfoo,1\n"

ITEMS = """\
defaults: { type: decision }
items:
  - id: DEC-001
    citations:
      - path: analysis/budget.csv
    body: |
      ```calc
      P = source("analysis/budget.csv", "rail_load") | W
      ```
  - id: DEC-002
    body: |
      ```calc
      Q = 1 | 1
      ```
"""


def make_root(tmp_path, *, csv: str = CSV, items: str = ITEMS, files=None):
    write_project_config(tmp_path, CONFIG)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text(csv, encoding="utf-8", newline="")
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="")
    (tmp_path / "items").mkdir(exist_ok=True)
    (tmp_path / "items" / "decisions.yaml").write_text(items, encoding="utf-8")
    return tmp_path


def start(root, **kw):
    app = EditorApp(str(root / "refdes-project.yaml"), poll_interval=60, **kw)
    app.start()
    return app


def fetch(root, *extra):
    """`refdes fetch` against this fixture, before the server is started.

    Order matters: the served model is built once, when the app starts, and its
    poll interval is 60 s in these tests, so a lockfile written after that
    would not be in the model a request reads. A test that needs a *different*
    pin state builds its own root, fetches, mutates, and only then starts."""
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "fetch", *extra]) == 0


@pytest.fixture
def served(tmp_path):
    """A project with a real pin in the lockfile -- the state every read here
    has to work from."""
    root = make_root(tmp_path)
    fetch(root)
    app = start(root)
    try:
        yield app, Client(app), root
    finally:
        app.stop()


def lock(root):
    return yaml.safe_load((root / ".refdes" / "citations.yaml").read_text("utf-8"))


def lock_bytes(root):
    return (root / ".refdes" / "citations.yaml").read_bytes()


def sources_url(ref, *parts):
    return "/api/item/" + ref + "/sources" + "".join(parts)


def strings(payload):
    """Every string anywhere in a JSON payload, for the no-leak assertion."""
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from strings(value)


# ---------------------------------------------------------------- 1: the files


def test_the_source_picker_lists_only_the_citing_item_s_own_files(served):
    _app, client, root = served
    fetch(root)

    status, payload = client.api_get(sources_url("DEC-001"))
    assert status == 200, payload
    assert payload["item"] == "DEC-001"
    assert [f["path"] for f in payload["files"]] == ["analysis/budget.csv"]
    budget = payload["files"][0]
    assert budget["reader"] == "csv"
    # The pin state is the build's own state, and the values already pinned for
    # this file are here so the panel can mark what is already in use.
    assert budget["state"] == "ok"
    assert budget["pinned_values"] == {"rail_load": "1.85"}
    assert len(budget["sha256"]) == 64
    assert budget["fetched"]

    # An item that cites nothing gets an empty list, not another item's file.
    status, other = client.api_get(sources_url("DEC-002"))
    assert status == 200
    assert other["files"] == [] and other["problems"] == []


def test_the_file_list_says_why_a_cited_file_is_not_listable(tmp_path):
    # A cited .pdf, a remote URL and a path that escapes the root are all named
    # with the reason, and none of them is listable. This is the honest gap of
    # §8 -- an item that cites no readable file gets an empty picker -- made
    # legible rather than silent.
    root = make_root(tmp_path, items=(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-003\n"
        "    citations:\n"
        "      - path: analysis/sheet.pdf\n"
        "      - path: https://example.com/budget.csv\n"
        "      - path: ../outside/budget.csv\n"
        "      - path: analysis/budget.csv\n"
    ))
    (root / "analysis" / "sheet.pdf").write_bytes(b"%PDF-1.4\n")
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-003"))
        assert status == 200, payload
        assert [f["path"] for f in payload["files"]] == ["analysis/budget.csv"]
        reasons = {p["path"]: p["problem"] for p in payload["problems"]}
        assert "no source reader for '.pdf' files" in reasons["analysis/sheet.pdf"]
        assert "remote citation" in reasons["https://example.com/budget.csv"]
        assert "escapes the project root" in reasons["../outside/budget.csv"]
    finally:
        app.stop()


def test_the_file_list_reports_a_cited_file_that_is_not_on_disk(tmp_path):
    # Pinned, then gone: the pin is what a `missing` is a statement about, so
    # an unpinned citation says `unpinned` instead and both are true.
    root = make_root(tmp_path)
    fetch(root)
    os.remove(root / "analysis" / "budget.csv")
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-001"))
        assert status == 200, payload
        assert payload["files"][0]["state"] == "missing"
    finally:
        app.stop()


def test_the_file_list_reports_an_unpinned_file_and_a_file_that_drifted(tmp_path):
    # Unpinned: cited, readable, no lockfile record yet.
    root = make_root(tmp_path)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-001"))
        assert status == 200, payload
        assert payload["files"][0]["state"] == "unpinned"
        assert "refdes fetch" in payload["files"][0]["detail"]
        assert payload["files"][0]["pinned_values"] == {}
    finally:
        app.stop()

    # Drifted: the same words the build's own loud warning uses, because it is
    # the build's own `CitationStatus` this reads rather than a second hash.
    root = make_root(tmp_path)
    fetch(root)
    (root / "analysis" / "budget.csv").write_text(
        CSV + "extra,1,y\n", encoding="utf-8", newline=""
    )
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-001"))
        assert status == 200, payload
        budget = payload["files"][0]
        assert budget["state"] == "hash_mismatch"
        assert "does not match its pinned hash" in budget["detail"]
        # and the pinned values are still the ones this project evaluates
        assert budget["pinned_values"] == {"rail_load": "1.85"}
    finally:
        app.stop()


# ------------------------------------------------------------------ 2: the rows


def test_the_entries_endpoint_lists_the_rows_of_a_cited_file(served):
    _app, client, root = served
    fetch(root)
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
    )
    assert status == 200, payload
    assert payload["path"] == "analysis/budget.csv"
    assert payload["reader"] == "csv"
    assert [e["key"] for e in payload["entries"]] == ["rail_load", "eff", "other"]
    assert payload["truncated"] is False
    assert payload["rows"] == 3
    assert payload["problems"] == []
    first = payload["entries"][0]
    assert first["raw"] == "1.85" and first["value"] == "1.85"
    assert first["line"] == 2
    assert first["context"] == [{"name": "note", "text": "mW budget"}]
    assert first["selectable"] is True and first["problem"] == ""
    # The live value and the pinned value sit side by side, and where the
    # lockfile has nothing for a key the pinned side is null rather than zero.
    assert (first["pinned"], first["changed"]) == ("1.85", False)
    assert (payload["entries"][1]["pinned"], payload["entries"][1]["changed"]) == (
        None, False,
    )


def test_the_entries_endpoint_marks_the_live_value_as_changed_from_the_pin(tmp_path):
    # The file holds 2.30, the lockfile pins 1.85, and the build keeps using the
    # pin -- so the panel has to be able to say so before anything is committed.
    root = make_root(tmp_path)
    fetch(root)
    (root / "analysis" / "budget.csv").write_text(
        CSV.replace("rail_load,1.85", "rail_load,2.30"), encoding="utf-8", newline=""
    )
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        first = payload["entries"][0]
        # `value` is the canonical text `extract()` would pin, and Decimal
        # keeps the lexeme's trailing zero -- `2.30` and `2.3` are the same
        # number and the same decision; the pin is `1.85`.
        assert (first["raw"], first["value"], first["pinned"], first["changed"]) == (
            "2.30", "2.30", "1.85", True,
        )
        # `changed` is a comparison between two numbers that both exist. A row
        # with no parseable value has not drifted from anything.
        assert payload["entries"][1]["pinned"] is None
        assert payload["entries"][1]["changed"] is False
    finally:
        app.stop()


def test_the_entries_endpoint_filters_server_side(served):
    _app, client, root = served
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
    )
    assert [e["key"] for e in payload["entries"]] == ["rail_load", "eff", "other"]

    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q=eff"
    )
    assert status == 200, payload
    assert [e["key"] for e in payload["entries"]] == ["eff"]
    assert payload["query"] == "eff"
    # A filter is a display filter: it changes what is shown, never what a row
    # is. The matching row still carries its own value and its pin.
    assert payload["entries"][0]["value"] == "0.93"

    # Case-insensitive, because this is a search box and not a key lookup.
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q=RAIL"
    )
    assert [e["key"] for e in payload["entries"]] == ["rail_load"]
    # A filter matching nothing is an empty list, not an error and not a
    # fallback to the whole file.
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q=nope"
    )
    assert status == 200 and payload["entries"] == []
    # An empty `q` is the whole file, not "keys containing the empty string
    # that is somehow none of them".
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q="
    )
    assert len(payload["entries"]) == 3


def test_the_entries_endpoint_shows_broken_rows_unselectable_rather_than_hiding_them(tmp_path):
    root = make_root(tmp_path, csv=BROKEN_CSV)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        by_key = {e["key"]: e for e in payload["entries"]}
        assert sorted(by_key) == ["dup", "not_a_number", "rail_load"]
        # Both copies of the duplicated key are listed and both are refused,
        # with the reader's own reason naming the two lines.
        dupes = [e for e in payload["entries"] if e["key"] == "dup"]
        assert [e["line"] for e in dupes] == [3, 4]
        assert all(e["selectable"] is False for e in dupes)
        assert all("appears on 2 rows (lines 3, 4)" in e["problem"] for e in dupes)
        # The non-numeric row is shown with the text the author wrote and no
        # number invented for it.
        bad = by_key["not_a_number"]
        assert (bad["raw"], bad["value"], bad["selectable"]) == ("abc", "", False)
        assert "not a plain ASCII decimal" in bad["problem"]
        # and a filter cannot make a broken row look pickable
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q=dup"
        )
        assert len(payload["entries"]) == 2
        assert all(e["selectable"] is False for e in payload["entries"])
    finally:
        app.stop()


def test_the_entries_endpoint_says_a_file_the_reader_cannot_read_is_not_browsable(tmp_path):
    # A header-level failure is fatal, exactly as in extract(), and the reason
    # is the reader's own: a file `fetch` cannot read is a file the picker must
    # not browse. It is a panel state (200, no rows), not a request failure.
    root = make_root(tmp_path, csv="Key,Value\nfoo,1\n")
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert payload["entries"] == []
        assert any("no 'key' column" in p for p in payload["problems"])
        assert any("no 'value' column" in p for p in payload["problems"])
        # and the near-miss hint the reader has always given, verbatim
        assert any("found 'Key'" in p for p in payload["problems"])
    finally:
        app.stop()


def test_the_picker_caps_an_oversized_file_and_names_the_limit(tmp_path):
    # Both caps, and both say what they are. The row cap is enforced where the
    # file is read, so this file is never fully materialised.
    big = "key,value\n" + "".join(f"key_{i},{i}\n" for i in range(20000))
    root = make_root(tmp_path, csv=big)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert payload["truncated"] is True
        assert payload["rows"] == 5000
        assert len(payload["entries"]) == 5000
        assert payload["entries"][-1]["key"] == "key_4999"
        assert payload["limits"] == {"max_rows": 5000, "max_bytes": 1048576}
        assert "5000-row cap" in payload["truncation"]
        assert "not read" in payload["truncation"]
    finally:
        app.stop()

    huge = "key,value\n" + "".join(f"key_{i},{i}\n" for i in range(200000))
    root = make_root(tmp_path, csv=huge)
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert payload["entries"] == []
        assert any(
            "refuses anything above 1048576 bytes" in p for p in payload["problems"]
        )
    finally:
        app.stop()


# ---------------------------------------------------------------- confinement


def test_the_picker_refuses_a_path_the_item_does_not_cite(served):
    """§6, first rule: only a file this item cites. The refusal is
    `authorize_source_path`'s own message, so the picker and the fetcher cannot
    disagree about what a `source()` line is allowed to name."""
    _app, client, root = served
    (root / "other.csv").write_text("key,value\nsecret,1\n", encoding="utf-8")
    before = snapshot_tree(root)

    for path in (
        "other.csv",
        "analysis/other.csv",
        "items/decisions.yaml",
        "refdes-project.yaml",
    ):
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=" + path
        )
        assert status == 422, (path, payload)
        assert payload["kind"] == "refused"
        assert "does not cite" in payload["error"], (path, payload)
    # A remote URL is refused with its own words, because it is a different
    # rule: source() reads a file committed with the project, not a URL.
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=https://example.com/budget.csv"
    )
    assert status == 422
    assert "is a remote citation" in payload["error"]
    # DEC-002 cites no file at all, so it authorizes nothing -- and in
    # particular not the file DEC-001 cites. A citation on another item does
    # not authorize this one.
    status, payload = client.api_get(
        sources_url("DEC-002", "/entries") + "?path=analysis/budget.csv"
    )
    assert status == 422
    assert "does not cite" in payload["error"]
    assert "another item does not authorize this one" in payload["error"]
    # The same rule governs the proposal endpoint.
    status, payload = client.api_get(
        sources_url("DEC-002", "/propose")
        + "?path=analysis/budget.csv&key=rail_load&unit=W"
    )
    assert status == 422 and "does not cite" in payload["error"]
    assert snapshot_tree(root) == before, "a refused read wrote something"


def test_the_picker_refuses_an_absolute_path_and_a_path_that_escapes_the_root(served):
    # Canonicalization is `classify()`'s, not this slice's, and it refuses
    # rather than guesses: an absolute path, a scheme, a backslash, a `..` that
    # leaves the root, and a symlink that resolves outside it.
    _app, client, root = served
    outside = root.parent / "outside.csv"
    outside.write_text("key,value\nsecret,1\n", encoding="utf-8")
    (root / "analysis" / "escape.csv").symlink_to(outside)
    before = snapshot_tree(root)

    for path in (
        "/etc/passwd",
        str(outside),
        "../../etc/passwd",
        "analysis/../../outside.csv",
        "analysis/../../../etc/passwd",
        "C:/Windows/win.ini",
        "file:///etc/passwd",
        "analysis\\budget.csv",
    ):
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=" + path
        )
        assert status == 422, (path, payload)
        assert payload["kind"] == "refused"
        # The reason is the authorizer's, whatever refused: absolute, scheme,
        # backslash, or out of the root.
        assert "citation path" in payload["error"], (path, payload)
    # The symlink that resolves outside the root is refused by the same call.
    status, payload = client.api_get(
        sources_url("DEC-001", "/entries") + "?path=analysis/escape.csv"
    )
    assert status == 422
    assert "resolves outside the project root" in payload["error"]
    assert snapshot_tree(root) == before, "a refused read wrote something"


def test_the_picker_refuses_a_cited_file_with_no_registered_reader(tmp_path):
    # Dispatch is `reader_for()` by extension, the same registry extraction
    # uses, and it is not a fallback to a text parse. A cited `.pdf` is named
    # with the registry's own words and never opened.
    root = make_root(tmp_path, files={"analysis/sheet.pdf": "%PDF-1.4\n"})
    (root / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-004\n"
        "    citations:\n"
        "      - path: analysis/sheet.pdf\n"
        "      - path: analysis/noext\n"
        "      - path: analysis/script.py\n",
        encoding="utf-8",
    )
    (root / "analysis" / "noext").write_text("key,value\nfoo,1\n", encoding="utf-8")
    (root / "analysis" / "script.py").write_text("x = 1\n", encoding="utf-8")
    app = start(root)
    try:
        client = Client(app)
        for path, fragment in (
            ("analysis/sheet.pdf", "no source reader for '.pdf' files"),
            ("analysis/noext", "no source reader for 'a file with no extension'"),
            ("analysis/script.py", "no source reader for '.py' files"),
        ):
            status, payload = client.api_get(
                sources_url("DEC-004", "/entries") + "?path=" + path
            )
            assert status == 422, (path, payload)
            assert fragment in payload["error"], (path, payload)
        # and it is not listable either
        status, payload = client.api_get(sources_url("DEC-004"))
        assert payload["files"] == []
        assert len(payload["problems"]) == 3
    finally:
        app.stop()


def test_the_picker_requires_the_launch_token_on_reads(served):
    # The launch token is required on reads as well as writes, and that is
    # inherited: these routes are `/api/` routes, so the framework's check runs
    # before any of this code does. The session cookie alone is not enough --
    # the header is what a cross-site page cannot set.
    _app, client, _root = served
    for path in (
        sources_url("DEC-001"),
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv",
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=rail_load&unit=W",
    ):
        status, headers, body = client.request("GET", path)
        assert status == 403, path
        assert b"token" in body
        status, _h, _b = client.request(
            "GET", path, headers={"X-Refdes-Token": "wrong"}
        )
        assert status == 403, path
        status, _h, _b = client.request("GET", path, cookie=True)
        assert status == 403, path
        assert client.api_get(path)[0] == 200


def test_the_picker_is_not_a_write_surface(served):
    _app, client, root = served
    before = snapshot_tree(root)
    for path in (
        sources_url("DEC-001"),
        sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv",
    ):
        status, _payload = client.api_post(path, {})
        assert status == 405
        assert snapshot_tree(root) == before


def test_a_row_problem_never_carries_an_absolute_server_path(tmp_path):
    """§6, and the case the payload-level walk above missed.

    Every string that reaches a response is checked there -- but that test only
    ever read *failing* listings and refusals. A listing that SUCCEEDS still
    ships the reader's per-row diagnostics on each unselectable row, and those
    name the file the reader was handed, which is `project.root + canon`. The
    top-level `path` field was always relative; the row `problem` strings were
    not, and they handed the server's home directory and username to anything
    that could reach the endpoint.

    So this asserts the narrow thing directly, on the narrowest possible
    fixture: an authorized, correctly-cited CSV whose rows have problems. If
    the label the reader writes ever stops being the caller's label again, this
    fails.
    """
    root = make_root(tmp_path, csv=BROKEN_CSV)
    app = start(root)
    try:
        client = Client(app)
        absolute = str(root.resolve())
        url = sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        status, payload = client.api_get(url)
        assert status == 200, payload
        # The fixture has to be one that actually produces row problems, or
        # this test would pass vacuously.
        problems = [e for e in payload["entries"] if e["problem"]]
        assert len(problems) == 3, payload["entries"]

        for entry in payload["entries"]:
            for text in (entry["problem"], entry["key"], entry["raw"], entry["value"]):
                assert absolute not in text, (entry, text)
            if not entry["problem"]:
                continue
            # ...and the canonical spelling is what is there instead.
            assert entry["problem"].startswith("analysis/budget.csv:"), entry["problem"]
            assert not entry["problem"].startswith("/"), entry["problem"]
            assert "\\" not in entry["problem"], entry["problem"]

        # The whole payload, walked, not just the problem strings: the leak was
        # a field-by-field oversight once already.
        for text in strings(payload):
            assert absolute not in text, text
            assert not text.startswith("/"), text
            assert "\\" not in text, text

        # The proposal endpoint quotes a row's problem back when it refuses an
        # unselectable key, so it carried the same leak by a different route --
        # a refusal, not a row. Both are covered, and the valid key on the same
        # broken file is covered too.
        for key, unit in (("dup", "1"), ("not_a_number", "1"), ("rail_load", "W")):
            status, payload = client.api_get(
                sources_url("DEC-001", "/propose")
                + f"?path=analysis/budget.csv&key={key}&unit={unit}"
            )
            assert status in (200, 422), (key, payload)
            for text in strings(payload):
                assert absolute not in text, (key, text)
                assert not text.startswith("/"), (key, text)
                assert "\\" not in text, (key, text)
    finally:
        app.stop()


def test_the_picker_never_returns_an_absolute_server_path(tmp_path):
    # §6: responses carry project-relative paths only. The picker's payloads
    # are built from the canonical path `authorize_source_path` returns, and
    # the reader's own diagnostics -- which name the file they were handed --
    # are folded back to that same spelling before they leave the process.
    root = make_root(tmp_path, items=(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-005\n"
        "    citations:\n"
        "      - path: analysis/budget.csv\n"
        "      - path: analysis/nocolumn.csv\n"
    ))
    (root / "analysis" / "nocolumn.csv").write_text(
        "key,note\nfoo,x\n", encoding="utf-8"
    )
    fetch(root)
    app = start(root)
    try:
        client = Client(app)
        absolute = str(root.resolve())
        payloads = [
            client.api_get(sources_url("DEC-005"))[1],
            client.api_get(
                sources_url("DEC-005", "/entries") + "?path=analysis/budget.csv"
            )[1],
            client.api_get(
                sources_url("DEC-005", "/entries") + "?path=analysis/nocolumn.csv"
            )[1],
            client.api_get(
                sources_url("DEC-001", "/entries") + "?path=/etc/passwd"
            )[1],
            client.api_get(
                sources_url("DEC-001", "/entries") + "?path=../../secret.csv"
            )[1],
            client.api_get(
                sources_url("DEC-001", "/propose")
                + "?path=analysis/budget.csv&key=rail_load&unit=nope"
            )[1],
        ]
        # the reader's own diagnostic, and it names the file relatively
        assert payloads[2]["entries"] == []
        assert any("no 'value' column" in p for p in payloads[2]["problems"])
        assert any("analysis/nocolumn.csv:1" in p for p in payloads[2]["problems"])
        for payload in payloads:
            for text in strings(payload):
                assert absolute not in text, text
                assert not text.startswith("/"), text
                assert "\\" not in text, text
        assert payloads[0]["files"][0]["path"] == "analysis/budget.csv"
    finally:
        app.stop()


def test_a_missing_path_or_key_is_a_400_not_a_search(served):
    _app, client, _root = served
    status, payload = client.api_get(sources_url("DEC-001", "/entries"))
    assert status == 400 and "path is required" in payload["error"]
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose") + "?key=rail_load"
    )
    assert status == 400 and "path is required" in payload["error"]
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose") + "?path=analysis/budget.csv"
    )
    assert status == 400 and "key is required" in payload["error"]
    # An item that is not there is a 404, like every other item read.
    status, payload = client.api_get(sources_url("NOPE-999"))
    assert status == 404 and "no item matches" in payload["error"]


# ------------------------------------------------------------- sealed/imported


def test_the_picker_reads_a_sealed_item_and_an_imported_one(tmp_path):
    # §9 Q6, recommended A: reads are allowed. Seeing where a value came from
    # is review, and review is what a sealed entry's readers do; the refusal
    # that belongs there is Accept's, because Accept is a body write. This test
    # pins the read half of that, because the alternative -- a picker that
    # silently shows nothing on a sealed entry -- is the shape that looks like
    # "this item has no sources".
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
        _status, view = client.api_get("/api/item/LOG-001")
        assert view["sealed"] is True
        assert view["edit"]["editable"] is False  # the write is still refused
        before = snapshot_tree(root)
        status, payload = client.api_get(sources_url("LOG-001"))
        assert status == 200, payload
        assert [f["path"] for f in payload["files"]] == ["analysis/budget.csv"]
        status, payload = client.api_get(
            sources_url("LOG-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert [e["key"] for e in payload["entries"]] == ["rail_load", "eff", "other"]
        status, payload = client.api_get(
            sources_url("LOG-001", "/propose")
            + "?path=analysis/budget.csv&key=eff&unit=1"
        )
        assert status == 200, payload
        assert payload["line"] == 'eff = source("analysis/budget.csv", "eff") | 1'
        assert snapshot_tree(root) == before, "a read on a sealed item wrote something"
    finally:
        app.stop()


def test_the_picker_reads_an_imported_item(tmp_path):
    # An imported item is not this project's to verify, so its citations are
    # not in `item.citations` and the pin state is only what the lockfile has.
    # It is still readable: the declared path is the declaration, and the
    # authorizer does not care where the item came from.
    upstream = {
        "title": "Platform",
        "version": "1.0",
        "items": [
            {
                "id": "IFC-001",
                "type": "decision",
                "fields": {
                    "citations": [{"path": "analysis/budget.csv"}],
                },
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    root = make_root(tmp_path)
    (root / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    with (root / "refdes-project.yaml").open("a", encoding="utf-8") as fh:
        fh.write('\nimports:\n  - name: platform\n    items: upstream.json\n')
    app = start(root)
    try:
        client = Client(app)
        _status, view = client.api_get("/api/item/IFC-001")
        assert view["external"] is True
        status, payload = client.api_get(sources_url("IFC-001"))
        assert status == 200, payload
        assert [f["path"] for f in payload["files"]] == ["analysis/budget.csv"]
        # no record of its own in this project's lockfile yet
        assert payload["files"][0]["state"] == "unpinned"
        assert payload["files"][0]["pinned_values"] == {}
        status, payload = client.api_get(
            sources_url("IFC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert [e["key"] for e in payload["entries"]] == ["rail_load", "eff", "other"]
    finally:
        app.stop()


# --------------------------------------------------------------- 3: the line


def test_the_proposed_line_parses_back_through_parse_source_call(served):
    from refdes import calc as calc_mod

    _app, client, root = served
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=rail_load&unit=W"
    )
    assert status == 200, payload
    # The name is proposed from the key, not from the item, and it is editable:
    # lowercased with non-alphanumerics folded to underscores.
    assert payload["line"] == 'rail_load = source("analysis/budget.csv", "rail_load") | W'
    assert payload["complete"] is True
    assert payload["name"] == "rail_load"
    # The server composed it and checked it against the evaluator's own
    # grammar, so the browser never learns the spelling.
    pipe = calc_mod.PIPE_UNIT_RE.match(payload["line"])
    assigned = calc_mod.ASSIGN_RE.match(pipe.group("lhs"))
    assert pipe.group("unit") == "W"
    assert assigned and assigned.group(1) == "rail_load"
    assert calc_mod.parse_source_call(assigned.group(2))[:2] == (
        "analysis/budget.csv", "rail_load",
    )
    # The row the line was read from comes back with it: the confirm panel's
    # whole point is that the author sees the cell this line names, next to the
    # value the lockfile pins for it.
    assert payload["entry"]["raw"] == "1.85"
    assert payload["entry"]["value"] == "1.85"
    assert payload["entry"]["line"] == 2
    assert payload["entry"]["context"] == [{"name": "note", "text": "mW budget"}]
    assert (payload["entry"]["pinned"], payload["entry"]["changed"]) == ("1.85", False)


def test_the_proposal_carries_no_unit_and_no_line_until_the_author_declares_one(served):
    # The unit is never guessed and never defaulted (`calc-sources.md` §6): with
    # no `unit` the endpoint returns no line at all and says why, rather than
    # putting a plausible one in the gap. `1` is offered as a suggestion
    # because a dimensionless value is written `| 1`, not because it is right.
    _app, client, root = served
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=rail_load"
    )
    assert status == 200, payload
    assert payload["line"] is None
    assert payload["complete"] is False
    assert payload["unit"] == ""
    assert "the unit is yours to declare" in payload["reason"]
    assert "no default" in payload["reason"]
    # suggestions, drawn from this item's own calc lines, `1` first
    assert payload["units"] == ["1", "W"]


def test_the_proposal_refuses_an_unknown_unit_before_anything_is_inserted(served):
    # The same pint path evaluation uses, so an unknown unit is refused on the
    # panel instead of becoming a failed calc row after a save.
    _app, client, root = served
    before = snapshot_tree(root)
    for unit in ("bananas", "notaunit", "Watt", "1%202"):
        status, payload = client.api_get(
            sources_url("DEC-001", "/propose")
            + f"?path=analysis/budget.csv&key=rail_load&unit={unit}"
        )
        assert status == 422, (unit, payload)
        assert payload["kind"] == "refused"
        assert "unknown unit" in payload["error"], (unit, payload)
    # `1` -- dimensionless, out loud -- is not an unknown unit.
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=rail_load&unit=1"
    )
    assert status == 200 and payload["line"].endswith("| 1")
    assert snapshot_tree(root) == before


def test_the_proposal_refuses_a_name_the_item_already_assigns(served):
    # A collision is a build error the diagnostic gate would refuse anyway; the
    # evaluator checks the whole item at once, because blocks share one scope.
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=eff&unit=1&name=P"
    )
    assert status == 422, payload
    assert "already assigned in this item" in payload["error"]
    assert "'P_2'" in payload["error"]  # and it names the way out
    # A name that is not a plain identifier would not parse as an assignment.
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=eff&unit=1&name=not%20a%20name"
    )
    assert status == 422 and "not usable as a calc variable name" in payload["error"]
    # A free name is accepted, and an author's own spelling is kept.
    status, payload = client.api_get(
        sources_url("DEC-001", "/propose")
        + "?path=analysis/budget.csv&key=eff&unit=1&name=my_eff"
    )
    assert status == 200, payload
    assert payload["line"] == 'my_eff = source("analysis/budget.csv", "eff") | 1'
    assert snapshot_tree(root) == before


def test_the_proposal_refuses_a_row_that_is_not_selectable(tmp_path):
    root = make_root(tmp_path, csv=BROKEN_CSV)
    app = start(root)
    try:
        client = Client(app)
        base = sources_url("DEC-001", "/propose") + "?path=analysis/budget.csv"
        # A duplicated key cannot be picked: offering either copy would be this
        # tool making the choice the reader exists to refuse.
        status, payload = client.api_get(base + "&key=dup&unit=1")
        assert status == 422, payload
        assert "cannot be picked" in payload["error"]
        assert "appears on 2 rows" in payload["error"]
        status, payload = client.api_get(base + "&key=not_a_number&unit=1")
        assert status == 422
        assert "not a plain ASCII decimal" in payload["error"]
        # A key the file does not have is refused by name, not offered as
        # something the picker might read for itself.
        status, payload = client.api_get(base + "&key=rail&unit=1")
        assert status == 422
        assert "no row has the key 'rail'" in payload["error"]
    finally:
        app.stop()


def test_the_proposal_refuses_a_key_source_cannot_express(tmp_path):
    # `source()` takes two string literals with no escapes, so a key holding a
    # quote has no source() spelling. That is refused with a reason rather than
    # composed into a line that would not parse later.
    root = make_root(
        tmp_path, csv='key,value,note\nwith"quote,1,x\nok,1,y\n'
    )
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/propose")
            + "?path=analysis/budget.csv&key=with%22quote&unit=1"
        )
        assert status == 422, payload
        assert "cannot express" in payload["error"]
        assert "no source() spelling" in payload["error"]
    finally:
        app.stop()


# ------------------------------------------------------------ nothing was written


def test_reading_the_picker_writes_nothing_anywhere(tmp_path):
    """The whole surface, in one assertion. These routes are reads, so the
    project -- item files, the cited CSV, and the citation lockfile -- must come
    out byte for byte as it went in. Accept, which writes the lockfile, is
    Slice B; this is the line that keeps Slice A honest until then."""
    root = make_root(tmp_path, csv=BROKEN_CSV, items=ITEMS + (
        "  - id: DEC-006\n"
        "    citations:\n"
        "      - path: analysis/budget.csv\n"
    ))
    fetch(root)
    pinned = lock_bytes(root)
    assert b"rail_load" in pinned  # the fixture really did pin something
    app = start(root)
    try:
        client = Client(app)
        before = snapshot_tree(root)
        calls = [
            sources_url("DEC-001"),
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv",
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv&q=dup",
            sources_url("DEC-001", "/propose")
            + "?path=analysis/budget.csv&key=eff&unit=1",
            sources_url("DEC-001", "/propose")
            + "?path=analysis/budget.csv&key=eff&unit=nonsense",
            sources_url("DEC-001", "/entries") + "?path=other.csv",
            sources_url("DEC-001", "/entries") + "?path=/etc/passwd",
            sources_url("DEC-001", "/entries") + "?path=analysis/nope.csv",
            sources_url("NOPE-999"),
        ]
        for call in calls:
            status, _payload = client.api_get(call)
            assert status in (200, 400, 404, 422), (call, status)
        assert snapshot_tree(root) == before
        assert lock_bytes(root) == pinned
    finally:
        app.stop()


def test_a_no_write_server_still_offers_the_picker(tmp_path):
    # A read-only server is still a reader: the picker browses and offers, and
    # the refusal that belongs to a write is the one the edit route already
    # carries. This is the read half of `test_a_no_write_server_offers_the_
    # picker_and_refuses_accept`'s eventual other half.
    root = make_root(tmp_path)
    fetch(root)
    app = start(root, read_only=True)
    try:
        client = Client(app)
        status, payload = client.api_get(sources_url("DEC-001"))
        assert status == 200, payload
        assert [f["path"] for f in payload["files"]] == ["analysis/budget.csv"]
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200 and len(payload["entries"]) == 3
        before = snapshot_tree(root)
        status, payload = client.api_post(
            "/api/item/DEC-001/edit",
            {"op": "set_field", "field": "x", "value": "y",
             "expected_revision": "0" * 64},
        )
        assert status == 403
        assert "--no-write" in payload["error"]
        assert snapshot_tree(root) == before
    finally:
        app.stop()


def test_a_missing_cited_file_is_named_not_silently_empty(tmp_path):
    root = make_root(tmp_path)
    os.remove(root / "analysis" / "budget.csv")
    app = start(root)
    try:
        client = Client(app)
        status, payload = client.api_get(
            sources_url("DEC-001", "/entries") + "?path=analysis/budget.csv"
        )
        assert status == 200, payload
        assert payload["entries"] == []
        assert any("cannot read file" in p for p in payload["problems"])
        assert any(str(root) not in p for p in payload["problems"])
    finally:
        app.stop()
