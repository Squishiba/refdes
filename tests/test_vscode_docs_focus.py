"""DC-4b-tests: red-first tests for the VS Code side of "follow the editor".

RED-FIRST: written before the feature exists; every red test fails on the
untouched tree because ``editors/vscode/extension.js`` has no docs-context
posting at all. This file touches nothing under ``editors/`` and no existing
test; the implementer adds the feature to ``extension.js``/``package.json``.

Contract under test (slice DC-4b, the conservative defaults the orchestrator
chose; the server side is DC-4a's ``POST /api/focus`` in
``tools/docs_context/server.py``, pinned by tests/test_docs_context_focus.py):

  1. OFF by default. A new setting ``refdes.docsContext.url`` (string, default
     ``""`` = disabled) turns it on; NO network call of any kind while it is
     empty.
  2. On a cursor/selection change of the ACTIVE text editor whose document is
     a file INSIDE the workspace: debounce 300 ms, then POST
     ``{"path": <workspace-relative path with forward slashes>, "line":
     <1-based cursor line>}`` to ``<url>/api/focus`` with headers
     ``Content-Type: application/json``, ``X-Docs-Context: 1`` and ``Origin``
     equal to the configured url's origin. Fire-and-forget: errors swallowed
     (at most one throttled output-channel line), never a popup, never
     blocking the editor; a pending request is never stacked (drop/coalesce).
  3. Only loopback urls are honoured (127.0.0.1, localhost, ::1). Any other
     host is ignored with ONE output-channel line -- the extension must never
     post file paths off the machine.
  4. Only path and line are sent: never file contents, never selection text.
  5. Same-line cursor moves after the first post do not re-post until the
     debounce elapses with a changed (path, line) pair.
  6. Setting the url back to ``""`` stops posting immediately.

Harness (the neighbouring tests/test_vscode_extension.py node posture,
extended to a whole-extension drive, which is what "copy that harness" needs
here -- text greps cannot observe a 300 ms debounce):
  * a real ``http.server`` thread on 127.0.0.1 port 0 is the fake
    docs-context server; it records the exact request (method, path, headers,
    body bytes) the extension sends and hands the captured list back over its
    own ``GET /__captures`` (snapshot-and-clear), so the node driver can
    interleave "fire event -> sleep -> snapshot" phases;
  * a node script loads the REAL ``editors/vscode/extension.js`` (Module._load
    hooks ``require("vscode")`` to the fake surface), activates it, fires
    selection/configuration events, and prints one JSON line of per-phase
    captures plus the output-channel lines and any popup calls;
  * node missing -> skip, exactly as tests/test_vscode_extension.py does.

Ambiguities this slice resolves (pinned so the implementer inherits them):
  * "inside the workspace" means relative to a configured workspaceFolder
    (the extension already keeps a root via findRoot; the workspace-folder
    reading is what the spec says and what makes ``..`` paths unconstructable
    by ``path.relative`` alone);
  * "1-based cursor line" = selection.active.line + 1 (VS Code positions are
    0-based);
  * the active editor is the source of truth: an event naming some OTHER
    editor posts the ACTIVE editor's document/selection, not the event's;
  * a non-loopback host is judged on the url's hostname, so
    ``http://127.0.0.1.evil.example/`` is NOT loopback;
  * an unparseable url (not http:, no host) is ignored silently -- no output
    line (the spec's one line is for "any other host");
  * "never shows a popup" is pinned as zero show*Message/showQuickPick calls
    from the whole run;
  * the throttle on error lines is pinned as <= 1 per burst (two bursts
    allowed: the 500 burst and the unreachable-host burst).

Servers bind 127.0.0.1:0 with a socket timeout on every node-side fetch, and
every server/thread is shut down in the test's ``finally`` -- on ubuntu and
windows alike (fixtures written with newline='', no platform path asserts).
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VSCODE_DIR = REPO_ROOT / "editors" / "vscode"
EXTENSION_JS = str(VSCODE_DIR / "extension.js")
PACKAGE_JSON = str(VSCODE_DIR / "package.json")
NODE = shutil.which("node")
NODE_TIMEOUT_S = 90

DOC_TEXT = "# Docs\n\nSECRET-CONTENT-MARKER-42\n\nSecond paragraph.\n"

skip_no_node = pytest.mark.skipif(NODE is None, reason="no node on PATH to run the extension")


# --------------------------------------------------------- the fake server side


class _CaptureHandler(BaseHTTPRequestHandler):
    """Records every POST exactly as it arrives; answers the node driver's
    snapshot fetches. mode="slow" sleeps before answering, mode="error"
    answers 500 -- both to pin the fire-and-forget half of default 2."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        """The request body: Content-Length framed, and chunked decoded too
        -- the capture records what was sent either way, and the wire-compat
        test asserts the extension does NOT use chunked (the real DC-4a
        server answers a chunked focus POST with 400, so a chunked client
        would follow nothing, silently)."""
        transfer = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in transfer:
            chunks = []
            while True:
                size_line = self.rfile.readline(65536).strip()
                try:
                    size = int(size_line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    self.rfile.readline(3)
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline(3)
            return b"".join(chunks)
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw)
        except (TypeError, ValueError):
            length = 0
        return self.rfile.read(length) if 0 < length <= 65536 else b""

    def do_POST(self):
        body = self._read_body()
        if getattr(self.server, "mode", "ok") == "slow":
            time.sleep(getattr(self.server, "slow_s", 1.0))
        entry = {
            "method": self.command,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            # latin-1 is the lossless byte<->str codec; tests decode to utf-8.
            "body": body.decode("latin-1"),
        }
        with self.server.capture_lock:
            self.server.captures.append(entry)
        if getattr(self.server, "mode", "ok") == "error":
            self._respond(500, {"error": "boom"})
        else:
            self._respond(200, {"followed": True, "line": 1, "block": 1})

    def do_GET(self):
        if self.path.startswith("/__captures"):
            with self.server.capture_lock:
                items = self.server.captures[:]
                self.server.captures.clear()
            self._respond(200, items)
        else:
            self._respond(404, {"error": "nope"})


class FakeFocusServer:
    """127.0.0.1:0, serve_forever on a daemon thread, shut down in the with."""

    def __init__(self, mode="ok", slow_s=1.0):
        self.mode = mode
        self.slow_s = slow_s
        self.httpd = None
        self.thread = None

    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.httpd.daemon_threads = True
        self.httpd.mode = self.mode
        self.httpd.slow_s = self.slow_s
        self.httpd.captures = []
        self.httpd.capture_lock = threading.Lock()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


# -------------------------------------------------------------- the node driver


DRIVER = r"""
"use strict";
const http = require("http");
const path = require("path");
const Module = require("module");

const cfg = JSON.parse(process.argv[2]);

const editors = {};
const state = {
  setting: cfg.url,
  activeEditor: null,
  output: [],
  popups: [],
  errors: [],
  listeners: { selection: [], active: [], config: [], save: [] },
};

function uriFor(fsPath, scheme) {
  return {
    scheme: scheme || "file",
    fsPath,
    path: fsPath,
    toString() {
      return (scheme || "file") + "://" + fsPath;
    },
  };
}

function makeEditor(name, fileKey, scheme) {
  const fsPath = cfg.docs[fileKey];
  const editor = {
    document: {
      uri: uriFor(fsPath, scheme),
      fileName: fsPath,
      languageId: "markdown",
      lineCount: 60,
      lineAt: () => ({ text: cfg.docText }),
      getText: () => cfg.docText,
    },
    selection: { active: { line: 0, character: 0 }, anchor: { line: 0, character: 0 } },
    setDecorations() {},
  };
  editor.selections = [editor.selection];
  editors[name] = editor;
}

function disposable() {
  return { dispose() {} };
}

function show(kind) {
  return (...args) => {
    state.popups.push(kind + ": " + String(args[0]));
    return Promise.resolve(undefined);
  };
}

const vscode = {
  workspace: {
    getConfiguration() {
      return {
        get(key, fallback) {
          if (key === "docsContext.url") return state.setting;
          if (key === "command") return cfg.command;
          if (key === "checkOnSave") return false;
          if (key === "showCalcResults") return true;
          return fallback;
        },
      };
    },
    workspaceFolders: cfg.roots.map((fsPath, index) => ({
      uri: uriFor(fsPath),
      name: "ws" + index,
      index,
    })),
    asRelativePath(uriOrPath) {
      const fsPath = typeof uriOrPath === "string" ? uriOrPath : String(uriOrPath.fsPath);
      return path.relative(cfg.roots[0], fsPath).split(path.sep).join("/");
    },
    onDidSaveTextDocument(cb) {
      state.listeners.save.push(cb);
      return disposable();
    },
    onDidChangeConfiguration(cb) {
      state.listeners.config.push(cb);
      return disposable();
    },
  },
  window: {
    get activeTextEditor() {
      return state.activeEditor;
    },
    createOutputChannel() {
      return {
        appendLine: (line) => state.output.push(String(line)),
        show() {},
        clear() {},
        dispose() {},
      };
    },
    createStatusBarItem() {
      return { text: "", tooltip: "", command: "", show() {}, dispose() {} };
    },
    createTextEditorDecorationType() {
      return { dispose() {} };
    },
    onDidChangeActiveTextEditor(cb) {
      state.listeners.active.push(cb);
      return disposable();
    },
    onDidChangeTextEditorSelection(cb) {
      state.listeners.selection.push(cb);
      return disposable();
    },
    showErrorMessage: show("error"),
    showWarningMessage: show("warning"),
    showInformationMessage: show("info"),
    withProgress: (_opts, cb) => Promise.resolve(cb({ report() {} })),
  },
  languages: {
    createDiagnosticCollection() {
      return { clear() {}, set() {}, dispose() {} };
    },
    registerHoverProvider: disposable,
    registerCodeLensProvider: disposable,
    registerDefinitionProvider: disposable,
    registerCompletionItemProvider: disposable,
  },
  commands: {
    executeCommand: () => Promise.resolve(),
    registerCommand: () => disposable(),
  },
  env: { openExternal: () => Promise.resolve(true) },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ProgressLocation: { Window: 1 },
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  Uri: { file: (f) => uriFor(f) },
  Range: class {
    constructor(sl, sc, el, ec) {
      this.start = { line: sl, character: sc };
      this.end = { line: el, character: ec };
    }
  },
  Position: class {
    constructor(line, character) {
      this.line = line;
      this.character = character;
    }
  },
  Diagnostic: class {
    constructor(range, message, severity) {
      this.range = range;
      this.message = message;
      this.severity = severity;
    }
  },
  MarkdownString: class {
    constructor() {
      this.value = "";
      this.supportThemeIcons = false;
    }
    appendMarkdown(text) {
      this.value += text;
      return this;
    }
  },
  Hover: class {
    constructor(contents, range) {
      this.contents = contents;
      this.range = range;
    }
  },
  CodeLens: class {
    constructor(range, command) {
      this.range = range;
      this.command = command;
    }
  },
  CompletionItem: class {
    constructor(label, kind) {
      this.label = label;
      this.kind = kind;
    }
  },
  CompletionItemKind: { EnumMember: 16, Field: 4, Reference: 17 },
  ThemeColor: class {
    constructor(id) {
      this.id = id;
    }
  },
};

const realLoad = Module._load;
Module._load = function (request) {
  if (request === "vscode") return vscode;
  return realLoad.apply(this, arguments);
};

function httpJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        text += chunk;
      });
      res.on("end", () => {
        if (res.statusCode !== 200) {
          reject(new Error("capture server answered " + res.statusCode));
          return;
        }
        try {
          resolve(JSON.parse(text));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.setTimeout(5000, () => req.destroy(new Error("capture fetch timed out")));
    req.on("error", reject);
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const phases = {};
const outAt = {};

function fire(name, line, activeName) {
  const editor = editors[name];
  if (!editor) {
    state.errors.push("no editor " + name);
    return;
  }
  editor.selection = { active: { line, character: 0 }, anchor: { line, character: 0 } };
  editor.selections = [editor.selection];
  if (activeName) state.activeEditor = editors[activeName];
  for (const cb of state.listeners.selection.slice()) {
    try {
      cb({ textEditor: editor, selections: editor.selections });
    } catch (err) {
      state.errors.push("selection listener: " + String(err));
    }
  }
}

async function main() {
  const context = {
    subscriptions: [],
    asAbsolutePath: (p) => path.join(cfg.extDir, p),
  };
  const ext = require(cfg.ext);
  for (const step of cfg.steps) {
    if (step.a === "activate") {
      try {
        await ext.activate(context);
      } catch (err) {
        state.errors.push("activate: " + String((err && err.stack) || err));
      }
    } else if (step.a === "deactivate") {
      try {
        if (typeof ext.deactivate === "function") ext.deactivate();
      } catch (err) {
        state.errors.push("deactivate: " + String(err));
      }
    } else if (step.a === "set") {
      state.setting = step.url;
    } else if (step.a === "configChange") {
      for (const cb of state.listeners.config.slice()) {
        try {
          cb({ affectsConfiguration: (ns) => String(ns).indexOf("refdes") === 0 });
        } catch (err) {
          state.errors.push("config listener: " + String(err));
        }
      }
    } else if (step.a === "editor") {
      makeEditor(step.name, step.file, step.scheme);
    } else if (step.a === "active") {
      state.activeEditor = editors[step.name] || null;
    } else if (step.a === "fire") {
      fire(step.name, step.line, step.name);
    } else if (step.a === "fireOn") {
      fire(step.name, step.line, step.active);
    } else if (step.a === "sleep") {
      await sleep(step.ms);
    } else if (step.a === "snap") {
      phases[step.name] = await httpJson(cfg.server + "/__captures");
      outAt[step.name] = state.output.slice();
    } else if (step.a === "out") {
      outAt[step.name] = state.output.slice();
    } else if (step.a === "waitposts") {
      // Poll until n posts have arrived (deadline-bounded), then drain a
      // quiet window too: the count is proved without a load-sensitive
      // fixed sleep, and the quiet drain proves nothing further arrived.
      const got = [];
      const t0 = Date.now();
      while (got.length < step.n && Date.now() - t0 < step.deadline) {
        got.push(...(await httpJson(cfg.server + "/__captures")));
        if (got.length < step.n) await sleep(50);
      }
      await sleep(step.quiet);
      got.push(...(await httpJson(cfg.server + "/__captures")));
      phases[step.name] = got;
      outAt[step.name] = state.output.slice();
    } else {
      state.errors.push("unknown step " + step.a);
    }
  }
}

main()
  .then(() => {
    finish({ phases, outAt, popups: state.popups, errors: state.errors });
  })
  .catch((err) => {
    finish({ fatal: String((err && err.stack) || err) });
  });

// stdout is a pipe: process.exit() can truncate an async write, so the last
// line goes out synchronously (the reader drains continuously, a blocking
// write cannot stall here with payloads this small).
function finish(payload) {
  const text = JSON.stringify(payload);
  try {
    require("fs").writeSync(1, text);
  } catch (err) {
    process.stdout.write(text);
  }
  process.exit(0);
}
"""


# ----------------------------------------------------------- the harness plumbing


def make_workspace(tmp_path: Path) -> Path:
    """A refdes-shaped workspace on real disk (findRoot and path.relative need
    real paths): ws/refdes-project.yaml, docs/a.md, docs/b.md, docs/sub/deep.md,
    a root-level a.md, an outside/x.md sibling, and the exit-1 command script."""
    ws = tmp_path / "ws"
    (ws / "docs" / "sub").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (ws / "refdes-project.yaml").write_text("site: _site\n", encoding="utf-8", newline="")
    for rel in ("docs/a.md", "docs/b.md", "docs/sub/deep.md", "a.md"):
        (ws / rel).write_text(DOC_TEXT, encoding="utf-8", newline="")
    (tmp_path / "outside" / "x.md").write_text(DOC_TEXT, encoding="utf-8", newline="")
    (tmp_path / "exit1.js").write_text("process.exit(1);\n", encoding="utf-8", newline="")
    return ws


def base_cfg(tmp_path: Path, ws: Path, server, url: str, steps: list) -> str:
    docs = {
        "a": str(ws / "docs" / "a.md"),
        "b": str(ws / "docs" / "b.md"),
        "deep": str(ws / "docs" / "sub" / "deep.md"),
        "root": str(ws / "a.md"),
        "outside": str(tmp_path / "outside" / "x.md"),
    }
    cfg = {
        "ext": EXTENSION_JS,
        "extDir": str(VSCODE_DIR),
        "server": server.url,
        "url": url,
        # The index refresh activate() spawns must fail fast and silently;
        # a node script exiting 1 is the cross-platform way to say so.
        "command": 'node "' + str(tmp_path / "exit1.js") + '"',
        "roots": [str(ws)],
        "docs": docs,
        "docText": DOC_TEXT,
        "steps": [{"a": "activate"}, *steps],
    }
    return json.dumps(cfg)


def run_extension(tmp_path: Path, cfg_json: str) -> dict:
    script = tmp_path / "focus-driver.js"
    script.write_text(DRIVER, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(script), cfg_json],
        capture_output=True,
        text=True,
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
    assert out["errors"] == [], out["errors"]
    return out


def body_json(item: dict) -> dict:
    return json.loads(item["body"].encode("latin-1").decode("utf-8"))


def docs_context_lines(lines: list) -> list:
    return [line for line in lines if re.search(r"docs.?context", line, re.IGNORECASE)]


REFUSAL_TEXT = "names the non-loopback host"


def refusal_lines(lines: list, needle: str = "") -> list:
    """Only the lines docsFocus.js really logs for a REFUSED host (its
    refusal wording), not the swallowed-failure line, not any other
    docs-context output. `needle` pins which host the refusal names."""
    return [
        line
        for line in docs_context_lines(lines)
        if REFUSAL_TEXT in line and (not needle or needle in line)
    ]


def closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# -------------------------------------------------------------------- defaults


def test_setting_is_declared_off_by_default():
    """Default 1: package.json contributes refdes.docsContext.url, a string
    whose default is the empty string -- the setting exists and is OFF.
    Fails today: the property is not contributed at all."""
    with open(PACKAGE_JSON, encoding="utf-8") as fh:
        properties = json.load(fh)["contributes"]["configuration"]["properties"]
    prop = properties.get("refdes.docsContext.url")
    assert prop is not None, (
        "editors/vscode/package.json contributes no refdes.docsContext.url "
        f"setting; it contributes {sorted(properties)}"
    )
    assert prop.get("type") == "string", prop
    assert prop.get("default") == "", (
        f"refdes.docsContext.url must default to '' (feature off by default), got {prop!r}"
    )


# ------------------------------------------------------------------ defaults 1/2


@skip_no_node
def test_empty_url_makes_no_network_call_at_all(tmp_path):
    """Default 1, the network half: with the setting empty, cursor changes
    produce zero requests of any kind. (PASSES on the untouched tree -- the
    tree never posts; it is the guard that keeps the feature's on-switch from
    ever being widened to a silent-on default.)"""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                "",
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p1"},
                ],
            ),
        )
    assert out["phases"]["p1"] == []
    assert out["popups"] == []


@skip_no_node
def test_enabled_url_posts_the_active_cursor(tmp_path):
    """Default 2: with the setting on, one debounced POST /api/focus with the
    three headers and the {"path", "line"} body; line 1-based, path
    workspace-relative with forward slashes; exactly one request."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    req = requests[0]
    assert req["method"] == "POST", req
    assert req["path"] == "/api/focus", req
    headers = req["headers"]
    assert headers.get("x-docs-context") == "1", headers
    assert headers.get("content-type") == "application/json", headers
    assert headers.get("origin") == server.url, headers
    # Wire-compat with the REAL DC-4a server, whose _read_ask_body answers a
    # chunked body with 400: the focus POST must be Content-Length framed.
    assert headers.get("transfer-encoding") is None, headers
    assert headers.get("content-length") == str(len(req["body"].encode("latin-1"))), headers
    body = body_json(req)
    assert set(body) == {"path", "line"}, body
    assert body["path"] == "docs/a.md", body
    assert body["line"] == 5, body
    assert out["popups"] == []


@skip_no_node
def test_paths_are_workspace_relative_with_forward_slashes(tmp_path):
    """Default 2's path spelling, on the real platform separators: docs/sub/
    deep.md and a root-level file both come out workspace-relative and
    slash-separated; line stays 1-based."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "deep", "file": "deep"},
                    {"a": "fire", "name": "deep", "line": 1},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "editor", "name": "root", "file": "root"},
                    {"a": "fire", "name": "root", "line": 9},
                    {"a": "waitposts", "name": "p2", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    assert [body_json(r)["path"] for r in out["phases"]["p1"]] == ["docs/sub/deep.md"]
    assert body_json(out["phases"]["p1"][0])["line"] == 2
    assert [body_json(r)["path"] for r in out["phases"]["p2"]] == ["a.md"]
    assert body_json(out["phases"]["p2"][0])["line"] == 10


@skip_no_node
def test_rapid_selection_changes_debounce_to_one_post(tmp_path):
    """Default 2's 300 ms debounce: five cursor moves in immediate
    succession produce exactly ONE post, carrying the LAST (path, line)."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    *[{"a": "fire", "name": "a", "line": line} for line in range(5)],
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 5}, requests


@skip_no_node
def test_same_path_and_line_are_not_reposted(tmp_path):
    """Default 5: after the first post, refiring the SAME (path, line) pair
    posts nothing; only a changed pair posts again."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 800},
                    {"a": "snap", "name": "p2"},
                    {"a": "fire", "name": "a", "line": 6},
                    {"a": "waitposts", "name": "p3", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    assert len(out["phases"]["p1"]) == 1, out["phases"]["p1"]
    assert out["phases"]["p2"] == [], out["phases"]["p2"]
    requests = out["phases"]["p3"]
    assert len(requests) == 1, requests
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 7}, requests


@skip_no_node
def test_returning_to_the_posted_pair_cancels_the_pending_post(tmp_path):
    """Round-1 review pin (the de-dupe is a CANCELLED post, not an early
    return over a live timer): after A is posted, a burst B -> A -- the
    cursor back on the posted pair inside the debounce window -- must
    leave NOTHING pending, so the viewer ends where the cursor settled;
    a burst A -> B -> C (never returning to A) posts only C."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},  # A = (docs/a.md, 5)
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "fire", "name": "a", "line": 6},  # B armed...
                    {"a": "fire", "name": "a", "line": 4},  # ...cancelled by A
                    {"a": "sleep", "ms": 800},
                    {"a": "snap", "name": "p2"},
                    {"a": "fire", "name": "a", "line": 8},  # a lone post after A
                    {"a": "waitposts", "name": "p3", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 5}, requests
    assert out["phases"]["p2"] == [], (
        "the cursor returned to the posted pair inside the debounce window, "
        "so the armed B must be CANCELLED, not posted: "
        f"{[body_json(r) for r in out['phases']['p2']]!r}"
    )
    requests = out["phases"]["p3"]
    assert len(requests) == 1, requests
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 9}, requests


@skip_no_node
def test_only_the_active_workspace_file_editor_is_posted(tmp_path):
    """Default 2's gate: the ACTIVE editor, whose document is a file INSIDE
    the workspace. A selection event naming a non-active editor posts the
    ACTIVE editor's (path, line); an untitled document and a file outside
    every workspace folder post nothing."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "editor", "name": "b", "file": "b"},
                    {"a": "active", "name": "a"},
                    {"a": "fireOn", "name": "b", "line": 2, "active": "a"},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "editor", "name": "t", "file": "a", "scheme": "untitled"},
                    {"a": "fire", "name": "t", "line": 3},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p2"},
                    {"a": "editor", "name": "o", "file": "outside"},
                    {"a": "fire", "name": "o", "line": 2},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p3"},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 1}, requests
    assert out["phases"]["p2"] == [], out["phases"]["p2"]
    assert out["phases"]["p3"] == [], out["phases"]["p3"]


@skip_no_node
def test_pending_requests_are_not_stacked(tmp_path):
    """Default 2's fire-and-forget half: against a server that answers each
    POST only after a second, a run of cursor moves never stacks requests --
    at most one post per burst is in flight, so the run produces 1-2 posts
    for six moves (drop), never six (coalesce)."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer(mode="slow", slow_s=1.0) as server:
        steps = [{"a": "editor", "name": "a", "file": "a"}]
        for line in range(6):
            steps.append({"a": "fire", "name": "a", "line": line})
            steps.append({"a": "sleep", "ms": 250})
        steps += [{"a": "sleep", "ms": 2600}, {"a": "snap", "name": "p1"}]
        out = run_extension(tmp_path, base_cfg(tmp_path, ws, server, server.url, steps))
    requests = out["phases"]["p1"]
    assert 1 <= len(requests) <= 2, requests
    assert body_json(requests[0])["path"] == "docs/a.md"


# ------------------------------------------------------------------- default 4


@skip_no_node
def test_body_carries_only_path_and_line(tmp_path):
    """Default 4: the raw body is exactly {"path", "line"}; the document's
    text (marker) appears nowhere in the body bytes, and no body-carrying
    header (Referer/Title/Selection) smuggles it."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 2},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    req = requests[0]
    body = body_json(req)
    assert set(body) == {"path", "line"}, body
    assert "SECRET" not in req["body"], req["body"]
    for name, value in req["headers"].items():
        assert "SECRET" not in value, (name, value)
        assert "SECRET" not in name.lower(), name


# ------------------------------------------------------------------- default 3


@skip_no_node
def test_non_loopback_url_is_ignored_with_one_output_line(tmp_path):
    """Default 3: a setting naming a non-loopback host posts NOTHING (the
    host never resolves to our capture server by design: .invalid) and says
    so with EXACTLY ONE refusal line naming the host -- matched by the
    refusal wording itself, not by "any line mentioning docs-context", so a
    swallowed failure line cannot masquerade as the refusal. No popup, no
    crash. The one line is the pin: the tree today produces zero output for
    the setting."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                "http://evil.invalid:8099",
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p1"},
                ],
            ),
        )
    assert out["phases"]["p1"] == []
    assert out["popups"] == []
    lines = refusal_lines(out["outAt"]["p1"], "evil.invalid")
    assert len(lines) == 1, (
        "a non-loopback refdes.docsContext.url must be refused with EXACTLY "
        "ONE refusal line naming the host; output was: "
        f"{out['outAt']['p1']!r}"
    )


@skip_no_node
def test_localhost_and_ipv6_loopback_urls_are_honoured(tmp_path):
    """Default 3's allow-list: http://localhost:<port> posts (the capture
    server binds 127.0.0.1; localhost resolves to it on both platforms) with
    Origin = that url's origin; http://[::1]:<port> is accepted as loopback
    too -- no refusal line (the connection itself is refused by the IPv4-only
    server, and default 2's swallow covers the failure)."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                f"http://localhost:{server.port}",
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "set", "url": f"http://[::1]:{server.port}"},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 6},
                    {"a": "sleep", "ms": 800},
                    {"a": "snap", "name": "p2"},
                ],
            ),
        )
    requests = out["phases"]["p1"]
    assert len(requests) == 1, requests
    assert requests[0]["headers"].get("origin") == f"http://localhost:{server.port}"
    assert requests[0]["headers"].get("x-docs-context") == "1", requests[0]["headers"]
    assert body_json(requests[0]) == {"path": "docs/a.md", "line": 5}, requests
    refused = [
        line
        for line in docs_context_lines(out["outAt"]["p2"])
        if re.search(r"ignor|refus|host", line, re.IGNORECASE)
    ]
    assert refused == [], (
        f"[::1] is loopback and must be honoured, not refused; output was: "
        f"{out['outAt']['p2']!r}"
    )
    assert out["popups"] == []


# ------------------------------------------------------------------- defaults 2/6


@skip_no_node
def test_clearing_the_url_stops_posting_immediately(tmp_path):
    """Default 6: with the feature on and posting, setting the url back to
    "" (plus the configuration-change event) stops every later post: the
    cursor move after the change produces nothing."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "waitposts", "name": "p1", "n": 1, "deadline": 5000, "quiet": 600},
                    {"a": "set", "url": ""},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 6},
                    {"a": "sleep", "ms": 800},
                    {"a": "snap", "name": "p2"},
                ],
            ),
        )
    assert len(out["phases"]["p1"]) == 1, out["phases"]["p1"]
    assert out["phases"]["p2"] == [], out["phases"]["p2"]


@skip_no_node
def test_server_errors_are_swallowed_with_one_throttled_line(tmp_path):
    """Default 2's fire-and-forget half, error side: three 500s produce three
    posts and AT MOST ONE throttled output-channel line; a burst of two
    failures against a closed port adds at most one more. Nothing ever
    reaches showErrorMessage/showWarningMessage/showInformationMessage, and
    the extension host never dies."""
    ws = make_workspace(tmp_path)
    dead = closed_port()
    with FakeFocusServer(mode="error") as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                server.url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 600},
                    {"a": "fire", "name": "a", "line": 5},
                    {"a": "sleep", "ms": 600},
                    {"a": "fire", "name": "a", "line": 6},
                    {"a": "waitposts", "name": "p1", "n": 3, "deadline": 5000, "quiet": 600},
                    {"a": "set", "url": f"http://127.0.0.1:{dead}"},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 8},
                    {"a": "sleep", "ms": 600},
                    {"a": "fire", "name": "a", "line": 9},
                    {"a": "sleep", "ms": 900},
                    {"a": "snap", "name": "p2"},
                ],
            ),
        )
    assert len(out["phases"]["p1"]) == 3, out["phases"]["p1"]
    assert len(docs_context_lines(out["outAt"]["p1"])) <= 1, out["outAt"]["p1"]
    assert len(docs_context_lines(out["outAt"]["p2"])) <= 2, out["outAt"]["p2"]
    assert out["popups"] == []


# --------------------------------------------------- the silent branch (round 2)


@skip_no_node
def test_unparseable_urls_are_ignored_silently(tmp_path):
    """The docstring's silent branch, pinned by running it: garbage text,
    a non-http scheme aimed at a loopback host, and https:// all post
    NOTHING and print NOTHING (the spec's one output line belongs to
    "any other host", not to unparseable input; the https case pins the
    round-1 skipped finding AS IS -- silently ignored)."""
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                "",
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "set", "url": "not a url"},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "g1"},
                    {"a": "set", "url": f"ftp://127.0.0.1:{server.port}"},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 6},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "g2"},
                    {"a": "set", "url": f"https://127.0.0.1:{server.port}"},
                    {"a": "configChange"},
                    {"a": "fire", "name": "a", "line": 8},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "g3"},
                ],
            ),
        )
    for name in ("g1", "g2", "g3"):
        assert out["phases"][name] == [], (name, out["phases"][name])
    assert docs_context_lines(out["outAt"]["g3"]) == [], out["outAt"]["g3"]
    assert out["popups"] == []


# ------------------------------------------------ loopback lookalikes (round 2)

# The PR's claim, now driven: hosts a startsWith-style check would wave
# through. Each refused host must produce zero posts AND exactly one
# refusal line naming it (the refusal line is the observable witness;
# port 8099 is not the capture server, so the post would be lost). The
# bracketed shape fails WHATWG host parsing (a bracketed IPv6 literal
# must be the whole host), so it lands in the silent branch with NO
# output line -- pinned per case.
LOOKALIKES = [
    ("http://127.0.0.1.evil.example:8099", "127.0.0.1.evil.example"),
    ("http://localhost.evil.example:8099", "localhost.evil.example"),
    ("http://evil.example/127.0.0.1", "evil.example"),
    ("http://[::1].evil.example:8099", None),
]


@skip_no_node
@pytest.mark.parametrize("url,needle", LOOKALIKES, ids=[u for u, _ in LOOKALIKES])
def test_loopback_lookalikes_are_refused(tmp_path, url, needle):
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                url,
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p1"},
                ],
            ),
        )
    assert out["phases"]["p1"] == [], out["phases"]["p1"]
    if needle is None:
        # Unparseable (bracketed host is not a valid IPv6 literal):
        # the silent branch -- no post AND no output line.
        assert docs_context_lines(out["outAt"]["p1"]) == [], out["outAt"]["p1"]
    else:
        lines = refusal_lines(out["outAt"]["p1"], needle)
        assert len(lines) == 1, (
            f"{url} must be refused with exactly one refusal line naming "
            f"the host; output was: {out['outAt']['p1']!r}"
        )
    assert out["popups"] == []


# --------------------------------- refusals observed against the capture (round 2)

# Refused urls that WOULD reach the capture server if wrongly accepted,
# so "zero posts" is observable there (not vacuous against a dead host):
#   * 0.0.0.0:<capture-port> -- on Linux connect(0.0.0.0) goes to
#     loopback, so a wrongly-accepted 0.0.0.0 lands on the capture
#     server; on Windows the connect fails, degrading that one case to
#     vacuous (the refusal line stays observable everywhere);
#   * the userinfo shapes pin that the host is what follows the '@':
#     "127.0.0.1@evil.example" has host evil.example (refused), while
#     "evil.example@127.0.0.1" has host 127.0.0.1 -- genuinely loopback,
#     so it must be HONOURED (a substring rule over the url text accepts
#     both; a WHATWG-host rule splits them exactly here).
USERINFO_CASES = [
    ("0.0.0.0", "refused", "0.0.0.0"),
    ("127.0.0.1@evil.example", "refused", "evil.example"),
    ("evil.example@127.0.0.1", "honoured", None),
]


@skip_no_node
@pytest.mark.parametrize(
    "hostpart,expect,needle", USERINFO_CASES, ids=[c[0] for c in USERINFO_CASES]
)
def test_url_host_observability_against_the_capture_server(tmp_path, hostpart, expect, needle):
    ws = make_workspace(tmp_path)
    with FakeFocusServer() as server:
        out = run_extension(
            tmp_path,
            base_cfg(
                tmp_path,
                ws,
                server,
                f"http://{hostpart}:{server.port}",
                [
                    {"a": "editor", "name": "a", "file": "a"},
                    {"a": "fire", "name": "a", "line": 4},
                    {"a": "sleep", "ms": 700},
                    {"a": "snap", "name": "p1"},
                ],
            ),
        )
    assert out["popups"] == []
    if expect == "refused":
        assert out["phases"]["p1"] == [], (
            f"http://{hostpart}:{server.port} is not loopback and must not "
            f"post; captured: {out['phases']['p1']!r}"
        )
        assert len(refusal_lines(out["outAt"]["p1"], needle)) == 1, out["outAt"]["p1"]
    else:
        requests = out["phases"]["p1"]
        assert len(requests) == 1, (
            f"http://{hostpart}:{server.port} parses to the loopback host "
            f"127.0.0.1 (userinfo is not the host) and must be honoured"
        )
        assert requests[0]["headers"].get("origin") == f"http://127.0.0.1:{server.port}"
        assert body_json(requests[0]) == {"path": "docs/a.md", "line": 5}
        assert refusal_lines(out["outAt"]["p1"]) == [], out["outAt"]["p1"]
