"""N6.3-review: the read-only status bar keeps its `--no-write` TOOLTIP across
index repaints (docs/design/navis-vscode-panel-plan.md §4's 403 row: "disable
write actions for the session, status bar tooltip names `--no-write`").

The S6.2b-2 slice made ``applyNavisLockStatus()`` (called at the end of
``updateStatusBar``'s repaint) re-apply the lock's TEXT after every index
refresh. It re-applies the text only: ``setNavisWriteStatus`` writes the
server's refusal sentence into ``statusBar.tooltip`` (the one naming
``--no-write``), and the very next index repaint overwrites the tooltip with
the index tooltip -- so the flag the plan promises to name survives less long
than the text it sits under.

Pinned here, at the level a real window shows (the tooltip string on the live
status item, read through the fake host's createStatusBarItem return -- no
real VS Code window exists, plan S7.2's posture):

  1. locked, index repaint: the text is the lock text AND the tooltip is the
     refusal text again -- a PLAIN string, never a MarkdownString (plan S6:
     the status strings are plain; the index tooltip IS a MarkdownString, so
     the type pin also pins that the repaint's value did not stand).
  2. a second refusal refreshes the remembered tooltip (the LAST refusal's
     text wins).
  3. after a reset (a new serve boot -- the shipped S6.2b reset), the repaint
     shows the normal index tooltip: the remembered string paints nothing
     once the lock is gone.

Harness: the whole-extension node drive of tests/test_vscode_docs_focus.py
(``Module._load`` hooks ``require("vscode")`` to the fake surface; the real
``editors/vscode/extension.js`` is activated), with a faked CLI answering
``index --compact`` (fixture JSON) and a faked ``./serveClient`` answering
every navis POST with the scripted 403 ``refused``. The lock phases run
through the SHIPPED wiring: ``refdes.navisArchive`` for the scripted row
(boot A), then ``refdes.navisMint`` after a second boot (boot B, whose
``startServe`` runs the shipped lock reset). node missing -> skip, as the
neighbours do.

Cross-platform (tests/test_crossplatform_lint.py): the node subprocess reads
with ``encoding="utf-8"`` (a Windows runner's cp1252 locale would mojibake
the middle dot in the index tooltip -- tests/test_editor_live_calc.py's
posture), the driver, stub and fixtures are written with ``newline=""``, the
run is bounded by NODE_TIMEOUT_S, and no path-separator assertions appear.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_DIR = os.path.join(REPO_ROOT, "editors", "vscode")
EXTENSION_JS = os.path.join(VSCODE_DIR, "extension.js")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to run the extension"
)

LOCK_TEXT = "$(lock) Refdes: read-only"
REFUSAL_A = {
    "status": 403,
    "body": {
        "kind": "refused",
        "error": "this server was started with --no-write: navis archive and restore are disabled",
    },
}
REFUSAL_B = {
    "status": 403,
    "body": {
        "kind": "refused",
        "error": "this server was started with --no-write: navis mint is disabled",
    },
}

MINT_OK = {
    "status": 200,
    "body": {
        "kind": "ok",
        "changed": True,
        "minted": [{"key": "5kk2m4ppqrs", "key6": "5kk2m4", "item": "NOTE-0001", "file": "items/a.md"}],
        "still_keyless": 0,
    },
}

INDEX_DATA = {
    "items": [{"id": "NOTE-0001", "title": "Alpha"}],
    "diagnostics": [
        {"level": "error", "file": "items/a.md", "item": "NOTE-0001", "message": "boom"},
        {"level": "warning", "file": "items/a.md", "item": "NOTE-0001", "message": "meh"},
    ],
    "coverage": {"NOTE-0001": {"stage": "open"}},
}
# The extension's own index tooltip, built the way updateStatusBar does --
# one middle dot included, the cross-platform canary for the utf-8 read.
INDEX_TOOLTIP = "1 items · 1 errors · 1 warnings\n1 not yet verified"
# updateStatusBar writes this plain string (no MarkdownString exists in
# editors/vscode/extension.js) -- the repaint's value, pinned from :200-202.

# One KEYLESS row: archive refuses it disabled (never posts), mint offers it.
# Phase A locks with the ARCHIVE refusal (POST #1) and refreshes the tree
# (GET /api/navis -- the stub answers it, so the payload is live); phase B's
# mint posts the MINT refusal (POST #2).
ROW = {
    "key": "",
    "key6": "",
    "text": "Alpha note.",
    "item": "NOTE-0001",
    "href": "note-001.html",
    "file": "items/a.md",
    "line": 2,
    "archived": False,
    "changed": False,
    "orphan": False,
}
PAYLOAD = {"navis": [ROW], "counts": {"active": 1, "archived": 0}}


DRIVER = r"""
"use strict";
const path = require("path");
const Module = require("module");

const cfg = JSON.parse(process.argv[2]);

function disposable() {
  return { dispose() {} };
}

function uriFor(fsPath) {
  return { scheme: "file", fsPath, path: fsPath, toString: () => "file://" + fsPath };
}

const state = {
  output: [],
  popups: [],
  errors: [],
  commands: new Map(),
  savedHandlers: [],
  statusItems: [],
  activeEditor: null,
};

let navisView = null;

// The ratified Q5 gesture: making the view visible runs refreshNavisTree(true),
// i.e. the extension's OWN startServe -- the site of the shipped lock reset.
// (A direct refdes.navisMint cannot boot: the boot lives in the tree's lazy
// path, not in the command.)
function makeNavisView() {
  navisView = {
    visible: false,
    badge: undefined,
    _visibilityHandlers: [],
    onDidExpandElement() {
      return disposable();
    },
    onDidChangeVisibility(cb) {
      navisView._visibilityHandlers.push(cb);
      return disposable();
    },
    dispose() {},
    async setVisible(value) {
      navisView.visible = Boolean(value);
      for (const cb of navisView._visibilityHandlers.slice()) {
        await cb();
      }
    },
  };
  state.navisView = navisView;
  return navisView;
}

function makeEditor() {
  const lines = [
    { text: "id: NOTE-0001" },
    { text: "title: Alpha" },
    { text: "body line" },
    { text: "```calc" },
    { text: "x = 1 + 1" },
    { text: "```" },
  ];
  const document = {
    uri: uriFor(cfg.docPath),
    fileName: cfg.docPath,
    languageId: "markdown",
    lineCount: lines.length,
    lineAt: (i) => lines[i],
    getText: () => lines.map((l) => l.text).join("\n"),
  };
  const selection = { active: { line: 0, character: 0 }, anchor: { line: 0, character: 0 } };
  return { document, selection, selections: [selection], setDecorations() {} };
}

function show(kind) {
  return (message, ...rest) => {
    state.popups.push(kind + ": " + String(message));
    const options = rest.find((x) => x && typeof x === "object");
    const buttons = rest.filter((x) => typeof x === "string");
    const chosen =
      options && options.modal === true && buttons.length ? buttons[0] : undefined;
    return Promise.resolve(chosen);
  };
}

const vscode = {
  workspace: {
    getConfiguration() {
      return {
        get(key, fallback) {
          if (key === "command") return cfg.command;
          if (key === "checkOnSave") return true;
          if (key === "showCalcResults") return true;
          return fallback;
        },
      };
    },
    workspaceFolders: [{ uri: uriFor(cfg.root), name: "ws0", index: 0 }],
    asRelativePath(p) {
      const fsPath = typeof p === "string" ? p : String(p.fsPath);
      return path.relative(cfg.root, fsPath).split(path.sep).join("/");
    },
    onDidSaveTextDocument(cb) {
      state.savedHandlers.push(cb);
      return disposable();
    },
    onDidChangeConfiguration() {
      return disposable();
    },
  },
  window: {
    get activeTextEditor() {
      return state.activeEditor;
    },
    createOutputChannel() {
      return { appendLine: (line) => state.output.push(String(line)), show() {}, clear() {}, dispose() {} };
    },
    createTreeView: (id, options) => {
      state.treeDataProvider = options && options.treeDataProvider;
      return makeNavisView();
    },
    createStatusBarItem() {
      const item = {
        text: "",
        tooltip: "",
        command: "",
        visible: false,
        show() {
          this.visible = true;
        },
        hide() {
          this.visible = false;
        },
        dispose() {},
      };
      state.statusItems.push(item);
      return item;
    },
    createTextEditorDecorationType() {
      return { dispose() {} };
    },
    onDidChangeActiveTextEditor() {
      return disposable();
    },
    onDidChangeTextEditorSelection() {
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
    registerHoverProvider: () => disposable(),
    registerCodeLensProvider: () => disposable(),
    registerDefinitionProvider: () => disposable(),
    registerCompletionItemProvider: () => disposable(),
  },
  commands: {
    registerCommand(id, fn) {
      state.commands.set(id, fn);
      return disposable();
    },
    executeCommand: () => Promise.resolve(),
  },
  env: { openExternal: () => Promise.resolve(true) },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ProgressLocation: { Window: 1 },
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  TreeItem: class {
    constructor(label, collapsibleState) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  },
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
  EventEmitter: class {
    constructor() {
      this.event = () => disposable();
    }
    fire() {}
    dispose() {}
  },
  Uri: { file: (f) => uriFor(f), parse: (s) => ({ scheme: "refdes", toString: () => s }) },
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
    constructor(value) {
      this.value = value || "";
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
// Absolute path of the faked ./serveClient module -- `require` of a
// "."-prefixed request from THIS file resolves exactly as extension.js's
// own `require("./serveClient")` will (Module._load gets the raw request
// string and no per-parent require object on Node 22, so the request is
// recognised by name and answered with the pre-resolved stub).
const serveStubPath = require.resolve(cfg.serveModule);
Module._load = function (request) {
  if (request === "vscode") return vscode;
  // The extension's OWN `require("./serveClient")` is redirected to the
  // faked stub -- the stub is the only ServeClient the extension ever
  // constructs, and it shares its module instance (same require.cache
  // entry) with the driver's own `Serve` handle below.
  if (request === "./serveClient") return require(serveStubPath);
  return realLoad.apply(this, arguments);
};

// The index item: the SHARED item is the first one activate() creates (the
// serve item is second -- the order of activate's own lines).
function indexItem() {
  return state.statusItems[0];
}

// The faked ./serveClient (hooked by the Module._load override above).
const Serve = require(cfg.serveModule);

const out = {};

function snapshot(name) {
  const item = indexItem();
  out[name] = {
    text: item.text,
    tooltip: item.tooltip,
    tooltipType: typeof item.tooltip,
  };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const context = { subscriptions: [], asAbsolutePath: (p) => path.join(cfg.extDir, p) };
  const ext = require(cfg.ext);
  await ext.activate(context);
  // activate's initial boot runs in the background (the boot-at-activation
  // is `void`-ed); the stub is armed "fail", so it lands on the shipped
  // dead-server path -- a popup, not an error. Let it drain (the index
  // refresh's output lines all land with it) so no boot lands mid-phase.
  while (Date.now() < cfg.drainDeadline) await sleep(25);
  snapshot("idle");

  // Lock the session through the SHIPPED wiring: the visibility gesture
  // boots the (armed-ready) client -- the shipped lazy-boot site -- and the
  // mint confirmation (the fake auto-presses the modal button) posts
  // against the keyless row; the faked server REFUSES -- plan S4's 403 row:
  // setStatus with the refusal text, the tooltip naming --no-write.
  state.activeEditor = makeEditor();
  Serve.__setBootMode("ok");
  Serve.__setPayload(cfg.payload);
  Serve.__setScript([cfg.refusalA, cfg.refusalA, cfg.refusalA]);
  await navisView.setVisible(true);
  // The visibility handler's boot resolves as a microtask chain; give it
  // its ticks so the mint gate reads the client (and the payload) settled.
  await sleep(75);
  await state.commands.get("refdes.navisMint")();
  snapshot("locked");

  // The index repaint: a document save runs scheduleRefresh -> refreshIndex
  // -> updateStatusBar, the repaint that erases the lock face today. The
  // text already carries the lock while locked, so the repaint is forced
  // with the refreshIndex command (the same path a save's 250 ms timer
  // fires) and the wait is on the TOOLTIP leaving the lock's value --
  // GREEN lands on the repaint's own 25 ms poll, RED on the 15 s deadline.
  await state.commands.get("refdes.refreshIndex")();
  const t0 = Date.now();
  while (Date.now() - t0 < cfg.repaintDeadline) {
    await sleep(25);
    if (indexItem().tooltip !== cfg.refusalA.body.error) break;
  }
  snapshot("repaint");

  // A NEW serve boot runs the shipped lock reset: deactivate() is the
  // shipped stopServe (serve -> null, the client killed) AND disposes the
  // tree view -- the fake's createTreeView is a getter, so re-disabling
  // then re-enabling the host view hands activate a fresh navisView. The
  // visibility gesture re-boots (startServe -- the site of the reset at
  // l.396). The scripted GET 404s while the payload is disarmed, so the
  // mint gate reads "no server": the lock is gone and paints nothing --
  // the index face stands alone.
  ext.deactivate();
  while (Date.now() < cfg.drainDeadline) await sleep(25);
  vscode.window.createTreeView = () => makeNavisView();
  Serve.__setBootMode("ok");
  Serve.__setPayload(null);
  Serve.__setScript([]);
  await navisView.setVisible(true);
  await state.commands.get("refdes.navisMint")();
  snapshot("resetByBoot");

  // Re-lock: the payload re-arms (the tree re-reads the keyless row, the
  // mint gate offers), and the mint refusal -- the SECOND refusal text --
  // writes the lock face again.
  Serve.__setPayload(cfg.payload);
  Serve.__setScript([cfg.refusalB, cfg.mintOk, cfg.mintOk]);
  await state.commands.get("refdes.navisMint")();
  snapshot("locked2");

  // The unlocked face: the reset (above) erased the lock, the repaint
  // paints the plain index face, and the mint gate says "no server" (the
  // boot above died -- the client is null): the remembered refusal paints
  // nothing once the lock is gone.
  await state.commands.get("refdes.refreshIndex")();
  await state.commands.get("refdes.navisMint")();
  snapshot("unlocked");
}

main()
  .then(() => {
    finish({ out, popups: state.popups, errors: state.errors, output: state.output });
  })
  .catch((err) => {
    finish({ fatal: String((err && err.stack) || err), output: state.output });
  });

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

SERVE_STUB = r"""
"use strict";
// A faked ./serveClient for the extension's own construction sites.
// __setBootMode picks the next boot's story -- "ok" (start() resolves true,
// the client becomes ready) or "fail" (resolves false: the shipped
// startServe failure path, output log + Retry modal, which the fake host
// never presses). __setPayload is the GET /api/navis answer (null -> 404,
// the tree's own "server-died" placeholder); __setScript sets the POST
// answers for the next phase (one entry per POST, the last one repeats).
// Every answer resolves as a microtask -- the real client's socket latency
// stands in: no shipped caller resumes its await before finishing its
// synchronous state setup, so a stub that resolves synchronously would
// race the extension's own null guards (a real launch takes a second).
let script = [];
let mode = "fail";
let payload = null;

// A POST answer is a microtask away (the real client's socket latency
// stands in): every shipped POST caller finishes its synchronous state
// setup before the await resumes, so no guard can race the resume.
function answer() {
  if (script.length === 0) {
    // A POST with no scripted answer: a call the extension's own gates must
    // make impossible. Surfaced as the client's "not recognised" popup so a
    // pin sees it, never as a silent 200.
    return Promise.resolve({ status: 599, body: { kind: "unreachable_fake" } });
  }
  const next = script.length === 1 ? script[0] : script.shift();
  return Promise.resolve(next);
}

class ServeClient {
  constructor() {
    this.ready = false;
    this.attached = false;
  }
  async start() {
    if (mode === "fail") return false;
    this.ready = true;
    return true;
  }
  kill() {
    this.ready = false;
  }
  async revision() {
    return { status: 0, error: "fake: no snapshot" };
  }
  async item() {
    return { status: 0, error: "fake: no item" };
  }
  deepLink() {
    return null;
  }
  navis() {
    if (payload === null) {
      return Promise.resolve({ status: 404, body: { kind: "no_payload" } });
    }
    return Promise.resolve({ status: 200, body: payload });
  }
  navisArchive() {
    return answer();
  }
  navisRestore() {
    return answer();
  }
  navisMint() {
    return answer();
  }
  static attach() {
    return null;
  }
}

function parseLaunchUrl() {
  return null;
}

module.exports = {
  ServeClient,
  parseLaunchUrl,
  __setScript: (entries) => {
    script = entries;
  },
  __setBootMode: (value) => {
    mode = value;
  },
  __setPayload: (value) => {
    payload = value;
  },
};
"""

INDEX_SCRIPT = (
    "import sys\n"
    "if sys.argv[1:3] == ['index', '--compact']:\n"
    "    sys.stdout.write(open(sys.argv[3], encoding='utf-8').read())\n"
    "else:\n"
    "    sys.exit(1)\n"
)


def run_extension(tmp_path) -> dict:
    (tmp_path / "refdes-project.yaml").write_text(
        "site: _site\n", encoding="utf-8", newline=""
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "a.md").write_text(
        "id: NOTE-0001\ntitle: Alpha\n", encoding="utf-8", newline=""
    )
    (tmp_path / "index.json").write_text(
        json.dumps(INDEX_DATA), encoding="utf-8", newline=""
    )
    (tmp_path / "refdes").write_text(INDEX_SCRIPT, encoding="utf-8", newline="")
    (tmp_path / "serveClient.js").write_text(SERVE_STUB, encoding="utf-8", newline="")
    script = tmp_path / "lock-tooltip-driver.js"
    script.write_text(DRIVER, encoding="utf-8", newline="")

    cfg = {
        "ext": EXTENSION_JS,
        "extDir": VSCODE_DIR,
        "serveModule": str(tmp_path / "serveClient.js"),
        "command": (
            f'"{sys.executable}" "{tmp_path / "refdes"}" '
            f'index --compact "{tmp_path / "index.json"}" '
            f'--config "{tmp_path / "refdes-project.yaml"}"'
        ),
        "root": str(tmp_path),
        "docPath": str(tmp_path / "items" / "a.md"),
        "payload": PAYLOAD,
        "refusalA": REFUSAL_A,
        "refusalB": REFUSAL_B,
        "repaintDeadline": 15000,
        "drainDeadline": int(time.time() * 1000) + 300,
    }
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner decodes with cp1252 and would
        # mojibake the middle dot in the index tooltip (the posture of
        # tests/test_editor_live_calc.py's harness).
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (
        f"node driver exited {proc.returncode}: stdout={proc.stdout[-2000:]!r} "
        f"stderr={proc.stderr[-2000:]!r}"
    )
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"node driver printed no JSON: stdout={proc.stdout[-2000:]!r} "
            f"stderr={proc.stderr[-2000:]!r}"
        )
    assert "fatal" not in result, result["fatal"]
    assert result["errors"] == [], result["errors"]
    return result


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to run the extension")
    tmp = tmp_path_factory.mktemp("navis-lock-tooltip")
    return run_extension(tmp)["out"]


def test_locked_before_the_repaint_the_tooltip_names_no_write(snapshots):
    """The starting state: the refusal's own write put the lock text AND the
    refusal sentence naming --no-write on the shared item, plain strings."""
    locked = snapshots["locked"]
    assert locked["text"] == LOCK_TEXT, locked
    assert locked["tooltip"] == REFUSAL_A["body"]["error"], locked
    assert locked["tooltipType"] == "string", locked


def test_the_index_repaint_keeps_the_no_write_tooltip(snapshots):
    """The fix: the repaint re-applies the WHOLE lock face -- the text (the
    shipped S6.2b-2 behaviour) AND the tooltip (plan §4: the tooltip names
    --no-write) -- the index repaint's own plain-string tooltip must not
    stand over the lock's."""
    repaint = snapshots["repaint"]
    assert repaint["text"] == LOCK_TEXT, repaint
    assert repaint["tooltip"] == REFUSAL_A["body"]["error"], repaint
    assert repaint["tooltipType"] == "string", repaint


def test_a_second_refusal_refreshes_the_remembered_tooltip(snapshots):
    """A lock re-named by a later refusal (the mint refusal on a fresh
    boot): the remembered tooltip is the LAST refusal's text -- the mint
    refusal naming --no-write too."""
    locked2 = snapshots["locked2"]
    assert locked2["text"] == LOCK_TEXT, locked2
    assert locked2["tooltip"] == REFUSAL_B["body"]["error"], locked2
    assert locked2["tooltipType"] == "string", locked2


def test_the_boot_reset_erases_the_lock_face(snapshots):
    """The shipped lock reset (a new serve boot) erases the lock: the mint
    gate says "no server" (the GET 404s, the tree reads server-died) and
    the index face stands alone -- the remembered refusal paints nothing
    once the lock is gone."""
    reset = snapshots["resetByBoot"]
    assert reset["text"] == "$(error) Refdes 1", reset
    assert reset["tooltip"] == INDEX_TOOLTIP, reset
    unlocked = snapshots["unlocked"]
    assert unlocked["text"] == "$(error) Refdes 1", unlocked
    assert unlocked["tooltip"] == INDEX_TOOLTIP, unlocked
    assert "--no-write" not in str(after["tooltip"]), after
