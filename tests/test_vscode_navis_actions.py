"""N6.2b-1-tests: red-first contract tests for ``editors/vscode/navisActions.js``
-- the decision logic of the Navis write actions (slice S6.2 of
docs/design/navis-vscode-panel-plan.md; Q1-Q7 ratified 2026-11-08, Q4: Mint
ships as an explicit command).

THE MODULE THE IMPLEMENTER BUILDS (pinned here; this file writes no module):
plain CommonJS, NO ``require("vscode")``, no http/fetch/fs/child_process,
plain strings only (never a MarkdownString), nothing token-like ever in its
output (plan S6). Driven under bare node like navisTree.js / serveClient.js
(plan S7.2). Exports, exactly five plain functions:

  planResult(result) -> {kind, refresh, lockWrites, message}
    ONE ``ServeClient.post()`` result (``{status, body}`` -- body JSON-parsed
    for every status, raw text when a non-200 body is not JSON -- or
    ``{error}``), mapped to a plain decision object per plan S4's table:
      200 (changed true OR false)  -> kind "refresh", refresh true, NO message
                                      (changed:false is a SILENT success)
      400 bad_request              -> kind "error", the server's ``error`` text
      403 kind:"refused"           -> kind "lock", lockWrites true, the message
                                      names ``--no-write`` (server text says it)
      404 not_found                -> kind "warn", refresh TRUE (the row set
                                      moved under us), the server's text
      409 ambiguous                -> kind "warn", refresh false, the message
                                      names every candidate (key, its text,
                                      ``file:line``) from ``candidates``
      409 conflict keyless         -> kind "warn", the server's message
      409 conflict not_archived    -> kind "warn", refresh TRUE, server text
      409 conflict orphan          -> kind "warn", the server's hand-restore
                                      hint, refresh false
      409 conflict journal_pending -> kind "warn", the store's refusal text,
                                      refresh false
      500                          -> kind "error", the server's ``error``
      {error} (no response at all) -> kind "error", that text; NO lock, no
                                      refresh
      ANY other status, an unnamed JSON ``kind``, a non-object body (the
      post() raw-text case), a 200 that is not an object -> kind "error" with
      a GENERIC safe message that includes the status number and NEVER the raw
      body verbatim (beyond a short truncation).
    The server's own text is passed through VERBATIM except: truncated to 300
    chars and control characters removed. A hostile ``error``/candidate text
    (markdown, ``[x](command:...)``, ``<script>``, 5000 chars) stays an inert
    plain string in ``message``.

  rowActions(row, state) -> {archive: {enabled, tooltip},
                             restore: {enabled, tooltip}}
    ``state = {writesLocked: bool}``. Disabled states computed from the row
    (plan S4 "Disabled states, computed from the row" -- each mirrors a
    shipped panel, docs/navis.md "The served preview panel"):
      key === ""            -> Archive disabled, tooltip "No key yet -- use
                               Mint keys" (navisTree.navisDescription's exact
                               string -- reuse the constant or pin equality)
      archived && orphan    -> Restore disabled, tooltip "Marker not found --
                               hand-restore the marker, then it re-links by
                               key" (navis-panel.js's ORPHAN_TITLE)
      active keyed          -> Archive enabled, Restore disabled
      archived keyed !orphan-> Restore enabled, Archive disabled
      writesLocked          -> everything disabled, both tooltips name
                               ``--no-write``
      keyless ARCHIVED row cannot exist: the function must not crash on one
      and must keep Archive disabled.

  selectorFor(row) -> the selector to POST: the FULL ``row.key`` (never key6,
    never an ordinal); null for a keyless row (pinned: null, not a throw --
    the conservative answer for a call the UI should never make).

  mintAvailable(payload, state) -> {enabled, count, label, tooltip}
    count = keyless rows among ALL rows (active AND archived); enabled iff
    count > 0 and not writesLocked; label `Mint keys (N)` (the preview
    panel's pill shape, docs/navis.md "Mint keys (N)").

  createWriteLock() -> {locked(): bool, lock(): void, reset(): void}
    the session lock a 403 refused flips; reset() on re-attach / new serve.

RED-FIRST: ``editors/vscode/navisActions.js`` does not exist on the untouched
tree -- every test here is red today (the node drivers die on the missing
require; the source pins fail on the missing file). The live captures build
their fixtures by calling the REAL serve routes (the posture of
tests/test_vscode_extension_http_client.py) and carry no assertion of their
own, so nothing in this file is green-by-construction before the module
exists.

The REAL server shapes (probed against live EditorApps for this slice, and
re-probed in-test): the plan's table matches them, with one naming note --
the plan's 200 row says "body adds verb and key"; true for archive/restore,
while the MINT 200 carries ``{kind:"ok", changed, minted[], still_keyless}``
(docs/navis.md "Mint keys", captured). planResult's 200 branch must not read
those fields: any 200 with an object body is a success.

A local reference implementation can be validated against these pins with
``REFDES_NAVIS_ACTIONS_JS=/path/to/navisActions.js`` before the real module
lands (the module path defaults to editors/vscode/navisActions.js).

Cross-platform (plan S7, tests/test_crossplatform_lint.py): node subprocesses
read with ``encoding="utf-8"`` (a Windows runner's locale is cp1252 and would
mojibake the non-ASCII in the captured texts), fixtures written with
``newline=""``, servers bind port 0 via EditorApp, no fixed ports, no POSIX-
only tools, Python 3.11 floor. One node process per scenario group;
``skip_no_node`` where node is missing.

No real VS Code window is involved: this slice is the pure decision logic;
the command wiring is S6.2b-2 (plan S7.2: "Cannot prove: any VS Code UI
behavior" -- and this tests nothing of it).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import write_project_config
from serve_support import Client

from refdes import cli as cli_mod
from refdes import keys
from refdes.serve.server import EditorApp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_DIR = os.path.join(REPO_ROOT, "editors", "vscode")
NAVIS_ACTIONS_JS = os.environ.get(
    "REFDES_NAVIS_ACTIONS_JS", os.path.join(VSCODE_DIR, "navisActions.js")
)
NAVIS_TREE_JS = os.path.join(VSCODE_DIR, "navisTree.js")

NODE = shutil.which("node")
NODE_TIMEOUT_S = 120
skip_no_node = pytest.mark.skipif(
    NODE is None, reason="no node on PATH to execute the actions module"
)

DECISION_FIELDS = {"kind", "refresh", "lockWrites", "message"}
KINDS = {"refresh", "error", "warn", "lock"}
EXPORT_NAMES = sorted(
    ["planResult", "rowActions", "selectorFor", "mintAvailable", "createWriteLock"]
)

# The shipped panels' exact wordings (the module reuses these strings;
# tests/test_vscode_navis_tree.py pins the same literals for the tree):
KEYLESS_HINT = "No key yet -- use Mint keys"  # navis-panel.js KEYLESS_TITLE
ORPHAN_HINT = (
    "Marker not found -- hand-restore the marker, then it re-links by key"
)  # navis-panel.js ORPHAN_TITLE

SCHEMA = (
    "site: { title: Navis Actions, out: _site }\n"
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
KEYLESS_TEXT = "A marker nobody minted."

# Two hand-declared keys sharing a 6-char prefix: the prefix selector answers
# 409 ambiguous naming both (the fabricated-key recipe of
# tests/test_serve_navis_write.py, keys.check_char closes the key).
AMBIGUOUS_PREFIX = "abcd12"


def _fabricate(prefix6: str, tail4: str) -> str:
    data = prefix6 + tail4
    assert all(ch in keys.ALPHABET for ch in data), data
    return data + keys.check_char(data)


KEY_A = _fabricate(AMBIGUOUS_PREFIX, "0000")
KEY_B = _fabricate(AMBIGUOUS_PREFIX, "1111")


def _note(item_id: str, title: str, text: str, key: str = "") -> str:
    return (
        f"---\nid: {item_id}\ntype: note\ntitle: {title}\n---\n"
        f"intro\n<!--navi:{key} {text}-->\n"
    )


def _read(path: str) -> str:
    if not os.path.exists(path):
        pytest.fail(
            f"{os.path.relpath(path, REPO_ROOT)} does not exist -- S6.2b has not "
            "landed, and this pin exists to catch it drifting afterwards"
        )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------- live route captures
#
# Every plan S4 row that a real server can produce, captured by POSTing the
# real routes (the cheap-fixture rule of the task: the shapes below ARE the
# server's JSON, not a transcription). No assertions here -- a fixture that
# cannot be captured raises KeyError in the node driver's ids list, and the
# test assertions all run post-node, so the whole test is red until the
# module exists.


def _build(root: pathlib.Path, files: dict[str, str], seed: bool = True) -> str:
    root.mkdir(parents=True, exist_ok=True)
    config = write_project_config(root, SCHEMA)
    items = root / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8", newline="")
    if seed:
        # one writable load mints every keyless marker it sees -- keyless
        # markers are written AFTER this call (the mint test files' recipe)
        assert cli_mod.main(["-c", str(config), "navis", "ls"]) == 0
    return str(config)


def _navi_key(path: pathlib.Path) -> str:
    found = re.findall(r"<!--navi:([0-9a-z]{11}) ", path.read_text(encoding="utf-8"))
    assert found, path
    return found[0]


def capture_write_shapes(tmp_path) -> dict:
    """Every real write-route outcome as the exact {status, body} post() hands
    the module. Four short-lived EditorApps (port 0 each), all stopped."""
    captured: dict = {}
    root = tmp_path / "main"
    config = _build(root, {
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT, KEY_A),
        "note-b.md": _note("NOTE-002", "Beta", BETA_TEXT, KEY_B),
    })
    # the keyless marker lands after the seeding load, so the served project
    # has one: ordinal 3 selects it (the keyless conflict needs it)
    (root / "items" / "note-c.md").write_text(
        _note("NOTE-003", "Gamma", KEYLESS_TEXT), encoding="utf-8", newline=""
    )

    root2 = tmp_path / "journal"
    config2 = _build(root2, {
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
        "note-b.md": _note("NOTE-002", "Beta", BETA_TEXT),
    })
    archived_key = _navi_key(root2 / "items" / "note-b.md")
    assert cli_mod.main(["-c", config2, "navis", "archive", archived_key]) == 0

    root3 = tmp_path / "orphan"
    config3 = _build(root3, {
        "note-a.md": _note("NOTE-001", "Alpha", ALPHA_TEXT),
    })
    orphan_key = _navi_key(root3 / "items" / "note-a.md")
    assert cli_mod.main(["-c", config3, "navis", "archive", orphan_key]) == 0
    # the marker is gone: the record survives as an orphan (design S9 row 3)
    (root3 / "items" / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\nintro\n",
        encoding="utf-8",
        newline="",
    )

    apps = []

    def _start(cfg, **kw):
        app = EditorApp(cfg, poll_interval=60, **kw)
        app.start()
        apps.append(app)
        return app

    def _post(app, verb: str, payload):
        client = Client(app)
        status, body = client.api_post(f"/api/navis/{verb}", payload)
        return {"status": status, "body": body}

    try:
        main = _start(config)
        captured["okTrue"] = _post(main, "archive", {"navi": KEY_A})
        captured["okFalse"] = _post(main, "archive", {"navi": KEY_A})
        captured["restoreOk"] = _post(main, "restore", {"navi": KEY_A})
        captured["notArchived"] = _post(main, "restore", {"navi": KEY_A})
        captured["badRequestNull"] = _post(main, "archive", {"navi": None})
        captured["badRequestRaw"] = _post(main, "archive", [1, 2])
        captured["notFound"] = _post(main, "archive", {"navi": "zzzzzzzzzzzz"})
        captured["ambiguous"] = _post(main, "archive", {"navi": AMBIGUOUS_PREFIX})
        captured["keyless"] = _post(main, "archive", {"navi": "3"})
        captured["mintOk"] = _post(main, "mint", {})

        journal_app = _start(config2)
        journal = root2 / ".refdes" / "editor-transaction"
        journal.mkdir(parents=True)
        (journal / "journal.yaml").write_text("stub", encoding="utf-8", newline="")
        captured["journalPending"] = _post(journal_app, "archive", {"navi": "1"})

        orphan_app = _start(config3)
        captured["orphan"] = _post(orphan_app, "restore", {"navi": orphan_key})

        no_write = _start(config, read_only=True)
        captured["refusedArchive"] = _post(no_write, "archive", {"navi": KEY_A})
        captured["refusedMint"] = _post(no_write, "mint", {})
    finally:
        for app in apps:
            app.stop()
    return captured


# --------------------------------------------------------------- node harness


def _run_driver(tmp_path, driver_src: str, cfg: dict, name: str) -> dict:
    script = tmp_path / name
    script.write_text(driver_src, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(script), json.dumps(cfg)],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the non-ASCII in the captured server texts (the neighbours'
        # harness posture, tests/test_editor_live_calc.py).
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


PLAN_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
let navisActions;
try {
  navisActions = require(cfg.module);
} catch (err) {
  const text = JSON.stringify({fatal: String((err && err.stack) || err)});
  require("fs").writeSync(1, text);
  process.exit(0);
}
const out = {results: {}};
for (const id of cfg.ids) {
  try {
    out.results[id] = navisActions.planResult(cfg.fixtures[id]);
  } catch (err) {
    out.results[id] = {threw: String((err && err.stack) || err)};
  }
}
require("fs").writeSync(1, JSON.stringify(out));
"""


def _run_plan(tmp_path, fixtures: dict) -> dict:
    out = _run_driver(
        tmp_path,
        PLAN_DRIVER,
        {"module": NAVIS_ACTIONS_JS, "ids": sorted(fixtures), "fixtures": fixtures},
        "plan-result-driver.js",
    )
    return out["results"]


def _decision(results: dict, name: str) -> dict:
    d = results[name]
    assert "threw" not in d, (name, d["threw"])
    assert set(d) == DECISION_FIELDS, (name, d)
    assert d["kind"] in KINDS, (name, d)
    assert isinstance(d["refresh"], bool), (name, d)
    assert isinstance(d["lockWrites"], bool), (name, d)
    assert isinstance(d["message"], str), (name, d)
    return d


# ---------------------------------------------------- 1. the plan S4 table,
#                                                     from real server JSON


@skip_no_node
def test_plan_result_maps_every_live_route_outcome_per_the_plan_table(tmp_path):
    """Every row of plan S4's Result-mapping table, fed with the REAL JSON
    the live routes answer (no transcription). The message pins are verbatim
    passthroughs of the captured server text; the flags pin the table's
    refresh/lock column."""
    fixtures = capture_write_shapes(tmp_path)
    results = _run_plan(tmp_path, fixtures)

    for name in ("okTrue", "okFalse", "restoreOk", "mintOk"):
        d = _decision(results, name)
        assert d == {"kind": "refresh", "refresh": True, "lockWrites": False, "message": ""}, (
            name,
            d,
        )
    # changed:false is a SILENT success -- the okFalse fixture is a real
    # re-archive; a toast for it would spam every double-click.

    d = _decision(results, "badRequestNull")
    assert d["kind"] == "error" and d["refresh"] is False and d["lockWrites"] is False, d
    assert d["message"] == fixtures["badRequestNull"]["body"]["error"], d
    d = _decision(results, "badRequestRaw")
    assert d["kind"] == "error", d
    assert d["message"] == "expected a JSON object", d

    for name in ("refusedArchive", "refusedMint"):
        d = _decision(results, name)
        assert d["kind"] == "lock" and d["lockWrites"] is True, (name, d)
        assert d["refresh"] is False, (name, d)
        assert "--no-write" in d["message"], (name, d)
        assert d["message"] == fixtures[name]["body"]["error"], (name, d)

    d = _decision(results, "notFound")
    assert d["kind"] == "warn" and d["refresh"] is True and d["lockWrites"] is False, d
    assert d["message"] == fixtures["notFound"]["body"]["error"], d

    d = _decision(results, "ambiguous")
    assert d["kind"] == "warn" and d["refresh"] is False, d
    for cand in fixtures["ambiguous"]["body"]["candidates"]:
        assert cand["key"] in d["message"], (cand, d)
        assert f"{cand['file']}:{cand['line']}" in d["message"], (cand, d)
        assert cand["text"] in d["message"], (cand, d)

    d = _decision(results, "keyless")
    assert d["kind"] == "warn" and d["refresh"] is False, d
    assert d["message"] == fixtures["keyless"]["body"]["error"], d

    d = _decision(results, "notArchived")
    assert d["kind"] == "warn" and d["refresh"] is True, d
    assert d["message"] == fixtures["notArchived"]["body"]["error"], d

    d = _decision(results, "orphan")
    assert d["kind"] == "warn" and d["refresh"] is False, d
    assert d["message"] == fixtures["orphan"]["body"]["error"], d
    assert "Hand-restore the marker" in d["message"], d

    d = _decision(results, "journalPending")
    assert d["kind"] == "warn" and d["refresh"] is False, d
    assert d["message"] == fixtures["journalPending"]["body"]["error"], d
    assert "editor transaction" in d["message"], d


# ------------------------------------------- 2. the safe-by-default fallbacks


HOSTILE_MD = '[x](command:workbench.action.closeAllEditors) <script>alert("x")</script>'
HOSTILE_CONTROL = HOSTILE_MD + "\n\trefused tail\x00with controls"
LONG_ERROR = "e" * 5000
HTML_500 = "<!doctype html><html><body>gateway boom</body></html>"

GENERIC_FIXTURES = {
    # the three shapes post() can answer that no route's table row names:
    "transport": {"error": "refdes serve is not running"},
    # the security layer's 403 is text/plain, NOT the JSON kind:"refused" --
    # plan S3 "With a stale token": it is a token problem, NOT the read-only
    # lock; a lockWrites:true here would disable writes on a token hiccup.
    "security403": {"status": 403, "body": "forbidden: origin not allowed"},
    "html500": {"status": 500, "body": HTML_500},
    "teapot418": {"status": 418, "body": {"kind": "teapot", "error": "I am a teapot, short and stout"}},
    "unknownKind409": {"status": 409, "body": {"kind": "sideways", "error": "SMUGGLED-BODY-MARKER"}},
    "raw400": {"status": 400, "body": [1, 2, 3]},
    "okRaw200": {"status": 200, "body": "<html>ok</html>"},
    "long400": {"status": 400, "body": {"kind": "bad_request", "error": LONG_ERROR}},
    "hostile400": {"status": 400, "body": {"kind": "bad_request", "error": HOSTILE_CONTROL}},
}


@skip_no_node
def test_plan_result_fails_safely_on_every_result_the_table_does_not_name(tmp_path):
    """The conservative floor: every unnamed status, unnamed JSON kind, raw
    (non-object) body, and the {error} transport case is a kind:"error" with
    a GENERIC message that names the status and never echoes the raw body;
    a 403-without-JSON-kind must NOT lock the session; the server's text is
    passed through truncated to 300 chars with control characters removed;
    hostile text stays an inert plain string; no token-like string ever
    leaves the module."""
    results = _run_plan(tmp_path, GENERIC_FIXTURES)

    d = _decision(results, "transport")
    assert d["kind"] == "error" and d["refresh"] is False and d["lockWrites"] is False, d
    assert d["message"] == "refdes serve is not running", d

    d = _decision(results, "security403")
    assert d["kind"] == "error", d
    assert d["lockWrites"] is False, d  # token problem, not the --no-write lock
    assert "403" in d["message"], d
    assert "forbidden" not in d["message"].lower(), d  # raw body not echoed

    d = _decision(results, "html500")
    assert d["kind"] == "error" and d["lockWrites"] is False, d
    assert "500" in d["message"], d
    assert "gateway boom" not in d["message"], d

    d = _decision(results, "teapot418")
    assert d["kind"] == "error" and d["refresh"] is False, d
    assert "418" in d["message"], d
    assert "teapot" not in d["message"].lower(), d

    d = _decision(results, "unknownKind409")
    assert d["kind"] == "error", d
    assert "409" in d["message"], d
    assert "SMUGGLED-BODY-MARKER" not in d["message"], d

    d = _decision(results, "raw400")
    assert d["kind"] == "error", d
    assert "400" in d["message"], d
    assert "1,2" not in d["message"], d

    d = _decision(results, "okRaw200")
    assert d["kind"] == "error" and d["refresh"] is False, d
    assert "200" in d["message"], d
    assert "<html>" not in d["message"], d

    d = _decision(results, "long400")
    assert d["kind"] == "error", d
    assert len(d["message"]) <= 300, len(d["message"])
    assert d["message"].startswith(LONG_ERROR[:250]), d["message"][:60]

    d = _decision(results, "hostile400")
    assert d["kind"] == "error", d
    assert HOSTILE_MD in d["message"], d  # verbatim, inert, plain string
    assert not re.search(r"[\x00-\x1f\n\t]", d["message"]), repr(d["message"])

    # nothing token-like ever reaches the module's output (plan S6):
    assert "X-Refdes-Token" not in json.dumps(results)
    assert "token=" not in json.dumps(results)


# ------------------------------------------------------------ 3. rowActions


def _row(
    key: str,
    text: str,
    *,
    file: str = "items/note-a.md",
    line: int = 9,
    archived: bool = False,
    orphan: bool = False,
    item: str = "NOTE-001",
    href: str = "note-001.html",
) -> dict:
    return {
        "key": key,
        "key6": key[:6],
        "text": text,
        "item": item,
        "href": href,
        "file": file,
        "line": line,
        "archived": archived,
        "changed": False,
        "orphan": orphan,
    }


MATRIX_ROWS = {
    "keyedActive": _row(KEY_A, ALPHA_TEXT),
    "keylessActive": _row("", KEYLESS_TEXT, line=10),
    "keyedArchived": _row(KEY_B, BETA_TEXT, file="items/note-b.md", archived=True),
    "orphan": _row(
        "9zzzzzzzzzz", "Beta archived then deleted", file="items/note-b.md", archived=True, orphan=True
    ),
    # cannot exist in a real payload (the projection never archives a keyless
    # marker); the matrix includes it to pin the no-crash + Archive-disabled
    # rule, not as a state the UI can reach:
    "keylessArchivedImpossible": _row("", "Impossible state.", archived=True),
}
MATRIX_STATES = {"open": {}, "locked": {"writesLocked": True}}

ROWS_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
let navisActions;
try {
  navisActions = require(cfg.module);
} catch (err) {
  const text = JSON.stringify({fatal: String((err && err.stack) || err)});
  require("fs").writeSync(1, text);
  process.exit(0);
}
const out = {};
for (const [rowName, row] of Object.entries(cfg.rows)) {
  for (const [stateName, state] of Object.entries(cfg.states)) {
    const key = rowName + "/" + stateName;
    try {
      const a = navisActions.rowActions(row, state);
      out[key] = {
        archive: {enabled: a.archive.enabled, tooltip: a.archive.tooltip},
        restore: {enabled: a.restore.enabled, tooltip: a.restore.tooltip},
      };
    } catch (err) {
      out[key] = {threw: String((err && err.stack) || err)};
    }
  }
}
require("fs").writeSync(1, JSON.stringify(out));
"""


def _actions(results: dict, name: str) -> dict:
    v = results[name]
    assert "threw" not in v, (name, v["threw"])
    assert set(v) == {"archive", "restore"}, v
    for half in v.values():
        assert set(half) == {"enabled", "tooltip"}, half
        assert isinstance(half["enabled"], bool), half
        assert isinstance(half["tooltip"], str), half
    return v


@skip_no_node
def test_row_actions_matrix_over_the_five_row_states(tmp_path):
    """The plan S4 disabled-state matrix over (active/archived) x
    (keyed/keyless) x (orphan/not) x (locked/not): a keyed active row archives,
    an archived keyed row restores, the keyless row's Archive tooltip is the
    preview panel's keyless line verbatim, the orphan's Restore tooltip is the
    hand-restore hint, and a locked session disables everything with the
    ``--no-write`` reason in both tooltips. The impossible keyless-archived
    row must not crash and keeps Archive disabled."""
    out = _run_driver(
        tmp_path,
        ROWS_DRIVER,
        {"module": NAVIS_ACTIONS_JS, "rows": MATRIX_ROWS, "states": MATRIX_STATES},
        "row-actions-driver.js",
    )

    v = _actions(out, "keyedActive/open")
    assert v["archive"]["enabled"] is True, v
    assert v["restore"]["enabled"] is False, v

    v = _actions(out, "keylessActive/open")
    assert v["archive"]["enabled"] is False, v
    assert v["archive"]["tooltip"] == KEYLESS_HINT, v  # navisTree.navisDescription's string
    assert v["restore"]["enabled"] is False, v

    v = _actions(out, "keyedArchived/open")
    assert v["restore"]["enabled"] is True, v
    assert v["archive"]["enabled"] is False, v

    v = _actions(out, "orphan/open")
    assert v["restore"]["enabled"] is False, v
    assert v["restore"]["tooltip"] == ORPHAN_HINT, v  # navis-panel.js's ORPHAN_TITLE
    assert v["archive"]["enabled"] is False, v

    v = _actions(out, "keylessArchivedImpossible/open")
    assert v["archive"]["enabled"] is False, v
    assert v["restore"]["enabled"] is False, v

    for row_name in MATRIX_ROWS:
        v = _actions(out, f"{row_name}/locked")
        assert v["archive"]["enabled"] is False, (row_name, v)
        assert v["restore"]["enabled"] is False, (row_name, v)
        assert "--no-write" in v["archive"]["tooltip"], (row_name, v)
        assert "--no-write" in v["restore"]["tooltip"], (row_name, v)


# --------------------------------------- 4. selectorFor / mintAvailable /
#                                          createWriteLock / exports


API_DRIVER = r"""
"use strict";
const cfg = JSON.parse(process.argv[2]);
let navisActions;
try {
  navisActions = require(cfg.module);
} catch (err) {
  const text = JSON.stringify({fatal: String((err && err.stack) || err)});
  require("fs").writeSync(1, text);
  process.exit(0);
}
const out = {exports: {keys: Object.keys(navisActions).sort(), types: {}},
             selectors: {}, mint: {}, lock: {}};
for (const k of out.exports.keys) out.exports.types[k] = typeof navisActions[k];
for (const [name, row] of Object.entries(cfg.rows)) {
  try {
    out.selectors[name] = navisActions.selectorFor(row);
  } catch (err) {
    out.selectors[name] = {threw: String((err && err.message) || err)};
  }
}
for (const [name, c] of Object.entries(cfg.mintCases)) {
  try {
    const m = navisActions.mintAvailable(c.payload, c.state);
    out.mint[name] = {enabled: m.enabled, count: m.count, label: m.label, tooltip: m.tooltip};
  } catch (err) {
    out.mint[name] = {threw: String((err && err.message) || err)};
  }
}
try {
  const lock = navisActions.createWriteLock();
  out.lock.fresh = lock.locked();
  lock.lock();
  out.lock.afterLock = lock.locked();
  lock.lock();
  out.lock.afterDouble = lock.locked();
  const other = navisActions.createWriteLock();
  out.lock.freshOther = other.locked();
  lock.reset();
  out.lock.afterReset = lock.locked();
  out.lock.otherUnaffected = other.locked();
  lock.lock();
  other.lock();
  lock.reset();
  out.lock.resetIsPerInstance = [lock.locked(), other.locked()];
} catch (err) {
  out.lock.threw = String((err && err.stack) || err);
}
require("fs").writeSync(1, JSON.stringify(out));
"""


def _run_api(tmp_path) -> dict:
    mint_cases = {
        "mixed": {
            "payload": {
                "navis": [
                    MATRIX_ROWS["keyedActive"],
                    MATRIX_ROWS["keylessActive"],
                    MATRIX_ROWS["keyedArchived"],
                    MATRIX_ROWS["keylessArchivedImpossible"],  # archived keyless
                    MATRIX_ROWS["orphan"],
                ],
                "counts": {"active": 2, "archived": 3},
            },
            "state": {},
        },
        "allKeyed": {
            "payload": {
                "navis": [MATRIX_ROWS["keyedActive"], MATRIX_ROWS["keyedArchived"]],
                "counts": {"active": 1, "archived": 1},
            },
            "state": {},
        },
        "lockedWithKeyless": {
            "payload": {
                "navis": [MATRIX_ROWS["keyedActive"], MATRIX_ROWS["keylessActive"]],
                "counts": {"active": 2, "archived": 0},
            },
            "state": {"writesLocked": True},
        },
    }
    return _run_driver(
        tmp_path,
        API_DRIVER,
        {"module": NAVIS_ACTIONS_JS, "rows": MATRIX_ROWS, "mintCases": mint_cases},
        "api-driver.js",
    )


@skip_no_node
def test_module_exports_exactly_the_five_pure_functions(tmp_path):
    """The module's whole surface: five plain functions, nothing else. The
    require succeeds under bare node, so the module imports no `vscode`
    (the serveClient.js/navisTree.js purity posture, plan S7.2)."""
    out = _run_api(tmp_path)
    assert out["exports"]["keys"] == EXPORT_NAMES, out["exports"]
    assert set(out["exports"]["types"].values()) == {"function"}, out["exports"]


@skip_no_node
def test_selector_for_is_the_full_key_and_null_for_keyless(tmp_path):
    """The selector the commands POST is the row's FULL key -- never key6 (an
    ambiguous prefix races the projection), never an ordinal (positions move
    between refreshes, docs/navis.md "The serve API"). A keyless row has no
    selector: null (pinned -- the conservative answer, the caller must not
    POST it)."""
    out = _run_api(tmp_path)
    keyed = out["selectors"]["keyedActive"]
    assert keyed == KEY_A, out["selectors"]
    assert keyed != MATRIX_ROWS["keyedActive"]["key6"], keyed
    archived = out["selectors"]["keyedArchived"]
    assert archived == KEY_B, out["selectors"]
    assert out["selectors"]["keylessActive"] is None, out["selectors"]
    assert out["selectors"]["keylessArchivedImpossible"] is None, out["selectors"]
    assert out["selectors"]["orphan"] == "9zzzzzzzzzz", out["selectors"]


@skip_no_node
def test_mint_available_counts_keyless_rows_including_archived(tmp_path):
    """The Mint pill (plan S4, docs/navis.md "Mint keys (N)"): count = keyless
    rows among ALL rows (active AND archived), enabled iff count > 0 and the
    session is not locked, label `Mint keys (N)`."""
    out = _run_api(tmp_path)["mint"]

    m = out["mixed"]
    assert "threw" not in m, m
    assert m["count"] == 2, m  # keylessActive + the archived keyless row
    assert m["enabled"] is True, m
    assert m["label"] == "Mint keys (2)", m
    assert isinstance(m["tooltip"], str), m

    m = out["allKeyed"]
    assert m["count"] == 0, m
    assert m["enabled"] is False, m
    assert isinstance(m["label"], str), m

    m = out["lockedWithKeyless"]
    assert m["count"] == 1, m
    assert m["enabled"] is False, m  # locked: the pill is disabled, count stands
    assert isinstance(m["tooltip"], str), m


@skip_no_node
def test_create_write_lock_locks_and_resets(tmp_path):
    """The session lock (plan S4: a 403 refused locks writes for the rest of
    the session; reset() on re-attach / new serve). Plain state, per instance,
    idempotent lock, resettable."""
    lock = _run_api(tmp_path)["lock"]
    assert "threw" not in lock, lock["threw"]
    assert lock["fresh"] is False, lock
    assert lock["afterLock"] is True, lock
    assert lock["afterDouble"] is True, lock
    assert lock["freshOther"] is False, lock
    assert lock["afterReset"] is False, lock
    assert lock["otherUnaffected"] is False, lock
    assert lock["resetIsPerInstance"] == [False, True], lock


# ------------------------------------------------------------- 5. source pins


def test_the_module_imports_nothing_it_must_not():
    """Plan S6/S7.2 purity: the module is drivable under bare node and touches
    no transport, no files, no editor host. No require of vscode/http/https/
    net/url/fs/child_process, no fetch(), no MarkdownString (row text is
    untrusted -- plain strings only), and it never names the launch secret
    (the token lives in ServeClient, plan S6). RED today: the file does not
    exist."""
    source = _read(NAVIS_ACTIONS_JS)
    banned = re.compile(
        r'require\(\s*["\'](?:vscode|http|https|net|url|fs|child_process)["\']\s*\)'
    )
    offenders = banned.findall(source)
    assert not offenders, f"navisActions.js requires {offenders}"
    assert not re.search(r"\bfetch\s*\(", source), "navisActions.js calls fetch()"
    assert "MarkdownString" not in source, (
        "navisActions.js mentions MarkdownString -- row/server text is "
        "untrusted; every rendered string is plain (plan S6)"
    )
    assert "Origin" not in source, (
        "navisActions.js names Origin -- header policy lives in serveClient.js "
        "post() (plan S4); the decision module must not grow a second one"
    )
    assert "token" not in source.lower(), (
        "navisActions.js names a token: the launch secret must never reach the "
        "actions' output (plan S6, the navisTree.js rule)"
    )


def test_the_disabled_state_wordings_are_the_shipped_panel_strings():
    """The disabled-state tooltips reuse the SHIPPED strings: the tree module's
    keyless line (navisTree.js, pinned by tests/test_vscode_navis_tree.py) and
    the preview panel's orphan hint (navis-panel.js's ORPHAN_TITLE -- the
    wording docs/navis.md quotes for the Restore-disabled row). Pin: both
    strings appear VERBATIM in the actions module, and their shipped sources
    still carry them (a wording drift in a panel is a user-visible drift).
    RED today: the actions module does not exist."""
    actions = _read(NAVIS_ACTIONS_JS)
    assert KEYLESS_HINT in actions, (
        "navisActions.js does not spell the keyless tooltip verbatim -- it "
        "must equal navisTree.navisDescription's string"
    )
    assert ORPHAN_HINT in actions, (
        "navisActions.js does not spell the orphan tooltip verbatim -- it "
        "must equal navis-panel.js's ORPHAN_TITLE"
    )
    tree = _read(NAVIS_TREE_JS)
    assert f'"{KEYLESS_HINT}"' in tree, (
        "navisTree.js no longer carries the keyless line the actions module "
        "pins equal -- re-check navis-panel.js's KEYLESS_TITLE and update both"
    )
    preview = _read(
        os.path.join(REPO_ROOT, "src", "refdes", "serve", "static", "navis-panel.js")
    )
    assert f"'{ORPHAN_HINT}'" in preview, (
        "navis-panel.js no longer carries the orphan hint the actions module "
        "pins equal -- re-check docs/navis.md's Restore-disabled wording"
    )
