"""N6.2a-tests: red-first wire tests for ``ServeClient.post()`` (slice S6.2's
client half), the file plan §7.3 names (docs/design/navis-vscode-panel-plan.md
line 303: "tests/test_vscode_extension_http_client.py ... node driving the real
serveClient.js ... against a live EditorApp: POST the three routes with real
headers, assert the 200/403/409/404 mapping, a 403 surfaces the JSON
kind:"refused", a dead child yields an error object not a hang").

RED-FIRST: ``ServeClient.post()`` does not exist on the untouched tree
(``serveClient.js`` is GET-only -- ``method: "GET"`` hard-coded, plan §4 line
180). Every test that drives ``post()``/``navisArchive``/``navisRestore``/
``navisMint`` fails today (the driver records the missing methods, every
Python-side shape assertion then fails); the source pins that quote the
``post()`` body are red on their first assertion. Two pins are GREEN by
construction today and named as guards: no ``require("vscode")`` in
serveClient.js, and the §4/§6-Q5 write ban over serveClient.js (POSTs are not
file writes -- plan S6.2: "write-ban test unchanged").

THE IMPLEMENTER FOLLOWS THESE NAMES (decided here, the only shape the plan
sketches -- plan §4 lines 180-187):

  ServeClient.post(pathname, body)
    Promise resolving, for EVERY HTTP response:
      - ``{status, body}`` where ``body`` is the JSON-parsed object for every
        status -- the client's GET path hands non-200 bodies back as strings
        (serveClient.js:258-260, plan §4: "post() parses JSON for every
        status");
      - ``{status, body: <raw text>}`` when a non-200 body is not JSON (the
        security-layer 403 is ``text/plain`` -- plan §3 "With a stale token");
      - ``{error: <string>}`` when a 200 body will not parse (the GET path's
        rule, ride it: "could not parse the response from ..."), when the
        client is not ready ("refdes serve is not running", the GET path's
        literal), and on transport failure (refused, reset, timeout). Never
        rejects, never hangs.
    Headers it must set on the wire:
      - ``method: "POST"``,
      - ``Origin: http://127.0.0.1:<port>`` EXPLICITLY (plan §4: matching the
        Host Node derives from ``host: "127.0.0.1"`` + port -- the server's
        ``origin_ok`` rejects the localhost/127.0.0.1 mismatch pair,
        security.py:57-65),
      - ``Content-Type: application/json`` (415 otherwise, server.py:798-811),
      - ``Accept: application/json``,
      - ``X-Refdes-Token`` -- the shared TOKEN_HEADER constant,
      - ``Content-Length`` equal to the UTF-8 BYTE length of the serialized
        body: ``Buffer.byteLength(payload)`` (411 without it, server.py:813),
      - never ``Transfer-Encoding``/chunked (the server reads exactly
        Content-Length bytes, server.py:813-819).
    The token must never enter an error string: a JSON.parse error message
    quotes a leading slice of the body (V8), so a body that happens to carry
    the launch token must not reach the ``{error}`` text through ``${err}``.

  navisArchive(selector)  ->  this.post("/api/navis/archive", { navi: selector })
  navisRestore(selector)  ->  this.post("/api/navis/restore", { navi: selector })
  navisMint()             ->  this.post("/api/navis/mint", {})
  (routes + bodies: docs/navis.md "The serve API", plan §4 lines 167-173.)

Ambiguities this slice resolves (pinned so the implementer inherits them):
  * a selector is a key/prefix/ordinal (navis_write.py:_selector), so a live
    server can never receive a non-ASCII selector body; the multibyte
    ``Content-Length`` byte-count is pinned on the capture server (arbitrary
    body), and the live half pins a multibyte Navi TEXT round-tripping
    (minted marker bytes + archive/restore of the minted key);
  * restore of an ACTIVE Navi is 409 ``kind:"conflict", reason:
    "not_archived"`` (docs/navis.md's captured curl, line 372) -- the extra
    status the live sequence pins;
  * the Origin control is raw ``http`` in the test driver (not through
    ``post()``): a POST with ``Origin: http://localhost:<port>`` arriving on
    ``Host: 127.0.0.1:<port>`` is 403 (security.py:57-65) -- a test that
    would notice ``post()`` dropping its explicit Origin;
  * the hang case rides the client's own 10 s request timeout
    (serveClient.js:40): a server that accepts and never answers must resolve
    ``{error: "timed out"}`` in bounded wall time, not hang the extension.

Servers bind 127.0.0.1:0, node output is read with ``encoding="utf-8"``,
fixtures are written with ``newline=""``, every node run is bounded by
NODE_TIMEOUT_S, and missing node skips (the neighbours' cross-platform
posture). One node process per scenario group, not per assertion.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import write_project_config
from serve_support import snapshot_tree

from refdes import cli as cli_mod
from refdes import keys
from refdes.serve import security
from refdes.serve.server import EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVE_CLIENT_JS = os.path.join(REPO_ROOT, "editors", "vscode", "serveClient.js")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to drive the real serveClient.js"
)

TOKEN_HEADER = security.TOKEN_HEADER  # pinned to the server's own constant

SCHEMA = (
    "site: { title: N6.2a Post, out: _site }\n"
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
MULTIBYTE_TEXT = "Ünïcödé 世界 navi: stitch the vias."

# Two hand-declared keys sharing a 6-char prefix: unique-prefix selection
# answers 409 ambiguous naming both (navis_write.py:127-140). The tails are
# distinct, so the full-key selectors below resolve one row each.
AMBIGUOUS_PREFIX = "abcd12"

MULTIBYTE_NAVI_BODY = {"navi": "Ünïcödé 世界 navi — mint me"}

HTML_500 = "<!doctype html><html><body>gateway boom</body></html>"
JSON_409 = json.dumps(
    {
        "kind": "conflict",
        "reason": "not_archived",
        "error": "this Navi is not archived -- nothing to restore",
    }
)


def _fabricate(prefix6: str, tail4: str) -> str:
    """A valid 11-char key with a chosen 6-char prefix (the mint test files'
    hand-declared-key recipe): 10 data chars + the Damm check char. The CLI's
    `navis ls` accepts it as-is, so the markers keep these keys."""
    data = prefix6 + tail4
    assert all(ch in keys.ALPHABET for ch in data), data
    return data + keys.check_char(data)


KEY_A = _fabricate(AMBIGUOUS_PREFIX, "0000")
KEY_B = _fabricate(AMBIGUOUS_PREFIX, "1111")


def _read(path: str) -> str:
    if not os.path.exists(path):
        pytest.fail(f"{os.path.relpath(path, REPO_ROOT)} does not exist")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_body(source: str, marker: str) -> str:
    """The brace-balanced body after `marker` (the neighbours' extractor: a
    lazy `.*?\\}` stops at the first nested block)."""
    start = source.find(marker)
    assert start != -1, f"serveClient.js no longer contains {marker!r}"
    i = start + len(marker)
    depth = 1
    while depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[start + len(marker) : i - 1]


def _note(item_id: str, title: str, text: str, key: str = "") -> str:
    return (
        f"---\nid: {item_id}\ntype: note\ntitle: {title}\n---\n"
        f"intro\n<!--navi:{key} {text}-->\n"
    )


def _navi_project(tmp_path) -> str:
    """Two keyed Navis (KEY_A, KEY_B, one ambiguous prefix between them) and
    one KEYLESS marker with multibyte text. The keyless file is written AFTER
    the writable CLI load: `navis ls` mints every keyless marker it sees, and
    the keyless marker is exactly what `POST /api/navis/mint` mints here (the
    mint test files' recipe)."""
    config = str(write_project_config(tmp_path, SCHEMA))
    items = tmp_path / "items"
    items.mkdir()
    (items / "note-a.md").write_text(
        _note("NOTE-001", "Alpha", ALPHA_TEXT, KEY_A), encoding="utf-8", newline=""
    )
    (items / "note-b.md").write_text(
        _note("NOTE-002", "Beta", BETA_TEXT, KEY_B), encoding="utf-8", newline=""
    )
    assert cli_mod.main(["-c", config, "navis", "ls"]) == 0
    (items / "note-c.md").write_text(
        _note("NOTE-003", "Gamma", MULTIBYTE_TEXT), encoding="utf-8", newline=""
    )
    return config


@pytest.fixture
def writable(tmp_path):
    """A real writable `refdes serve` on port 0 -- the live half of plan §7.3
    ("node driving the real serveClient.js ... against a live EditorApp")."""
    config = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, tmp_path
    finally:
        app.stop()


@pytest.fixture
def no_write(tmp_path):
    """The same project served `--no-write` (read_only=True): every navis
    POST answers 403 kind:"refused" gate-first."""
    config = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=60, read_only=True)
    app.start()
    try:
        yield app, tmp_path
    finally:
        app.stop()


# ------------------------------------------------------------------ node driver


DRIVER = r"""
"use strict";
const http = require("http");
const fs = require("fs");
const cfg = JSON.parse(process.argv[2]);
const serveClient = require(cfg.client);
const ServeClient = serveClient.ServeClient;

// A raw POST that does NOT go through post() -- the control that proves the
// live test would notice post() dropping its explicit Origin.
function rawPost(pathname, body, origin) {
  return new Promise((resolve) => {
    const payload = JSON.stringify(body);
    const req = http.request(
      {
        host: "127.0.0.1",
        port: cfg.port,
        method: "POST",
        path: pathname,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
          Origin: origin,
          [cfg.header]: cfg.token,
        },
      },
      (res) => {
        let text = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => (text += chunk));
        res.on("end", () => resolve({ status: res.statusCode, text }));
      }
    );
    req.on("error", (err) => resolve({ error: String((err && err.message) || err) }));
    req.setTimeout(8000, () => req.destroy(new Error("raw post timed out")));
    req.end(payload);
  });
}

function attach(url, port, token) {
  return ServeClient.attach({ base: url, port: port, token: token }, {});
}

const main = attach(cfg.base, cfg.port, cfg.token);
const clients = {
  main: main,
  // Not ready: never attached, never started -- post() must answer the
  // GET path's not-running literal, not dial anything.
  notReady: new ServeClient({}),
  refused: attach("http://127.0.0.1:" + cfg.deadPort, cfg.deadPort, "x"),
  hanging: attach("http://127.0.0.1:" + cfg.hangPort, cfg.hangPort, "x"),
};

const state = {};

async function run(c) {
  const selector = c.use ? state[c.use] : c.selector;
  switch (c.fn) {
    case "archive":
      return await clients.main.navisArchive(selector);
    case "restore":
      return await clients.main.navisRestore(selector);
    case "mint":
      return await clients.main.navisMint();
    case "post":
      return await clients.main.post(c.pathname, c.body);
    case "rawOrigin":
      return await rawPost(c.pathname, c.body, c.origin);
    case "notReady":
      return await clients.notReady.post("/api/navis/mint", {});
    case "refused":
      return await clients.refused.post("/api/navis/mint", {});
    case "hang":
      return await clients.hanging.post("/api/navis/mint", {});
    default:
      return { unknownFn: c.fn };
  }
}

async function main2() {
  const out = {
    methods: {
      post: typeof main.post === "function",
      navisArchive: typeof main.navisArchive === "function",
      navisRestore: typeof main.navisRestore === "function",
      navisMint: typeof main.navisMint === "function",
      request: typeof main.request === "function",
    },
    ready: main.ready,
    results: {},
  };
  for (const c of cfg.calls) {
    const t0 = Date.now();
    let value;
    try {
      value = await run(c);
    } catch (err) {
      value = { threw: String((err && err.message) || err) };
    }
    out.results[c.id] = { elapsedMs: Date.now() - t0, value: value };
    if (c.saveKeyFromMint) {
      const body = value && value.body;
      const minted = body && body.minted && body.minted[0];
      if (minted && minted.key) state[c.saveKeyFromMint] = minted.key;
    }
  }
  return out;
}

main2()
  .then((o) => finish(o))
  .catch((err) => finish({ fatal: String((err && err.stack) || err) }));

function finish(payload) {
  const text = JSON.stringify(payload);
  try {
    fs.writeSync(1, text);
  } catch (err) {
    process.stdout.write(text);
  }
  process.exit(0);
}
"""


def run_client(tmp_path, cfg: dict) -> dict:
    script = tmp_path / "post-driver.js"
    script.write_text(DRIVER, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the multibyte bodies on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (
        f"node driver exited {proc.returncode}: stdout={proc.stdout[-2000:]!r} "
        f"stderr={proc.stderr[-2000:]!r}"
    )
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"node driver printed no JSON: stdout={proc.stdout[-2000:]!r} "
            f"stderr={proc.stderr[-2000:]!r}"
        )
    assert "fatal" not in out, out["fatal"]
    return out


def client_cfg(app, calls, **extra) -> dict:
    cfg = {
        "client": SERVE_CLIENT_JS,
        "base": f"http://127.0.0.1:{app.port}",
        "port": app.port,
        "token": app.token,
        "header": TOKEN_HEADER,
        "calls": calls,
        "deadPort": closed_port(),
        "hangPort": 0,
    }
    cfg.update(extra)
    return cfg


def closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------ 1. live writable round trip


LIVE_CALLS = [
    {"id": "archive", "fn": "archive", "selector": KEY_A},
    {"id": "archiveAgain", "fn": "archive", "selector": KEY_A},
    {"id": "restore", "fn": "restore", "selector": KEY_A},
    {"id": "restoreActive", "fn": "restore", "selector": KEY_A},
    {"id": "mint", "fn": "mint", "saveKeyFromMint": "mintedKey"},
    {"id": "mintAgain", "fn": "mint"},
    {"id": "archiveMinted", "fn": "archive", "use": "mintedKey"},
    {"id": "restoreMinted", "fn": "restore", "use": "mintedKey"},
    {"id": "notFound", "fn": "post", "pathname": "/api/navis/archive",
     "body": {"navi": "zzzzzzzzzzzz"}},
    {"id": "ambiguous", "fn": "post", "pathname": "/api/navis/archive",
     "body": {"navi": AMBIGUOUS_PREFIX}},
    {"id": "rawBadOrigin", "fn": "rawOrigin", "pathname": "/api/navis/archive",
     "body": {"navi": KEY_A}, "origin": "http://localhost:0"},  # port fixed below
    {"id": "rawGoodOrigin", "fn": "rawOrigin", "pathname": "/api/navis/mint",
     "body": {}, "origin": "http://127.0.0.1:0"},
]


@skip_no_node
def test_post_round_trips_the_three_routes_over_the_wire(tmp_path, writable):
    """Plan §7.3's live contract, through the REAL serveClient.js: archive
    (200 ok, re-archive changed:false), restore (200 ok, restore-active 409
    not_archived), mint (200 changed:true then idempotent changed:false),
    404 not_found, 409 ambiguous with candidates -- and the raw-Origin
    control the server refuses. Every body arrives JSON-PARSED."""
    app, root = writable
    calls = [dict(c) for c in LIVE_CALLS]
    for c in calls:
        if c["id"] == "rawBadOrigin":
            c["origin"] = f"http://localhost:{app.port}"
        if c["id"] == "rawGoodOrigin":
            c["origin"] = f"http://127.0.0.1:{app.port}"
    out = run_client(tmp_path, client_cfg(app, calls))
    assert out["ready"] is True, out
    assert out["methods"]["post"] is True, out["methods"]
    assert out["methods"]["navisArchive"] is True, out["methods"]
    assert out["methods"]["navisRestore"] is True, out["methods"]
    assert out["methods"]["navisMint"] is True, out["methods"]

    got = {key: entry["value"] for key, entry in out["results"].items()}

    assert got["archive"] == {
        "status": 200,
        "body": {"kind": "ok", "verb": "archive", "key": KEY_A, "changed": True},
    }, got["archive"]
    assert got["archiveAgain"]["status"] == 200, got["archiveAgain"]
    assert got["archiveAgain"]["body"]["changed"] is False, got["archiveAgain"]
    assert got["restore"]["status"] == 200, got["restore"]
    assert got["restore"]["body"]["changed"] is True, got["restore"]
    assert got["restoreActive"]["status"] == 409, got["restoreActive"]
    assert got["restoreActive"]["body"]["kind"] == "conflict", got["restoreActive"]
    assert got["restoreActive"]["body"]["reason"] == "not_archived", got["restoreActive"]

    mint = got["mint"]
    assert mint["status"] == 200, mint
    assert mint["body"]["kind"] == "ok" and mint["body"]["changed"] is True, mint
    assert len(mint["body"]["minted"]) == 1, mint
    assert mint["body"]["minted"][0]["item"] == "NOTE-003", mint
    assert mint["body"]["minted"][0]["file"] == "items/note-c.md", mint
    minted_key = mint["body"]["minted"][0]["key"]
    assert got["mintAgain"]["status"] == 200, got["mintAgain"]
    assert got["mintAgain"]["body"]["changed"] is False, got["mintAgain"]
    assert got["mintAgain"]["body"]["minted"] == [], got["mintAgain"]

    # the multibyte marker: mint wrote the key into it, archive/restore of
    # the minted key round-trips through the same wire path
    assert got["archiveMinted"]["status"] == 200, got["archiveMinted"]
    assert got["archiveMinted"]["body"]["key"] == minted_key, got["archiveMinted"]
    assert got["restoreMinted"]["status"] == 200, got["restoreMinted"]
    assert got["restoreMinted"]["body"]["changed"] is True, got["restoreMinted"]
    disk = (root / "items" / "note-c.md").read_text(encoding="utf-8")
    assert f"<!--navi:{minted_key} {MULTIBYTE_TEXT}-->" in disk, disk

    assert got["notFound"]["status"] == 404, got["notFound"]
    assert got["notFound"]["body"]["kind"] == "not_found", got["notFound"]

    amb = got["ambiguous"]
    assert amb["status"] == 409, amb
    assert amb["body"]["kind"] == "ambiguous", amb
    assert {cand["key"] for cand in amb["body"]["candidates"]} == {KEY_A, KEY_B}, amb
    for cand in amb["body"]["candidates"]:
        assert {"text", "file", "line"} <= set(cand), cand

    # the control: the server refuses the localhost-Origin mismatch (a post()
    # that dropped its explicit Origin would hit exactly this wall); the
    # matching Origin passes.
    assert got["rawBadOrigin"]["status"] == 403, got["rawBadOrigin"]
    assert "forbidden" in got["rawBadOrigin"]["text"], got["rawBadOrigin"]
    assert got["rawGoodOrigin"]["status"] == 200, got["rawGoodOrigin"]


# -------------------------------------------------- 2. live --no-write refusals


@skip_no_node
def test_a_no_write_server_refuses_all_three_and_the_json_reaches_the_caller(
    tmp_path, no_write
):
    """Plan §3 "With --no-write" + §7.3: every write action answers 403
    gate-first with the JSON kind:"refused" -- and post() PARSES it (the GET
    path would hand it back as a string; the extension's write-lock branch
    reads body.kind). Nothing moves on disk."""
    app, root = no_write
    before = snapshot_tree(root)
    out = run_client(
        tmp_path,
        client_cfg(
            app,
            [
                {"id": "archive", "fn": "archive", "selector": KEY_A},
                {"id": "restore", "fn": "restore", "selector": KEY_A},
                {"id": "mint", "fn": "mint"},
            ],
        ),
    )
    for name in ("archive", "restore", "mint"):
        value = out["results"][name]["value"]
        assert value.get("status") == 403, (name, value)
        body = value.get("body")
        assert isinstance(body, dict), (name, value)
        assert body.get("kind") == "refused", (name, value)
        assert "--no-write" in body.get("error", ""), (name, value)
    assert snapshot_tree(root) == before


# ---------------------------------------------- 3. wire frames + failure shapes


class _CaptureHandler(BaseHTTPRequestHandler):
    """Records every POST as it arrives; answers with the per-path canned
    response. HTTP/1.0 (Connection: close): a lying Content-Length can
    desynchronize one connection, never the next request's framing."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _reply(self, status, content_type, data: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        self.server.captures.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                # latin-1 is the lossless byte<->str codec; tests decode utf-8.
                "body": raw.decode("latin-1"),
            }
        )
        status, ctype, body = self.server.responses.get(
            self.path, (200, "application/json", b'{"ok": true}')
        )
        self._reply(status, ctype, body)

    def do_GET(self):
        self._reply(404, "application/json", b'{"error": "nope"}')


class CaptureServer:
    """127.0.0.1:0, per-path canned responses, captures on the server."""

    def __init__(self, responses=None):
        self.responses = {
            path: (status, ctype, body.encode("utf-8"))
            for path, (status, ctype, body) in (responses or {}).items()
        }
        self.httpd = None
        self.thread = None

    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.httpd.daemon_threads = True
        self.httpd.responses = self.responses
        self.httpd.captures = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class HangServer:
    """Accepts connections and NEVER answers: post() must time out with an
    {error}, bounded, not hang the extension host."""

    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._conns = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()
        return self

    def _accept(self):
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn = self.sock.accept()[0]
            except (TimeoutError, OSError):
                continue
            self._conns.append(conn)

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass
        self.sock.close()


CAPTURE_CALLS = [
    {"id": "multibyte", "fn": "post", "pathname": "/api/navis/archive",
     "body": MULTIBYTE_NAVI_BODY},
    {"id": "html500", "fn": "post", "pathname": "/html500", "body": {"navi": "x"}},
    {"id": "json409", "fn": "post", "pathname": "/json409", "body": {"navi": "x"}},
    {"id": "tokenecho", "fn": "post", "pathname": "/tokenecho", "body": {}},
    {"id": "notReady", "fn": "notReady"},
    {"id": "refused", "fn": "refused"},
    {"id": "hang", "fn": "hang"},
]


@skip_no_node
def test_post_frames_the_request_and_maps_every_failure_shape(tmp_path):
    """The wire contract, observed on the bytes: method/path/headers/body as
    plan §4 specifies (explicit Origin matching the Host,
    Content-Type/Accept json, the token header, Content-Length == UTF-8 BYTE
    length of a multibyte body, no chunked) -- the non-200 JSON/HTML parse
    split, the token never surfacing inside an {error}, and the three ways a
    request dies (not ready, refused, unanswered) each resolving {error}
    without hanging."""
    token = "cap-" + security.new_token()
    with CaptureServer(
        responses={
            "/html500": (500, "text/html", HTML_500),
            "/json409": (409, "application/json", JSON_409),
            "/tokenecho": (200, "text/plain", token),
        }
    ) as capture, HangServer() as hang:
        cfg = {
            "client": SERVE_CLIENT_JS,
            "base": capture.url,
            "port": capture.port,
            "token": token,
            "header": TOKEN_HEADER,
            "calls": CAPTURE_CALLS,
            "deadPort": closed_port(),
            "hangPort": hang.port,
        }
        out = run_client(tmp_path, cfg)
        captures = capture.httpd.captures

    req = captures[0]
    assert [c["path"] for c in captures] == [
        "/api/navis/archive",
        "/html500",
        "/json409",
        "/tokenecho",
    ], captures
    assert req["method"] == "POST", req
    headers = req["headers"]
    assert headers.get("content-type") == "application/json", headers
    assert headers.get("accept") == "application/json", headers
    assert headers.get(TOKEN_HEADER.lower()) == token, headers
    # plan §4: Origin EXPLICITLY the printed IPv4 form -- the Host Node
    # derives (a localhost Origin arriving on Host 127.0.0.1 is the refused
    # pair, security.py:57-65).
    assert headers.get("origin") == f"http://127.0.0.1:{capture.port}", headers
    assert headers.get("transfer-encoding") is None, headers
    raw = req["body"].encode("latin-1")
    expected = json.dumps(
        MULTIBYTE_NAVI_BODY, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert raw == expected, req["body"]
    # the byte-count trap: multibyte text makes JS string length < UTF-8
    # byte length; Content-Length must be the bytes (server.py reads exactly
    # Content-Length bytes).
    assert int(headers["content-length"]) == len(raw), headers
    assert len(raw) > len(expected.decode("utf-8")), (len(raw), expected)

    results = {key: entry["value"] for key, entry in out["results"].items()}
    timing = {key: entry["elapsedMs"] for key, entry in out["results"].items()}

    assert results["multibyte"] == {"status": 200, "body": {"ok": True}}, results["multibyte"]
    # 500 with an HTML body: status + RAW TEXT (plan §3 "With a stale token":
    # the client must be able to tell text/plain refusals from JSON ones).
    html = results["html500"]
    assert html["status"] == 500, html
    assert html["body"] == HTML_500, html
    # 409 with a JSON body: PARSED (the GET path would hand a string here).
    conflict = results["json409"]
    assert conflict["status"] == 409, conflict
    assert conflict["body"]["kind"] == "conflict", conflict
    assert conflict["body"]["reason"] == "not_archived", conflict

    # the token-echo case: a 200 body that is the bare token does not parse;
    # the {error} text must not smuggle the token out (V8's JSON.parse
    # messages quote a leading slice of the input).
    echo = results["tokenecho"]
    assert "status" not in echo, echo
    assert isinstance(echo.get("error"), str) and echo["error"], echo
    for i in range(len(token) - 7):
        assert token[i : i + 8] not in echo["error"], (i, echo["error"])

    # the three ways to die: each an {error}, none a hang.
    assert results["notReady"] == {"error": "refdes serve is not running"}, results["notReady"]
    refused = results["refused"]
    assert "status" not in refused, refused
    assert isinstance(refused.get("error"), str) and refused["error"], refused
    assert timing["refused"] < 8000, timing
    hanging = results["hang"]
    assert "status" not in hanging, hanging
    assert isinstance(hanging.get("error"), str) and hanging["error"], hanging
    # the client's own 10 s request timeout (serveClient.js:40), bounded
    assert 8000 < timing["hang"] < 30000, timing


# ---------------------------------------------------------------- 4. source pins


def test_post_sets_origin_content_type_and_byte_length_explicitly():
    """Plan §4 (the failure-mode rule it quotes: "Pin this in a test, because
    it is the kind of header a future refactor drops"): the post() source
    names its headers literally -- method POST, the explicit IPv4 Origin built
    from this.port, application/json, the token via the shared TOKEN_HEADER,
    Content-Length from Buffer.byteLength (not the JS string length) -- and
    the file never uses Transfer-Encoding. RED today: no post() exists."""
    source = _read(SERVE_CLIENT_JS)
    signature = re.search(r"\bpost\(\s*pathname\s*,\s*body\s*\)\s*\{", source)
    assert signature, (
        'editors/vscode/serveClient.js has no post(pathname, body) -- plan §4: '
        '"slice S6.2 adds a post(pathname, body)"'
    )
    body = _function_body(source, "post(pathname, body) {")
    assert re.search(r'method:\s*"POST"', body), body
    assert "Origin" in body, body
    assert "http://127.0.0.1:" in body, body
    assert "this.port" in body, body
    assert "Content-Type" in body and '"application/json"' in body, body
    assert "Accept" in body, body
    assert "TOKEN_HEADER" in body, body
    assert "Content-Length" in body, body
    assert "Buffer.byteLength" in body, body
    assert "Transfer-Encoding" not in source, source


def test_the_three_wrappers_delegate_to_post_with_the_pinned_routes():
    """The exact client API S6.2's commands are written against (routes and
    bodies per docs/navis.md "The serve API", plan §4). RED today: no wrappers
    exist."""
    source = _read(SERVE_CLIENT_JS)
    for name, route, body_src in (
        ("navisArchive", "/api/navis/archive", r"\{\s*navi:\s*selector\s*\}"),
        ("navisRestore", "/api/navis/restore", r"\{\s*navi:\s*selector\s*\}"),
        ("navisMint", "/api/navis/mint", r"\{\s*\}"),
    ):
        pattern = (
            rf"{name}\([^)]*\)\s*\{{[\s\S]*?return this\.post\(\s*\"{re.escape(route)}\"\s*,\s*{body_src}\s*\)"
        )
        assert re.search(pattern, source), (
            f"serveClient.js has no {name}() delegating to "
            f'this.post("{route}", ...) -- the command surface '
            "(plan §4) is written against exactly this shape"
        )


def test_the_token_never_enters_an_error_string():
    """The token's one job in post() is the header. A JSON.parse failure
    quotes the body (V8), and the 200-body parse error embeds err -- so
    post()'s error strings must be built without the token in scope beyond
    the header map. Mechanical form: every line touching this.token is the
    header line. RED today: post() does not exist."""
    source = _read(SERVE_CLIENT_JS)
    signature = re.search(r"\bpost\(\s*pathname\s*,\s*body\s*\)\s*\{", source)
    assert signature, "post(pathname, body) does not exist -- see the signature pin"
    body = _function_body(source, "post(pathname, body) {")
    offenders = [
        line.strip()
        for line in body.splitlines()
        if "this.token" in line and "TOKEN_HEADER" not in line
    ]
    assert not offenders, offenders
    assert not re.search(r"error:\s*[^,\n]*this\.token", body), body


# --------------------------------------------------- guards (green today, named)


def test_serve_client_still_imports_no_vscode():
    """serveClient.js stays drivable under bare node (adapter §7.2, the file
    header at serveClient.js:4-6) -- this whole file's harness depends on it.
    GREEN today by construction; the guard keeps S6.2's additions pure."""
    source = _read(SERVE_CLIENT_JS)
    assert not re.search(r'require\(\s*["\']vscode["\']\s*\)', source), source


def test_the_write_ban_still_holds_over_serve_client():
    """§4's write ban (tests/test_vscode_extension.py:108-110's FORBIDDEN_WRITE
    -- POSTs are not file writes, plan S6.2 "write-ban test unchanged").
    GREEN today; the guard: S6.2 adds POSTs, and the extension still writes
    nothing. Comments skipped, the neighbour's rule (the ban is stated in
    prose in this file's own header)."""
    forbidden = re.compile(
        r"\bapplyEdit\b|\bWorkspaceEdit\b|\bfs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)\b"
    )
    offenders = []
    for number, line in enumerate(_read(SERVE_CLIENT_JS).splitlines(), start=1):
        if line.strip().startswith(("//", "/*", "*")):
            continue
        match = forbidden.search(line)
        if match:
            offenders.append(f"{number}: {match.group(0)}")
    assert not offenders, offenders
