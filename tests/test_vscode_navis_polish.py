"""N6.3-tests: red-first contract tests for slice S6.3 (freshness polish and
secondary actions) of docs/design/navis-vscode-panel-plan.md, plus the two
items the S6.2b-2 review deferred into it (the lock text surviving an index
refresh, and the Mint log line). This file writes NO module; THE IMPLEMENTER
BUILDS what is pinned here.

S6.3 adds five things, each pinned by a section below:

(1) ``refdes.refreshNavis`` ("Refdes: Refresh Navis") -- contributed with that
    exact title, VISIBLE in the command palette (no ``commandPalette`` when
    clause hides it -- the refdes.openInEditor pattern inverted: this one has
    NO entry, and absence is what visibility is), and registered in
    extension.js as the existing refresh path with boot=true semantics
    (``() => refreshNavisTree(true)``): on success it shows nothing, with no
    server it lands on the existing placeholder (both are refreshNavisTree's
    shipped behavior -- pinned here as the body's ensureServe/showNavisPlaceholder
    calls, which S6.1 shipped).

(2) The "Mint keys (N)" row at the TOP of the tree. THE IMPLEMENTER FOLLOWS
    THESE NAMES (decided here, the smallest shape that keeps the S6.1 pins
    green -- ``childrenFor(payload, root)`` must NOT grow the row by default,
    the shipped tree tests pin its exact length, so the row is a separate
    factory the wiring prepends):
      createNavisTree(vscode).mintRow(payload, state) -> TreeItem | null
        null when navisActions.mintAvailable(payload, state).enabled is false
        (count 0 -- and a locked session, whose mintAvailable is disabled);
        else a TreeItem whose:
          label         === mintAvailable(...).label  ("Mint keys (N)" pill)
          tooltip       === mintAvailable(...).tooltip (the shipped sentence)
          contextValue  === "refdesNaviMint"  (a word NO view/item/context
                          when-clause matches -- the tree's row regexes are
                          word-bounded /(^| )refdesNavi( |$)/ and
                          /refdesNaviArchived|Keyless/, none of which matches
                          the single word "refdesNaviMint" -- pinned by the
                          visibility table below)
          command       === { command: "refdes.navisMint" }  (NO arguments:
                          mint is project-wide)
          plain strings only (plan S6): never a MarkdownString; the label and
          tooltip are mintAvailable's composed count sentences -- NO row text
          (hostile row text must not reach the pill).
        The row is counted in NO badge: badgeFor(payload) stays
        payload.counts.active (the pin below).

(3) The read-only indicator surviving index refreshes (DEFERRED ITEM ONE from
    the S6.2b-2 review). Today setNavisWriteStatus writes
    ``$(lock) Refdes: read-only`` into the SHARED index status item and the
    next refreshIndex repaint (its statusBar.text = line) erases it. Chosen
    mechanism (smallest honest one, stated for the record): RE-APPLY IN THE
    REFRESH PATH, not a dedicated item -- a dedicated item is a second
    permanent piece of chrome for a transient state, and the plan's §2 inventory
    counts exactly two status-bar items. Pinned in extension.js:
      - setNavisWriteStatus keeps writing the LOCK text verbatim;
      - a helper ``applyNavisLockStatus()`` re-applies the LOCK text onto the
        shared item, and ONLY while navisWriteLock.locked() (the lock is the
        single source of truth, not a remembered string);
      - ``updateStatusBar()`` (the index status repaint that refreshIndex
        runs on every refresh -- the writer that overwrites the line) calls
        the helper at the END of its repaint (after statusBar.show());
      - the lock's .reset() (new serve / attach -- S6.2b's shipped resets) is
        what clears it: once unlocked the helper paints nothing.

(4) The secondary row action "Open in editor": ``refdes.navisOpenInEditor``,
    an INLINE view/item/context entry gated to keyed rows, handled in
    navisCommands.js (the node-testable layer) by
      createNavisCommands(deps).openInEditor(item)
    with deps GROWN by exactly two injected names:
      openExternal(uri) -> thenable  (wired to vscode.env.openExternal)
      deepLink(key) -> uri string | null (wired to ServeClient.deepLink --
                     the shipped V0 deep link, plan S5)
    Handler order pinned (the conservative one, matching the archive/restore
    handlers, which check the server BEFORE consulting the row):
      1. no client or !client.ready -> showWarningMessage ServeClient's own
         "refdes serve is not running", no calls (pinned to precede the
         keyless refusal by the no-client + keyless-row scenario).
      2. recover the row the SAME way archive/restore do (rowForItem against
         getRows() -- the item carries no row field) and take selectorFor(row)
         (the FULL key); no row / keyless row -> ONE showInformationMessage
         naming the missing key, NO deepLink, NO openExternal.
      3. openExternal(deepLink(key)) -- ONE deepLink call with the row's FULL
         key (never key6, never a prefix), openExternal receives EXACTLY the
         value deepLink returned (opaque passthrough -- the handler never
         composes a URL, never names http/127.0.0.1/token: source-pinned).
      4. a handler NEVER throws: a throwing deepLink lands on
         showErrorMessage with a plain string, openExternal untouched.

(5) The Mint log line (DEFERRED ITEM TWO): after a SUCCESSFUL mint (plan S4's
    refresh decision), the mint handler logs EXACTLY ONE line through the
    injected ``log`` dep naming how many keys were minted (the 200's
    ``minted`` list length) and that open editors of those files reload from
    disk (dirty buffers show VS Code's own external-change prompt -- plan
    S11.1 / checklist 4). Pinned LOOSELY on content as the task rules: the
    count and the word "reload". No log line on any failure path (lock,
    transport, dismiss).

RED-FIRST: on the branch base (main, with N6.2b-2 merged as the task states --
this branch's base is main, where navisCommands.js is absent outright) every
test here is red today: the node drivers die on the missing module / the
missing ``mintRow`` export (fatal JSON), and the package.json/extension.js
pins fail on strings that do not exist yet.

GREEN-PROOF OVERRIDES (reference implementations only, nothing in this file
reads them by default): REFDES_NAVIS_COMMANDS_JS, REFDES_NAVIS_TREE_JS,
REFDES_VSCODE_PACKAGE_JSON, REFDES_VSCODE_EXTENSION_JS.

NO REAL VS CODE WINDOW exists in CI: tree-item rendering, real menus/when
clauses, the status bar and vscode.env.openExternal are pinned at LOGIC and
JSON level only (plan S7.2 "Cannot prove: any VS Code UI behavior" -- Jared's
manual checklist covers the window, plan S8: "Acceptance: checklist 1-6
re-pass").

Cross-platform (tests/test_crossplatform_lint.py): node subprocesses read
with ``encoding="utf-8"`` (a Windows runner's cp1252 locale would mojibake
the non-ASCII row texts), drivers written with ``newline=""``, bounded by
NODE_TIMEOUT_S; no servers (the client is faked -- the wire contract is
tests/test_vscode_extension_http_client.py's), no path-separator assertions,
no POSIX-only tools.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_DIR = os.path.join(REPO_ROOT, "editors", "vscode")
PACKAGE_JSON = os.environ.get(
    "REFDES_VSCODE_PACKAGE_JSON", os.path.join(VSCODE_DIR, "package.json")
)
EXTENSION_JS = os.environ.get(
    "REFDES_VSCODE_EXTENSION_JS", os.path.join(VSCODE_DIR, "extension.js")
)
NAVIS_ACTIONS_JS = os.path.join(VSCODE_DIR, "navisActions.js")
NAVIS_TREE_JS = os.environ.get(
    "REFDES_NAVIS_TREE_JS", os.path.join(VSCODE_DIR, "navisTree.js")
)
NAVIS_COMMANDS_JS = os.environ.get(
    "REFDES_NAVIS_COMMANDS_JS", os.path.join(VSCODE_DIR, "navisCommands.js")
)

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to execute the navis modules"
)

VIEW_ID = "refdes.navisTree"

# The shipped strings the new surface must reuse (navisActions.js /
# serveClient.js -- pinned equal by the neighbour files, restated here).
NOT_RUNNING = "refdes serve is not running"
MINT_CONTEXT = "refdesNaviMint"
LOCK_TEXT = "$(lock) Refdes: read-only"

# The command ids S6.3 contributes.
REFRESH_ID = "refdes.refreshNavis"
OPEN_ID = "refdes.navisOpenInEditor"


def _read(path: str) -> str:
    if not os.path.exists(path):
        pytest.fail(
            f"{path} does not exist -- S6.3 has not landed, and this pin "
            "exists to catch it drifting afterwards"
        )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_body(source: str, marker: str) -> str:
    """The brace-balanced body after `marker` (the neighbour's posture: a
    lazy `.*?\\}` would stop at the first nested block)."""
    start = source.find(marker)
    assert start != -1, f"the source no longer contains {marker!r}"
    i = start + len(marker)
    depth = 1
    while depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[start + len(marker) : i - 1]


# ---------------------------------------------------------------- fixtures


def _row(key: str, text: str, *, file: str, line: int, archived=False, orphan=False) -> dict:
    return {
        "key": key,
        "key6": key[:6],
        "text": text,
        "item": "NOTE-001",
        "href": "note-001.html",
        "file": file,
        "line": line,
        "archived": archived,
        "changed": False,
        "orphan": orphan,
    }


KEY_A = "abcd1200000e"
KEY_B = "abcd1211110"  # same key6 as KEY_A: the collision pair (first match)
KEY_C = "ffff1100006"
KEYLESS_TEXT = "A marker nobody minted."
KEYLESS2_TEXT = "A second marker, also unminted."
HOSTILE_MD = "[x](command:workbench.action.closeAllEditors) <script>alert(\"x\")</script>"

ROWS = {
    "keyedActive": _row(KEY_A, "Alpha model worst-case copper temperature.", file="items/note-a.md", line=6),
    "dupe": _row(KEY_B, "Alpha model worst-case copper temperature.", file="items/note-b.md", line=6),
    "keyedArchived": _row(KEY_C, "Beta recheck decoupling near U14.", file="items/note-d.md", line=8, archived=True),
    "keyless": _row("", KEYLESS_TEXT, file="items/note-c.md", line=7),
    "keyless2": _row("", KEYLESS2_TEXT, file="items/note-c.md", line=12),
    "archivedKeyless": _row("", "Gamma archived while keyless.", file="items/note-e.md", line=4, archived=True),
    "hostile": _row("", HOSTILE_MD, file="items/note-f.md", line=3),
}

# 4 active (keyedActive, dupe, keyless, keyless2) + 2 archived (keyedArchived,
# archivedKeyless); keyless rows among ALL rows: keyless, keyless2,
# archivedKeyless -> 3 (mintAvailable counts active AND archived).
PAYLOAD = {
    "navis": [
        ROWS["keyedActive"],
        ROWS["dupe"],
        ROWS["keyless"],
        ROWS["keyless2"],
        ROWS["keyedArchived"],
        ROWS["archivedKeyless"],
    ],
    "counts": {"active": 4, "archived": 2},
}
NO_KEYLESS_PAYLOAD = {
    "navis": [ROWS["keyedActive"], ROWS["keyedArchived"]],
    "counts": {"active": 1, "archived": 1},
}
HOSTILE_PAYLOAD = {
    "navis": [ROWS["hostile"]],
    "counts": {"active": 1, "archived": 0},
}

PILL_3 = "Mint keys (3)"
PILL_TOOLTIP_3 = "Mint keys for 3 unkeyed Navis"
LOCKED_TOOLTIP = (
    "This server runs with --no-write: writes are disabled for this session"
)

# Scripted POST results (the {status, body} shapes of the navis routes; the
# plan S4 table itself is pinned by tests/test_vscode_navis_actions.py).
MINT200_3 = {
    "status": 200,
    "body": {
        "kind": "ok",
        "changed": True,
        "minted": [
            {"key": "5kk2m4ppqrs", "key6": "5kk2m4", "item": "NOTE-003", "file": "items/note-c.md"},
            {"key": "6kk2m4ppqrs", "key6": "6kk2m4", "item": "NOTE-004", "file": "items/note-c.md"},
            {"key": "7kk2m4ppqrs", "key6": "7kk2m4", "item": "NOTE-005", "file": "items/note-f.md"},
        ],
        "still_keyless": 0,
    },
}
MINT200_1 = {
    "status": 200,
    "body": {
        "kind": "ok",
        "changed": True,
        "minted": [{"key": "5kk2m4ppqrs", "key6": "5kk2m4", "item": "NOTE-003", "file": "items/note-c.md"}],
        "still_keyless": 0,
    },
}
REFUSED = {
    "status": 403,
    "body": {
        "kind": "refused",
        "error": "this server was started with --no-write: navis mint is disabled",
    },
}

# Scenarios for the commands driver. open* pin (4); mintLog* pin (5). The
# deepLink dep answers with the sentinel `deeplink:<key>` and records its
# argument; openExternal records exactly what it receives.
SCENARIOS = [
    {"name": "openKeyed", "command": "openInEditor", "item": "keyedActive",
     "client": {"ready": True}},
    {"name": "openArchived", "command": "openInEditor", "item": "keyedArchived",
     "client": {"ready": True}},
    {"name": "openCollision", "command": "openInEditor", "item": "keyedActive",
     "client": {"ready": True}},  # PAYLOAD: KEY_A/KEY_B render identically
    {"name": "openKeyless", "command": "openInEditor", "item": "keyless",
     "client": {"ready": True}},
    {"name": "openForeign", "command": "openInEditor", "item": "foreign",
     "client": {"ready": True}},
    {"name": "openNullArg", "command": "openInEditor", "item": "null",
     "client": {"ready": True}},
    {"name": "openNoClient", "command": "openInEditor", "item": "keyedActive",
     "client": None},
    {"name": "openNotReady", "command": "openInEditor", "item": "keyedActive",
     "client": {"ready": False}},
    {"name": "openKeylessNoClient", "command": "openInEditor", "item": "keyless",
     "client": None},  # the server refusal PRECEDES the keyless refusal
    {"name": "openDeepLinkThrows", "command": "openInEditor", "item": "keyedActive",
     "client": {"ready": True}, "deepLinkThrows": True},
    {"name": "openPayloadNull", "command": "openInEditor", "item": "keyedActive",
     "payload": "null", "client": {"ready": True}},
    {"name": "mintLog3", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200_3}},
    {"name": "mintLog1", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200_1}},
    {"name": "mintLogDismiss", "command": "mint", "mintChoice": "dismiss",
     "client": {"result": MINT200_3}},
    {"name": "mintLog403", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": REFUSED}},
    {"name": "mintLogRejects", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200_3, "reject": True}},
]


# ---------------------------------------------------------------- drivers


TREE_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
const out = {};

let navisTree, navisActions;
try {
  navisTree = require(cfg.treeModule);
  navisActions = require(cfg.actionsModule);
} catch (err) {
  require("fs").writeSync(1, JSON.stringify({fatal: String((err && err.stack) || err)}));
  process.exit(0);
}

const vscode = {
  TreeItem: class {
    constructor(label, collapsibleState) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  },
  TreeItemCollapsibleState: {None: 0, Collapsed: 1, Expanded: 2},
  Uri: {file: (f) => ({scheme: "file", fsPath: f})},
  MarkdownString: class {
    constructor(value) { this.value = value; }
  },
};

const tree = navisTree.createNavisTree(vscode);
if (typeof tree.mintRow !== "function") {
  require("fs").writeSync(1, JSON.stringify({
    fatal: "createNavisTree(vscode).mintRow is not a function -- S6.3 (2) has not landed",
  }));
  process.exit(0);
}

function plainify(item) {
  if (item === null || item === undefined) return null;
  return {
    label: item.label,
    labelType: typeof item.label,
    labelIsMarkdown: item.label instanceof vscode.MarkdownString,
    tooltip: item.tooltip === undefined ? null : item.tooltip,
    tooltipType: typeof item.tooltip,
    tooltipIsMarkdown: item.tooltip instanceof vscode.MarkdownString,
    contextValue: item.contextValue === undefined ? null : item.contextValue,
    command: item.command === undefined ? null : item.command,
  };
}

for (const sc of cfg.scenarios) {
  const payload = cfg.payloads[sc.payload];
  const res = {};
  const item = tree.mintRow(payload, sc.state);
  res.item = plainify(item);
  res.availability = navisActions.mintAvailable(payload, sc.state);
  res.badge = tree.badgeFor(payload);
  out[sc.name] = res;
}

require("fs").writeSync(1, JSON.stringify(out));
"""


COMMANDS_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
const out = {scenarios: {}};

let mod, navisTree, navisActions;
try {
  mod = require(cfg.commandsModule);
  navisTree = require(cfg.treeModule);
  navisActions = require(cfg.actionsModule);
} catch (err) {
  require("fs").writeSync(1, JSON.stringify({fatal: String((err && err.stack) || err)}));
  process.exit(0);
}

function makeVscode(sc, rec) {
  return {
    TreeItem: class {
      constructor(label, collapsibleState) {
        this.label = label;
        this.collapsibleState = collapsibleState;
      }
    },
    TreeItemCollapsibleState: {None: 0, Collapsed: 1, Expanded: 2},
    Uri: {file: (f) => ({scheme: "file", fsPath: f})},
    window: {
      showWarningMessage: (message, ...rest) => {
        const options = rest.find((x) => x && typeof x === "object");
        const buttons = rest.filter((x) => typeof x === "string");
        rec.push({fn: "warn", message: String(message), messageType: typeof message,
          modal: Boolean(options && options.modal === true), buttons});
        const chosen = options && options.modal === true
          && buttons.includes(sc.mintChoice) ? sc.mintChoice : undefined;
        return Promise.resolve(chosen);
      },
      showInformationMessage: (message) => {
        rec.push({fn: "info", message: String(message), messageType: typeof message});
        return Promise.resolve(undefined);
      },
      showErrorMessage: (message) => {
        rec.push({fn: "error", message: String(message), messageType: typeof message});
        return Promise.resolve(undefined);
      },
    },
  };
}

function makeClient(sc, rec) {
  if (!sc.client) return null;
  const spec = sc.client;
  const client = {ready: spec.ready !== false};
  for (const name of ["navisArchive", "navisRestore", "navisMint"]) {
    client[name] = async (selector) => {
      rec.push({fn: "call", method: name,
        selector: selector === undefined ? null : selector});
      if (spec.reject) {
        throw new Error("connect ECONNREFUSED 127.0.0.1:41235 (fake reject)");
      }
      return spec.result;
    };
  }
  return client;
}

async function runScenario(sc) {
  const rec = [];
  const vscode = makeVscode(sc, rec);
  const tree = navisTree.createNavisTree(vscode);
  const lock = navisActions.createWriteLock();
  const client = makeClient(sc, rec);
  const payload = sc.payload === "null" ? null : cfg.payload;
  const deepLinks = [];
  const cmds = mod.createNavisCommands({
    vscode,
    getClient: () => client,
    refreshTree: async () => { rec.push({fn: "refresh"}); },
    getRows: () => payload,
    lock,
    setStatus: (text) => { rec.push({fn: "setStatus", text: text === null ? null : String(text)}); },
    log: (line) => { rec.push({fn: "log", line: String(line)}); },
    deepLink: (key) => {
      const k = String(key);
      deepLinks.push(k);
      rec.push({fn: "deepLink", key: k});
      if (sc.deepLinkThrows) throw new Error("deep link exploded (fake)");
      return "deeplink:" + k;
    },
    openExternal: (uri) => {
      rec.push({fn: "openExternal", uri: typeof uri === "string" ? uri : JSON.stringify(uri),
        uriType: typeof uri});
      return Promise.resolve(true);
    },
  });
  let item;
  if (sc.item === "foreign") item = tree.placeholderFor("no-navis");
  else if (sc.item && sc.item !== "null") item = tree.itemForRow(cfg.rows[sc.item], cfg.root);
  const handler = cmds[sc.command];
  let threw = null;
  const before = rec.length;
  try {
    await handler(item);
  } catch (err) {
    threw = String((err && err.stack) || err);
  }
  return {rec: rec.slice(before), deepLinks, threw,
    handlerType: typeof handler, api: Object.keys(cmds).sort()};
}

(async () => {
  for (const sc of cfg.scenarios) {
    try {
      out.scenarios[sc.name] = await runScenario(sc);
    } catch (err) {
      out.scenarios[sc.name] = {fatal: String((err && err.stack) || err)};
    }
  }
  require("fs").writeSync(1, JSON.stringify(out));
})().catch((err) => {
  require("fs").writeSync(1, JSON.stringify({fatal: String((err && err.stack) || err)}));
  process.exit(0);
});
"""


def _run_node(tmp_path, driver: str, cfg: dict) -> dict:
    script = tmp_path / "navis-polish-driver.js"
    script.write_text(driver, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the non-ASCII row texts on the way back in (the posture of
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
        out = json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"node driver printed no JSON: stdout={proc.stdout[-2000:]!r} "
            f"stderr={proc.stderr[-2000:]!r}"
        )
    assert "fatal" not in out, out["fatal"]
    return out


@pytest.fixture(scope="module")
def tree_cases(tmp_path_factory) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to execute the tree module")
    tmp = tmp_path_factory.mktemp("navis-polish-tree")
    return _run_node(
        tmp,
        TREE_DRIVER,
        {
            "treeModule": NAVIS_TREE_JS,
            "actionsModule": NAVIS_ACTIONS_JS,
            "payloads": {
                "main": PAYLOAD,
                "keyed": NO_KEYLESS_PAYLOAD,
                "hostile": HOSTILE_PAYLOAD,
            },
            "scenarios": [
                {"name": "unlocked", "payload": "main", "state": {"writesLocked": False}},
                {"name": "locked", "payload": "main", "state": {"writesLocked": True}},
                {"name": "keyed", "payload": "keyed", "state": {"writesLocked": False}},
                {"name": "hostile", "payload": "hostile", "state": {"writesLocked": False}},
            ],
        },
    )


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to execute the commands module")
    tmp = tmp_path_factory.mktemp("navis-polish-commands")
    out = _run_node(
        tmp,
        COMMANDS_DRIVER,
        {
            "commandsModule": NAVIS_COMMANDS_JS,
            "treeModule": NAVIS_TREE_JS,
            "actionsModule": NAVIS_ACTIONS_JS,
            "rows": ROWS,
            "payload": PAYLOAD,
            "root": "D:/posix/root",
            "scenarios": SCENARIOS,
        },
    )
    got = out["scenarios"]
    for sc in SCENARIOS:
        assert sc["name"] in got, sc["name"]
        assert "fatal" not in got[sc["name"]], (sc["name"], got[sc["name"]]["fatal"])
    return got


def seq(sc: dict) -> list:
    return [entry["fn"] for entry in sc["rec"]]


def first(sc: dict, fn: str) -> dict:
    hits = [e for e in sc["rec"] if e["fn"] == fn]
    assert hits, (fn, sc["rec"])
    return hits[0]


def count(sc: dict, fn: str) -> int:
    return sum(1 for e in sc["rec"] if e["fn"] == fn)


# ------------------------------------------- (2) the Mint keys row (node)


@skip_no_node
def test_mint_row_is_the_pill_with_the_mint_command(tree_cases):
    """The Mint row: label is mintAvailable's EXACT pill text, tooltip its
    tooltip, command refdes.navisMint with no arguments (mint is
    project-wide), contextValue the distinct word refdesNaviMint."""
    s = tree_cases["unlocked"]
    item = s["item"]
    assert item is not None, s
    assert s["availability"]["count"] == 3, s["availability"]
    assert item["label"] == PILL_3 == s["availability"]["label"], item
    assert item["tooltip"] == PILL_TOOLTIP_3 == s["availability"]["tooltip"], item
    assert item["command"] == {"command": "refdes.navisMint"}, item
    assert item["contextValue"] == MINT_CONTEXT, item
    assert s["availability"]["enabled"] is True, s["availability"]


@skip_no_node
def test_mint_row_strings_are_plain_and_free_of_row_text(tree_cases):
    """Plan S6: every string is plain (never a MarkdownString). The pill is a
    COUNT sentence -- hostile row text must not reach the label/tooltip, and
    nothing names the token."""
    hostile = tree_cases["hostile"]["item"]
    assert hostile is not None, tree_cases["hostile"]
    assert hostile["labelType"] == "string", hostile
    assert hostile["tooltipType"] == "string", hostile
    assert not hostile["labelIsMarkdown"] and not hostile["tooltipIsMarkdown"]
    assert HOSTILE_MD not in hostile["label"]
    assert HOSTILE_MD not in hostile["tooltip"]
    blob = json.dumps(tree_cases)
    assert "X-Refdes-Token" not in blob
    assert "token=" not in blob
    # plain strings on the ordinary pill too
    item = tree_cases["unlocked"]["item"]
    for key in ("label", "tooltip", "contextValue"):
        assert isinstance(item[key], str), (key, item[key])


@skip_no_node
def test_mint_row_absent_when_count_is_zero(tree_cases):
    """count 0 (every row keyed) -> NO Mint row: mintRow returns null, the
    pill's availability is disabled with the shipped nothing-to-mint tooltip."""
    s = tree_cases["keyed"]
    assert s["item"] is None, s
    assert s["availability"]["count"] == 0, s["availability"]
    assert s["availability"]["enabled"] is False, s["availability"]
    assert s["availability"]["tooltip"] == "No keyless Navis to mint", s["availability"]


@skip_no_node
def test_mint_row_absent_when_locked(tree_cases):
    """A locked session (--no-write, seen as a 403): mintAvailable is
    disabled with the locked reason -> NO Mint row."""
    s = tree_cases["locked"]
    assert s["item"] is None, s
    assert s["availability"]["enabled"] is False, s["availability"]
    assert s["availability"]["tooltip"] == LOCKED_TOOLTIP, s["availability"]


@skip_no_node
def test_mint_row_is_counted_in_no_badge(tree_cases):
    """The view badge is payload.counts.active -- with the 3-keyless payload
    (badge 4, pill "Mint keys (3)") the badge must be the ACTIVE count, not
    the mint count, and unchanged by the Mint row's existence."""
    s = tree_cases["unlocked"]
    assert s["badge"] == PAYLOAD["counts"]["active"] == 4, s
    assert s["badge"] != 3  # the pill counts keyless rows, the badge does not
    assert tree_cases["locked"]["badge"] == 4, tree_cases["locked"]


# ---------------------------------- (4) Open in editor, the node handler


@skip_no_node
def test_open_in_editor_exports_the_fourth_handler(scenarios):
    """createNavisCommands grows exactly one handler: openInEditor, alongside
    the three S6.2b commands; the require succeeded under bare node, so the
    module imports no vscode (the purity posture)."""
    s = scenarios["openKeyed"]
    assert s["api"] == ["archive", "mint", "openInEditor", "restore"], s["api"]
    assert s["handlerType"] == "function", s


@skip_no_node
def test_open_in_editor_opens_the_deep_link_with_the_full_key(scenarios):
    """A keyed row (active AND archived): ONE deepLink call with the row's
    FULL key (never key6, never a prefix), and openExternal receives EXACTLY
    the value deepLink returned (opaque passthrough -- the handler composes
    no URL). No tree refresh, no message."""
    for name, key in (("openKeyed", KEY_A), ("openArchived", KEY_C)):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert seq(s) == ["deepLink", "openExternal"], (name, s["rec"])
        assert first(s, "deepLink")["key"] == key, (name, s["rec"])
        assert first(s, "openExternal")["uri"] == f"deeplink:{key}", (name, s["rec"])
        assert count(s, "warn") == 0 and count(s, "info") == 0, (name, s["rec"])


@skip_no_node
def test_open_in_editor_collision_takes_the_first_rows_full_key(scenarios):
    """KEY_A/KEY_B render IDENTICALLY (same key6, same text): the row
    recovery is rowForItem's FIRST match -- the same function archive/restore
    use -- and the deep link names that row's full key."""
    s = scenarios["openCollision"]
    assert first(s, "deepLink")["key"] == KEY_A, s["rec"]


@skip_no_node
def test_open_in_editor_keyless_row_refuses_with_information(scenarios):
    """A keyless row has no key to deep-link: ONE showInformationMessage
    naming the missing key, and NO deepLink, NO openExternal."""
    s = scenarios["openKeyless"]
    assert s["threw"] is None, s["threw"]
    assert seq(s) == ["info"], s["rec"]
    info = first(s, "info")
    assert info["messageType"] == "string", info
    assert "key" in info["message"].lower(), info
    assert count(s, "deepLink") == 0 and count(s, "openExternal") == 0, s["rec"]


@skip_no_node
def test_open_in_editor_refuses_items_that_are_not_rows(scenarios):
    """A placeholder item, a null arg (palette invocation) and a null payload
    all resolve to no row (rowForItem's rule) -> the keyless-style
    information refusal, no calls."""
    for name in ("openForeign", "openNullArg", "openPayloadNull"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert seq(s) == ["info"], (name, s["rec"])
        assert "key" in first(s, "info")["message"].lower(), (name, s["rec"])
        assert count(s, "deepLink") == 0 and count(s, "openExternal") == 0, (name, s["rec"])


@skip_no_node
def test_open_in_editor_not_running_is_the_existing_warning(scenarios):
    """No server: ServeClient's own not-running sentence as a warning, no
    deepLink, no openExternal -- and it PRECEDES the keyless refusal (the
    no-client + keyless-row scenario warns, it does not inform)."""
    for name in ("openNoClient", "openNotReady"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert seq(s) == ["warn"], (name, s["rec"])
        assert first(s, "warn")["message"] == NOT_RUNNING, (name, s["rec"])
        assert count(s, "deepLink") == 0 and count(s, "openExternal") == 0, (name, s["rec"])
    s = scenarios["openKeylessNoClient"]
    assert seq(s) == ["warn"], s["rec"]
    assert first(s, "warn")["message"] == NOT_RUNNING, s["rec"]


@skip_no_node
def test_open_in_editor_never_throws(scenarios):
    """A throwing deepLink is a plain-string error message (never a stack),
    and openExternal is never reached."""
    s = scenarios["openDeepLinkThrows"]
    assert s["threw"] is None, s["threw"]
    assert seq(s) == ["deepLink", "error"], s["rec"]
    assert first(s, "error")["messageType"] == "string", s["rec"]
    assert "stack" not in first(s, "error")["message"].lower(), s["rec"]
    assert count(s, "openExternal") == 0, s["rec"]


# ------------------------------------------ (5) the Mint log line (node)


@skip_no_node
def test_mint_logs_one_line_naming_the_count_and_the_reload(scenarios):
    """S6.3 (5), pinned LOOSELY (count + the word reload): after a successful
    mint the handler logs EXACTLY ONE line naming the minted count (the 200's
    minted list length -- 3, not the payload's keyless count) and that open
    editors reload from disk. Pinned via the injected log dep."""
    s = scenarios["mintLog3"]
    assert s["threw"] is None, s["threw"]
    logs = [e["line"] for e in s["rec"] if e["fn"] == "log"]
    assert len(logs) == 1, s["rec"]
    line = logs[0].lower()
    assert "3" in line, logs
    assert "reload" in line, logs
    assert "disk" in line, logs
    # the success also does what S6.2b's mint success did: one POST, one refresh
    assert count(s, "call") == 1 and count(s, "refresh") == 1, s["rec"]


@skip_no_node
def test_mint_log_names_the_minted_count_not_the_pill_count(scenarios):
    """The count is the minted list's length (1 here -- the payload has 3
    keyless rows, the answer minted 1): the log names the ANSWER."""
    s = scenarios["mintLog1"]
    logs = [e["line"] for e in s["rec"] if e["fn"] == "log"]
    assert len(logs) == 1, s["rec"]
    assert "1" in logs[0].lower(), logs
    assert "3" not in logs[0], logs


@skip_no_node
def test_mint_logs_nothing_when_the_mint_did_not_happen(scenarios):
    """No success, no log line: dismissed confirmation, the 403 --no-write
    refusal (the session locks, it does not log a mint), a rejecting
    transport."""
    for name in ("mintLogDismiss", "mintLog403", "mintLogRejects"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "log") == 0, (name, s["rec"])


@skip_no_node
def test_open_in_editor_messages_are_plain_strings(scenarios):
    """Plan S6: every message recorded in every scenario is typeof string
    (never a MarkdownString), and nothing token-like leaves a handler."""
    for name, s in scenarios.items():
        for e in s["rec"]:
            for key in ("message", "uri"):
                if key in e:
                    assert e[f"{key}Type"] == "string", (name, e)
    blob = json.dumps(scenarios)
    assert "X-Refdes-Token" not in blob
    assert "token=" not in blob


# --------------------------------------------------- the handler's purity


@skip_no_node
def test_the_module_stays_pure_with_the_new_deps():
    """S6.3 grows the deps, not the module's reach: navisCommands.js imports
    no transport/fs/host -- deepLink and openExternal are INJECTED (the
    wiring passes client.deepLink and vscode.env.openExternal). It must not
    compose the deep link itself (no URL, no loopback literal, no token
    name), and MarkdownString stays banned."""
    source = _read(NAVIS_COMMANDS_JS)
    banned = re.compile(
        r'require\(\s*["\'](?:vscode|http|https|net|url|fs|child_process)["\']\s*\)'
    )
    offenders = banned.findall(source)
    assert not offenders, f"navisCommands.js requires {offenders}"
    assert not re.search(r"\bfetch\s*\(", source), "navisCommands.js calls fetch()"
    assert "MarkdownString" not in source, "navisCommands.js mentions MarkdownString"
    assert "token" not in source.lower(), (
        "navisCommands.js names a token: the launch secret lives in "
        "serveClient.js alone, and the deep link is an INJECTED dep (plan S6)"
    )
    assert "http" not in source.replace("https://github.com", ""), (
        "navisCommands.js spells a URL scheme -- openExternal/deepLink are "
        "injected, the handler passes the key and nothing else (plan S6)"
    )
    assert "127.0.0.1" not in source, (
        "navisCommands.js names the loopback literal: it belongs to "
        "serveClient.js's transport (plan S4)"
    )


# ------------------------------------------------- (1)(3) package.json pins


def _manifest() -> dict:
    return json.loads(_read(PACKAGE_JSON))


OPEN_WHEN = (
    f"view == {VIEW_ID} && viewItem =~ /(^| )refdesNavi( |$)/ "
    f"&& !(viewItem =~ /refdesNaviKeyless/)"
)

# contextValue strings the tree module emits (navisContextValue) plus the
# Mint row's distinct word.
CONTEXT_VALUES = {
    "keyedActive": "refdesNavi",
    "archived": "refdesNavi refdesNaviArchived",
    "keyless": "refdesNavi refdesNaviKeyless",
    "mintRow": MINT_CONTEXT,
    "placeholder": "",
}


def _when_allows(when: str, context_value: str) -> bool:
    """Evaluate the pinned when-clause shape against a contextValue string
    (the neighbour's evaluator, GROWN to also evaluate the POSITIVE
    un-parenthesised `viewItem =~ /re/` clause -- the mint row's single word
    must be REFUSED by a clause whose base-word match is a positive clause,
    which the neighbour's negation-only loop vacuously passes)."""
    if f"view == {VIEW_ID}" not in when:
        return False
    clauses = re.findall(
        r"(!)?\(viewItem =~ /([^/]+)/\)|viewItem =~ /([^/]+)/", when
    )
    for neg, pat_neg, pat_pos in clauses:
        pattern = pat_neg or pat_pos
        hit = re.search(pattern, context_value) is not None
        if hit == bool(neg):
            return False
    return True


def test_package_json_contributes_refresh_navis_in_the_palette():
    """(1): refdes.refreshNavis with the title "Refdes: Refresh Navis"
    EXACTLY, and PALETTE-VISIBLE -- the pattern is absence: the hidden
    commands carry a commandPalette when:"false" entry (refdes.openInEditor,
    the two row commands); refreshNavis must have NO commandPalette entry at
    all. RED today: the command is not contributed."""
    commands = {c["command"]: c.get("title", "") for c in _manifest()["contributes"]["commands"]}
    assert REFRESH_ID in commands, f"{REFRESH_ID} is not contributed: {sorted(commands)}"
    assert commands[REFRESH_ID] == "Refdes: Refresh Navis", commands[REFRESH_ID]
    palette = _manifest()["contributes"]["menus"].get("commandPalette", [])
    hidden = {e["command"] for e in palette if e.get("when") == "false"}
    assert REFRESH_ID not in hidden, palette


def test_package_json_contributes_navis_open_in_editor_hidden_from_palette():
    """(4): refdes.navisOpenInEditor contributed with a "Refdes: ... Open in
    editor" title and HIDDEN from the command palette (the
    refdes.openInEditor/refdes.navisArchive pattern -- it acts on a tree
    item). RED today."""
    commands = {c["command"]: c.get("title", "") for c in _manifest()["contributes"]["commands"]}
    assert OPEN_ID in commands, f"{OPEN_ID} is not contributed: {sorted(commands)}"
    title = commands[OPEN_ID]
    assert title.startswith("Refdes: ") and "Open in editor" in title, title
    palette = {e["command"]: e.get("when") for e in _manifest()["contributes"]["menus"].get("commandPalette", [])}
    assert palette.get(OPEN_ID) == "false", palette
    # S6.3 adds commands, not chrome: no keybindings, activation events
    # unchanged (plan S9) -- pinned here (the palette test of a slice that
    # contributes) so the guard is red-first like the rest of this file.
    assert "keybindings" not in _manifest()["contributes"], sorted(_manifest()["contributes"])
    assert _manifest()["activationEvents"] == ["workspaceContains:**/refdes-project.yaml"], (
        "new activation events: a command contribution adds none (plan S9)"
    )


def test_package_json_inline_menu_for_open_in_editor_keyed_rows_only():
    """(4): the view/item/context entry for refdes.navisOpenInEditor is an
    INLINE group gated to keyed rows. The exact when-clause is pinned
    verbatim, and the visibility table (evaluated against the contextValue
    words the tree emits) shows: keyed active AND keyed archived rows allow
    it; keyless rows and the Mint row (contextValue refdesNaviMint) do NOT;
    a placeholder (no contextValue) does not. What the window really shows
    is Jared's checklist (plan S7.2). RED today."""
    menus = _manifest()["contributes"]["menus"]
    entries = [
        e for e in menus.get("view/item/context", []) if e.get("command") == OPEN_ID
    ]
    assert entries, f"no view/item/context entry for {OPEN_ID}: {menus.get('view/item/context')}"
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry["when"] == OPEN_WHEN, entry
    assert entry.get("group") == "inline", entry
    table = {
        "keyedActive": True,
        "archived": True,  # keyed archived rows have a key: the deep link works
        "keyless": False,
        "mintRow": False,  # the Mint word attaches NO row menu
        "placeholder": False,
    }
    for name, visible in table.items():
        assert _when_allows(entry["when"], CONTEXT_VALUES[name]) is visible, (
            name,
            CONTEXT_VALUES[name],
        )


def test_the_mint_word_attaches_no_shipped_row_menu():
    """(2)'s menu half: the Mint row's contextValue must attach NO existing
    row action -- every view/item/context when-clause in the manifest
    (archive/restore/mint/openInEditor) must refuse the single word
    refdesNaviMint. This is the mechanical pin behind "contextValue distinct
    from the Navi words so no row menu attaches". RED today: the row menus
    are not contributed (the S6.2b-2 slice ships them, S6.3 adds
    navisOpenInEditor to the same list)."""
    menus = _manifest()["contributes"]["menus"]
    row_menus = menus.get("view/item/context", [])
    assert row_menus, "no view/item/context entries at all -- S6.2b-2 has not landed"
    contributed = {e.get("command") for e in row_menus}
    assert {"refdes.navisArchive", "refdes.navisRestore", OPEN_ID} <= contributed, contributed
    for entry in row_menus:
        assert _when_allows(entry["when"], MINT_CONTEXT) is False, (
            f"{entry['command']} attaches to the Mint row: {entry['when']}"
        )
    # and the word is distinct from the S6.1/S6.2b words themselves
    assert MINT_CONTEXT not in ("refdesNavi", "refdesNaviArchived", "refdesNaviKeyless")


# ------------------------------------------------ (1)(3) extension.js pins


def test_extension_registers_refresh_navis_as_the_boot_true_refresh():
    """(1) wiring: registerCommand("refdes.refreshNavis", () =>
    refreshNavisTree(true)) -- the EXISTING refresh path, boot=true semantics
    (ensureServe lazily boots, success shows nothing, no server lands on the
    existing placeholder -- the shipped refreshNavisTree body pinned here
    too, so the command inherits them). RED today: no such registration."""
    source = _read(EXTENSION_JS)
    assert re.search(
        r'registerCommand\(\s*"refdes\.refreshNavis"\s*,\s*\(\)\s*=>\s*refreshNavisTree\(\s*true\s*\)\s*\)',
        source,
    ), (
        'extension.js does not register "refdes.refreshNavis" as '
        "() => refreshNavisTree(true) -- the manual refresh is the existing "
        "path with boot=true semantics, not a second implementation"
    )
    body = _function_body(source, "async function refreshNavisTree(boot) {")
    assert "ensureServe(" in body, (
        "refreshNavisTree lost its boot path -- boot=true is what makes the "
        "manual refresh work with no server running (ratified Q5)"
    )
    assert "showNavisPlaceholder(" in body, (
        "refreshNavisTree no longer lands on a placeholder -- the manual "
        "refresh of a dead/absent server must show the existing placeholder"
    )


def test_extension_registers_navis_open_in_editor_with_the_two_new_deps():
    """(4) wiring, thin: registerCommand("refdes.navisOpenInEditor",
    navisCommands.openInEditor) and the createNavisCommands deps grown by
    EXACTLY the two injected names (openExternal wired to
    vscode.env.openExternal, deepLink to the live client's deepLink). The
    wiring stays thin: NO planResult/rowActions calls in extension.js (the
    S6.2b pin, restated). RED today."""
    source = _read(EXTENSION_JS)
    assert re.search(
        r'registerCommand\(\s*"refdes\.navisOpenInEditor"\s*,\s*navisCommands\.openInEditor\s*\)',
        source,
    ), 'extension.js does not register "refdes.navisOpenInEditor" on navisCommands.openInEditor'
    build = source.find("createNavisCommands({")
    assert build != -1, "extension.js never builds createNavisCommands"
    deps_block = _function_body(source, "createNavisCommands({")
    assert re.search(r"openExternal:", deps_block), (
        "the createNavisCommands deps do not inject openExternal -- the "
        "handler must be node-testable (task: put the handler in "
        "navisCommands.js with injected deps)"
    )
    assert re.search(r"deepLink:", deps_block), (
        "the createNavisCommands deps do not inject deepLink -- the deep "
        "link is ServeClient's (plan S5), not a second copy in the handler"
    )
    assert "vscode.env.openExternal" in source, (
        "the openExternal dep is not wired to vscode.env.openExternal"
    )
    assert "planResult(" not in source, (
        "extension.js calls planResult -- keep the wiring thin (the S6.2b rule)"
    )
    assert "rowActions(" not in source, (
        "extension.js calls rowActions -- the row recovery lives in navisCommands.js"
    )


def test_the_lock_line_survives_the_index_refresh():
    """(3) (the S6.2b-2 review's deferred item): the mechanism pinned is
    RE-APPLY IN THE REFRESH PATH (stated in the module docstring):
      - setNavisWriteStatus keeps writing the LOCK text verbatim;
      - applyNavisLockStatus() re-applies it onto the shared status item,
        and ONLY while navisWriteLock.locked() (the lock is the source of
        truth -- a cleared lock paints nothing, so .reset() is the clear);
      - updateStatusBar() -- the index status repaint refreshIndex runs on
        every index refresh, the writer that erases the line today -- calls
        the helper at the END of its own repaint (after statusBar.show()).
    RED today: setNavisWriteStatus lives on the S6.2b-2 branch, and no
    extension.js (any branch) has the helper."""
    source = _read(EXTENSION_JS)
    setter = _function_body(source, "function setNavisWriteStatus(text) {")
    assert LOCK_TEXT in setter, (
        f"setNavisWriteStatus no longer writes {LOCK_TEXT!r} -- the plan S4 "
        "row: the status bar names --no-write"
    )
    assert re.search(r"function applyNavisLockStatus\(\)\s*\{", source), (
        "extension.js has no applyNavisLockStatus() helper -- the chosen "
        "mechanism for the lock surviving an index refresh (re-apply, not a "
        "dedicated item: see this test's docstring)"
    )
    body = _function_body(source, "function applyNavisLockStatus() {")
    assert "navisWriteLock.locked()" in body, body
    assert LOCK_TEXT in body, body
    assert "statusBar.text" in body, body
    refresh = _function_body(source, "async function refreshIndex(silent) {")
    assert "updateStatusBar(" in refresh, (
        "refreshIndex no longer repaints the status item through "
        "updateStatusBar -- the repaint is the eraser this pin guards"
    )
    repaint = _function_body(source, "function updateStatusBar(data) {")
    show = repaint.find("statusBar.show()")
    assert show != -1, "updateStatusBar no longer shows the status item"
    assert "applyNavisLockStatus()" in repaint[show:], (
        "the index repaint rewrites the status item without re-applying the "
        "lock -- the lock line is erased by the next index refresh (the "
        "deferred S6.2b-2 bug this pin exists to catch)"
    )
    assert source.count("navisWriteLock.reset()") >= 2, (
        "the write lock must reset on a NEW serve (boot) and on attach -- "
        "that is what clears the re-applied lock line"
    )
