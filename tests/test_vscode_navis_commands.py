"""N6.2b-2-tests: red-first contract tests for the Navis write COMMANDS of the
VS Code extension (slice S6.2 of docs/design/navis-vscode-panel-plan.md;
questions ratified 2026-11-08 -- Q4: Mint ships as an explicit command).

This file writes NO module. THE IMPLEMENTER BUILDS (pinned here):

(A) editors/vscode/navisCommands.js -- plain CommonJS, NO top-level
    ``require("vscode")`` (the host is injected, the serveClient.js /
    navisTree.js posture), no http/https/net/url/fs/child_process, no fetch(),
    no MarkdownString, no ``Origin``/token text (plan S6: the header policy and
    the launch secret live in serveClient.js only). Requires ./navisActions and
    ./navisTree freely (both pure). Exports exactly:

      createNavisCommands(deps) -> {archive(arg), restore(arg), mint()}
      deps = {
        vscode,                                  -- the injected host
        getClient() -> a ServeClient-like object (with .ready) or null,
        refreshTree() -> Promise,                -- re-renders the tree
        getRows() -> the last GET /api/navis payload ({navis, counts}) or null,
        lock,                                    -- a navisActions.createWriteLock() instance
        setStatus(text|null) -> void,            -- the status-bar write state
        log(line) -> void,
      }

    ROW RECOVERY (pinned -- the tree item carries no row field): VS Code passes
    a command invoked from the view/item/context menu the tree item. The
    handler recovers the row by matching the item against ``getRows().navis``,
    recomputing the tree's OWN rendered fields (navisTree.navisLabel,
    navisDescription, navisTooltip, navisContextValue; an unset description
    counts as "") and taking the FIRST row whose rendered triple equals the
    item's. An item that matches nothing (a placeholder, null, a stale item)
    resolves to no row; the handler then refuses with rowActions(null)'s
    generic tooltip ("No Navis row to act on") and no client call. (A key6
    collision renders two rows with identical labels; the first match wins --
    the UI cannot tell those items apart, and the selector is each row's FULL
    key, so the POST is never ambiguous.)

    EVERY handler, in this order:
      1. lock.locked() -> showWarningMessage naming ``--no-write``, return.
         No client call, no refresh.
      2. no client (getClient() null) or !client.ready -> showWarningMessage
         "refdes serve is not running" (ServeClient's own transport string),
         return. No call.
      3. resolve the row; rowActions(row, {writesLocked: lock.locked()})
         disables this action -> showWarningMessage(the tooltip), return.
         No call. selector = selectorFor(row); null -> the same refusal.
      4. await client.navisArchive(selector) / navisRestore(selector) /
         (mint) client.navisMint().
      5. feed the result to navisActions.planResult(result) and render:
         "refresh" -> await refreshTree(), SILENT (no message, changed:false
                      included);
         "warn"    -> showWarningMessage(message) (+ refreshTree() when the
                      decision refreshes);
         "error"   -> showErrorMessage(message) (+ refreshTree() when asked);
         "lock"    -> lock.lock(); setStatus(naming --no-write);
                      showWarningMessage(message); NO refresh.
      6. a handler NEVER throws: a rejecting client lands on
         showErrorMessage with a plain string (err.message), never a stack,
         never the token (plan S6).

    MINT is project-wide and writes marker bytes into item files (plan S11.1),
    so it asks ONE modal confirmation BEFORE the POST:
    ``showWarningMessage(text, {modal: true}, "Mint keys")`` -- anything other
    than the "Mint keys" button (dismiss, undefined) -> no POST. The refusal
    when mintAvailable(getRows(), {writesLocked}).enabled is false (nothing to
    mint) is a showInformationMessage -- NO modal prompt, no POST. After a
    200: refreshTree(), and when the body says ``still_keyless`` > 0 say so in
    a showInformationMessage naming the count. Archive/Restore ask NO
    confirmation (reversible, write no bytes -- plan S4).

(B) editors/vscode/package.json -- commands refdes.navisArchive /
    refdes.navisRestore / refdes.navisMint ("Refdes: ..." titles);
    menus.view/item/context entries gated on ``view == refdes.navisTree`` and
    the viewItem contextValue words navisTree.js emits (refdesNavi /
    refdesNaviArchived / refdesNaviKeyless): archive for keyed active rows
    only, restore for refdesNaviArchived only, mint for refdesNaviKeyless
    rows; mint also as a view/title button. The two per-row commands are
    hidden from the command palette (``"when": "false"``, the
    refdes.openInEditor pattern); refdes.navisMint stays in the palette. NO
    keybindings, NO new activation events.

(C) editors/vscode/extension.js -- ONLY thin wiring: construct the write lock
    once (reset it when a NEW serve is attached/started), build
    createNavisCommands with the real deps, register the three commands. No
    planResult/rowActions calls there (they live in navisCommands.js).

RED-FIRST: navisCommands.js does not exist and the package.json commands /
menus / extension.js wiring are absent on the untouched tree -- every test
here is red today (the node drivers die on the missing require, the JSON pins
fail on their first assertion, the source pins fail on missing strings).

NO REAL VS CODE WINDOW exists in CI: the menu ``when`` behaviour, the modal
prompt and the view/title button are pinned at LOGIC and JSON level only
(plan S7.2: "Cannot prove: any VS Code UI behavior" -- Jared's manual
checklist items 3, 4, 5 cover the window). The fake vscode shows only that the
handlers CALL the right API with string messages; VS Code shows only in a real
window that the call renders the way the docs say.

A local reference implementation can be validated against these pins with
``REFDES_NAVIS_COMMANDS_JS=/path/to/navisCommands.js`` before the module
lands.

Cross-platform (tests/test_crossplatform_lint.py): the node subprocess reads
with ``encoding="utf-8"`` (a Windows runner's cp1252 locale would mojibake the
non-ASCII in the server texts), the driver is written with ``newline=""``, no
fixed ports (no servers at all -- the client is faked; the wire contract is
tests/test_vscode_extension_http_client.py's), no POSIX-only tools, bounded
processes.
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
PACKAGE_JSON = os.path.join(VSCODE_DIR, "package.json")
EXTENSION_JS = os.path.join(VSCODE_DIR, "extension.js")
NAVIS_ACTIONS_JS = os.path.join(VSCODE_DIR, "navisActions.js")
NAVIS_TREE_JS = os.path.join(VSCODE_DIR, "navisTree.js")
NAVIS_COMMANDS_JS = os.environ.get(
    "REFDES_NAVIS_COMMANDS_JS", os.path.join(VSCODE_DIR, "navisCommands.js")
)

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to execute the commands module"
)

VIEW_ID = "refdes.navisTree"

# The shipped strings the handlers must reuse (navisActions.js / navisTree.js /
# serveClient.js -- pinned equal by the neighbour files).
KEYLESS_HINT = "No key yet -- use Mint keys"
ORPHAN_HINT = "Marker not found -- hand-restore the marker, then it re-links by key"
ALREADY = "Already archived"
NOT_ARCHIVED = "Not archived -- nothing to restore"
NO_ROW = "No Navis row to act on"
NOT_RUNNING = "refdes serve is not running"
MINT_NOTHING = "No keyless Navis to mint"

# ---------------------------------------------------------------- row fixtures


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
KEY_B = "abcd1211110"  # same key6 as KEY_A: the collision pair
KEY_C = "ffff1100006"
KEY_D = "eeee220000b"

ROWS = {
    "keyedActive": _row(KEY_A, "Alpha model worst-case copper temperature.", file="items/note-a.md", line=6),
    "dupe": _row(KEY_B, "Alpha model worst-case copper temperature.", file="items/note-b.md", line=6),
    "keyless": _row("", "A marker nobody minted.", file="items/note-c.md", line=7),
    "keyedArchived": _row(KEY_C, "Beta recheck decoupling near U14.", file="items/note-d.md", line=8, archived=True),
    "archivedOrphan": _row(KEY_D, "Gamma archived then deleted.", file="items/note-e.md", line=9, archived=True, orphan=True),
}

PAYLOAD = {"navis": list(ROWS.values()), "counts": {"active": 3, "archived": 2}}
KEYED_PAYLOAD = {
    "navis": [ROWS["keyedActive"], ROWS["keyedArchived"]],
    "counts": {"active": 1, "archived": 1},
}

# Scripted ServeClient.post() results (the {status, body} / {error} shapes the
# routes answer; the plan S4 table and their live captures are pinned by
# tests/test_vscode_navis_actions.py -- here the FAKED client answers them to
# the handler, which renders the decision).
OK200 = {"status": 200, "body": {"kind": "ok", "changed": True, "verb": "archive", "key": KEY_A}}
OK200_UNCHANGED = {"status": 200, "body": {"kind": "ok", "changed": False, "verb": "archive", "key": KEY_A}}
NOT_FOUND = {
    "status": 404,
    "body": {"kind": "not_found", "error": "no Navi matches 'zzzzzzzzzzz'"},
}
AMBIGUOUS = {
    "status": 409,
    "body": {
        "kind": "ambiguous",
        "error": "navi key prefix 'abcd12' is ambiguous: name one of its candidates",
        "candidates": [
            {"key": KEY_A, "text": "Alpha model worst-case copper temperature.", "file": "items/note-a.md", "line": 6},
            {"key": KEY_B, "text": "Alpha model worst-case copper temperature.", "file": "items/note-b.md", "line": 6},
        ],
    },
}
REFUSED = {
    "status": 403,
    "body": {
        "kind": "refused",
        "error": "this server was started with --no-write: navis archive is disabled",
    },
}
REFUSED_MINT = {
    "status": 403,
    "body": {
        "kind": "refused",
        "error": "this server was started with --no-write: navis mint is disabled",
    },
}
JSON500 = {"status": 500, "body": {"kind": "error", "error": "navis archive: the store exploded"}}
HOSTILE_MD = '[x](command:workbench.action.closeAllEditors) <script>alert("x")</script>'
HOSTILE_500 = {"status": 500, "body": {"kind": "error", "error": HOSTILE_MD + "\x00 tail with \x07controls"}}
RAW_HTML_500 = {
    "status": 500,
    "body": "<!doctype html><html><body>gateway boom SMUGGLE-MARKER</body></html>",
}
TRANSPORT = {"error": "socket hang up"}
NOT_ARCHIVED_409 = {
    "status": 409,
    "body": {"kind": "conflict", "reason": "not_archived", "error": "Navi abcd12 is not archived"},
}
MINT200 = {
    "status": 200,
    "body": {
        "kind": "ok",
        "changed": True,
        "minted": [{"key": "5kk2m4ppqrs", "key6": "5kk2m4", "item": "NOTE-003", "file": "items/note-c.md"}],
        "still_keyless": 0,
    },
}
MINT200_STILL = {
    "status": 200,
    "body": {
        "kind": "ok",
        "changed": True,
        "minted": [{"key": "5kk2m4ppqrs", "key6": "5kk2m4", "item": "NOTE-003", "file": "items/note-c.md"}],
        "still_keyless": 2,
    },
}

# ------------------------------------------------------------------ scenarios

# Each scenario runs the named handler under node against a fake vscode + fake
# client; the assertions (post-node) pin the exact recorded call sequence.
# payload: "main" | "keyed" | "null".
SCENARIOS = [
    {"name": "arch200", "command": "archive", "item": "keyedActive",
     "client": {"result": OK200}},
    {"name": "arch200Unchanged", "command": "archive", "item": "keyedActive",
     "client": {"result": OK200_UNCHANGED}},
    {"name": "arch404", "command": "archive", "item": "keyedActive",
     "client": {"result": NOT_FOUND}},
    {"name": "arch409Ambiguous", "command": "archive", "item": "keyedActive",
     "client": {"result": AMBIGUOUS}},
    {"name": "arch403Refused", "command": "archive", "item": "keyedActive",
     "client": {"result": REFUSED}},
    {"name": "arch500", "command": "archive", "item": "keyedActive",
     "client": {"result": JSON500}},
    {"name": "arch500RawHtml", "command": "archive", "item": "keyedActive",
     "client": {"result": RAW_HTML_500}},
    {"name": "arch500Hostile", "command": "archive", "item": "keyedActive",
     "client": {"result": HOSTILE_500}},
    {"name": "archTransport", "command": "archive", "item": "keyedActive",
     "client": {"result": TRANSPORT}},
    {"name": "archRejects", "command": "archive", "item": "keyedActive",
     "client": {"result": OK200, "reject": True}},
    {"name": "archLocked", "command": "archive", "item": "keyedActive",
     "locked": True, "client": {"result": OK200}},
    {"name": "archNoClient", "command": "archive", "item": "keyedActive",
     "client": None},
    {"name": "archNotReady", "command": "archive", "item": "keyedActive",
     "client": {"result": OK200, "ready": False}},
    {"name": "archKeyless", "command": "archive", "item": "keyless",
     "client": {"result": OK200}},
    {"name": "archArchived", "command": "archive", "item": "keyedArchived",
     "client": {"result": OK200}},
    {"name": "restoreActive", "command": "restore", "item": "keyedActive",
     "client": {"result": OK200}},
    {"name": "restoreKeyless", "command": "restore", "item": "keyless",
     "client": {"result": OK200}},
    {"name": "restoreOrphan", "command": "restore", "item": "archivedOrphan",
     "client": {"result": OK200}},
    {"name": "restore200", "command": "restore", "item": "keyedArchived",
     "client": {"result": {"status": 200, "body": {"kind": "ok", "changed": True, "verb": "restore", "key": KEY_C}}}},
    {"name": "restore409NotArchived", "command": "restore", "item": "keyedArchived",
     "client": {"result": NOT_ARCHIVED_409}},
    {"name": "restoreLocked", "command": "restore", "item": "keyedArchived",
     "locked": True, "client": {"result": OK200}},
    {"name": "foreignItem", "command": "archive", "item": "foreign",
     "client": {"result": OK200}},
    {"name": "nullItem", "command": "archive", "item": "null",
     "client": {"result": OK200}},
    {"name": "payloadNull", "command": "archive", "item": "keyedActive",
     "payload": "null", "client": {"result": OK200}},
    {"name": "dupeFirst", "command": "archive", "item": "keyedActive",
     "client": {"result": OK200}},  # main payload: KEY_A and KEY_B render the same label
    {"name": "mintLocked", "command": "mint", "client": {"result": MINT200},
     "locked": True},
    {"name": "mintNoClient", "command": "mint", "client": None},
    {"name": "mintNoClientKeyed", "command": "mint", "client": None,
     "payload": "keyed"},  # the no-server refusal precedes the mintAvailable refusal
    {"name": "mintNothing", "command": "mint", "payload": "keyed",
     "client": {"result": MINT200}},
    {"name": "mintPayloadNull", "command": "mint", "payload": "null",
     "client": {"result": MINT200}},
    {"name": "mintDismiss", "command": "mint", "mintChoice": "dismiss",
     "client": {"result": MINT200}},
    {"name": "mintConfirm", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200}},
    {"name": "mintConfirmStillKeyless", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200_STILL}},
    {"name": "mintConfirm403Refused", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": REFUSED_MINT}},
    {"name": "mintConfirm500", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": JSON500}},
    {"name": "mintConfirmRejects", "command": "mint", "mintChoice": "Mint keys",
     "client": {"result": MINT200, "reject": True}},
]


# ---------------------------------------------------------------- node driver


DRIVER = r"""
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
    Uri: {
      file: (f) => ({scheme: "file", fsPath: f, path: f,
        toString() { return "file://" + f; }}),
    },
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
  if (sc.locked) lock.lock();
  const client = makeClient(sc, rec);
  const payload = sc.payload === "null" ? null
    : sc.payload === "keyed" ? cfg.keyedPayload
    : cfg.payload;
  const cmds = mod.createNavisCommands({
    vscode,
    getClient: () => client,
    refreshTree: async () => { rec.push({fn: "refresh"}); },
    getRows: () => payload,
    lock,
    setStatus: (text) => { rec.push({fn: "setStatus", text: text === null ? null : String(text)}); },
    log: (line) => { rec.push({fn: "log", line: String(line)}); },
  });
  const handlers = {archive: cmds.archive, restore: cmds.restore, mint: cmds.mint};
  const handler = handlers[sc.command];
  let item;
  if (sc.item === "foreign") item = tree.placeholderFor("no-navis");
  else if (sc.item && sc.item !== "null") item = tree.itemForRow(cfg.rows[sc.item], cfg.root);
  let threw = null;
  const before = rec.length;
  try {
    await handler(item);
  } catch (err) {
    threw = String((err && err.stack) || err);
  }
  return {rec: rec.slice(before), lockAfter: lock.locked(), threw,
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


def _read(path: str) -> str:
    if not os.path.exists(path):
        pytest.fail(
            f"{os.path.relpath(path, REPO_ROOT)} does not exist -- S6.2b has not "
            "landed, and this pin exists to catch it drifting afterwards"
        )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to execute the commands module")
    tmp = tmp_path_factory.mktemp("navis-commands")
    script = tmp / "navis-commands-driver.js"
    script.write_text(DRIVER, encoding="utf-8", newline="")
    cfg = {
        "commandsModule": NAVIS_COMMANDS_JS,
        "treeModule": NAVIS_TREE_JS,
        "actionsModule": NAVIS_ACTIONS_JS,
        "rows": ROWS,
        "payload": PAYLOAD,
        "keyedPayload": KEYED_PAYLOAD,
        "root": "D:/posix/root",
        "scenarios": SCENARIOS,
    }
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the non-ASCII in the server texts (the neighbours' harness
        # posture, tests/test_editor_live_calc.py ~1272-1278).
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
    got = out["scenarios"]
    for sc in SCENARIOS:
        assert sc["name"] in got, sc["name"]
        assert "fatal" not in got[sc["name"]], (sc["name"], got[sc["name"]]["fatal"])
    return got


def seq(sc: dict) -> list:
    """The recorded call sequence, fn names in order."""
    return [entry["fn"] for entry in sc["rec"]]


def messages(sc: dict, *fns: str) -> list:
    return [e for e in sc["rec"] if e["fn"] in (fns or ("warn", "info", "error"))]


def first(sc: dict, fn: str) -> dict:
    hits = [e for e in sc["rec"] if e["fn"] == fn]
    assert hits, (fn, sc["rec"])
    return hits[0]


def calls(sc: dict) -> list:
    return [e for e in sc["rec"] if e["fn"] == "call"]


def count(sc: dict, fn: str) -> int:
    return sum(1 for e in sc["rec"] if e["fn"] == fn)


# ------------------------------------------------------- the module's surface


@skip_no_node
def test_module_exports_the_command_surface(scenarios):
    """createNavisCommands(deps) returns exactly {archive, restore, mint}, all
    functions -- and the require succeeded under bare node, so the module
    imports no vscode (the serveClient.js/navisTree.js purity posture)."""
    s = scenarios["arch200"]
    assert s["api"] == ["archive", "mint", "restore"], s["api"]
    assert s["handlerType"] == "function", s
    for name in ("arch200", "restore200", "mintConfirm"):
        assert scenarios[name]["api"] == ["archive", "mint", "restore"], name


# ------------------------------------------------ the plan S4 table, rendered


@skip_no_node
def test_archive_success_is_a_silent_refresh_with_the_full_key(scenarios):
    """200 (changed true AND changed:false) -> ONE client call with the row's
    FULL key as selector (never key6, never an ordinal), then refreshTree(),
    and NO message at all (a toast per double-click is spam). No confirmation
    prompt for archive (reversible, writes no bytes)."""
    for name in ("arch200", "arch200Unchanged"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert seq(s) == ["call", "refresh"], (name, s["rec"])
        assert calls(s)[0]["method"] == "navisArchive", name
        assert calls(s)[0]["selector"] == KEY_A, (name, calls(s))
        assert not messages(s), (name, messages(s))
        assert s["lockAfter"] is False, name


@skip_no_node
def test_restore_success_is_a_silent_refresh_with_the_full_key(scenarios):
    s = scenarios["restore200"]
    assert s["threw"] is None, s["threw"]
    assert seq(s) == ["call", "refresh"], s["rec"]
    assert calls(s)[0]["method"] == "navisRestore", s["rec"]
    assert calls(s)[0]["selector"] == KEY_C, calls(s)
    assert not messages(s), messages(s)


@skip_no_node
def test_404_warns_with_the_servers_text_then_refreshes(scenarios):
    """The ordinal moved under us: warning with the server's text, then the
    refresh (plan S4's 404 row: the number may be valid now)."""
    s = scenarios["arch404"]
    assert seq(s) == ["call", "warn", "refresh"], s["rec"]
    assert first(s, "warn")["message"] == NOT_FOUND["body"]["error"], s["rec"]
    assert s["lockAfter"] is False, s


@skip_no_node
def test_409_ambiguous_warns_naming_every_candidate_and_keeps_the_tree(scenarios):
    s = scenarios["arch409Ambiguous"]
    assert seq(s) == ["call", "warn"], s["rec"]
    m = first(s, "warn")["message"]
    for cand in AMBIGUOUS["body"]["candidates"]:
        assert cand["key"] in m, (cand, m)
        assert f"{cand['file']}:{cand['line']}" in m, (cand, m)
    assert count(s, "refresh") == 0, s["rec"]


@skip_no_node
def test_403_refused_locks_the_session_names_no_write_and_never_refreshes(scenarios):
    """plan S4's 403 row through the handler: lock.lock(), the status bar
    names --no-write, a warning (the server's text), NO refresh, and the lock
    sticks for every later handler in the same instance."""
    s = scenarios["arch403Refused"]
    assert seq(s) == ["call", "setStatus", "warn"], s["rec"]
    assert s["lockAfter"] is True, s["rec"]
    status = first(s, "setStatus")
    assert "--no-write" in status["text"], status
    assert first(s, "warn")["message"] == REFUSED["body"]["error"], s["rec"]
    assert count(s, "refresh") == 0, s["rec"]


@skip_no_node
def test_500_is_a_loud_error_never_silent_never_a_refresh(scenarios):
    s = scenarios["arch500"]
    assert seq(s) == ["call", "error"], s["rec"]
    assert first(s, "error")["message"] == JSON500["body"]["error"], s["rec"]
    assert count(s, "refresh") == 0, s["rec"]
    assert s["lockAfter"] is False, s


@skip_no_node
def test_not_archived_conflict_warns_with_the_servers_text_and_refreshes(scenarios):
    """plan S4's 409 not_archived row (the Restore of a row the store says is
    active): warning with the store's text, refresh true."""
    s = scenarios["restore409NotArchived"]
    assert seq(s) == ["call", "warn", "refresh"], s["rec"]
    assert first(s, "warn")["message"] == NOT_ARCHIVED_409["body"]["error"], s["rec"]


@skip_no_node
def test_transport_error_is_a_loud_error_no_lock_no_refresh(scenarios):
    s = scenarios["archTransport"]
    # the POST was sent (the call is recorded); no response came back.
    assert seq(s) == ["call", "error"], s["rec"]
    assert first(s, "error")["message"] == TRANSPORT["error"], s["rec"]
    assert count(s, "refresh") == 0, s["rec"]
    assert s["lockAfter"] is False, s


@skip_no_node
def test_a_rejecting_client_never_throws_out_of_a_handler(scenarios):
    """The handler boundary: a client whose promise rejects lands on
    showErrorMessage with a plain string, the handler resolves, no stack, no
    crash (a quiet failure -- and a loud crash -- are both the bug class)."""
    for name in ("archRejects", "mintConfirmRejects"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "error") == 1, (name, s["rec"])
        m = first(s, "error")["message"]
        assert isinstance(m, str) and m, (name, m)
        assert "\n" not in m, (name, repr(m))
        assert "at " not in m, (name, m)  # no stack frame in a toast


# ------------------------------------------------------- the refused requests


@skip_no_node
def test_locked_session_refuses_every_write_without_calling(scenarios):
    """(1): lock.locked() -> a warning naming --no-write, and NOTHING reaches
    the client (not one POST, not one refresh) -- for all three commands."""
    for name in ("archLocked", "restoreLocked", "mintLocked"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "call") == 0, (name, s["rec"])
        assert count(s, "refresh") == 0, (name, s["rec"])
        warns = messages(s, "warn")
        assert len(warns) == 1, (name, s["rec"])
        assert "--no-write" in warns[0]["message"], (name, warns[0])
        assert warns[0]["modal"] is False, (name, warns[0])  # not the mint prompt


@skip_no_node
def test_no_server_refuses_with_the_transport_string_without_calling(scenarios):
    """(2): no client (getClient() null) and an un-ready client both get
    ServeClient's own string and no POST (the mint case proves the refusal
    precedes the modal prompt and the mintAvailable refusal)."""
    for name in ("archNoClient", "archNotReady", "mintNoClient", "mintNoClientKeyed"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "call") == 0, (name, s["rec"])
        assert seq(s) == ["warn"], (name, s["rec"])
        assert first(s, "warn")["message"] == NOT_RUNNING, (name, s["rec"])


@skip_no_node
def test_disabled_actions_refuse_with_the_shipped_tooltip_and_no_call(scenarios):
    """(3): a keyless row archives to the preview panel's keyless line; an
    already archived row to "Already archived"; a restore of an active row,
    of a keyless row, of an archived orphan -- each to its shipped tooltip
    (navisActions.rowActions, pinned by tests/test_vscode_navis_actions.py),
    each with ZERO client calls and no refresh."""
    expected = {
        "archKeyless": KEYLESS_HINT,
        "archArchived": ALREADY,
        "restoreActive": NOT_ARCHIVED,
        "restoreKeyless": KEYLESS_HINT,
        "restoreOrphan": ORPHAN_HINT,
    }
    for name, tooltip in expected.items():
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "call") == 0, (name, s["rec"])
        assert seq(s) == ["warn"], (name, s["rec"])
        assert first(s, "warn")["message"] == tooltip, (name, s["rec"])
        assert count(s, "refresh") == 0, (name, s["rec"])


@skip_no_node
def test_an_item_that_resolves_to_no_row_refuses_without_calling(scenarios):
    """Row recovery: a placeholder item, a null arg (palette invocation), and
    a null payload all resolve to no row -> the generic refusal
    (rowActions(null)'s tooltip) and no call. The tree renders these items;
    the commands must not POST a selector for a row they cannot name."""
    for name in ("foreignItem", "nullItem", "payloadNull"):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "call") == 0, (name, s["rec"])
        assert seq(s) == ["warn"], (name, s["rec"])
        assert first(s, "warn")["message"] == NO_ROW, (name, s["rec"])


@skip_no_node
def test_the_row_of_two_identically_labelled_rows_is_the_first_match(scenarios):
    """Row recovery under a key6 collision: KEY_A and KEY_B render the same
    label and contextValue; the item built for the FIRST payload row resolves
    to the first row, and the POST carries THAT row's full key (so the
    archive is never ambiguous on the wire)."""
    s = scenarios["dupeFirst"]
    assert s["threw"] is None, s["threw"]
    assert seq(s) == ["call", "refresh"], s["rec"]
    assert calls(s)[0]["selector"] == KEY_A, calls(s)


# ------------------------------------------------------------------ the mint


@skip_no_node
def test_mint_asks_one_modal_confirmation_and_nothing_happens_on_dismiss(scenarios):
    """Mint writes marker bytes into item files (plan S11.1), so it asks ONE
    modal confirmation -- showWarningMessage(text, {modal:true}, "Mint keys")
    -- and a dismiss (any answer but the "Mint keys" button) POSTs nothing
    and refreshes nothing."""
    s = scenarios["mintDismiss"]
    assert s["threw"] is None, s["threw"]
    prompts = [e for e in s["rec"] if e["fn"] == "warn" and e["modal"]]
    assert len(prompts) == 1, s["rec"]
    assert prompts[0]["buttons"] == ["Mint keys"], prompts[0]
    assert isinstance(prompts[0]["message"], str) and prompts[0]["message"], prompts[0]
    assert "mint" in prompts[0]["message"].lower(), prompts[0]
    assert count(s, "call") == 0, s["rec"]
    assert count(s, "refresh") == 0, s["rec"]


@skip_no_node
def test_mint_confirm_posts_mint_and_refreshes_silently(scenarios):
    s = scenarios["mintConfirm"]
    assert s["threw"] is None, s["threw"]
    prompts = [e for e in s["rec"] if e["fn"] == "warn" and e["modal"]]
    assert len(prompts) == 1, s["rec"]
    assert prompts[0]["buttons"] == ["Mint keys"], prompts[0]
    # the prompt precedes the POST; the POST is mint (no selector); 200 ->
    # silent refresh, no toast (changed:true is the mint's business).
    assert [e["fn"] for e in s["rec"]] == ["warn", "call", "refresh"], s["rec"]
    assert s["rec"][1]["method"] == "navisMint", s["rec"]
    assert s["rec"][1]["selector"] is None, s["rec"]
    assert not messages(s, "info", "error"), s["rec"]


@skip_no_node
def test_mint_200_says_so_when_markers_are_still_keyless(scenarios):
    """The mint 200's `still_keyless` (the store refused to mint some markers)
    is a plain info message naming the count -- the tree refreshes either
    way, and the author is told the mint was partial."""
    s = scenarios["mintConfirmStillKeyless"]
    assert s["threw"] is None, s["threw"]
    assert seq(s) == ["warn", "call", "refresh", "info"], s["rec"]
    m = first(s, "info")["message"]
    assert "2" in m and "keyless" in m.lower(), m


@skip_no_node
def test_mint_refusals_never_prompt_and_never_post(scenarios):
    """Nothing to mint (all rows keyed, and the null payload) -> an
    INFORMATION message with the mintAvailable tooltip, no modal prompt, no
    POST. (The locked case is pinned in test_locked_session_refuses_every_write.)"""
    for name, expected in (("mintNothing", MINT_NOTHING), ("mintPayloadNull", MINT_NOTHING)):
        s = scenarios[name]
        assert s["threw"] is None, (name, s["threw"])
        assert count(s, "call") == 0, (name, s["rec"])
        prompts = [e for e in s["rec"] if e["fn"] == "warn" and e["modal"]]
        assert prompts == [], (name, s["rec"])
        assert seq(s) == ["info"], (name, s["rec"])
        assert first(s, "info")["message"] == expected, (name, s["rec"])


@skip_no_node
def test_mint_failures_use_the_same_plan_s4_mapping(scenarios):
    """A mint POST is a POST: 403 refused locks the session (status + warning,
    no refresh); 500 is a loud error, no refresh, no lock."""
    s = scenarios["mintConfirm403Refused"]
    assert s["threw"] is None, s["threw"]
    assert [e["fn"] for e in s["rec"]] == ["warn", "call", "setStatus", "warn"], s["rec"]
    assert s["lockAfter"] is True, s["rec"]
    assert "--no-write" in first(s, "setStatus")["text"], s["rec"]
    assert messages(s, "warn")[-1]["message"] == REFUSED_MINT["body"]["error"], s["rec"]
    assert count(s, "refresh") == 0, s["rec"]

    s = scenarios["mintConfirm500"]
    assert [e["fn"] for e in s["rec"]] == ["warn", "call", "error"], s["rec"]
    assert first(s, "error")["message"] == JSON500["body"]["error"], s["rec"]
    assert count(s, "refresh") == 0, s["rec"]
    assert s["lockAfter"] is False, s


# ------------------------------------------------------- plain-string rule


@skip_no_node
def test_every_message_a_handler_shows_is_a_plain_string(scenarios):
    """Plan S6: row/server text is untrusted. Every message recorded in every
    scenario is a typeof-string (never a MarkdownString object); a hostile
    500 body arrives as its sanitized passthrough (control characters
    stripped, markdown kept INERT as text); a raw non-JSON 500 body is never
    echoed (the generic names the status only)."""
    for name, s in scenarios.items():
        for e in s["rec"]:
            if "message" in e:
                assert e["messageType"] == "string", (name, e)

    hostile = scenarios["arch500Hostile"]
    shown = first(hostile, "error")["message"]
    assert HOSTILE_MD in shown, shown  # verbatim, inert, plain text
    assert not re.search(r"[\x00-\x1f\x7f\x80-\x9f]", shown), repr(shown)
    assert len(shown) <= 300, len(shown)

    raw = scenarios["arch500RawHtml"]
    shown = first(raw, "error")["message"]
    assert "500" in shown, shown
    assert "SMUGGLE-MARKER" not in shown, shown

    # nothing token-like ever leaves a handler (plan S6):
    blob = json.dumps(scenarios)
    assert "X-Refdes-Token" not in blob
    assert "token=" not in blob


# ------------------------------------------------------------- source pins


def test_the_module_imports_nothing_it_must_not():
    """Plan S6/S7.2 purity of navisCommands.js: drivable under bare node
    (everything injected), no transport, no files, no editor host, no
    MarkdownString (plain strings only), and it never names the launch secret
    or the Origin header (both live in serveClient.js -- the decision layer
    must not grow a second copy). RED today: the file does not exist."""
    source = _read(NAVIS_COMMANDS_JS)
    banned = re.compile(
        r'require\(\s*["\'](?:vscode|http|https|net|url|fs|child_process)["\']\s*\)'
    )
    offenders = banned.findall(source)
    assert not offenders, f"navisCommands.js requires {offenders}"
    assert not re.search(r"\bfetch\s*\(", source), "navisCommands.js calls fetch()"
    assert "MarkdownString" not in source, (
        "navisCommands.js mentions MarkdownString -- row/server text is "
        "untrusted; every message is a plain string (plan S6)"
    )
    assert "Origin" not in source, (
        "navisCommands.js names Origin -- the header policy lives in "
        "serveClient.js post() (plan S4)"
    )
    assert "token" not in source.lower(), (
        "navisCommands.js names a token: the launch secret must never reach "
        "the command layer (plan S6, the navisTree.js rule)"
    )


def test_package_json_contributes_the_three_commands_with_titles():
    """Plan S4's Command surface: refdes.navisArchive / refdes.navisRestore /
    refdes.navisMint in contributes.commands, each with a "Refdes: ..." title
    naming the verb. RED today: the commands are not contributed."""
    manifest = json.loads(_read(PACKAGE_JSON))
    commands = {c["command"]: c.get("title", "") for c in manifest["contributes"]["commands"]}
    for cid, verb in (
        ("refdes.navisArchive", "Archive"),
        ("refdes.navisRestore", "Restore"),
        ("refdes.navisMint", "Mint"),
    ):
        assert cid in commands, f"{cid} is not contributed: {sorted(commands)}"
        assert commands[cid].startswith("Refdes: "), (cid, commands[cid])
        assert verb in commands[cid], (cid, commands[cid])


# The exact `when` clauses (pinned verbatim; the contextValue words are the
# ones navisTree.navisContextValue emits). Substring matching is safe: the
# state words are strict superstrings of the base word, never vice versa.
ARCHIVE_WHEN = (
    f"view == {VIEW_ID} && viewItem =~ /(^| )refdesNavi( |$)/ "
    f"&& !(viewItem =~ /refdesNaviArchived/) && !(viewItem =~ /refdesNaviKeyless/)"
)
RESTORE_WHEN = f"view == {VIEW_ID} && viewItem =~ /refdesNaviArchived/"
MINT_ITEM_WHEN = f"view == {VIEW_ID} && viewItem =~ /refdesNaviKeyless/"
VIEW_TITLE_WHEN = f"view == {VIEW_ID}"

CONTEXT_VALUES = {
    "keyedActive": "refdesNavi",
    "archived": "refdesNavi refdesNaviArchived",
    "keyless": "refdesNavi refdesNaviKeyless",
    "archivedKeyless": "refdesNavi refdesNaviArchived refdesNaviKeyless",
}


def _when_allows(when: str, context_value: str) -> bool:
    """Evaluate the pinned when-clause shape against a contextValue string."""
    if f"view == {VIEW_ID}" not in when:
        return False
    for neg, pattern in re.findall(r"(!)?\(viewItem =~ /([^/]+)/\)", when):
        hit = re.search(pattern, context_value) is not None
        if hit == bool(neg):
            return False
    return True


def test_package_json_context_menus_gate_on_the_context_value_words():
    """menus.view/item/context gates Archive to keyed ACTIVE rows, Restore to
    refdesNaviArchived, Mint to refdesNaviKeyless, and the mint view/title
    button to the view. The visibility table below is evaluated against the
    contextValue strings navisTree emits -- archive hidden for archived AND
    keyless, restore shown only for archived, mint shown for keyless rows.
    RED today: the menus are not contributed. (What the window shows of this
    is Jared's checklist 3 -- see the module docstring.)"""
    manifest = json.loads(_read(PACKAGE_JSON))
    menus = manifest["contributes"]["menus"]
    item_context = menus.get("view/item/context", [])
    by_command = {}
    for entry in item_context:
        by_command.setdefault(entry["command"], []).append(entry)

    def when_for(cid: str) -> str:
        hits = by_command.get(cid, [])
        assert hits, f"{cid} has no view/item/context entry: {item_context}"
        assert len(hits) == 1, (cid, hits)
        return hits[0]["when"]

    # the exact clause strings are pinned verbatim (the contextValue words are
    # the ones navisTree.navisContextValue emits), and their visibility table
    # is evaluated against those strings,
    assert when_for("refdes.navisArchive") == ARCHIVE_WHEN
    assert when_for("refdes.navisRestore") == RESTORE_WHEN
    assert when_for("refdes.navisMint") == MINT_ITEM_WHEN

    table = {
        ARCHIVE_WHEN: {  # archive: keyed active rows only
            "keyedActive": True,
            "archived": False,
            "keyless": False,
            "archivedKeyless": False,
        },
        RESTORE_WHEN: {  # restore: archived rows only
            "keyedActive": False,
            "archived": True,
            "keyless": False,
            "archivedKeyless": False,  # a keyless archive cannot restore (the panel's rule)
        },
        MINT_ITEM_WHEN: {  # mint on keyless rows
            "keyedActive": False,
            "archived": False,
            "keyless": True,
            "archivedKeyless": True,
        },
    }
    for when, expects in table.items():
        for name, visible in expects.items():
            assert _when_allows(when, CONTEXT_VALUES[name]) is visible, (when, name)

    titles = menus.get("view/title", [])
    mint_title = [e for e in titles if e.get("command") == "refdes.navisMint"]
    assert mint_title, f"no view/title entry for refdes.navisMint: {titles}"
    assert mint_title[0]["when"] == VIEW_TITLE_WHEN, mint_title


def test_package_json_hides_the_row_commands_from_the_palette_not_mint():
    """The refdes.openInEditor pattern (package.json): the two per-row
    commands are hidden from the command palette (they act on a tree item);
    refdes.navisMint is project-wide and STAYS in the palette. NO keybindings
    are contributed, and the activation events do not grow (plan S9).
    RED today: the palette entries do not exist."""
    manifest = json.loads(_read(PACKAGE_JSON))
    contributes = manifest["contributes"]
    palette = {e["command"]: e.get("when") for e in contributes["menus"].get("commandPalette", [])}
    assert palette.get("refdes.navisArchive") == "false", palette
    assert palette.get("refdes.navisRestore") == "false", palette
    assert palette.get("refdes.navisMint", "false") != "false", palette
    assert "keybindings" not in contributes, sorted(contributes)
    assert manifest["activationEvents"] == ["workspaceContains:**/refdes-project.yaml"], (
        "new activation events: a view contribution adds none (plan S9)"
    )


def test_extension_wiring_is_thin_and_registers_the_three_commands():
    """extension.js (C): requires ./navisCommands, builds
    createNavisCommands(...), registers the three ids, and carries the write
    lock (construct + reset on a NEW serve). NO planResult/rowActions calls
    there -- the decision layer lives in navisCommands.js, and extension.js
    grows only the wiring (task: no logic in extension.js beyond it).
    RED today: none of this is wired."""
    source = _read(EXTENSION_JS)
    assert 'require("./navisCommands")' in source, (
        "extension.js does not require ./navisCommands -- the command "
        "handlers must live in the pure module, not in the host file"
    )
    assert "createNavisCommands(" in source, "extension.js never builds the command handlers"
    for cid in ("refdes.navisArchive", "refdes.navisRestore", "refdes.navisMint"):
        assert f'registerCommand("{cid}"' in source, f"{cid} is not registered"
    assert "createWriteLock" in source, (
        "extension.js does not construct the session write lock "
        "(navisActions.createWriteLock)"
    )
    assert ".reset()" in source, (
        "extension.js never resets the write lock -- a NEW serve (attach/"
        "start) must clear the --no-write lock of the old one"
    )
    assert "planResult(" not in source, (
        "extension.js calls planResult -- render the decision INSIDE "
        "navisCommands.js, keep the wiring thin"
    )
    assert "rowActions(" not in source, (
        "extension.js calls rowActions -- the row-disabled refusal belongs "
        "to the command handlers"
    )
