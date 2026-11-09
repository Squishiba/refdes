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
every navis POST with a scripted answer. The lock phases run through the
SHIPPED wiring: a fresh activation's visibility gesture boots serve A,
``refdes.navisArchive`` posts the scripted keyless row's refusal (boot A
locks), the index repaint runs, a fresh activation boots serve B --
``startServe`` runs the shipped lock reset -- and the repaint after it
shows the plain index face; a second refusal (boot B) then re-names the
lock. node missing -> skip, as the neighbours do.

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

# The scenario's payloads: one keyless row (the mint offers it -- the
# archive on it would be disabled) and one keyed row (archive/restore act
# on it). Phase A locks with the MINT refusal (POST on the keyless row);
# the second refusal -- phase B's ARCHIVE on the keyed row -- carries the
# mint's --no-write sentence, a DIFFERENT text: the remembered tooltip is
# the LAST refusal's.

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

# One keyless row (the mint offers it -- the archive on it would be
# disabled) and one keyed row (archive/restore act on it): phase A locks
# with the MINT refusal, phase B re-locks with the ARCHIVE refusal -- the
# second refusal text.
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
KEYED_ROW = {
    "key": "abcd1200000e",
    "key6": "abcd12",
    "text": "Beta note.",
    "item": "NOTE-0002",
    "href": "note-002.html",
    "file": "items/b.md",
    "line": 2,
    "archived": False,
    "changed": False,
    "orphan": False,
}
PAYLOAD = {"navis": [ROW, KEYED_ROW], "counts": {"active": 2, "archived": 0}}


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

// The index item: each activation creates a fresh pair (index item first,
// serve item second -- the order of activate's own lines). `itemBase` marks
// where the CURRENT activation's items start; the driver bumps it when it
// re-activates the extension.
let itemBase = 0;
function indexItem() {
  return state.statusItems[itemBase];
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

// The stub resolves every answer as a microtask (the real client's socket
// latency), so a phase is settled once the extension's own await chain has
// drained: one real timer turn (macrotask) runs after every pending
// microtask, which is where each command's render/setStatus lands.
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function settle() {
  await sleep(0);
  await sleep(0);
}

// The badge is the extension's own marker of a landed navis payload
// (setNavisBadge runs right after the GET 200 stores it; every placeholder
// erases it). The payload's active count, pinned.
async function treeReadsPayload() {
  while (!state.navisView || (state.navisView.badge || {}).value !== 2) await settle();
}

async function main() {
  // The fake's host subscriptions: deactivate() disposes them (stopping the
  // extension's tree-view listeners), and the driver re-arms them for the
  // next activation -- a host view can be re-created, a dead window can't.
  const subscriptions = [];
  const context = {
    subscriptions,
    asAbsolutePath: (p) => path.join(cfg.extDir, p),
  };
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
  // The visibility handler's boot and tree read resolve as microtask
  // chains (the stub's answers too); setVisible has already run them, and
  // real-timer turns drain everything the shipped code chains onto them --
  // the mint gate reads the ready client and the badge marks the landed
  // payload it posts against.
  await settle();
  await treeReadsPayload();
  await state.commands.get("refdes.navisMint")();
  snapshot("locked");

  // The index repaint: a document save runs scheduleRefresh -> refreshIndex
  // -> updateStatusBar, the repaint that erases the lock face today. The
  // text already carries the lock while locked, so the repaint is forced
  // with the refreshIndex command (the same path a save's 250 ms timer
  // fires) and settles -- GREEN lands on the repaint's own value, RED on
  // the stub's untouched index tooltip.
  await state.commands.get("refdes.refreshIndex")();
  await settle();
  snapshot("repaint");

  // The shipped stopServe + a fresh activation: the shared status item
  // carries the LOCKED face across the session boundary. The visibility
  // gesture boots (startServe -- the site of the reset at the l.396 call)
  // with the payload disarmed, landing on the shipped dead-server path;
  // the forced repaint below runs updateStatusBar -> applyNavisLockStatus
  // against the erased lock: the index face stands, the remembered
  // refusal paints nothing. (No mint here: any POST's refusal answer
  // would re-lock the fresh session -- the shipped lock mechanics.)
  ext.deactivate();
  while (Date.now() < cfg.drainDeadline) await sleep(25);
  subscriptions.length = 0;
  itemBase = state.statusItems.length;
  await ext.activate(context);
  Serve.__setBootMode("ok");
  Serve.__setPayload(null);
  Serve.__setScript([]);
  await navisView.setVisible(true);
  // The visibility handler's boot resolves as a microtask chain; the
  // real-timer turns drain it -- the shipped dead-server path (the payload
  // is disarmed) lands.
  await settle();
  await state.commands.get("refdes.refreshIndex")();
  await settle();
  snapshot("resetByBoot");

  // The second refusal, on a fresh session: the payload re-arms (the tree
  // re-reads the rows) and ARCHIVING the keyed row (navisTree.navis* are
  // the tree's own renderers -- rowForItem's exact match) posts the
  // ARCHIVE refusal -- the mint refusal on this payload, the SECOND
  // refusal text -- writing the lock face with it: the remembered tooltip
  // is the LAST refusal's text. (A mint on a locked session short-circuits
  // with the lock's warning and never POSTs, so the second refusal comes
  // from a row action.)
  Serve.__setPayload(cfg.payload);
  Serve.__setScript([cfg.refusalB]);
  // The archive gate and the POST's row selector read the tree's rows --
  // the tree's own refresh (the visibility handler, boot=false: no re-boot)
  // carries the re-armed payload in, and the badge poll proves the GET 200
  // landed in the extension before the archive.
  state.navisView.badge = undefined;
  await navisView.setVisible(true);
  await treeReadsPayload();
  const keyed = cfg.keyedRow;
  await state.commands.get("refdes.navisArchive")({
    label: `${keyed.key6} · ${keyed.text}`,
    description: "",
    tooltip: keyed.text,
    contextValue: "refdesNavi",
  });
  await settle();
  snapshot("locked2");
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
        "keyedRow": KEYED_ROW,
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
    """A lock re-named by a later refusal (the mint refusal on the second
    boot, posted through the shipped archive wiring): the remembered
    tooltip is the LAST refusal's text -- the mint refusal naming
    --no-write too."""
    locked2 = snapshots["locked2"]
    assert locked2["text"] == LOCK_TEXT, locked2
    assert locked2["tooltip"] == REFUSAL_B["body"]["error"], locked2
    assert locked2["tooltipType"] == "string", locked2


def test_the_boot_reset_erases_the_lock_face(snapshots):
    """The shipped lock reset (a new serve boot -- startServe's reset site)
    erases the lock: the repaint after the new boot shows the normal index
    face, text and tooltip -- the remembered refusal paints nothing once
    the lock is gone."""
    reset = snapshots["resetByBoot"]
    assert reset["text"] == "$(error) Refdes 1", reset
    assert reset["tooltip"] == INDEX_TOOLTIP, reset
    assert reset["tooltipType"] == "string", reset
