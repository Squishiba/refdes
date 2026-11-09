"""W5b.4c-1a contract tests: the tick pane's DECISION MODEL (docs/design/
thread-workbench-w5b-plan.md, §4 W5b.4 + §6 Q1/Q3/Q5/Q6/Q8, all RATIFIED
2026-11-06).

The module under test is `src/refdes/serve/static/tick-pane.js`: ONE new pure
ES module -- the pane's decision logic over plain objects the DOM glue builds
(4c-1b). NO DOM, no network, no storage, no page globals, and it imports
NOTHING. The harnesses below define no `document`, `window`, `fetch` or
`sessionStorage` globals (node has none of them), so a module that touches
one fails the import itself -- the purity proof runs, it is not only a text
scan. Harness posture: tests/test_tick_drafts.py (one node process per
scenario group, skip when node is absent, utf-8 decoding, node timeouts).

The pinned export surface, EXACTLY these names (the `exports` scenario pins
the module's key set -- anything more or less fails):

    panelFromRows(panel)
      panel = {tipKey, revision, rows: [{taskId, state, tickStates, checked}]}
        // the rendered rows: tickStates is the row's comma list of legal
        // tick targets (data-refdes-tick-states), checked is the rendered
        // `checked` attribute (present iff the state is `done`)
      -> {canDraft, reason, rows: [{taskId, draftable, reason, targets}]}
      canDraft is false -- with a plain-string reason naming the tip's
      missing key/revision and PREVIEW-ONLY -- when tipKey or revision is
      missing/empty; a row is draftable only when canDraft AND taskId is a
      non-empty string AND tickStates is non-empty; an id-less row (taskId
      "") is NOT draftable, its reason saying the task has no id so it
      cannot be saved. targets is tickStates split, trimmed, empties dropped.

    wantedState(row, nowChecked)
      -> the state a click names: nowChecked EQUAL to the row's rendered
      checked returns the row's rendered state (the un-tick back to the
      original, Q6(b)); otherwise the FIRST target of its tickStates
      (open -> "done"; done -> "open"; dropped -> "open" -- the markup
      emits `checked` iff state is done, so ticking a dropped row names
      "open": see test_the_markup...below, pinned from the server's own
      _ticks_for).

    applyDraft(rows, pendingTicks)
      pendingTicks = [[taskId, wantedState], ...] (tick-drafts.js's
      pendingTicks(tipKey) shape)
      -> {rows: [{taskId, checked, pending}], orphans: [[taskId, state]]}
      a pending tick sets that row's checked per its wanted state (checked
      iff "done") and marks pending; a draft entry whose taskId matches no
      row is an ORPHAN -- returned, NOT applied (nothing silently dropped);
      the empty taskId never matches; hostile ids (`__proto__`,
      `constructor`) are ordinary data: a row with such an id gets its tick,
      an entry for a missing row is an orphan, and Object.prototype is
      never polluted.

    indicator({pending, stale, orphans, canDraft}) -> {text, hidden}
      "" + hidden for 0 pending and no orphans; "1 unsaved tick" / "N
      unsaved ticks" (Q8's ratified header count); a stale draft adds a
      clause saying it was made against an older version and saving will
      ask to resolve (Q3(a)); orphans add "(K no longer match a task)";
      canDraft false -> text says ticks on this tip are preview-only,
      nothing is saved. Plain strings only.

    isStale(draftRevision, panelRevision) -> true only when both are
      non-empty strings and differ (a keyless tip is never stale: no
      revision, nothing to be stale against).

    tabLabel(baseLabel, pendingCount) -> baseLabel for 0, `${baseLabel}
      (N)` otherwise (Q5(a): each tip's tab shows its OWN pending count).

    needsUnloadPrompt(counts) -> true iff any tip has pending > 0. counts
      is tick-drafts' counts() object -- NULL-PROTOTYPE, so a naive
      for-in/hasOwnProperty-free walk over a plain object is the bug this
      pins against.

    discardPlan(rows) -> {rows: [{taskId, checked}]}
      the checked state every row returns to on discard: the RENDERED state
      (Q8(a): what the file says -- the draft never wrote a byte).

tests/test_serve_static.py lists `static/*.js` at COLLECTION time, so the
new module is auto-picked-up by its inline-handler / dynamic-code / balance
checks the moment it lands; the source pins below mirror the same rules
(plus the no-globals / imports-nothing contract) for this module alone.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO_ROOT, "src", "refdes", "serve", "static")
TICK_PANE_JS = os.path.join(STATIC, "tick-pane.js")

NODE = shutil.which("node")

# One node spawn per scenario; generous for a cold process start on a shared
# runner (the timeout note in tests/test_tick_drafts.py).
NODE_TIMEOUT_S = 120

EXPORT_NAMES = [
    "applyDraft",
    "discardPlan",
    "indicator",
    "isStale",
    "needsUnloadPrompt",
    "panelFromRows",
    "tabLabel",
    "wantedState",
]

# -- the node harness ---------------------------------------------------------

HARNESS = """
import { pathToFileURL } from 'node:url';

const [panePath, scenario, seedJson] = process.argv.slice(2);
const input = seedJson ? JSON.parse(seedJson) : {};

const mod = await import(pathToFileURL(panePath).href);
const {
  panelFromRows, wantedState, applyDraft, indicator,
  isStale, tabLabel, needsUnloadPrompt, discardPlan,
} = mod;

const out = { scenario, exports: Object.keys(mod).sort() };

// The rendered rows, exactly as the W5b.3/4a markup spells them: open/done/
// dropped rows (checked iff done, targets from TICK_TARGETS) and an id-less
// row (data-refdes-task is empty there).
const PANEL = {
  tipKey: 'LOG-001@k-9',
  revision: 'r-7',
  rows: [
    { taskId: 'T-1', state: 'open', tickStates: 'done,dropped', checked: false },
    { taskId: 'T-2', state: 'done', tickStates: 'open', checked: true },
    { taskId: 'T-3', state: 'dropped', tickStates: 'open', checked: false },
    { taskId: '', state: 'open', tickStates: 'done,dropped', checked: false },
  ],
};

if (scenario === 'panelDraftable') {
  out.panel = panelFromRows(PANEL);
}

if (scenario === 'panelKeyless') {
  out.noKey = panelFromRows({ tipKey: '', revision: 'r-7', rows: PANEL.rows });
  out.noRevision = panelFromRows({ tipKey: 'k-9', revision: '', rows: PANEL.rows });
  out.missing = panelFromRows({ rows: PANEL.rows });
  out.nullish = panelFromRows({ tipKey: null, revision: null, rows: PANEL.rows });
}

if (scenario === 'panelIdLess') {
  const p = panelFromRows(PANEL);
  out.idLess = p.rows.find((r) => r.taskId === '');
}

if (scenario === 'targetsParse') {
  out.rows = panelFromRows({
    tipKey: 'k-9', revision: 'r-7',
    rows: [
      { taskId: 'T-1', state: 'open', tickStates: 'done, dropped', checked: false },
      { taskId: 'T-2', state: 'open', tickStates: 'open,,', checked: false },
      { taskId: 'T-3', state: 'open', tickStates: ' ', checked: false },
      { taskId: 'T-4', state: 'open', tickStates: '', checked: false },
    ],
  }).rows;
}

if (scenario === 'wantedStates') {
  const [open, done, dropped] = PANEL.rows;
  out.openTicked = wantedState(open, true);
  out.openUnticked = wantedState(open, false);
  out.doneUnticked = wantedState(done, false);
  out.doneReticked = wantedState(done, true);
  out.droppedTicked = wantedState(dropped, true);
  out.droppedUnticked = wantedState(dropped, false);
}

if (scenario === 'applyDraft') {
  out.result = applyDraft(PANEL.rows, [['T-1', 'done'], ['T-2', 'open']]);
}

if (scenario === 'applyDraftOrphan') {
  out.result = applyDraft(PANEL.rows, [['T-404', 'done']]);
}

if (scenario === 'applyDraftHostile') {
  const rows = [
    { taskId: '__proto__', state: 'open', tickStates: 'done,dropped', checked: false },
    { taskId: 'constructor', state: 'done', tickStates: 'open', checked: true },
    { taskId: 'T-1', state: 'open', tickStates: 'done,dropped', checked: false },
  ];
  out.result = applyDraft(rows, [
    ['__proto__', 'done'], ['constructor', 'open'], ['', 'done'], ['T-1', 'dropped'],
  ]);
  out.protoClean =
    ({}).checked === undefined && ({}).pending === undefined &&
    ({}).done === undefined && ({}).dropped === undefined;
}

if (scenario === 'applyDraftDuplicates') {
  out.result = applyDraft(PANEL.rows, [['T-1', 'done'], ['T-1', 'dropped']]);
}

if (scenario === 'indicator') {
  out.zero = indicator({ pending: 0, stale: false, orphans: 0, canDraft: true });
  out.one = indicator({ pending: 1, stale: false, orphans: 0, canDraft: true });
  out.many = indicator({ pending: 3, stale: false, orphans: 0, canDraft: true });
  out.stale = indicator({ pending: 1, stale: true, orphans: 0, canDraft: true });
  out.orphans = indicator({ pending: 2, stale: false, orphans: 2, canDraft: true });
  out.orphanOnly = indicator({ pending: 0, stale: false, orphans: 1, canDraft: true });
  out.preview = indicator({ pending: 3, stale: true, orphans: 2, canDraft: false });
}

if (scenario === 'stale') {
  out.diff = isStale('r-7', 'r-8');
  out.same = isStale('r-7', 'r-7');
  out.emptyDraft = isStale('', 'r-8');
  out.emptyPanel = isStale('r-7', '');
  out.nullDraft = isStale(null, 'r-8');
  out.nullPanel = isStale('r-7', null);
  out.bothNull = isStale(null, null);
  out.undef = isStale(undefined, 'r-8');
}

if (scenario === 'tabLabel') {
  out.zero = tabLabel('LOG-001@k-9', 0);
  out.one = tabLabel('LOG-001@k-9', 1);
  out.many = tabLabel('LOG-002@k-9', 4);
}

if (scenario === 'unload') {
  out.empty = needsUnloadPrompt({});
  const np = Object.create(null);
  out.npEmpty = needsUnloadPrompt(np);
  np['LOG-001@k-9'] = 0;
  out.npZero = needsUnloadPrompt(np);
  np['LOG-002@k-9'] = 2;
  out.npDirty = needsUnloadPrompt(np);
  out.plainZero = needsUnloadPrompt({ a: 0, b: 0 });
  out.plainDirty = needsUnloadPrompt({ a: 0, b: 1 });
}

if (scenario === 'discard') {
  out.plan = discardPlan(PANEL.rows);
}

process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path, scenario: str) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to run the tick pane module")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(harness), TICK_PANE_JS, scenario],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake non-ASCII (an em dash in a reason string) on the way back.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness {scenario!r} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# -- the module's identity: exports and purity --------------------------------


def test_the_module_exists_and_is_served(tmp_path):
    assert os.path.isfile(TICK_PANE_JS)


def test_the_exports_are_exactly_the_pinned_names(tmp_path):
    r = _run(tmp_path, "exports")
    assert r["exports"] == EXPORT_NAMES


# -- panelFromRows: can this panel draft at all? -------------------------------


def test_a_keyed_panel_drafts_and_marks_every_row_its_draftability(tmp_path):
    r = _run(tmp_path, "panelDraftable")
    panel = r["panel"]
    assert panel["canDraft"] is True
    assert panel["reason"] == ""
    rows = panel["rows"]
    assert [row["taskId"] for row in rows] == ["T-1", "T-2", "T-3", ""]
    assert all(set(row) == {"taskId", "draftable", "reason", "targets"} for row in rows)
    by_id = {row["taskId"]: row for row in rows}
    assert by_id["T-1"]["draftable"] is True and by_id["T-1"]["reason"] == ""
    assert by_id["T-1"]["targets"] == ["done", "dropped"]
    assert by_id["T-2"]["draftable"] is True and by_id["T-2"]["targets"] == ["open"]
    # a dropped row IS draftable: Q6(b) gives it the reopening tick
    assert by_id["T-3"]["draftable"] is True and by_id["T-3"]["targets"] == ["open"]


def test_a_panel_without_key_or_revision_is_preview_only(tmp_path):
    r = _run(tmp_path, "panelKeyless")
    for name in ("noKey", "noRevision", "missing", "nullish"):
        panel = r[name]
        assert panel["canDraft"] is False, f"{name}: the panel may not draft"
        assert isinstance(panel["reason"], str) and panel["reason"], f"{name}: no reason string"
        assert "preview-only" in panel["reason"].lower(), f"{name}: {panel['reason']!r}"
        assert all(row["draftable"] is False for row in panel["rows"])


def test_an_id_less_row_cannot_be_saved(tmp_path):
    r = _run(tmp_path, "panelIdLess")
    row = r["idLess"]
    assert row["draftable"] is False
    assert isinstance(row["reason"], str) and row["reason"]
    assert "no id" in row["reason"].lower(), row["reason"]
    assert "saved" in row["reason"].lower(), row["reason"]


def test_targets_are_split_trimmed_and_empties_dropped(tmp_path):
    r = _run(tmp_path, "targetsParse")
    by_id = {row["taskId"]: row for row in r["rows"]}
    assert by_id["T-1"]["targets"] == ["done", "dropped"]
    assert by_id["T-1"]["draftable"] is True
    assert by_id["T-2"]["targets"] == ["open"]
    assert by_id["T-3"]["targets"] == [] and by_id["T-3"]["draftable"] is False
    assert by_id["T-4"]["targets"] == [] and by_id["T-4"]["draftable"] is False


# -- wantedState: the state a click names --------------------------------------


def test_the_markup_renders_a_dropped_row_unticked_with_open_only():
    """The fact wantedState's dropped case rests on, pinned from the SERVER's
    own model (task_pane._ticks_for): a dropped row gets `checked` False (the
    template emits `checked` iff the state is `done`) and
    data-refdes-tick-states="open". So ticking a dropped row (nowChecked
    true != rendered false) names its first -- only -- target, "open": the
    row reopens. wantedState must agree (next test)."""
    from refdes.task_pane import TICK_TARGETS, _ticks_for

    ticks = _ticks_for(
        [
            {"id": "T-1", "state": "open"},
            {"id": "T-2", "state": "done"},
            {"id": "T-3", "state": "dropped"},
        ],
        "LOG-001",
    )
    assert TICK_TARGETS == {"open": "done,dropped", "done": "open", "dropped": "open"}
    assert [tick["targets"] for tick in ticks] == ["done,dropped", "open", "open"]
    assert [tick["checked"] for tick in ticks] == [False, True, False]


def test_a_click_names_its_first_target_and_an_untick_names_the_rendered_state(tmp_path):
    """Q6(b) ratified: open->done, open->dropped, un-tick (done->open),
    dropped->open. A click landing the checkbox on its RENDERED state names
    that rendered state (the un-tick back to the original -- draft-free);
    any other click names the FIRST target of the row's tickStates."""
    r = _run(tmp_path, "wantedStates")
    assert r["openTicked"] == "done"      # first target of "done,dropped"
    assert r["openUnticked"] == "open"    # back to rendered: no change
    assert r["doneUnticked"] == "open"
    assert r["doneReticked"] == "done"    # back to rendered: no change
    assert r["droppedTicked"] == "open"   # the reopening tick (see the markup pin)
    assert r["droppedUnticked"] == "dropped"


# -- applyDraft: the draft over the rendered rows ------------------------------


def test_a_pending_tick_moves_its_row_and_marks_it(tmp_path):
    r = _run(tmp_path, "applyDraft")
    result = r["result"]
    assert all(set(row) == {"taskId", "checked", "pending"} for row in result["rows"])
    assert result["rows"] == [
        {"taskId": "T-1", "checked": True, "pending": True},   # open -> done
        {"taskId": "T-2", "checked": False, "pending": True},   # done -> open (un-tick)
        {"taskId": "T-3", "checked": False, "pending": False},
        {"taskId": "", "checked": False, "pending": False},
    ]
    assert result["orphans"] == []


def test_a_draft_entry_with_no_row_is_an_orphan_not_a_drop(tmp_path):
    """The tip moved under the draft (Q3's pane-side notice, Q1's reload with
    a row gone): the entry is RETURNED as an orphan and NOT applied -- the
    rows stay as rendered; nothing is silently dropped, the indicator counts
    it, the save sends what the draft holds."""
    r = _run(tmp_path, "applyDraftOrphan")
    result = r["result"]
    assert result["orphans"] == [["T-404", "done"]]
    assert result["rows"] == [
        {"taskId": "T-1", "checked": False, "pending": False},
        {"taskId": "T-2", "checked": True, "pending": False},
        {"taskId": "T-3", "checked": False, "pending": False},
        {"taskId": "", "checked": False, "pending": False},
    ]


def test_hostile_task_ids_are_data_never_code(tmp_path):
    """A task id is user data (an authored id lands in data-refdes-task):
    `__proto__` and `constructor` are ordinary ids -- the rows carrying them
    take their ticks, an entry with the EMPTY taskId matches nothing and is
    an orphan, and Object.prototype stays clean (Map / null-prototype, not a
    naive object literal)."""
    r = _run(tmp_path, "applyDraftHostile")
    result = r["result"]
    assert result["rows"] == [
        {"taskId": "__proto__", "checked": True, "pending": True},
        {"taskId": "constructor", "checked": False, "pending": True},
        {"taskId": "T-1", "checked": False, "pending": True},
    ]
    assert result["orphans"] == [["", "done"]]
    assert r["protoClean"] is True, "Object.prototype was polluted by a task id"


def test_a_duplicate_entry_wins_by_last_write(tmp_path):
    """Conservative pin: pendingTicks is insertion-ordered (tick-drafts.js
    documents it), and a draft holds ONE entry per id -- a duplicate pair in
    a hand-built list resolves to the LAST entry, the way Map.set does."""
    r = _run(tmp_path, "applyDraftDuplicates")
    assert r["result"]["rows"][0] == {"taskId": "T-1", "checked": False, "pending": True}
    assert r["result"]["orphans"] == []


# -- indicator: Q8's "N unsaved ticks" header ----------------------------------


def test_the_indicator_counts_pending_ticks_in_words(tmp_path):
    r = _run(tmp_path, "indicator")
    assert r["zero"] == {"text": "", "hidden": True}
    assert r["one"]["hidden"] is False
    assert r["one"]["text"] == "1 unsaved tick"
    assert r["many"]["hidden"] is False
    assert r["many"]["text"] == "3 unsaved ticks"


def test_a_stale_draft_says_saving_will_ask_to_resolve(tmp_path):
    r = _run(tmp_path, "indicator")
    text = r["stale"]["text"]
    assert r["stale"]["hidden"] is False
    assert "1 unsaved tick" in text
    assert "older version" in text.lower(), text
    assert "resolve" in text.lower(), text


def test_orphans_say_the_tasks_they_no_longer_match(tmp_path):
    r = _run(tmp_path, "indicator")
    assert r["orphans"]["hidden"] is False
    assert "2 unsaved ticks" in r["orphans"]["text"]
    assert "(2 no longer match a task)" in r["orphans"]["text"], r["orphans"]["text"]
    # pending 0 with an orphan keeps the indicator VISIBLE (it is not "" /
    # hidden: the rule is 0 pending AND no orphans)
    assert r["orphanOnly"]["hidden"] is False
    assert "(1 no longer match a task)" in r["orphanOnly"]["text"], r["orphanOnly"]["text"]


def test_a_keyless_panel_says_ticks_are_preview_only(tmp_path):
    r = _run(tmp_path, "indicator")
    preview = r["preview"]
    assert preview["hidden"] is False
    assert "preview-only" in preview["text"].lower(), preview["text"]


# -- isStale / tabLabel / needsUnloadPrompt / discardPlan -----------------------


def test_staleness_needs_two_revisions_that_differ(tmp_path):
    """Q3(a) is a revision compare: a keyless tip (no revision to stamp --
    tick-drafts drops the stamp with the last tick) is NEVER stale; two
    non-empty strings that differ are."""
    r = _run(tmp_path, "stale")
    assert r["diff"] is True
    assert r["same"] is False
    assert r["emptyDraft"] is False
    assert r["emptyPanel"] is False
    assert r["nullDraft"] is False
    assert r["nullPanel"] is False
    assert r["bothNull"] is False
    assert r["undef"] is False


def test_each_tip_tab_carries_its_own_pending_count(tmp_path):
    """Q5(a) ratified: the tab-switch UI shows each tip's OWN pending count;
    a clean tab carries no count at all."""
    r = _run(tmp_path, "tabLabel")
    assert r["zero"] == "LOG-001@k-9"
    assert r["one"] == "LOG-001@k-9 (1)"
    assert r["many"] == "LOG-002@k-9 (4)"


def test_the_unload_prompt_fires_for_any_tip_with_a_pending_tick(tmp_path):
    """counts() is the null-prototype object tick-drafts.js returns (Q1(b):
    the per-tab mirror, Q5(a): one draft per tip). The prompt is per-PAGE:
    true iff ANY tip has pending > 0 -- and it must read a null-prototype
    object as ordinary data (a hasOwnProperty call on it is a TypeError)."""
    r = _run(tmp_path, "unload")
    assert r["empty"] is False
    assert r["npEmpty"] is False
    assert r["npZero"] is False
    assert r["npDirty"] is True
    assert r["plainZero"] is False
    assert r["plainDirty"] is True


def test_discard_returns_every_row_to_the_rendered_state(tmp_path):
    """Q8(a) ratified: Discard is the explicit release -- every row returns
    to what the FILE says (the rendered checked), the draft's ticks are
    gone; a done row stays checked, an open row stays unchecked."""
    r = _run(tmp_path, "discard")
    plan = r["plan"]
    assert set(plan) == {"rows"}
    assert plan["rows"] == [
        {"taskId": "T-1", "checked": False},
        {"taskId": "T-2", "checked": True},
        {"taskId": "T-3", "checked": False},
        {"taskId": "", "checked": False},
    ]
    assert all(set(row) == {"taskId", "checked"} for row in plan["rows"])


# -- source pins: pure, self-contained, served-clean ----------------------------

INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")


def _strip_js_comments(text: str) -> str:
    """The string-aware comment stripper from tests/test_serve_static.py: the
    purity scan runs on code, not prose."""
    out = []
    i = 0
    n = len(text)
    in_string = None
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "'\"`":
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _pane_code() -> str:
    with open(TICK_PANE_JS, encoding="utf-8") as fh:
        return _strip_js_comments(fh.read())


def test_the_module_is_pure_no_dom_no_network_no_storage(tmp_path):
    """4c-1a is the pure half: the DOM glue (4c-1b) owns every page touch.
    The harnesses above prove the same fact by running the module with NO
    document/window/fetch/sessionStorage globals defined (node has none of
    them); this pins it for the whole list."""
    code = _pane_code()
    for forbidden in (
        "document",
        "window",
        "fetch",
        "XMLHttpRequest",
        "eval",
        "innerHTML",
        "sessionStorage",
        "localStorage",
        "globalThis",
    ):
        assert forbidden not in code, f"tick-pane.js touches {forbidden!r}"


def test_the_module_imports_nothing(tmp_path):
    code = _pane_code()
    assert JS_IMPORT.findall(code) == [], "tick-pane.js must be self-contained"
    assert "tick-drafts.js" not in code, "pure module: not even a reference to the store"


def test_the_module_passes_the_served_js_rules(tmp_path):
    """test_serve_static.py's js_files() lists static/*.js at collection
    time, so the new file is picked up by its inline-handler / dynamic-code /
    ES2020 balance checks automatically the moment it lands; this pins the
    same checks (and the file's presence in the served dir) here."""
    listing = [n for n in os.listdir(STATIC) if n.endswith(".js")]
    assert "tick-pane.js" in listing, "the file is not in the served static dir"
    code = _pane_code()
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code), "no eval/new Function in the editor"
    assert "javascript:" not in code
    # the ES2020 balance check from test_serve_static.py, mirrored
    depth = {"(": ")", "[": "]", "{": "}"}
    stack = []
    in_string = None
    escaped = False
    for ch in code:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in "'\"`":
            in_string = ch
        elif ch in depth:
            stack.append(depth[ch])
        elif stack and ch in ")]}":
            assert stack.pop() == ch, f"unbalanced {ch}"
    assert not stack, f"unclosed {stack}"
