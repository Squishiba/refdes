"""Contract tests for "follow the editor" in the docs-context viewer (DC-4a-tests).

RED-FIRST: written before the implementation exists. The implementer adds a
``POST /api/focus`` + ``GET /api/focus`` pair to ``tools/docs_context/server.py``
and the follow control to ``static/app.js``/``static/index.html``. This file
creates nothing under ``tools/``; every test here fails on its own.

The feature (slice DC-4): Jared edits a docs page in VS Code; a small
unshipped extension (DC-4b, a later slice) POSTs the editor's cursor line to
the viewer so the viewer tab beside the editor selects the block under the
cursor. This slice is the viewer side only.

Contract under test (spec DC-4a):
  POST   ``/api/focus`` {"path": repo-relative posix path, "line": int 1-based}.
         Same guards as /api/ask: Host guard, ``X-Docs-Context: 1`` required,
         Origin absent-or-exactly-own-origin, Content-Type application/json
         (415), body <= 1024 bytes (400), invalid JSON/types/line < 1 or
         > 10_000_000 (400), security headers on every response, no CORS.
         200 {"followed": true, "line": N, "block": B} when path names the
         served doc (posix, case-sensitive, a leading ``./`` normalised), B
         being the start_line of the block containing N, else of the nearest
         block that starts at or before N, else the first block; a line past
         the last block clamps to the last block. 200 {"followed": false,
         "reason": "other-doc"} for any other path -- ``..``, absolute, NUL and
         dot-prefixed lookalikes are answered by string comparison only,
         never opened, never resolved on disk.
  state  the last accepted focus lives in memory only (lock-protected,
         monotonically increasing ``seq``); nothing is written to disk.
  GET    ``/api/focus`` -> 200 {"seq", "line", "block", "path"}: the
         remembered focus (seq 0, line/block null before any POST; path is
         the served doc's repo-relative path). Cheap: never parses. seq
         increments on every ACCEPTED (followed) POST -- including the same
         line twice; the UI de-duplicates by block. Other methods -> 405 JSON.
         block is computed at POST time from the same (mtime_ns, size) cache
         /api/doc uses, so a POST on an unchanged file resolves nothing, and
         an edited file's POST reflects the NEW analysis.
  page   app.js polls /api/focus on the EXISTING interval (no second
         setInterval), has a checkbox ``follow`` (default checked); when it is
         on and the focused block changes it selects that block and scrolls it
         into view; manual click selection wins until the next focus seq (the
         app carries that comment). All DOM via textContent; index.html keeps
         the no-inline-script / no-external-URL contract.

Ambiguities this slice resolves (pinned here so the implementer inherits them):
  * "path" in the GET payload is the SERVED doc's repo-relative path, always
    (the spec types it ``str``, not nullable; nulls are line/block only).
  * "accepted" means answered with followed=true: an other-doc POST, a 4xx,
    and a GET change nothing, not even seq.
  * the POST responses carry EXACTLY the enumerated keys (no seq in the POST
    reply; the UI reads seq from GET /api/focus).
  * a body of exactly 1024 bytes is accepted ("<= 1024"); extra keys are
    ignored, as on /api/ask.

Servers bind 127.0.0.1:0 with the socket timeout on every client call, and
every thread is shut down in the ``finally`` -- on ubuntu and windows alike.
"""

from __future__ import annotations

import builtins
import http.client
import json
import os
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from docs_context import refs
from test_docs_context_server import (
    STATIC,
    addr_of,
    get_json,
    make_repo,
    request,
    running,
    tree_snapshot,
)

FOCUS_HEADERS = {"X-Docs-Context": "1", "Content-Type": "application/json"}

F_DOC = "\n\nFirst paragraph `src/pkg/mod.py:5`.\n\nSecond paragraph.\n"

# docs/a.md blocks (make_repo's fixture): 1 heading, 3, 5, 7 paragraphs.
# docs/f.md (served in the "before the first block" case): 3, 5 paragraphs.


def post_focus(base, body, headers):
    host, port = addr_of(base)
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("POST", "/api/focus", body=body, headers=headers)
        resp = conn.getresponse()
        return (
            resp.status,
            resp.getheader("Content-Type", "").lower(),
            {k.lower(): v for k, v in resp.getheaders()},
            resp.read(),
        )
    finally:
        conn.close()


def focus(base, path, line, headers=None):
    body = json.dumps({"path": path, "line": line}).encode("utf-8")
    return post_focus(base, body, FOCUS_HEADERS if headers is None else headers)


def raw_request(base, method, path, body=None):
    host, port = addr_of(base)
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        return (
            resp.status,
            resp.getheader("Content-Type", "").lower(),
            {k.lower(): v for k, v in resp.getheaders()},
            resp.read(),
        )
    finally:
        conn.close()


def focus_json(base, path, line, **kwargs):
    status, ctype, headers, body = focus(base, path, line, **kwargs)
    assert "application/json" in ctype, (status, ctype)
    return status, json.loads(body), headers


def followed(base, path, line):
    """POST a focus on the served doc and return the block it selected."""
    status, data, _headers = focus_json(base, path, line)
    assert status == 200, data
    assert data["followed"] is True, data
    return data


def get_focus(base):
    return get_json(base, "/api/focus")


def append_line(doc, text):
    doc.write_text(doc.read_text(encoding="utf-8") + text, encoding="utf-8", newline="")


def tick_body(app_text):
    """The body of the app's poll function, as text (the interval machinery)."""
    match = re.search(r"async function tick\(\)\s*\{(.*?)\n\}", app_text, flags=re.DOTALL)
    assert match, "app.js must keep its async tick() poll function"
    return match.group(1)


def input_tags(index_text):
    return re.findall(r"<input\b[^>]*>", index_text, flags=re.IGNORECASE)


# ------------------------------------------------------- POST: block under cursor


def test_focus_post_follows_the_block_under_the_cursor(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        assert followed(base, "docs/a.md", 3) == {"followed": True, "line": 3, "block": 3}
        assert followed(base, "docs/a.md", 1) == {"followed": True, "line": 1, "block": 1}
        assert followed(base, "docs/a.md", 5)["block"] == 5
        assert followed(base, "docs/a.md", 7)["block"] == 7


def test_focus_post_accepts_a_leading_dot_slash(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        assert followed(base, "./docs/a.md", 3) == {"followed": True, "line": 3, "block": 3}


def test_focus_post_on_a_gap_line_uses_the_block_before_it(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for line, block in ((2, 1), (4, 3), (6, 5)):
            data = followed(base, "docs/a.md", line)
            assert data["line"] == line, (line, data)
            assert data["block"] == block, (line, data)


def test_focus_post_past_the_last_block_clamps_to_the_last_block(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for line in (8, 400, 10_000_000):
            data = followed(base, "docs/a.md", line)
            assert data["block"] == 7, (line, data)


def test_focus_post_before_the_first_block_uses_the_first_block(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "f.md"
    doc.write_text(F_DOC, encoding="utf-8", newline="")
    with running(repo, doc=doc) as base:
        data = followed(base, "docs/f.md", 1)
        assert data == {"followed": True, "line": 1, "block": 3}


# ---------------------------------------------------------- POST: other documents


OTHER_DOC_PATHS = [
    "docs/b.md",  # a real page, not the served one
    "./docs/b.md",  # normalised, still other
    "docs/nope.md",  # a shape that does not exist
    "docs/A.md",  # case-sensitive: the served doc on a case-insensitive FS
    "DOCS/a.md",
    "src/pkg/mod.py",  # not markdown at all
]


def test_focus_post_on_another_doc_is_not_followed(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for path in OTHER_DOC_PATHS:
            status, data, _headers = focus_json(base, path, 3)
            assert status == 200, (path, data)
            assert data == {"followed": False, "reason": "other-doc"}, (path, data)


def test_focus_post_never_opens_a_path_it_is_given(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    outside_md = os.path.realpath(tmp_path / "outside.md")
    outside_txt = os.path.realpath(tmp_path / "outside.txt")
    git_config = os.path.realpath(repo / ".git" / "config")
    git_config_md = os.path.realpath(repo / ".git" / "config.md")

    # answered by string comparison alone: never opened, never resolved
    probes = [
        "../outside.md",
        "docs/../../outside.md",
        "..\\outside.md",
        str(tmp_path / "outside.md"),  # absolute
        "/etc/passwd",
        "C:\\outside.md",
        "docs/a.md\x00.md",  # NUL: a path component, not a suffix
        ".git/config.md",
        ".git/config",
    ]

    opened = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    with running(repo) as base:
        for probe in probes:
            status, data, _headers = focus_json(base, probe, 3)
            assert status == 200, (probe, status)
            assert data == {"followed": False, "reason": "other-doc"}, (probe, data)
        assert get_json(base, "/api/mtime")[0] == 200  # server survived the matrix

    forbidden = {outside_md, outside_txt, git_config, git_config_md}
    for file in opened:
        if isinstance(file, int):  # open(fd)
            continue
        name = os.fsdecode(file)
        assert "\x00" not in name, name
        assert os.path.realpath(name) not in forbidden, name


# ------------------------------------------------------------------ POST: guards


def test_focus_post_requires_the_docs_context_header(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for headers in (
            {"Content-Type": "application/json"},
            {"X-Docs-Context": "0", "Content-Type": "application/json"},
            {"X-Docs-Context": "yes", "Content-Type": "application/json"},
        ):
            status, _ctype, _headers, body = focus(base, "docs/a.md", 3, headers=headers)
            assert status == 403, headers
            assert json.loads(body) == {"error": "forbidden"}, headers


def test_focus_post_allows_only_its_own_origin(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        port = addr_of(base)[1]
        for origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            status, _data, _headers = focus_json(
                base, "docs/a.md", 3, headers=dict(FOCUS_HEADERS, Origin=origin)
            )
            assert status == 200, origin
        for origin in (
            "http://evil.example.com",
            "null",
            "file://",
            f"http://127.0.0.1:{port + 1}",
        ):
            status, _ctype, _headers, body = focus(
                base, "docs/a.md", 3, headers=dict(FOCUS_HEADERS, Origin=origin)
            )
            assert status == 403, origin
            assert json.loads(body) == {"error": "forbidden"}, origin


def test_focus_post_keeps_the_host_guard(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        assert focus_json(base, "docs/a.md", 3)[0] == 200  # the route itself
        host, port = addr_of(base)
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request(
                "POST",
                "/api/focus",
                body=json.dumps({"path": "docs/a.md", "line": 3}),
                headers=dict(FOCUS_HEADERS, Host="evil.example.com"),
            )
            resp = conn.getresponse()
            body = json.loads(resp.read())
            assert resp.status == 403
            assert body == {"error": "bad host"}
        finally:
            conn.close()


def test_focus_post_rejects_a_non_json_content_type(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for ctype in ("text/plain", "application/x-www-form-urlencoded"):
            status, _ctype, _headers, body = focus(
                base,
                "docs/a.md",
                3,
                headers={"X-Docs-Context": "1", "Content-Type": ctype},
            )
            assert status == 415, ctype
            assert "error" in json.loads(body), ctype
        status, _ctype, _headers, body = focus(
            base, "docs/a.md", 3, headers={"X-Docs-Context": "1"}
        )
        assert status == 415, "a POST with no Content-Type is not JSON"
        assert "error" in json.loads(body)


def test_focus_post_accepts_a_json_content_type_with_charset(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        headers = {"X-Docs-Context": "1", "Content-Type": "application/json; charset=utf-8"}
        status, data, _headers = focus_json(base, "docs/a.md", 3, headers=headers)
        assert status == 200, data
        assert data["block"] == 3


def test_focus_post_rejects_bad_bodies(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        cases = [
            b"not json at all",
            b"[1, 2, 3]",
            b'"a string"',
            b"null",
            b"{}",
            json.dumps({"line": 3}).encode(),  # path missing
            json.dumps({"path": "docs/a.md"}).encode(),  # line missing
            json.dumps({"path": 7, "line": 3}).encode(),
            json.dumps({"path": "docs/a.md", "line": "3"}).encode(),
            json.dumps({"path": "docs/a.md", "line": 3.5}).encode(),
            json.dumps({"path": "docs/a.md", "line": 3.0}).encode(),
            json.dumps({"path": "docs/a.md", "line": True}).encode(),
            json.dumps({"path": "docs/a.md", "line": None}).encode(),
            json.dumps({"path": "docs/a.md", "line": 0}).encode(),
            json.dumps({"path": "docs/a.md", "line": -5}).encode(),
            json.dumps({"path": "docs/a.md", "line": 10_000_001}).encode(),
        ]
        for body in cases:
            status, _ctype, _headers, response = post_focus(base, body, FOCUS_HEADERS)
            assert status == 400, (body, status)
            assert "error" in json.loads(response), body


def test_focus_post_accepts_a_body_of_exactly_1024_bytes(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        payload = {"path": "docs/a.md", "line": 3}
        pad = 1024 - len(json.dumps(payload)) - len(', "pad": ""')
        assert pad > 0
        payload["pad"] = "x" * pad
        body = json.dumps(payload).encode("utf-8")
        assert len(body) == 1024, len(body)
        status, _ctype, _headers, response = post_focus(base, body, FOCUS_HEADERS)
        assert status == 200, (len(body), response)
        assert json.loads(response)["block"] == 3


def test_focus_post_rejects_a_body_over_1024_bytes_without_desyncing(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        host, port = addr_of(base)
        body = json.dumps(
            {"path": "docs/a.md", "line": 3, "pad": "x" * 1100}
        ).encode("utf-8")
        assert len(body) > 1024
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request("POST", "/api/focus", body=body, headers=FOCUS_HEADERS)
            resp = conn.getresponse()
            assert resp.status == 400
            assert "error" in json.loads(resp.read())
            conn.request("GET", "/api/mtime")  # body drained: connection in sync
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
        finally:
            conn.close()


def test_focus_responses_carry_security_headers_and_no_cors(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        cases = [
            focus(base, "docs/a.md", 3),  # 200
            focus(base, "docs/b.md", 3),  # 200 other-doc
            post_focus(base, b"not json", FOCUS_HEADERS),  # 400
            focus(base, "docs/a.md", 0),  # 400 line < 1
            focus(base, "docs/a.md", 3, headers={"Content-Type": "application/json"}),  # 403
            focus(base, "docs/a.md", 3, headers={"X-Docs-Context": "1"}),  # 415
            request(base, "PUT", "/api/focus")[:4],  # 405
        ]
        statuses = [case[0] for case in cases]
        assert statuses == [200, 200, 400, 400, 403, 415, 405], statuses
        for status, _ctype, headers, _body in cases:
            assert headers.get("x-content-type-options") == "nosniff", status
            assert headers.get("cache-control") == "no-store", status
            for key in headers:
                assert not key.startswith("access-control-"), (status, key)


# -------------------------------------------------------------- GET: remembered state


def test_focus_get_reports_the_remembered_focus_and_counts_every_post(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        status, fresh, _ = get_focus(base)
        assert status == 200
        assert fresh == {"seq": 0, "line": None, "block": None, "path": "docs/a.md"}
        focus(base, "docs/a.md", 3)
        _status, first, _ = get_focus(base)
        assert first == {"seq": 1, "line": 3, "block": 3, "path": "docs/a.md"}
        focus(base, "docs/a.md", 3)  # the same line twice: seq increments, UI de-dupes
        _status, second, _ = get_focus(base)
        assert second == {"seq": 2, "line": 3, "block": 3, "path": "docs/a.md"}, second
        focus(base, "docs/a.md", 5)
        _status, third, _ = get_focus(base)
        assert third == {"seq": 3, "line": 5, "block": 5, "path": "docs/a.md"}, third
        focus(base, "docs/b.md", 3)  # not accepted: remembered focus untouched
        focus(base, "docs/a.md", 0)  # 400: not accepted
        _status, after, _ = get_focus(base)
        assert after == third, after
        assert get_json(base, "/api/doc")[0] == 200  # the doc route is untouched


def test_focus_get_is_cheap_and_never_parses(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("/api/focus GET must not parse the doc")

    monkeypatch.setattr(refs, "analyze", boom)
    monkeypatch.setattr(refs, "parse_doc", boom)
    with running(repo) as base:
        for _ in range(3):
            status, data, _ = get_focus(base)
            assert status == 200
            assert data["seq"] == 0


def test_focus_post_on_an_unchanged_file_adds_no_resolve_calls(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    calls = {"n": 0}
    real_resolve = refs.resolve

    def counting(ref, repo_root, doc_path=None):
        calls["n"] += 1
        return real_resolve(ref, repo_root, doc_path=doc_path)

    monkeypatch.setattr(refs, "resolve", counting)
    with running(repo) as base:
        assert get_json(base, "/api/doc")[0] == 200  # warm the shared cache
        warmed = calls["n"]
        assert warmed > 0, "the warm /api/doc must resolve the fixture refs"
        for line in (3, 5, 7, 999):
            assert followed(base, "docs/a.md", line)["block"] is not None, line
        assert calls["n"] == warmed, "a focus POST on an unchanged file resolves nothing"


def test_focus_block_follows_an_edit(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    with running(repo) as base:
        assert followed(base, "docs/a.md", 9)["block"] == 7  # clamps: line 9 is past EOF
        append_line(doc, "\nAppended paragraph `src/pkg/mod.py:20`.\n")
        assert followed(base, "docs/a.md", 9)["block"] == 9  # the NEW analysis
        assert followed(base, "docs/a.md", 11)["block"] == 9  # clamps to the new last block


def test_focus_state_lives_in_memory_only(tmp_path):
    repo = make_repo(tmp_path)
    before = tree_snapshot(tmp_path)
    with running(repo) as base:
        for line in (1, 3, 5, 7, 999):
            status, data, _ = focus_json(base, "docs/a.md", line)
            assert status == 200, (line, data)
        assert get_focus(base)[0] == 200
        for probe in ("../outside.md", str(tmp_path / "outside.md"), "docs/a.md\x00.md"):
            assert focus_json(base, probe, 3)[0] == 200
        assert get_json(base, "/api/doc")[0] == 200
    assert tree_snapshot(tmp_path) == before


def test_focus_seq_increments_once_per_accepted_post_under_concurrency(tmp_path):
    repo = make_repo(tmp_path)
    lines = [1, 3, 5, 7, 2, 4, 6, 8]

    def worker(line, results):
        try:
            status, data, _ = focus_json(base, "docs/a.md", line)
            results.append((status, data))
        except (OSError, http.client.HTTPException, ValueError, AssertionError) as exc:
            results.append(("error", repr(exc)))

    with running(repo) as base:
        results = []
        threads = [
            threading.Thread(target=worker, args=(line, results)) for line in lines
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive(), "a focus POST hung"
        assert [status for status, _data in results] == [200] * len(lines), results
        assert all(data["followed"] is True for _status, data in results), results
        _status, state, _ = get_focus(base)
        assert state["seq"] == len(lines), state
        assert state["block"] in (1, 3, 5, 7), state  # one of the four real blocks
        assert state["line"] in lines, state


def test_focus_route_leaves_every_other_path_alone(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        assert focus_json(base, "docs/a.md", 3)[0] == 200
        assert get_focus(base)[0] == 200
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            status, ctype, _headers, body = request(base, method, "/api/focus")
            assert status == 405, method
            assert "application/json" in ctype, method
            assert json.loads(body) == {"error": "method not allowed"}, method
        for path in ("/api/mtime", "/api/doc", "/", "/nope"):
            status, _ctype, _headers, body = raw_request(base, "POST", path, b"{}")
            assert status == 405, path
            assert json.loads(body) == {"error": "method not allowed"}, path
        assert get_json(base, "/api/mtime")[0] == 200


# ------------------------------------------------------------------- static page


def app_js_text():
    return (STATIC / "app.js").read_text(encoding="utf-8")


def index_html_text():
    return (STATIC / "index.html").read_text(encoding="utf-8")


def has(needle, haystack, why):
    assert needle in haystack, f"{why}: missing {needle!r}"


def has_not(needle, haystack, why):
    assert needle not in haystack, f"{why}: found {needle!r}"


def test_app_js_polls_the_focus_route_on_the_existing_interval():
    app = app_js_text()
    has("/api/focus", app, "the viewer polls the focus route")
    has("/api/mtime", app, "the mtime poll must survive")
    assert app.count("setInterval(") == 1, "one interval machinery: the tick polls both"
    body = tick_body(app).lower()
    assert "focus" in body, "tick() must poll the focus route (no second setInterval)"


def test_app_js_has_a_follow_checkbox_control():
    app = app_js_text()
    has('getElementById("follow")', app, "the follow checkbox is looked up by id")
    has(".checked", app, "the follow state is read from the checkbox")
    index = index_html_text()
    has('id="follow"', index, "index.html carries the follow checkbox markup")
    follow_tags = [tag for tag in input_tags(index) if 'id="follow"' in tag]
    assert follow_tags, 'no <input id="follow"> in index.html'
    assert 'type="checkbox"' in follow_tags[0], follow_tags[0]
    assert re.search(r"\bchecked\b", follow_tags[0]), f"default checked: {follow_tags[0]}"
    labels = re.findall(r"<label\b[^>]*>(.*?)</label>", index, flags=re.DOTALL | re.IGNORECASE)
    label_text = " ".join(re.sub(r"<[^>]*>", " ", text) for text in labels)
    assert "follow" in label_text.lower(), "the checkbox label must say follow"


def test_app_js_follow_selects_and_scrolls_the_focused_block():
    app = app_js_text()
    assert app.count("scrollIntoView") >= 2, (
        "the follow path selects the focused block and scrolls it into view "
        "(the existing keyboard moveSelection is the first call site)"
    )
    has("select(", app, "selecting the block reuses the existing selection path")
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        has_not(forbidden, app, "the DOM stays textContent-only")


def test_app_js_manual_selection_wins_until_the_next_focus():
    app = app_js_text()
    has(
        "manual selection wins until the next focus",
        app,
        "the documented rule: a manual click is not overridden until the seq moves",
    )


def test_index_html_focus_markup_keeps_the_page_contract():
    index = index_html_text()
    has('id="follow"', index, "the checkbox markup lives in index.html")
    for attrs, body in re.findall(
        r"<script\b([^>]*)>(.*?)</script>", index, flags=re.DOTALL | re.IGNORECASE
    ):
        has("src=", attrs, "scripts stay external only")
        assert body.strip() == "", "the follow checkbox must not need an inline script"
    has_not("http://", index, "no external urls in index.html")
    has_not("https://", index, "no external urls in index.html")
