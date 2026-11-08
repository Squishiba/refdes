"""N6.1-tests: red-first contract tests for slice S6.1 (the read-only Navis tree).

docs/design/navis-vscode-panel-plan.md (Jared ratified all seven defaults on
2026-11-08: GET /api/navis, native TreeView, Explorer section with no new
activity-bar icon, lazy ensureServe on expand, visible "no Navis" empty state).
S6.1 is the read-only half: rows -> TreeItems, click-through, placeholders,
refresh triggers. NO POST, NO archive/restore/mint commands -- that is S6.2
(plan S8), and this file pins the ban.

The module this file pins (THE IMPLEMENTER FOLLOWS THESE NAMES -- decided here
from the plan's "e.g. editors/vscode/navisTree.js" and the neighbours
serveClient.js/docsFocus.js, both pure CommonJS with no `vscode` import):

  editors/vscode/navisTree.js, plain CommonJS, no `require("vscode")`, no
  `require("http")`, no `require("fs")`, exports exactly:

    TEXT_LIMIT = 120
      The plan S6 (line 267): tree labels truncated for display at ~120 chars,
      the hover's field-row precedent (extension.js's `slice(0, 120)`).
    truncateText(text, limit = TEXT_LIMIT)
      -> String(text).slice(0, limit) + "..." when longer, else the string.
    navisLabel(row)
      keyed:  `${row.key6} · ${truncateText(row.text)}`  (the plan's checklist
              "key6 . text", the middle dot U+00B7 the plan spells it with);
      keyless (row.key === ""):  truncateText(row.text)  (no key6, no dot).
    navisDescription(row)
      "marker not found" for an orphan, 'No key yet -- use Mint keys' for a
      keyless row (both the SHIPPED panels' spellings: cli.py labels the
      orphan "marker not found", navis-panel.js's KEYLESS_TITLE), else "".
    navisTooltip(row)
      A plain string: the FULL untruncated row.text, plus the description
      note when there is one, joined with " -- ". Never a MarkdownString.
    navisContextValue(row)
      Space-separated tokens, "refdesNavi" first, then "refdesNaviArchived"
      when row.archived, then "refdesNaviKeyless" when keyless (plan S4's
      contextValue strings, for S6.2's menus).
    navisBadge(payload)
      payload.counts.active -- the active count is what the view badge shows
      (plan checklist 1: active rows with "count in the view badge").
    navisOpenTarget(row, root)
      -> { file: path.join(root, row.file), line: Math.max(0, row.line - 1) }
      (plan S5: the definitionProvider's arithmetic -- join index.root with
      row.file, land on line - 1; orphan rows keep the snapshot location, so
      the same arithmetic). Null for a row with no file.
    createNavisTree(vscode)   -- the host is INJECTED, like docsFocus.js's
      createDocsFocusWatcher(vscode, ...), because the module must not import
      vscode (plan S7.2's posture, serveClient.js:4-6). Returns:
        itemForRow(row, root)      -> vscode.TreeItem (label/description/
                                      tooltip plain strings, contextValue,
                                      command = { command: "vscode.open",
                                      arguments: [vscode.Uri.file(t.file),
                                      { selection: { start: { line: t.line,
                                      character: 0 }, end: { line: t.line,
                                      character: 0 } } }] } when t, undefined
                                      command when the target is null)
        childrenFor(payload, root) -> TreeItem[]: the ACTIVE rows in payload
                                      order, then -- only when counts.archived
                                      (or trailing archived rows) > 0 -- one
                                      group item labelled
                                      `Show all (${archived}) ...` with
                                      collapsibleState Collapsed and NO command
        childrenOf(item, payload)  -> the archived rows' items, in payload
                                      order (the group's children)
        placeholderFor(state)      -> a plain-string TreeItem for
                                      "no-project" | "no-server" |
                                      "server-died" | "no-navis"
        badgeFor(payload)          -> navisBadge(payload)

  The four placeholder labels, exactly as the plan words them:
    "no-server":   "No server -- hover an item, or run Refdes: Attach to
                    running server" (plan S3's literal, the ASCII double-hyphen
                    -- that is this repo's house style: cli.py prints it, the
                    shipped panels print it)
    "no-project":  "No refdes-project.yaml found." (plan S5 names the
                    extension's existing warning, extension.js's
                    "no refdes-project.yaml found")
    "server-died": "Refdes: server died -- run Refdes: Attach to running
                    server" (plan checklist 6: status goes "server died", the
                    tree placeholder matches, Attach recovers)
    "no-navis":    "No Navis in this project" (ratified Q7: a visible empty
                    "no Navis" state)

  The wiring in editors/vscode/extension.js this file pins by name:
    require("./navisTree"), `let navisTree = null;`,
    `async function refreshNavisTree(boot) {` -- it reads the project root,
    boots lazily when `boot` is true (Q5: ensureServe on expand), calls
    serve.navis() and hands the payload to navisTree -- called from
    refreshIndex() (save + the refdes.refreshIndex command run through it),
    from pollServeRevision() (serial change), and from the view's
    onDidExpandElement callback as refreshNavisTree(true);
    `vscode.window.createTreeView("refdes.navisTree", { treeDataProvider:
    ... })`; package.json contributes.views.explorer entry with id
    "refdes.navisTree", no viewsContainers anywhere.

RED-FIRST: the module, the ServeClient.navis() method, the contributes.views
entry and the wiring do not exist on the untouched tree; every test that
interrogates one of them is red today (the node driver dies on the missing
require, the source pins fail on their first assertion). The live-server tests
pin facts that shipped with N5a (`GET /api/navis`, src/refdes/serve/
navis_read.py) -- they are GREEN today BY CONSTRUCTION, exactly the gate-parity
posture tests/test_serve_navis_read.py documents: they pin the server facts
S6.1 renders, and S6.1 cannot regress them.

No real VS Code window is available to CI, so view rendering, `when` clauses,
real menus, native tooltips and the real vscode API are pinned only at logic/
source level (plan S7: "Cannot prove: any VS Code UI behavior"; the manual
checklist is Jared's).

Cross-platform: fixtures written with newline='', node subprocesses bounded by
NODE_TIMEOUT_S and read with encoding="utf-8" (node speaks UTF-8; a Windows
runner's locale is cp1252 and would mojibake the middot in the pinned labels),
servers bind port 0 (the EditorApp fixture), path expectations built with
os.path.join and normalised, no fixed ports, no POSIX-only tools.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest
from conftest import write_project_config
from serve_support import Client, snapshot_tree

from refdes import cli as cli_mod
from refdes import keys
from refdes.serve.server import EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_DIR = os.path.join(REPO_ROOT, "editors", "vscode")
PACKAGE_JSON = os.path.join(VSCODE_DIR, "package.json")
EXTENSION_JS = os.path.join(VSCODE_DIR, "extension.js")
SERVE_CLIENT_JS = os.path.join(VSCODE_DIR, "serveClient.js")
NAVIS_TREE_JS = os.path.join(VSCODE_DIR, "navisTree.js")
SECURITY_PY = os.path.join(REPO_ROOT, "src", "refdes", "serve", "security.py")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to execute the tree module"
)

VIEW_ID = "refdes.navisTree"

# The row shape GET /api/navis answers with (navis_panel.panel_model plus the
# full key, docs/navis.md "The serve API"), pinned as the extension's input.
ROW_FIELDS = {"key", "key6", "text", "item", "href", "file", "line",
              "archived", "changed", "orphan"}

SCHEMA = (
    "site: { title: Navis Tree, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

ACTIVE_TEXT = "Active alpha reminder."
KEYLESS_TEXT = "A marker nobody minted."
ARCHIVED_TEXT = "Gamma archived away."

ACTIVE_KEYLESS_TEXT = "Keyless keeper note."
HOSTILE_MD = "[x](command:workbench.action.closeAllEditors) <script>alert(\"x\")</script>"
LONG_TEXT = "Long navi sentence that goes on. " * 16  # 480 chars, over the 120 limit


def _read(path: str) -> str:
    if not os.path.exists(path):
        pytest.fail(
            f"{os.path.relpath(path, REPO_ROOT)} does not exist -- S6.1 has not "
            "landed, and this pin exists to catch it drifting afterwards"
        )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_body(source: str, marker: str) -> str:
    """The brace-balanced body after `marker` (the neighbour's
    `_provide_completion_items_body` posture: a lazy `.*?\\}` would stop at the
    first nested block)."""
    start = source.find(marker)
    assert start != -1, f"extension.js no longer contains {marker!r}"
    i = start + len(marker)
    depth = 1
    while depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[start + len(marker) : i - 1]


# ---------------------------------------------------------------- live fixture


def _navi_project(tmp_path):
    """A project with three Navis -- one keyed active, one KEYLESS active, one
    archived (archived through the real CLI, the way the tool writes records).
    The keyless marker is added AFTER the archive run on purpose: a writable
    CLI run mints every keyless marker it sees, and a keyless row is exactly
    what a read-only server (the `--no-write` posture, read_only=True -- the
    loader cannot mint) serves to the tree.

    The key is minted by `keys.mint()` and written INTO the marker text, so
    the archive run has nothing to mint and the active row keeps its key."""
    config = str(write_project_config(tmp_path, SCHEMA))
    items = tmp_path / "items"
    items.mkdir()
    active_key, archived_key = keys.mint(), keys.mint()
    (items / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\n"
        f"intro\n<!--navi:{active_key} {ACTIVE_TEXT}-->\n",
        encoding="utf-8",
        newline="",
    )
    (items / "note-c.md").write_text(
        "---\nid: NOTE-003\ntype: note\ntitle: Gamma\n---\n"
        f"intro\n<!--navi:{archived_key} {ARCHIVED_TEXT}-->\n",
        encoding="utf-8",
        newline="",
    )
    assert cli_mod.main(["-c", config, "navis", "archive", archived_key]) == 0
    (items / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\n"
        f"intro\n<!--navi:{active_key} {ACTIVE_TEXT}-->\n"
        f"<!--navi: {KEYLESS_TEXT}-->\n",
        encoding="utf-8",
        newline="",
    )
    return config, active_key, archived_key


@pytest.fixture
def served(tmp_path):
    config, _active_key, _archived_key = _navi_project(tmp_path)
    app = EditorApp(config, poll_interval=60, read_only=True)
    app.start()
    try:
        yield app, Client(app), tmp_path
    finally:
        app.stop()


# ------------------------------------------------------------- 1. live contract


def test_the_read_answers_the_shape_the_tree_renders(served):
    """Plan S3: `GET /api/navis` answers 200 {"navis": rows, "counts":
    {"active", "archived"}}, rows the panel row shape + the full key, for a
    project with a keyed row, a keyless row and an archived row. Green today
    by construction (N5a shipped it) -- S6.1 renders exactly this."""
    _app, client, _root = served
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    assert set(payload) == {"navis", "counts"}
    assert set(payload["counts"]) == {"active", "archived"}
    rows = payload["navis"]
    assert len(rows) >= 2, payload
    for row in rows:
        assert set(row) == ROW_FIELDS, row
    by_text = {row["text"]: row for row in rows}
    assert by_text[ACTIVE_TEXT]["key"] and by_text[ACTIVE_TEXT]["archived"] is False
    assert by_text[KEYLESS_TEXT]["key"] == "" and by_text[KEYLESS_TEXT]["key6"] == ""
    assert by_text[ARCHIVED_TEXT]["archived"] is True
    assert payload["counts"] == {
        "active": sum(1 for row in rows if not row["archived"]),
        "archived": sum(1 for row in rows if row["archived"]),
    }
    assert payload["counts"] == {"active": 2, "archived": 1}
    # the projection's order, active first (navis_panel's contract)
    assert [row["archived"] for row in rows] == [False, False, True]


def test_the_read_carries_the_click_through_location(served):
    """Plan S5: rows carry file/line, which the click-through joins onto
    index.root. The keyless row keeps its location, the archived row keeps
    the record's snapshot location."""
    _app, client, _root = served
    _status, payload = client.api_get("/api/navis")
    by_text = {row["text"]: row for row in payload["navis"]}
    for row in by_text.values():
        assert isinstance(row["file"], str) and row["file"], row
        assert isinstance(row["line"], int) and row["line"] >= 1, row
    assert by_text[ACTIVE_TEXT]["file"] == "items/note-a.md"
    assert by_text[KEYLESS_TEXT]["file"] == "items/note-a.md"
    assert by_text[ARCHIVED_TEXT]["file"] == "items/note-c.md"


def test_the_token_gates_this_read(served):
    """The plan's data path is a token-gated read (S3; every /api/ read is
    gated -- adapter S3.2). Parity with /api/items, compared, not hard-coded
    (the posture of test_serve_navis_read's gate test)."""
    _app, client, _root = served
    for kwargs in (
        {},
        {"headers": {"X-Refdes-Token": "wrong"}},
        {"cookie": True},
    ):
        navis_answer = client.request("GET", "/api/navis", **kwargs)
        items_answer = client.request("GET", "/api/items", **kwargs)
        assert (navis_answer[0], navis_answer[2]) == (items_answer[0], items_answer[2])
        assert items_answer[0] >= 400, kwargs
    assert client.api_get("/api/navis")[0] == 200


def test_a_no_write_server_still_serves_the_tree(served):
    """Plan S3 "With --no-write": reads work -- the tree renders, the counts
    render. The fixture IS a --no-write server (read_only=True); a navis POST
    is refused while the GET serves, and the GET changes nothing on disk (the
    read-only tree of S6.1 is all this server can be asked for)."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = client.api_get("/api/navis")
    assert status == 200, payload
    assert payload["counts"] == {"active": 2, "archived": 1}
    refused = client.api_post("/api/navis/archive", {"navi": "nope"})
    assert refused[0] == 403, refused
    assert "--no-write" in refused[1]["error"], refused
    assert snapshot_tree(root) == before


# ----------------------------------------------------- node harness (2 + pins)


LOGIC_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
const navisTree = require(cfg.module);

const vscode = {
  TreeItem: class {
    constructor(label, collapsibleState) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  },
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
  Uri: {
    file: (f) => ({ scheme: "file", fsPath: f, path: f,
      toString() { return "file://" + f; } }),
  },
  ThemeIcon: class {
    constructor(id) { this.id = id; }
  },
  MarkdownString: class {
    constructor(value) { this.value = value; }
  },
};

const tree = navisTree.createNavisTree(vscode);

function plainify(item) {
  const out = {
    labelType: typeof item.label,
    labelIsMarkdown: item.label instanceof vscode.MarkdownString,
    label: item.label,
    descriptionType: typeof item.description,
    description: item.description === undefined ? null : item.description,
    tooltipType: typeof item.tooltip,
    tooltipIsMarkdown: item.tooltip instanceof vscode.MarkdownString,
    contextValue: item.contextValue,
    collapsibleState: item.collapsibleState,
    // JSON.stringify drops undefined keys; the tests ask for command === null
    command: item.command === undefined ? null : item.command,
  };
  return out;
}

const results = {
  exports: {
    TEXT_LIMIT: navisTree.TEXT_LIMIT,
    fns: ["truncateText", "navisLabel", "navisDescription", "navisTooltip",
      "navisContextValue", "navisBadge", "navisOpenTarget", "createNavisTree"]
      .filter((n) => typeof navisTree[n] === "function"),
  },
  childrenFor: tree.childrenFor(cfg.payload, cfg.root).map(plainify),
  badge: tree.badgeFor(cfg.payload),
  placeholders: {},
};
for (const state of ["no-project", "no-server", "server-died", "no-navis"]) {
  results.placeholders[state] = plainify(tree.placeholderFor(state));
}

// childrenOf takes the item the provider handed out, not a plainified copy:
// the same object childrenFor returned for the group. Payloads with no
// archived rows have no group, and the driver does not ask about a leaf --
// the tests must not depend on unspecified leniency there.
const handed = tree.childrenFor(cfg.payload, cfg.root);
results.groupChildren = cfg.payload.counts.archived
  ? tree.childrenOf(handed[handed.length - 1], cfg.payload).map(plainify)
  : [];

results.targets = {};
for (const [name, row] of Object.entries(cfg.rows)) {
  const t = navisTree.navisOpenTarget(row, cfg.root);
  results.targets[name] = t ? { file: t.file, line: t.line } : null;
}
results.pure = {
  labels: {},
  descriptions: {},
  tooltips: {},
  contextValues: {},
};
for (const [name, row] of Object.entries(cfg.rows)) {
  results.pure.labels[name] = navisTree.navisLabel(row);
  results.pure.descriptions[name] = navisTree.navisDescription(row);
  results.pure.tooltips[name] = navisTree.navisTooltip(row);
  results.pure.contextValues[name] = navisTree.navisContextValue(row);
}
results.badgePure = navisTree.navisBadge(cfg.payload);
results.truncate = {
  limit: navisTree.TEXT_LIMIT,
  long: navisTree.truncateText(cfg.rows.long.text),
  short: navisTree.truncateText("short"),
};

require("fs").writeSync(1, JSON.stringify(results));
"""


def run_logic_tree(tmp_path, cfg: dict) -> dict:
    script = tmp_path / "navis-tree-driver.js"
    script.write_text(LOGIC_DRIVER, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the U+00B7 in the pinned `key6 · text` labels on the way
        # back in (the posture of tests/test_editor_live_calc.py's harness).
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (
        f"node driver exited {proc.returncode}: stdout={proc.stdout[-2000:]!r} "
        f"stderr={proc.stderr[-2000:]!r}"
    )
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"node driver printed no JSON: stdout={proc.stdout[-2000:]!r} "
            f"stderr={proc.stderr[-2000:]!r}"
        )


def _row(key, text, *, file="items/note-a.md", line=9, archived=False, orphan=False):
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


ROWS = {
    "keyed": _row("4jp6qysbahb", ACTIVE_TEXT),
    "keyless": _row("", KEYLESS_TEXT, line=10),
    "archived": _row("3fm1dgvv6p3", ARCHIVED_TEXT, file="items/note-c.md", archived=True),
    "orphan": _row("9zzzzzzzzzz", "Beta archived then deleted", archived=True, orphan=True),
    "long": _row("abcdef12345", LONG_TEXT),
    "hostile": _row("mdcmd012345", HOSTILE_MD),
}
PAYLOAD = {
    # the long and hostile rows ride in the payload too, so the tree items
    # (not just the pure functions) are checked against them
    "navis": [
        ROWS["keyed"],
        ROWS["keyless"],
        ROWS["long"],
        ROWS["hostile"],
        ROWS["archived"],
        ROWS["orphan"],
    ],
    "counts": {"active": 4, "archived": 2},
}
WIN_DRIVE_ROOT = "D:/posix/root"


@pytest.fixture
def logic(tmp_path):
    return run_logic_tree(tmp_path, {"module": NAVIS_TREE_JS, "root": WIN_DRIVE_ROOT, "rows": ROWS, "payload": PAYLOAD})


def _joined(*parts):
    return os.path.join(*parts).replace(os.sep, "/")


# ------------------------------------------------- 2. node-executed tree logic


@skip_no_node
def test_module_exports_the_pure_api(logic):
    """The module exists, imports nothing from vscode (it is pure -- the
    require of a vscode-free module succeeds under bare node), and exports
    the names S6.1's wiring is written against."""
    assert logic["exports"]["fns"] == [
        "truncateText",
        "navisLabel",
        "navisDescription",
        "navisTooltip",
        "navisContextValue",
        "navisBadge",
        "navisOpenTarget",
        "createNavisTree",
    ], logic["exports"]
    assert logic["exports"]["TEXT_LIMIT"] == 120, logic["exports"]


@skip_no_node
def test_top_level_rows_are_active_rows_in_payload_order_then_show_all(logic):
    """Plan S8/S6.1: active rows first, in the projection's (payload's)
    order, then one 'Show all' group for the archived ones -- archived rows
    are NOT top level. Labels are `key6 · text`, keyless rows label by text
    alone (there is no key6 to spell)."""
    kids = logic["childrenFor"]
    assert [k["label"] for k in kids[:2]] == [
        f"4jp6qy · {ACTIVE_TEXT}",
        KEYLESS_TEXT,
    ], kids
    assert kids[-1]["label"].startswith("Show all (2)"), kids[-1]
    assert len(kids) == PAYLOAD["counts"]["active"] + 1, kids
    assert kids[-1]["collapsibleState"] == 1, kids[-1]  # Collapsed
    assert kids[-1]["command"] is None, kids[-1]


@skip_no_node
def test_show_all_children_are_the_archived_rows_in_order(logic):
    kids = logic["groupChildren"]
    assert [k["label"] for k in kids] == [
        f"3fm1dg · {ARCHIVED_TEXT}",
        "9zzzzz · Beta archived then deleted",
    ], kids


@skip_no_node
def test_descriptions_name_the_orphan_and_the_keyless_states(logic):
    """The plan S4 disabled-state notes, mirroring the shipped panels: the
    keyless row says 'No key yet -- use Mint keys' (navis-panel.js's
    KEYLESS_TITLE), the orphan row says 'marker not found' (cli.py's label).
    Plain rows carry no note."""
    descs = logic["pure"]["descriptions"]
    assert descs["keyless"] == "No key yet -- use Mint keys"
    assert descs["orphan"] == "marker not found"
    assert descs["keyed"] == ""
    assert descs["archived"] == ""
    # the group-rendered rows carry their description on the item too
    by_label = {k["label"]: k for k in logic["childrenFor"]}
    assert by_label[KEYLESS_TEXT]["description"] == "No key yet -- use Mint keys"


@skip_no_node
def test_labels_are_truncated_at_120_and_tooltips_keep_the_full_text(logic):
    """Plan S6 (line 267) / S11.5: labels truncate at ~120 chars, the full
    text lives in the plain-string tooltip. A 480-char Navi text must not
    reach a label whole, and must not be truncated away entirely."""
    long_row = ROWS["long"]
    expected_label = f"abcdef · {long_row['text'][:120]}..."
    assert logic["pure"]["labels"]["long"] == expected_label, logic["pure"]
    assert logic["pure"]["tooltips"]["long"] == long_row["text"]
    assert logic["truncate"]["limit"] == 120
    assert logic["truncate"]["long"] == f"{long_row['text'][:120]}..."
    assert logic["truncate"]["short"] == "short"
    # and the truncation is what the item wears:
    kid = next(k for k in logic["childrenFor"] if k["label"].startswith("abcdef"))
    assert kid["label"] == expected_label
    assert len(kid["label"]) < len(long_row["text"])


@skip_no_node
def test_hostile_row_text_is_inert_plain_string_everywhere(logic):
    """Plan S6: every string in a row is untrusted author text; label,
    description and tooltip are PLAIN strings -- markdown link syntax and
    command URIs inside the text render literally, nothing is parsed, and
    nothing is a MarkdownString."""
    label = logic["pure"]["labels"]["hostile"]
    assert label == f"mdcmd0 · {HOSTILE_MD}", label
    assert logic["pure"]["tooltips"]["hostile"] == HOSTILE_MD
    kids = logic["childrenFor"] + logic["groupChildren"]
    for kid in kids:
        for key in ("labelIsMarkdown", "tooltipIsMarkdown"):
            assert not kid[key], (key, kid["label"])
        for key in ("label", "description", "tooltip", "contextValue"):
            value = kid.get(key)
            if value is not None:
                assert isinstance(value, str), (key, kid["label"], type(value))
    # nothing the module rendered ever names the token
    assert "X-Refdes-Token" not in json.dumps(logic)


@skip_no_node
def test_context_values_carry_the_state_tokens(logic):
    """S6.2's menus hang on these (plan S4: contextValue
    `refdesNaviArchived`, `refdesNaviKeyless`, ...); S6.1 must mint them now
    so the later slice only adds contributions."""
    cvs = logic["pure"]["contextValues"]
    assert cvs["keyed"] == "refdesNavi"
    assert cvs["keyless"] == "refdesNavi refdesNaviKeyless"
    assert cvs["archived"] == "refdesNavi refdesNaviArchived"
    assert cvs["orphan"] == "refdesNavi refdesNaviArchived"


@skip_no_node
def test_badge_is_the_active_count(logic):
    assert logic["badge"] == PAYLOAD["counts"]["active"]
    assert logic["badgePure"] == PAYLOAD["counts"]["active"]


@skip_no_node
def test_click_through_arithmetic_matches_the_definition_provider(logic):
    """Plan S5: open `path.join(index.root, row.file)` at `row.line - 1` --
    the definitionProvider's arithmetic (extension.js:586-587). The line is
    0-based for VS Code, clamped at 0; a line-1 marker lands on line 0.
    Orphan rows keep the snapshot location, so the same arithmetic applies.
    A row with no file has no target (the wiring must not crash on it)."""
    targets = logic["targets"]
    keyed = ROWS["keyed"]
    assert targets["keyed"] == {
        "file": _joined(WIN_DRIVE_ROOT.replace("/", os.sep), "items", "note-a.md"),
        "line": keyed["line"] - 1,
    }, targets
    assert targets["archived"]["file"] == _joined(
        WIN_DRIVE_ROOT.replace("/", os.sep), "items", "note-c.md"
    )
    assert targets["archived"]["line"] == 8
    # the orphan row's snapshot location (same file/line as the keyed row in
    # this fixture) goes through the SAME arithmetic -- plan S5: "Orphan rows
    # ... keep the click: the snapshot location is the best available pointer"
    assert targets["orphan"] == {"file": targets["keyed"]["file"], "line": 8}
    assert targets["keyless"]["line"] == ROWS["keyless"]["line"] - 1
    # the command the item wears is the same arithmetic, in vscode shapes:
    kid = next(k for k in logic["childrenFor"] if k["label"].startswith("4jp6qy"))
    assert kid["command"]["command"] == "vscode.open"
    uri, options = kid["command"]["arguments"]
    assert uri["fsPath"] == targets["keyed"]["file"]
    assert options["selection"]["start"]["line"] == keyed["line"] - 1
    assert options["selection"]["end"]["line"] == keyed["line"] - 1


@skip_no_node
def test_line_one_and_missing_file_targets(tmp_path):
    """A marker on line 1 lands on 0-based line 0 (never -1); a row without
    a file has no click-through target at all (command omitted, no crash)."""
    script_rows = dict(ROWS)
    script_rows["first"] = _row("firstkey1", "First line marker.", line=1)
    script_rows["nofile"] = _row("nofilekey", "Nowhere navi.", file=None)
    out = run_logic_tree(
        tmp_path,
        {
            "module": NAVIS_TREE_JS,
            "root": WIN_DRIVE_ROOT,
            "rows": script_rows,
            "payload": {
                "navis": [script_rows["first"], script_rows["nofile"]],
                "counts": {"active": 2, "archived": 0},
            },
        },
    )
    assert out["targets"]["first"]["line"] == 0, out["targets"]
    assert out["targets"]["nofile"] is None, out["targets"]
    first_kid = next(k for k in out["childrenFor"] if k["label"].startswith("firstk"))
    assert first_kid["command"]["arguments"][1]["selection"]["start"]["line"] == 0
    nofile_kid = next(k for k in out["childrenFor"] if "Nowhere navi." in k["label"])
    assert nofile_kid["command"] is None, nofile_kid


@skip_no_node
def test_placeholder_states_are_named_items(logic):
    """The plan's four placeholder states, worded as the plan words them
    (S3's no-server literal, S5's no-project warning, checklist 6's
    'server died', ratified Q7's visible 'no Navis'). Plain strings."""
    ph = logic["placeholders"]
    assert ph["no-server"]["label"] == (
        "No server -- hover an item, or run Refdes: Attach to running server"
    )
    assert "no refdes-project.yaml found" in ph["no-project"]["label"].lower()
    assert "server died" in ph["server-died"]["label"].lower()
    assert "Attach to running server" in ph["server-died"]["label"]
    assert "no navis" in ph["no-navis"]["label"].lower()
    for state, item in ph.items():
        assert item["labelType"] == "string", (state, item)
        assert not item["labelIsMarkdown"], state


# ------------------------------------------------------------- 3. source pins


def test_package_json_contributes_the_view_in_the_explorer_only():
    """Ratified Q3: a `views` entry in the Explorer container, NO
    viewsContainers, no new activity-bar icon. Fails today: package.json
    has no `views` key at all (adapter S2.1's confirmed absence)."""
    manifest = json.loads(_read(PACKAGE_JSON))
    contributes = manifest["contributes"]
    assert "viewsContainers" not in contributes, (
        "package.json declares viewsContainers -- the ratified Q3 default is "
        "an Explorer section with no new activity-bar icon"
    )
    views = contributes.get("views", {})
    assert "explorer" in views, f"no views.explorer entry: {sorted(views)}"
    entries = views["explorer"]
    assert any(entry.get("id") == VIEW_ID for entry in entries), entries
    for container, items in views.items():
        assert container == "explorer", f"views contributed to {container!r}, not the Explorer"
        for entry in items:
            assert "icon" not in entry, entry


def test_the_view_entry_starts_collapsed_so_expand_is_the_boot():
    """Ratified Q5: expanding the view IS the ask. VS Code shows a contributed
    view expanded/visible by default, and extension.js treats the view becoming
    visible as that gesture (it refreshes with boot=true) -- so an
    expanded-by-default section would boot a Python `refdes serve` child on
    the first Explorer open of any refdes project, with no user gesture
    (plan §3 "no boot at activation", §9). The contribution's
    `visibility: "collapsed"` is what makes the first expansion the ask."""
    manifest = json.loads(_read(PACKAGE_JSON))
    entries = manifest["contributes"]["views"]["explorer"]
    entry = next(e for e in entries if e.get("id") == VIEW_ID)
    assert entry.get("visibility") == "collapsed", (
        f"the {VIEW_ID} view entry does not start collapsed: {entry}"
    )


def test_the_tree_wiring_lives_in_the_extension_and_the_pure_module():
    """The thin wiring (extension.js) requires the pure module and creates
    the tree view with the id package.json contributes; the pure module
    imports NO vscode (the plan: "a NEW pure module (no `vscode` import)" --
    the serveClient.js/docsFocus.js posture). Fails today: neither the
    require, the createTreeView call, nor the module file exists."""
    source = _read(EXTENSION_JS)
    assert re.search(r'require\("\./navisTree"\)', source), (
        "extension.js does not require ./navisTree -- the tree logic must "
        "live in the pure module, not in the 1,000-line extension host file"
    )
    created = re.search(r'createTreeView\(\s*"([^"]+)"', source)
    assert created, "extension.js never calls vscode.window.createTreeView"
    assert created.group(1) == VIEW_ID, created.group(1)

    tree_source = _read(NAVIS_TREE_JS)  # the module does not exist today
    assert not re.search(r'require\(\s*["\']vscode["\']\s*\)', tree_source), (
        "navisTree.js imports vscode -- it must stay pure (drivable under "
        "bare node, like serveClient.js)"
    )


def test_the_tree_module_never_names_the_token():
    """Plan S6: the token lives in ServeClient and never enters the tree --
    labels/tooltips are row fields only. The mechanical form: the module
    never names a token at all, so nothing can put one in its output."""
    tree_source = _read(NAVIS_TREE_JS)
    assert "token" not in tree_source.lower(), (
        "navisTree.js names a token: the launch token must never reach the "
        "tree's labels, tooltips or any rendered string (plan S6)"
    )


def test_no_markdown_string_is_built_from_navis_rows():
    """Plan S6: TreeItem label/description/tooltip are plain strings only;
    building a MarkdownString from row data is forbidden. The tree module
    has zero MarkdownString; the extension keeps exactly the one it already
    has (the hover's -- extension.js:291), so the tree wiring adds none."""
    tree_source = _read(NAVIS_TREE_JS)
    assert "MarkdownString" not in tree_source, (
        "navisTree.js mentions MarkdownString -- row text is untrusted; the "
        "plan forbids building markdown from it"
    )
    source = _read(EXTENSION_JS)
    assert source.count("new vscode.MarkdownString") == 1, (
        "extension.js's MarkdownString count moved off the single hover use "
        "-- the navis tree must render plain strings"
    )


def test_serve_client_navis_uses_the_shared_token_header_path():
    """S6.1 BUILDS `ServeClient.navis()` -- the GET /api/navis read through
    the EXISTING token-header path (the request() method that sets
    X-Refdes-Token, the header the server compares in constant time). Pinned
    two-sided like the launch-line pin: the header name from
    serve/security.py, the delegation from serveClient.js. Fails today:
    serveClient.js has no navis() method."""
    header_match = re.search(r'TOKEN_HEADER = "([^"]+)"', _read(SECURITY_PY))
    assert header_match, "src/refdes/serve/security.py no longer defines TOKEN_HEADER"
    source = _read(SERVE_CLIENT_JS)

    navis_method = re.search(
        r"navis\(\)\s*\{[^}]*return this\.request\(\"/api/navis\"\);?\s*\}", source
    )
    assert navis_method, (
        "editors/vscode/serveClient.js has no navis() delegating to "
        'this.request("/api/navis") -- the read must ride the existing '
        "GET path (which sets the token header), not a second http.request"
    )
    assert header_match.group(1) in source, (
        f"serveClient.js does not send {header_match.group(1)!r}, which every "
        "/api/ read must carry"
    )
    assert re.search(r'method: "GET"', source), (
        "serveClient.js's shared request path no longer hard-codes GET -- "
        "S6.1's tree adds no POST path (that is S6.2)"
    )


def test_the_tree_module_is_a_read_only_surface():
    """S6.1 is read-only and file-silent: the module that turns rows into
    TreeItems has no HTTP (no POST of any kind -- the plan bans the actions
    until S6.2) and no fs write (the extension's one write ban, §4/§6 Q5,
    extended to the new file). The shipped FORBIDDEN_WRITE sweep of
    tests/test_vscode_extension.py scans editors/vscode/*.js by directory
    listing, so it covers this file too; this is the new file's own pin."""
    tree_source = _read(NAVIS_TREE_JS)
    for needle in ("POST", 'require("http")', "require('http')"):
        assert needle not in tree_source, f"navisTree.js references {needle!r}"
    assert not re.search(r'\bapplyEdit\b|\bWorkspaceEdit\b|fs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)', tree_source), (
        "navisTree.js names a write path -- S6.1 is the read-only tree"
    )


def test_the_tree_refreshes_on_every_trigger_the_plan_names():
    """Plan S3 refresh + S6.1: the tree re-renders on serial move (the poller
    already stores serveSerial), on save and on `refdes.refreshIndex` (both
    run through refreshIndex), and on view expand -- where expand is the one
    trigger that boots the server lazily (ratified Q5, the hover's
    ensureServe posture, plan S3 "With no server attached"). Fails today:
    extension.js has no refreshNavisTree and no onDidExpandElement.

    The UI half -- VS Code really re-rendering, the badge really updating --
    is not verifiable without a window (plan S7.2 "Cannot prove: any VS Code
    UI behavior"); this pins the calls that make it happen."""
    source = _read(EXTENSION_JS)

    assert re.search(r"async function refreshNavisTree\(\s*boot\s*\)\s*\{", source), (
        "extension.js defines no `async function refreshNavisTree(boot)` -- "
        "the plan's named refresh entry point"
    )
    body = _function_body(source, "async function refreshNavisTree(boot) {")
    assert "serve.navis()" in body, (
        "refreshNavisTree no longer reads the tree through "
        "ServeClient.navis() -- the plan S3 data path"
    )
    assert "ensureServe(" in body, (
        "refreshNavisTree never calls ensureServe() -- ratified Q5: expanding "
        "the view lazily boots the server, like the hover"
    )

    refresh_index = _function_body(source, "async function refreshIndex(silent) {")
    assert "refreshNavisTree(" in refresh_index, (
        "refreshIndex no longer refreshes the navis tree -- the save hook "
        "(scheduleRefresh -> refreshIndex) and the refdes.refreshIndex command "
        "run through it, so those two triggers die with it"
    )
    poll = _function_body(source, "async function pollServeRevision() {")
    assert "refreshNavisTree(" in poll, (
        "pollServeRevision no longer refreshes the navis tree on the serial "
        "it stores (plan S3: 'on serial change, refresh the tree')"
    )

    expand = source.find("onDidExpandElement")
    assert expand != -1, (
        "the tree view has no onDidExpandElement handler -- plan S6.1 lists "
        "expand as a refresh trigger, and ratified Q5 boots the server on it"
    )
    window = source[expand : expand + 600]
    assert "refreshNavisTree(true)" in window, window

    created = re.search(r'createTreeView\(\s*"([^"]+)"\s*,\s*\{', source)
    assert created, "extension.js has no vscode.window.createTreeView call"
    assert created.group(1) == VIEW_ID, created.group(1)
    assert "treeDataProvider" in source[created.end() : created.end() + 200], (
        "createTreeView is called without a treeDataProvider"
    )
    assert re.search(r"\bnavisTree\s*=\s*null\s*;", source), (
        "extension.js keeps no navisTree handle -- the view has nothing to "
        "render through once it is created"
    )
    assert "placeholderFor(" in source, (
        "the wiring never calls navisTree.placeholderFor() -- the plan's four "
        "placeholder states (no project / no server / server died / no Navis) "
        "are how the tree fails loudly, per serveClient.js's own rule"
    )
