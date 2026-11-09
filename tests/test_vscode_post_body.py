"""The BODY half of ``ServeClient.post(pathname, body)`` (serveClient.js,
added by #458), pinned at the wire and against a real ``refdes serve``.

WHY THIS FILE EXISTS: ``post()`` serialises with a bare ``JSON.stringify(body)``
(serveClient.js:297). Called as ``post(pathname)`` -- the shape a caller passes
only a path in -- ``JSON.stringify(undefined)`` is ``undefined``, so
``Buffer.byteLength(payload)`` (serveClient.js:316) throws a
``ERR_INVALID_ARG_TYPE`` TypeError INSIDE the promise executor: ``post()``
rejects a TypeError and the request is never made, breaking the
"resolves, never rejects" contract every caller is written against
(plan §4, docs/design/navis-vscode-panel-plan.md). The same executor throw is
what a non-serialisable body (circular, BigInt) already does today -- the
case this file pins as the one place rejection IS the contract.

THE NARROWEST CORRECT BEHAVIOUR, decided against the real server (rules: run
it, not recall). ``src/refdes/serve/server.py:_api`` on any ``POST /api/*``:

  * ``Content-Type`` must be ``application/json`` -> 415 ``expected
    application/json`` (server.py:907-908);
  * ``Content-Length`` is required -> 411 (server.py:911-913), and exactly
    that many bytes are read (server.py:916);
  * the bytes are ``json.loads``-ed -- an EMPTY body is 400
    ``{"error": "invalid JSON"}`` (server.py:927-930): no ``kind``, so a
    caller branching on ``body.kind`` (navisActions.js planResult) reads
    ``undefined`` off a 400;
  * a JSON ``null``/array/number body reaches the route renderer, which wants
    an object: ``navis_write.handle`` -> 400 ``kind:"bad_request"``,
    ``"expected a JSON object"`` (navis_write.py:57-58);
  * ``{}`` is a valid JSON object body: ``POST /api/navis/mint`` answers 200
    (it is project-wide, docs/navis.md "The serve API"), and
    ``POST /api/navis/archive`` answers 400 ``kind:"bad_request"`` naming
    the missing selector -- a structured, kind-carrying answer.

So: an omitted (``undefined``) body sends ``{}`` with
``Content-Type: application/json`` -- byte-identical to what
``post(path, {})`` sends today, which is what ``navisMint()``
(serveClient.js:382) already sends. ``null`` is NOT coerced:
``JSON.stringify(null)`` is the text ``"null"``, so ``post(path, null)``
sends the JSON ``null`` literal and the server's ``kind:"bad_request"``
answers it -- pinned as-is, not "fixed", because a caller that passes
explicit ``null`` is naming a body and the 400 is the honest answer. A body
``JSON.stringify`` cannot serialise REJECTS the returned promise with a
plain ``Error`` naming the problem: never a synchronous throw, never a hang,
never an unhandled rejection.

The three callers cannot change (read before deciding): ``navisArchive``/
``navisRestore`` pass ``{navi: selector}`` and ``navisMint`` passes ``{}``
(serveClient.js:369-383); ``navisActions.js`` is a pure answerer and never
calls ``post()`` itself; no caller in ``editors/vscode/`` calls ``post()``
with only a path today, which is exactly why the bug is latent.

Harness copied from tests/test_vscode_extension_http_client.py (the neighbour
this file extends): node driving the REAL serveClient.js against a real
server, a capture server for the bytes, one node process per scenario group,
node output read with ``encoding="utf-8"``, fixtures written with
``newline=""``, every run bounded, missing node skips.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import write_project_config

from refdes.serve import security
from refdes.serve.server import EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVE_CLIENT_JS = os.path.join(REPO_ROOT, "editors", "vscode", "serveClient.js")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to drive the real serveClient.js"
)

TOKEN_HEADER = security.TOKEN_HEADER  # the server's own constant

SCHEMA = (
    "site: { title: Post body, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

KEYLESS_TEXT = "Gamma marker with no key -- mint writes one."


# ------------------------------------------------------------------ node driver

DRIVER = r"""
"use strict";
const fs = require("fs");
const cfg = JSON.parse(process.argv[2]);
const ServeClient = require(cfg.client).ServeClient;

const attached = ServeClient.attach({ base: cfg.base, port: cfg.port, token: cfg.token }, {});
// Never attached, never started: post() must answer the not-running literal
// for a path-only call too (the ready check precedes any serialisation).
const notReady = new ServeClient({});

function rejection(err) {
  return {
    rejected: true,
    isError: err instanceof Error,
    ctorName: (err && err.constructor && err.constructor.name) || null,
    name: (err && err.name) || null,
    message: String((err && err.message) || err),
  };
}

// The body is built HERE, in node: a circular object and a BigInt cannot
// survive a JSON argv. Each call records whether post() threw synchronously
// (the contract violation this file is about), resolved, or rejected.
function openPromise(c) {
  const target = c.notReady ? notReady : attached;
  switch (c.fn) {
    case "noBody":
      return target.post(c.pathname);
    case "undefinedBody":
      return target.post(c.pathname, undefined);
    case "nullBody":
      return target.post(c.pathname, null);
    case "objBody":
      return target.post(c.pathname, { a: 1 });
    case "emptyObj":
      return target.post(c.pathname, {});
    case "circular": {
      const o = { label: "loop" };
      o.self = o;
      return target.post(c.pathname, o);
    }
    case "bigint":
      return target.post(c.pathname, { n: BigInt(1) });
    default:
      throw new Error("unknown fn " + c.fn);
  }
}

async function call(c) {
  const t0 = Date.now();
  let p;
  try {
    p = openPromise(c);
  } catch (err) {
    return {
      syncThrew: true,
      message: String((err && err.message) || err),
      elapsedMs: Date.now() - t0,
    };
  }
  try {
    const value = await p;
    return { syncThrew: false, resolved: value, elapsedMs: Date.now() - t0 };
  } catch (err) {
    const out = rejection(err);
    out.syncThrew = false;
    out.elapsedMs = Date.now() - t0;
    return out;
  }
}

// A rejection handled the `.then(onFulfilled, onRejected)` way: if post()
// ever rejects a promise nobody can attach to in time, node prints
// "Unhandled promise rejection" and this file's Python side fails on it.
async function callViaCatch(c) {
  const o = { label: "loop" };
  o.self = o;
  const t0 = Date.now();
  return await attached
    .post(c.pathname, o)
    .then((v) => ({ syncThrew: false, resolved: v }))
    .catch((err) => {
      const out = rejection(err);
      out.syncThrew = false;
      return out;
    })
    .then((out) => Object.assign(out, { elapsedMs: Date.now() - t0 }));
}

async function main() {
  const out = { methods: { post: typeof attached.post === "function" }, results: {} };
  for (const c of cfg.calls) {
    out.results[c.id] = c.fn === "viaCatch" ? await callViaCatch(c) : await call(c);
  }
  return out;
}

main()
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


def run_client(tmp_path, cfg: dict) -> subprocess.CompletedProcess:
    script = tmp_path / "post-body-driver.js"
    script.write_text(DRIVER, encoding="utf-8", newline="")
    return subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake anything non-ASCII on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )


def client_dict(tmp_path, cfg: dict) -> dict:
    proc = run_client(tmp_path, cfg)
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


# -------------------------------------------------------------- capture server


class _CaptureHandler(BaseHTTPRequestHandler):
    """Records every POST as it arrives (the bytes are the point of this
    file), answers 200 application/json {"ok": true}. HTTP/1.0: a lying
    Content-Length desynchronises one connection, never the next."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        self.server.captures.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                # latin-1 is the lossless byte<->str codec; tests encode back.
                "body": raw.decode("latin-1"),
            }
        )
        data = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class CaptureServer:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.httpd.daemon_threads = True
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


CAPTURE_CALLS = [
    {"id": "noBody", "fn": "noBody", "pathname": "/api/navis/mint"},
    {"id": "undefinedBody", "fn": "undefinedBody", "pathname": "/api/navis/mint"},
    {"id": "nullBody", "fn": "nullBody", "pathname": "/api/navis/archive"},
    {"id": "objBody", "fn": "objBody", "pathname": "/api/navis/archive"},
    {"id": "emptyObj", "fn": "emptyObj", "pathname": "/api/navis/mint"},
    {"id": "circular", "fn": "circular", "pathname": "/api/navis/mint"},
    {"id": "bigint", "fn": "bigint", "pathname": "/api/navis/mint"},
    {"id": "viaCatch", "fn": "viaCatch", "pathname": "/api/navis/mint"},
    {"id": "notReadyNoBody", "fn": "noBody", "pathname": "/api/navis/mint", "notReady": True},
]

# Requests that must reach the wire, in call order, each with the exact bytes
# post() is required to send and the Content-Length that counts them.
WIRE = [
    ("noBody", "/api/navis/mint", b"{}"),
    ("undefinedBody", "/api/navis/mint", b"{}"),
    ("nullBody", "/api/navis/archive", b"null"),
    ("objBody", "/api/navis/archive", b'{"a":1}'),
    ("emptyObj", "/api/navis/mint", b"{}"),
]


def _capture_run(tmp_path):
    token = "cap-" + security.new_token()
    with CaptureServer() as capture:
        cfg = {
            "client": SERVE_CLIENT_JS,
            "base": capture.url,
            "port": capture.port,
            "token": token,
            "calls": CAPTURE_CALLS,
        }
        out = client_dict(tmp_path, cfg)
        captures = capture.httpd.captures
    return out, captures, token, capture.port


# ------------------------------------------------------- the real writable server


@pytest.fixture
def writable(tmp_path):
    """A real writable ``refdes serve`` with ONE keyless marker:
    ``POST /api/navis/mint`` is the route whose whole body is ``{}``, so it is
    the route that tells an omitted body from a hang."""
    config = str(write_project_config(tmp_path, SCHEMA))
    items = tmp_path / "items"
    items.mkdir()
    (items / "note-c.md").write_text(
        f"---\nid: NOTE-003\ntype: note\ntitle: Gamma\n---\nintro\n<!--navi: {KEYLESS_TEXT}-->\n",
        encoding="utf-8",
        newline="",
    )
    app = EditorApp(config, poll_interval=60)
    app.start()
    try:
        yield app, tmp_path
    finally:
        app.stop()


LIVE_CALLS = [
    {"id": "mintNoBody", "fn": "noBody", "pathname": "/api/navis/mint"},
    {"id": "mintAgainEmpty", "fn": "emptyObj", "pathname": "/api/navis/mint"},
    {"id": "archiveNoBody", "fn": "noBody", "pathname": "/api/navis/archive"},
    {"id": "archiveNull", "fn": "nullBody", "pathname": "/api/navis/archive"},
]


# ------------------------------------------------------------------- the tests


@skip_no_node
def test_post_with_no_body_sends_an_empty_json_object_on_the_wire(tmp_path):
    """THE FIX, on the bytes: ``post(path)`` and ``post(path, undefined)``
    serialise to ``{}`` -- the SAME bytes, Content-Type and Content-Length as
    today's ``post(path, {})`` -- and resolve ``{status, body}``. Today they
    never reach the server at all (the driver records a rejection, and the
    capture shows three requests where five belong)."""
    out, captures, token, port = _capture_run(tmp_path)
    assert out["methods"]["post"] is True, out["methods"]

    assert [c["path"] for c in captures] == [path for _, path, _ in WIRE], captures
    for (case_id, path, raw), capture in zip(WIRE, captures):
        headers = capture["headers"]
        assert capture["method"] == "POST", (case_id, capture)
        assert capture["path"] == path, (case_id, capture)
        assert capture["body"].encode("latin-1") == raw, (case_id, capture)
        assert headers.get("content-type") == "application/json", (case_id, headers)
        assert headers.get("content-length") == str(len(raw)), (case_id, headers)
        assert headers.get("accept") == "application/json", (case_id, headers)
        assert headers.get(TOKEN_HEADER.lower()) == token, (case_id, headers)
        assert headers.get("origin") == f"http://127.0.0.1:{port}", (case_id, headers)
        assert headers.get("transfer-encoding") is None, (case_id, headers)

    results = {key: entry for key, entry in out["results"].items()}
    for case_id, _path, _raw in WIRE:
        entry = results[case_id]
        assert entry["syncThrew"] is False, (case_id, entry)
        assert "rejected" not in entry, (case_id, entry)
        assert entry["resolved"] == {"status": 200, "body": {"ok": True}}, (case_id, entry)


@skip_no_node
def test_post_with_no_body_reaches_a_real_server_as_an_empty_json_object(writable, tmp_path):
    """The same claim against the real ``refdes serve`` (the neighbour file's
    live posture): ``post("/api/navis/mint")`` with NO body argument mints the
    keyless marker -- 200 ``kind:"ok"``, the same answer ``navisMint()``
    (which passes ``{}``) gets, and the second call with an explicit ``{}`` is
    the idempotent no-op. ``post("/api/navis/archive")`` with no body is the
    server's structured 400 ``kind:"bad_request"`` naming the missing
    selector -- a kind-carrying body the caller can branch on, NOT the
    ``{"error": "invalid JSON"}`` an empty body would earn (server.py:927-930,
    verified by running it)."""
    app, root = writable
    out = client_dict(
        tmp_path,
        {
            "client": SERVE_CLIENT_JS,
            "base": f"http://127.0.0.1:{app.port}",
            "port": app.port,
            "token": app.token,
            "calls": LIVE_CALLS,
        },
    )
    got = {key: entry for key, entry in out["results"].items()}

    mint = got["mintNoBody"]
    assert mint["syncThrew"] is False, mint
    assert "rejected" not in mint, mint
    assert mint["resolved"]["status"] == 200, mint
    body = mint["resolved"]["body"]
    assert body["kind"] == "ok" and body["changed"] is True, body
    assert [m["item"] for m in body["minted"]] == ["NOTE-003"], body
    assert [m["file"] for m in body["minted"]] == ["items/note-c.md"], body
    disk = (root / "items" / "note-c.md").read_text(encoding="utf-8")
    assert f"<!--navi:{body['minted'][0]['key']} {KEYLESS_TEXT}-->" in disk, disk

    again = got["mintAgainEmpty"]
    assert again["resolved"]["status"] == 200, again
    assert again["resolved"]["body"]["changed"] is False, again
    assert again["resolved"]["body"]["minted"] == [], again

    archive = got["archiveNoBody"]
    assert archive["syncThrew"] is False, archive
    assert "rejected" not in archive, archive
    assert archive["resolved"]["status"] == 400, archive
    assert archive["resolved"]["body"]["kind"] == "bad_request", archive
    assert "navi is required" in archive["resolved"]["body"]["error"], archive


@skip_no_node
def test_post_with_null_sends_the_json_null_literal_unchanged(writable, tmp_path):
    """What ``post(path, null)`` sends, stated and pinned: ``JSON.stringify``
    has an honest answer for ``null``, so the body on the wire is the four
    bytes ``null`` with ``Content-Length: 4`` -- NOT ``{}`` (only an OMITTED
    argument is an empty object), and not a rejection. The real server's
    answer is the object-wanting 400 ``kind:"bad_request"``
    "expected a JSON object" (navis_write.py:57-58) -- the route renderer
    reading a JSON null. GREEN today, and it must stay green: this is the
    pin that keeps the fix from over-reaching into ``null``."""
    app, _root = writable
    out = client_dict(
        tmp_path,
        {
            "client": SERVE_CLIENT_JS,
            "base": f"http://127.0.0.1:{app.port}",
            "port": app.port,
            "token": app.token,
            "calls": [{"id": "archiveNull", "fn": "nullBody", "pathname": "/api/navis/archive"}],
        },
    )
    entry = out["results"]["archiveNull"]
    assert entry["syncThrew"] is False, entry
    assert "rejected" not in entry, entry
    assert entry["resolved"]["status"] == 400, entry
    assert entry["resolved"]["body"]["kind"] == "bad_request", entry
    assert entry["resolved"]["body"]["error"] == "expected a JSON object", entry


@skip_no_node
def test_a_circular_body_rejects_the_promise_with_an_error_naming_the_problem(tmp_path):
    """A body ``JSON.stringify`` cannot serialise REJECTS the returned
    promise: a plain ``Error`` (``instanceof Error``) whose message names the
    problem ("circular"), resolved in bounded time, and -- the part a
    ``try { JSON.stringify } catch { throw }`` outside the executor gets
    wrong -- NOT a synchronous throw out of ``post()``. Today the executor
    throw happens to reach the caller as a rejection with V8's own message;
    this test is the pin that keeps the fix's own ``catch`` in the executor
    (a ``throw`` there is the same rejection, a ``throw`` outside it is the
    contract violation)."""
    out, captures, _token, _port = _capture_run(tmp_path)
    entry = out["results"]["circular"]
    assert entry["syncThrew"] is False, entry
    assert entry.get("rejected") is True, entry
    assert entry["isError"] is True, entry
    assert "circular" in entry["message"].lower(), entry
    assert entry["elapsedMs"] < 8000, entry
    # the capture server saw ONLY the five wire calls: no request is framed
    # from a body that cannot be serialised.
    assert len(captures) == len(WIRE), captures


@skip_no_node
def test_a_bigint_body_rejects_the_promise_with_an_error_naming_the_problem(tmp_path):
    """The second non-serialisable family: ``BigInt`` makes
    ``JSON.stringify`` throw ``TypeError: Do not know how to serialize a
    BigInt``. Same contract -- rejection, plain ``Error``, message names
    BigInt, no sync throw, no hang."""
    out, _captures, _token, _port = _capture_run(tmp_path)
    entry = out["results"]["bigint"]
    assert entry["syncThrew"] is False, entry
    assert entry.get("rejected") is True, entry
    assert entry["isError"] is True, entry
    assert "BigInt" in entry["message"], entry
    assert entry["elapsedMs"] < 8000, entry


@skip_no_node
def test_post_with_an_object_body_is_unchanged(tmp_path):
    """The fix must not touch what the callers send today:
    ``post(path, {a: 1})`` is ``{"a":1}`` (JSON.stringify's compact form,
    no spaces) with the matching byte-length Content-Length, and resolves
    ``{status, body}`` as before. GREEN today by construction; the guard
    against a fix that re-serialises (e.g. via a replacer)."""
    out, captures, _token, _port = _capture_run(tmp_path)
    obj = [c for c in captures if c["path"] == "/api/navis/archive" and c["body"] == '{"a":1}']
    assert len(obj) == 1, captures
    assert obj[0]["headers"]["content-length"] == "7", obj[0]["headers"]
    entry = out["results"]["objBody"]
    assert entry["syncThrew"] is False, entry
    assert entry["resolved"] == {"status": 200, "body": {"ok": True}}, entry


@skip_no_node
def test_post_with_no_body_on_a_not_ready_client_answers_the_not_running_literal(tmp_path):
    """``post(path)`` on a client that never attached must resolve
    ``{"error": "refdes serve is not running"}`` -- the ready check runs
    BEFORE any serialisation, so a path-only call can neither reject nor dial
    anything. The fix lives after this check, which is why this is a pin and
    not a red."""
    out, _captures, _token, _port = _capture_run(tmp_path)
    entry = out["results"]["notReadyNoBody"]
    assert entry["syncThrew"] is False, entry
    assert "rejected" not in entry, entry
    assert entry["resolved"] == {"error": "refdes serve is not running"}, entry


@skip_no_node
def test_the_node_process_exits_zero_and_prints_no_unhandled_rejection(tmp_path):
    """Every rejection in this file's run is one the driver ATTACHES to
    (awaited, and one via ``.then(onFulfilled, onRejected)``), so node exits
    0 with a clean stderr: an unhandled rejection is the bug class plan §4
    names ("never rejects, never hangs" -- a rejection nobody can catch is
    the one shape that kills an extension host). The exit code is asserted by
    the harness; this test names the other half, including the ``viaCatch``
    case, whose rejection the ``.catch`` handler turns into a resolved
    record."""
    token = "cap-" + security.new_token()
    with CaptureServer() as capture:
        proc = run_client(
            tmp_path,
            {
                "client": SERVE_CLIENT_JS,
                "base": capture.url,
                "port": capture.port,
                "token": token,
                "calls": CAPTURE_CALLS,
            },
        )
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    assert "Unhandled" not in proc.stdout, proc.stdout[-2000:]
    assert "Unhandled" not in proc.stderr, proc.stderr[-2000:]
    assert "unhandled" not in proc.stderr.lower(), proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    assert "fatal" not in out, out["fatal"]
    via = out["results"]["viaCatch"]
    assert via["syncThrew"] is False, via
    assert via.get("rejected") is True, via
    assert "circular" in via["message"].lower(), via
