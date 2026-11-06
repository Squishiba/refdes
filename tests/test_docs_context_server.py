"""Contract tests for the docs-context viewer server (tools/docs_context/server.py).

DC-2 (slice DC-2-tests, written red-first) adds a small local web viewer on
top of DC-1's refs library: a stdlib-only HTTP server bound to 127.0.0.1 plus
a static page, so Jared can keep it open beside his editor while
hand-rewriting a docs page and see, per paragraph, what it references. No
Qwen, no network egress, no writes.

Imported from its file path the way ``tests/test_docs_context_refs.py``
imports ``refs``: ``tools/`` is not a shipped package; a namespace-package
import off a ``sys.path`` entry needs no ``__init__.py``.

Contract under test (spec DC-2):
  CLI  ``python tools/docs_context/server.py <doc.md> [--repo ROOT]
        [--port N] [--no-open]``; default --repo found upward from the doc
        (git/refdes root, else the doc's parent); port default 0; binds only
        127.0.0.1; prints exactly one banner line
        ``docs-context: http://127.0.0.1:<port>/`` once listening; exit 2 +
        stderr for a missing/non-.md doc or a doc outside --repo.
  API  make_server(doc_path, repo_root, port=0) -> (httpd, base_url).
       GET /, /static/<name>, /api/doc(+?path=), /api/mtime,
       /api/file?path=&line=; any other method -> 405 JSON.
  Sec  Host allowlist (DNS-rebinding), nosniff + no-store on every response,
       never any CORS header, never writes, path probes never open()
       outside the repo, HEAD never crashes it.
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from queue import Queue
from urllib.parse import quote, urlsplit

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from docs_context import refs, server

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "docs_context" / "server.py"
STATIC = ROOT / "tools" / "docs_context" / "static"


def make_mod_py():
    lines = ["# mod.py", "def alpha42():", "    return 42"]
    lines += [f"# line {n}" for n in range(4, 31)]
    return lines


MOD_PY = make_mod_py()

A_DOC_LINES = [
    "# Alpha guide",  # 1
    "",  # 2
    "See `src/pkg/mod.py:5` and run `refdes navis ls` for the listing.",  # 3
    "",  # 4
    "Details in [usage](b.md#usage). Bad anchor: [nope](b.md#nope).",  # 5
    "",  # 6
    "The end refers to `src/pkg/mod.py:28`.",  # 7
]
A_DOC = "\n".join(A_DOC_LINES) + "\n"

B_DOC_LINES = [
    "# B page",  # 1
    "",  # 2
    "## Usage",  # 3
    "",  # 4
    "Usage paragraph.",  # 5
]
B_DOC = "\n".join(B_DOC_LINES) + "\n"


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "mod.py").write_text(
        "\n".join(MOD_PY) + "\n", encoding="utf-8", newline=""
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text(A_DOC, encoding="utf-8", newline="")
    (repo / "docs" / "b.md").write_text(B_DOC, encoding="utf-8", newline="")
    (repo / "sub").mkdir()
    (repo / "sub" / "data.bin").write_bytes(b"\x00\x01\x02\nbinary\n")
    with open(repo / "sub" / "big.bin", "wb") as fh:
        fh.truncate(3 * 1024 * 1024)
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8", newline="")
    (repo / ".git" / "config.md").write_text(
        "# Inside git\n\nNot a doc.\n", encoding="utf-8", newline=""
    )
    (tmp_path / "outside.txt").write_text("outside file\n", encoding="utf-8", newline="")
    (tmp_path / "outside.md").write_text(
        "# Outside\n\nsecret page.\n", encoding="utf-8", newline=""
    )
    return repo


def append_line(doc, text):
    doc.write_text(
        doc.read_text(encoding="utf-8") + text, encoding="utf-8", newline=""
    )


# ------------------------------------------------------------- server plumbing


def addr_of(base_url):
    parts = urlsplit(base_url)
    assert parts.scheme == "http", base_url
    assert parts.hostname == "127.0.0.1", base_url
    assert parts.port is not None, base_url
    return parts.hostname, parts.port


@contextlib.contextmanager
def running(repo, doc=None):
    """make_server + serve_forever in a thread; always shut down in the finally."""
    doc = repo / "docs" / "a.md" if doc is None else doc
    httpd, base_url = server.make_server(str(doc), str(repo), port=0)
    thread = threading.Thread(
        target=httpd.serve_forever, daemon=True, name="docs-context-test-server"
    )
    thread.start()
    try:
        yield base_url
    finally:
        httpd.shutdown()
        thread.join(timeout=10)
        httpd.server_close()


def request(base_url, method, path, headers=None):
    """One request, socket timeout on every call; (status, ctype, headers, body)."""
    host, port = addr_of(base_url)
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        headers_out = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, resp.getheader("Content-Type", "").lower(), headers_out, body
    finally:
        conn.close()


def get_json(base_url, path, headers=None):
    status, ctype, headers, body = request(base_url, "GET", path, headers)
    assert "application/json" in ctype, (path, ctype)
    return status, json.loads(body), headers


def get(base_url, path):
    return request(base_url, "GET", path)[:3]


# ------------------------------------------------------------------ make_server


def test_make_server_binds_loopback_ephemeral_and_answers(tmp_path):
    repo = make_repo(tmp_path)
    httpd, base_url = server.make_server(str(repo / "docs" / "a.md"), str(repo))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    try:
        thread.start()
        _host, port = addr_of(base_url)
        assert tuple(httpd.server_address[:2]) == ("127.0.0.1", port)
        assert 0 < port < 65536
        status, data, _ = get_json(base_url, "/api/mtime")
        assert status == 200
        assert isinstance(data["mtime"], float)
    finally:
        httpd.shutdown()
        thread.join(timeout=10)
        httpd.server_close()


# ----------------------------------------------------------------------- routes


def test_root_serves_the_static_index_html(tmp_path):
    repo = make_repo(tmp_path)
    index_text = (STATIC / "index.html").read_text(encoding="utf-8")
    with running(repo) as base:
        status, ctype, _ = get(base, "/")
        assert status == 200
        assert "text/html" in ctype
        body = request(base, "GET", "/")[3].decode("utf-8")
        assert body == index_text


def test_static_serves_app_js_by_name(tmp_path):
    repo = make_repo(tmp_path)
    app_text = (STATIC / "app.js").read_text(encoding="utf-8")
    with running(repo) as base:
        status, ctype, _headers, body = request(base, "GET", "/static/app.js")
        assert status == 200
        assert "javascript" in ctype
        assert body.decode("utf-8") == app_text


STATIC_TRAVERSAL_PATHS = [
    "/static/../refs.py",
    "/static/%2e%2e/refs.py",
    "/static/..\\refs.py",
    "/static/..%5crefs.py",
    "/static/%2f%2e%2e%2frefs.py",
    "/static/%2fetc/passwd",
    "/static//etc/passwd",
    "/static/",
    "/static/%00app.js",
    "/static/app.js%00.png",
    "/static/%2e%2e%2f%2e%2e%2foutside.txt",
]


def test_static_serves_only_names_from_its_own_dir(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for path in STATIC_TRAVERSAL_PATHS:
            status, _ctype, _headers, body = request(base, "GET", path)
            assert status == 404, path
            assert b"docs context refs" not in body  # never leaks refs.py's source
            assert b"outside file" not in body
        # the server is unharmed by the probe storm
        assert get(base, "/api/mtime")[0] == 200


def test_api_doc_shape_matches_refs_analyze(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    expected = refs.analyze(str(doc), str(repo))
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/doc")
        assert status == 200
        assert data["doc"] == "docs/a.md"
        assert data["mtime"] == os.stat(doc).st_mtime
        assert data["blocks"] == expected["blocks"]


def test_api_doc_block_ref_and_card_keys(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _status, data, _ = get_json(base, "/api/doc")
        blocks = data["blocks"]
        assert blocks
        for block in blocks:
            assert {"kind", "start_line", "end_line", "text", "refs"} <= set(block)
            for ref in block["refs"]:
                assert {"kind", "raw", "start", "end"} <= set(ref)
                assert isinstance(ref["card"], dict)
        kinds = {r["kind"] for b in blocks for r in b["refs"]}
        assert {"code_ref", "command", "link"} <= kinds
        cards = {r["kind"]: r["card"] for b in blocks for r in b["refs"]}
        assert cards["command"]["known"] is True
        assert cards["command"]["help"].startswith("usage:")
        anchors = {
            r["anchor"]: r["card"]
            for b in blocks
            for r in b["refs"]
            if r["kind"] == "link"
        }
        assert anchors["usage"]["anchor_ok"] is True
        assert anchors["nope"]["anchor_ok"] is False


def test_api_doc_reflects_edits_between_requests(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    with running(repo) as base:
        _status, first, _ = get_json(base, "/api/doc")
        assert all("Appended paragraph" not in b["text"] for b in first["blocks"])
        append_line(doc, "\nAppended paragraph `src/pkg/mod.py:20`.\n")
        _status, second, _ = get_json(base, "/api/doc")
        assert any("Appended paragraph" in b["text"] for b in second["blocks"])


def test_api_doc_cached_by_mtime_and_size(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    calls = {"n": 0}
    real_resolve = refs.resolve

    def counting(ref, repo_root, doc_path=None):
        calls["n"] += 1
        return real_resolve(ref, repo_root, doc_path=doc_path)

    monkeypatch.setattr(refs, "resolve", counting)
    with running(repo) as base:
        get_json(base, "/api/doc")
        first = calls["n"]
        assert first > 0, "first /api/doc must resolve every ref"
        get_json(base, "/api/doc")
        assert calls["n"] == first, "unchanged (mtime_ns, size) must not re-resolve"
        append_line(doc, "\nExtra paragraph.\n")
        _status, third, _ = get_json(base, "/api/doc")
        assert calls["n"] > first, "changed file must re-resolve"
        assert any("Extra paragraph" in b["text"] for b in third["blocks"])


def test_api_doc_path_param_serves_another_page(tmp_path):
    repo = make_repo(tmp_path)
    expected = refs.analyze(str(repo / "docs" / "b.md"), str(repo))
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/doc?path=docs/b.md")
        assert status == 200
        assert data["doc"] == "docs/b.md"
        assert data["blocks"] == expected["blocks"]


def test_api_doc_path_param_validation(tmp_path):
    repo = make_repo(tmp_path)
    cases = [
        ("src/pkg/mod.py", 400),  # not .md
        ("../outside.txt", 400),  # walks out of the repo
        ("docs/../../outside.txt", 400),
        (".git/config.md", 400),  # .md, inside the repo, under .git/
        (str(tmp_path / "outside.md"), 400),  # absolute
        ("docs/nope.md", 404),  # safe shape, missing file
    ]
    with running(repo) as base:
        for raw, want in cases:
            status, _ctype, _headers, body = request(
                base, "GET", "/api/doc?path=" + quote(raw, safe="")
            )
            assert status == want, (raw, status)
            if want == 400:
                assert "error" in json.loads(body), raw


def test_api_mtime_is_stat_only_never_parses(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"

    def boom(*args, **kwargs):
        raise AssertionError("/api/mtime must not parse the doc")

    monkeypatch.setattr(refs, "analyze", boom)
    monkeypatch.setattr(refs, "parse_doc", boom)
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/mtime")
        assert status == 200
        assert data["mtime"] == os.stat(doc).st_mtime
        # a handler crash under /api/doc must not take the server down
        with pytest.raises(OSError):
            request(base, "GET", "/api/doc")
        assert get(base, "/api/mtime")[0] == 200


def test_api_mtime_reflects_edits(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    with running(repo) as base:
        _status, first, _ = get_json(base, "/api/mtime")
        append_line(doc, "\nExtra.\n")
        _status, second, _ = get_json(base, "/api/mtime")
        assert second["mtime"] == os.stat(doc).st_mtime
        assert second["mtime"] != first["mtime"]


def test_api_file_window_is_plus_minus_15_lines(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/file?path=src/pkg/mod.py&line=10")
        assert status == 200
        assert data["path"] == "src/pkg/mod.py"
        assert data["exists"] is True
        ns = [entry["n"] for entry in data["lines"]]
        assert ns == list(range(1, 26))  # 10-15 clamped to 1, 10+15
        assert all(set(entry) == {"n", "text"} for entry in data["lines"])
        by_n = {entry["n"]: entry["text"] for entry in data["lines"]}
        assert by_n[10] == "# line 10"

        _status, top, _ = get_json(base, "/api/file?path=src/pkg/mod.py&line=1")
        assert [entry["n"] for entry in top["lines"]] == list(range(1, 17))
        _status, tail, _ = get_json(base, "/api/file?path=src/pkg/mod.py&line=30")
        assert [entry["n"] for entry in tail["lines"]] == list(range(15, 31))


def test_api_file_requires_path_and_int_line(tmp_path):
    repo = make_repo(tmp_path)
    cases = [
        "/api/file?path=src/pkg/mod.py",  # line missing
        "/api/file?line=5",  # path missing
        "/api/file?path=src/pkg/mod.py&line=abc",
        "/api/file?path=src/pkg/mod.py&line=1.5",
        "/api/file?path=src/pkg/mod.py&line=",
    ]
    with running(repo) as base:
        for path in cases:
            status, _ctype, _headers, body = request(base, "GET", path)
            assert status == 400, path
            assert "error" in json.loads(body), path


def test_api_file_missing_file_reports_exists_false(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/file?path=src/pkg/gone.py&line=3")
        assert status == 200
        assert data["path"] == "src/pkg/gone.py"
        assert data["exists"] is False
        assert "lines" not in data


def test_api_file_binary_and_oversized_get_refs_error_cards(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/file?path=sub/data.bin&line=1")
        assert status == 200
        assert data["error"] == "not a text file"
        assert "lines" not in data
        _status, big, _ = get_json(base, "/api/file?path=sub/big.bin&line=1")
        assert big["error"] == "too large"
        assert "lines" not in big


def test_other_methods_are_405_json(tmp_path):
    repo = make_repo(tmp_path)
    routes = ["/", "/api/doc", "/api/mtime", "/api/file?path=src/pkg/mod.py&line=1", "/nope"]
    with running(repo) as base:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            for route in routes:
                status, ctype, _headers, body = request(base, method, route)
                assert status == 405, (method, route)
                assert "application/json" in ctype, (method, route)
                assert json.loads(body) == {"error": "method not allowed"}, (method, route)
        assert get(base, "/api/mtime")[0] == 200


def test_head_requests_do_not_crash_the_server(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        for path in ("/", "/api/doc", "/nope"):
            status, _ctype, _headers, body = request(base, "HEAD", path)
            assert status < 500, path
            assert body == b"", path
        assert get(base, "/api/mtime")[0] == 200


def test_unknown_route_is_404(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        status, _ctype, _headers, body = request(base, "GET", "/nope")
        assert status == 404
        assert body is not None
        assert get(base, "/api/mtime")[0] == 200


# ---------------------------------------------------------------------- security


def raw_get(port, host_header, path="/"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": host_header})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_host_header_guard(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _host, port = addr_of(base)
        status, body = raw_get(port, "evil.example.com:1")
        assert status == 403
        assert json.loads(body) == {"error": "bad host"}
        status, body = raw_get(port, f"localhost:{port + 1}")  # rebinding: wrong port
        assert status == 403
        status, body = raw_get(port, f"localhost:{port}")
        assert status == 200
        status, body = raw_get(port, f"127.0.0.1:{port}", "/api/mtime")
        assert status == 200


def test_security_headers_on_every_response(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _host, port = addr_of(base)
        cases = [
            get(base, "/"),
            get(base, "/api/doc"),
            get(base, "/api/mtime"),
            get(base, "/nope"),  # 404
            request(base, "POST", "/api/mtime")[:3],  # 405
        ]
        for status, _ctype, headers in cases:
            assert status in (200, 404, 405)
            assert headers.get("x-content-type-options") == "nosniff", status
            assert headers.get("cache-control") == "no-store", status
        # the 403 from the Host guard carries them too
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", "/", headers={"Host": "evil.example.com:1"})
            resp = conn.getresponse()
            resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            assert resp.status == 403
            assert hdrs.get("x-content-type-options") == "nosniff"
            assert hdrs.get("cache-control") == "no-store"
        finally:
            conn.close()


def test_no_cors_headers_ever(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        cases = [
            get(base, "/"),
            get(base, "/api/doc"),
            get(base, "/nope"),
            request(base, "POST", "/api/mtime")[:3],
        ]
        for _status, _ctype, headers in cases:
            for key in headers:
                assert not key.startswith("access-control-"), key


def tree_snapshot(root):
    """names + content bytes of every regular file under root."""
    snap = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            snap[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


def test_server_never_writes(tmp_path):
    repo = make_repo(tmp_path)
    doc = repo / "docs" / "a.md"
    append_line(doc, "\nPre-existing extra paragraph.\n")  # written before snapshot
    before = tree_snapshot(tmp_path)
    with running(repo) as base:
        hits = [
            ("GET", "/"),
            ("GET", "/static/app.js"),
            ("GET", "/api/doc"),
            ("GET", "/api/doc"),
            ("GET", "/api/doc?path=docs/b.md"),
            ("GET", "/api/mtime"),
            ("GET", "/api/file?path=src/pkg/mod.py&line=10"),
            ("GET", "/api/file?path=sub/data.bin&line=1"),
            ("GET", "/nope"),
            ("GET", "/static/../refs.py"),
            ("GET", "/api/doc?path=" + quote("../outside.txt", safe="")),
            ("POST", "/api/doc"),
            ("HEAD", "/"),
        ]
        for method, path in hits:
            request(base, method, path)
    assert tree_snapshot(tmp_path) == before


def test_path_probes_never_open_outside_files(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    outside_txt = os.path.realpath(tmp_path / "outside.txt")
    outside_md = os.path.realpath(tmp_path / "outside.md")
    git_config = os.path.realpath(repo / ".git" / "config")
    git_config_md = os.path.realpath(repo / ".git" / "config.md")

    # probes are given in WIRE form: the server sees them after one
    # percent-decode, so "%2e%2e" decodes to ".." exactly as it must
    doc_probes = [
        "../outside.txt",
        "%2e%2e/outside.md",
        "docs/../../outside.md",
        ".git/config.md",
        quote(str(tmp_path / "outside.md"), safe=""),  # absolute, no ".."
    ]
    file_probes = [
        "../outside.txt",
        "%2e%2e/outside.txt",
        "..\\outside.txt",
        ".git/config",
        "src%00.py",
    ]
    if os.name != "nt":
        (repo / "sub2").mkdir()
        (repo / "sub2" / "link.py").symlink_to(tmp_path / "outside.txt")
        (repo / "sub2" / "link.md").symlink_to(tmp_path / "outside.md")
        doc_probes.append("sub2/link.md")
        file_probes.append("sub2/link.py")

    opened = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    with running(repo) as base:
        for probe in doc_probes:
            status, _ctype, _headers, _body = request(
                base, "GET", "/api/doc?path=" + probe
            )
            assert status in (400, 404), (probe, status)  # never 5xx, never served
        for probe in file_probes:
            status, _ctype, _headers, body = request(
                base,
                "GET",
                "/api/file?path=" + probe + "&line=1",
            )
            assert status == 200, (probe, status)
            data = json.loads(body)
            # refs.py's safety posture: refused as an error card, never opened
            assert "error" in data or data.get("exists") is False, (probe, data)
            assert "lines" not in data, probe
        assert get(base, "/api/mtime")[0] == 200  # server survived the matrix

    forbidden = {outside_txt, outside_md, git_config, git_config_md}
    for file in opened:
        if isinstance(file, int):  # open(fd)
            continue
        name = os.fsdecode(file)
        assert "\x00" not in name, name
        assert os.path.realpath(name) not in forbidden, name


# ------------------------------------------------------------------ static page


def test_index_html_app_js_no_inline_script_no_external_urls():
    index_text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/static/app.js" in index_text
    for attrs, body in re.findall(
        r"<script\b([^>]*)>(.*?)</script>", index_text, flags=re.DOTALL | re.IGNORECASE
    ):
        assert "src=" in attrs, attrs
        assert body.strip() == "", attrs  # no inline script body
    assert "http://" not in index_text
    assert "https://" not in index_text  # no CDN, no network


def test_app_js_touches_dom_only_via_textContent_and_polls_mtime():
    app_text = (STATIC / "app.js").read_text(encoding="utf-8")
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert forbidden not in app_text, forbidden
    assert "/api/mtime" in app_text  # the UI polls mtime
    assert "http://" not in app_text
    assert "https://" not in app_text


# -------------------------------------------------------------------------- CLI


def cli_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_cli(args, cwd=None, timeout=180):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        env=cli_env(),
        cwd=cwd,
        timeout=timeout,
        check=False,
    )


def read_line_deadline(pipe, timeout=60):
    """readline with a deadline (select is POSIX-only; a thread is portable)."""
    box = Queue()

    def reader():
        try:
            box.put(pipe.readline())
        except (OSError, ValueError) as exc:  # closed/broken pipe: report, not hang
            box.put(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not box.empty(), "server printed no banner line in time"
    line = box.get_nowait()
    assert isinstance(line, str) and line, f"broken stdout pipe: {line!r}"
    return line


def get_at(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_cli_prints_one_banner_line_then_serves(tmp_path):
    repo = make_repo(tmp_path)
    argv = [
        sys.executable,
        str(TOOL),
        str(repo / "docs" / "a.md"),
        "--repo",
        str(repo),
        "--port",
        "0",
        "--no-open",
    ]
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=cli_env(),
        cwd=str(repo),
    )
    try:
        line = read_line_deadline(proc.stdout)
        match = re.fullmatch(
            r"docs-context: http://127\.0\.0\.1:(\d+)/", line.rstrip("\r\n")
        )
        assert match, f"bad banner line: {line!r}"
        port = int(match.group(1))
        assert 0 < port < 65536
        status, body = get_at(port, "/api/mtime")
        assert status == 200
        assert json.loads(body)["mtime"] == os.stat(repo / "docs" / "a.md").st_mtime
    finally:
        proc.terminate()
        out, _err = proc.communicate(timeout=30)
    assert out.strip() == "", f"stdout must carry exactly the banner line: {out!r}"


@contextlib.contextmanager
def serve_cli(doc, repo=None, extra=()):
    """Start the server with the default --repo omitted; kill it in the finally."""
    args = [sys.executable, str(TOOL), str(doc), "--port", "0", *extra]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=cli_env(),
        cwd=str(repo) if repo is not None else None,
    )
    try:
        line = read_line_deadline(proc.stdout)
        match = re.fullmatch(
            r"docs-context: http://127\.0\.0\.1:(\d+)/", line.rstrip("\r\n")
        )
        assert match, f"bad banner line: {line!r}"
        yield proc, int(match.group(1))
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - shutdown safety
            proc.kill()
            proc.communicate()


def test_cli_default_repo_is_found_upward(tmp_path):
    repo = make_repo(tmp_path)
    with serve_cli(repo / "docs" / "a.md") as (_proc, port):
        status, body = get_at(port, "/api/doc")
        assert status == 200
        data = json.loads(body)
        assert data["doc"] == "docs/a.md"  # repo root found via the fixture .git
        assert data["blocks"]


def test_cli_missing_doc_exits_two(tmp_path):
    repo = make_repo(tmp_path)
    proc = run_cli([str(repo / "docs" / "nope.md"), "--repo", str(repo)])
    assert proc.returncode == 2
    assert proc.stderr.strip()
    assert proc.stdout.strip() == ""


def test_cli_non_markdown_doc_exits_two(tmp_path):
    repo = make_repo(tmp_path)
    page = repo / "docs" / "a.txt"
    page.write_text("not markdown\n", encoding="utf-8", newline="")
    proc = run_cli([str(page), "--repo", str(repo)])
    assert proc.returncode == 2
    assert proc.stderr.strip()


def test_cli_doc_outside_repo_exits_two(tmp_path):
    repo = make_repo(tmp_path)
    proc = run_cli([str(tmp_path / "outside.md"), "--repo", str(repo)])
    assert proc.returncode == 2
    assert proc.stderr.strip()


# --- review round 2 (authorized append): 405 for EVERY method word, Host
# case-insensitivity, and 405/403 body draining --------------------------------


def raw_request(port, method, path="/", body=None, host_header=None):
    """One request with any method word; (status, ctype, headers, body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Host": host_header} if host_header is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return (
            resp.status,
            resp.getheader("Content-Type", "").lower(),
            {k.lower(): v for k, v in resp.getheaders()},
            resp.read(),
        )
    finally:
        conn.close()


def test_every_other_method_gets_the_405_json_with_security_headers(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _host, port = addr_of(base)
        for method in ("TRACE", "CONNECT", "FOO"):
            status, ctype, headers, body = raw_request(port, method, "/api/mtime")
            assert status == 405, method
            assert "application/json" in ctype, method
            assert json.loads(body) == {"error": "method not allowed"}, method
            assert headers.get("x-content-type-options") == "nosniff", method
            assert headers.get("cache-control") == "no-store", method
        assert get(base, "/api/mtime")[0] == 200


def test_host_allowlist_is_case_insensitive(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _host, port = addr_of(base)
        for host_header in (f"LOCALHOST:{port}", f"LocalHost:{port}", f"127.0.0.1:{port}"):
            status, _body = raw_get(port, host_header)
            assert status == 200, host_header
        for host_header in (
            f"LOCALHOST:{port + 1}",
            f"Evil.Example.COM:{port}",
            "LOCALHOST.local:1",
        ):
            status, _body = raw_get(port, host_header)
            assert status == 403, host_header


def test_405_on_a_request_with_a_body_keeps_the_connection_in_sync(tmp_path):
    repo = make_repo(tmp_path)
    with running(repo) as base:
        _host, port = addr_of(base)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("POST", "/api/mtime", body=b"x" * 100)
            resp = conn.getresponse()
            assert resp.status == 405
            assert json.loads(resp.read()) == {"error": "method not allowed"}
            conn.request("GET", "/api/mtime")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            assert resp.status == 200, resp.status
            assert isinstance(body["mtime"], float), body
        finally:
            conn.close()


def test_repo_discovery_accepts_a_dotgit_file_like_a_worktree(tmp_path):
    repo = tmp_path / "linked-checkout"
    (repo / "docs").mkdir(parents=True)
    doc = repo / "docs" / "a.md"
    doc.write_text("# A\n\nBody text.\n", encoding="utf-8", newline="\n")
    (repo / ".git").write_text(
        "gitdir: /nowhere/.git/worktrees/linked-checkout\n",
        encoding="utf-8",
        newline="\n",
    )
    with serve_cli(doc, repo=tmp_path) as (_proc, port):
        # docs/a.md exists only under linked-checkout, the directory found
        # by walking up from the doc: the .git FILE accepted the discovery.
        status, body = get_at(port, "/api/mtime")
        assert status == 200, body
        assert json.loads(body)["mtime"] == os.stat(doc).st_mtime


# ---- appended by the implementer: PERF-2 analyze() prefetches --help
# ---- concurrently. Existing tests untouched.


def test_api_doc_with_warmable_help_cache_matches_refs_analyze(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "src" / "refdes").mkdir(parents=True)
    (repo / "src" / "refdes" / "cli.py").write_text(
        "def main(argv):\n    raise SystemExit(0)\n", encoding="utf-8", newline=""
    )
    doc = repo / "docs" / "a.md"

    def run(argv, **kwargs):
        verbs = " ".join(argv[3:-1])
        return subprocess.CompletedProcess(
            argv, 0, stdout=f"usage: refdes {verbs}\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Popen used"))
    expected = refs.analyze(str(doc), str(repo))
    with running(repo) as base:
        status, data, _ = get_json(base, "/api/doc")
        assert status == 200
        assert data["blocks"] == expected["blocks"]
    cards = [
        r["card"] for b in data["blocks"] for r in b["refs"] if r["kind"] == "command"
    ]
    assert cards
    assert all(c["known"] is True for c in cards)
    assert all(c["help"].startswith("usage: refdes ") for c in cards)
