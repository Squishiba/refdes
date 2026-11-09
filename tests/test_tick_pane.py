"""W5b.4c-1a contract tests: the tick pane's decision model (docs/design/
thread-workbench-w5b-plan.md, §4 W5b.4 + §6 Q1/Q3/Q5/Q6/Q8, all RATIFIED
2026-11-06).

The module under test is `src/refdes/serve/static/tick-pane.js`: ONE new pure
ES module holding the DECISION LOGIC of the tick pane's draft UI -- no DOM,
no network, no storage, no globals. The DOM glue (4c-1b) will build the plain
objects these functions read from the W5b.3/W5b.4a markup
(`pane.html.j2` / `task_pane.py`) and feed them in; the draft itself is
`tick-drafts.js` (merged #460). The harnesses below deliberately define NO
`document`, `window`, `localStorage` or `sessionStorage` globals: a module
that touches one of those fails the import itself (the purity proof runs, it
is not only a text scan; `fetch` exists in modern node, so it is pinned by
source scan only). Harness posture: tests/test_tick_drafts.py -- one node
process per scenario, skip when node is absent, utf-8 decoding of node's
output.

The pinned export surface (the 4c-1b DOM glue builds against this):

    panelFromRows(panel) -> {canDraft, reason, rows:[{taskId, draftable,
                                reason, targets}]}
        panel = {tipKey, revision, rows:[{taskId, state, tickStates,
                                          checked}]}  // the rendered rows
    wantedState(row, nowChecked) -> string   // the state a click names
        row = {state, checked, tickStates}   // the rendered row
    applyDraft(rows, pendingTicks) -> {rows: [{taskId, checked, pending}],
                                       orphans: [[taskId, state], ...]}
        pendingTicks = [[taskId, wantedState], ...]  // tick-drafts'
        pendingTicks(tipKey) shape, exactly
    indicator({pending, stale, orphans, canDraft}) -> {text, hidden}
    isStale(draftRevision, panelRevision) -> bool
    tabLabel(baseLabel, pendingCount) -> string
    needsUnloadPrompt(counts) -> bool        // tick-drafts' counts() object
    discardPlan(rows) -> {rows: [{taskId, checked}]}

Pinned plain strings (4c-1b renders these verbatim -- Q8's indicator wording
is a header sentence, and the pane says plainly when there is no save):

    PANEL_PREVIEW_REASON = "This tip has no key/revision -- ticks here are
                            preview-only."
    NO_ID_REASON         = "This task has no id -- it cannot be saved."
    INDICATOR_PREVIEW    = "Ticks on this tip are preview-only -- nothing
                            is saved."
    indicator count text  "1 unsaved tick" / "N unsaved ticks" (Q8's
                            ratified "3 unsaved ticks" header)
    indicator stale suffix " -- this draft was made against an older
                            version; saving will ask to resolve." (Q3(a):
                            the save will land on a Conflict, not a merge)
    indicator orphan suffix " (K no longer match a task)"

What the server's own markup says about a DROPPED row (verified by running
`task_pane._ticks_for` -- see test_the_server_renders_a_dropped_row_unticked
below, which pins it): a dropped row renders UNCHECKED (`checked` is emitted
iff the state is `done`) with `data-refdes-tick-states="open"`. So
`wantedState(droppedRow, true)` -- ticking a dropped row -- names "open":
the only tick a dropped row can make is a reopening (Q6(b)), and the FIRST
target rule gives it for free.

`tests/test_serve_static.py::js_files()` lists `static/*.js` at COLLECTION
time, so the new file is picked up by that module's inline-handler /
dynamic-code / balance checks automatically the moment it lands; the last
test here pins the same rules (and the file's presence in the served dir).

Development hook: REFDES_TICK_PANE_JS points the harnesses at an alternative
module path (used to prove these tests can go green before the real module
exists; CI leaves it unset).
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
TICK_PANE_JS = os.environ.get(
    "REFDES_TICK_PANE_JS", os.path.join(STATIC, "tick-pane.js")
)

NODE = shutil.which("node")

# One node spawn per scenario; generous for a cold process start on a shared
# runner (the timeout note in tests/test_tick_drafts.py).
NODE_TIMEOUT_S = 120

PANEL_PREVIEW_REASON = (
    "This tip has no key/revision -- ticks here are preview-only."
)
NO_ID_REASON = "This task has no id -- it cannot be saved."
INDICATOR_PREVIEW = "Ticks on this tip are preview-only -- nothing is saved."
STALE_CLAUSE = (
    " -- this draft was made against an older version; saving will ask to resolve."
)


# -- the node harness ---------------------------------------------------------

HARNESS = """
import { pathToFileURL } from 'node:url';

const [panePath, scenario, seedJson] = process.argv.slice(2);
const input = JSON.parse(seedJson);
const mod = await import(pathToFileURL(panePath).href);
const {
  panelFromRows, wantedState, applyDraft, indicator,
  isStale, tabLabel, needsUnloadPrompt, discardPlan,
} = mod;

const PANEL = {
  tipKey: 'LOG-001@k-9',
  revision: 'rev-7',
  rows: [
    { taskId: 'T-1', state: 'open', tickStates: 'done,dropped', checked: false },
    { taskId: 'T-2', state: 'done', tickStates: 'open', checked: true },
    { taskId: 'T-3', state: 'dropped', tickStates: 'open', checked: false },
    { taskId: '', state: 'open', tickStates: 'done,dropped', checked: false },
  ],
};

const out = { scenario };

if (scenario === 'panelDraftable') {
  out.panel = panelFromRows(PANEL);
}

if (scenario === 'panelIdentity') {
  out.panel = panelFromRows(input.panel);
}

if (scenario === 'targetsParse') {
  out.panels = input.states.map((tickStates) => panelFromRows({
    tipKey: 'LOG-001@k-9', revision: 'rev-7',
    rows: [{ taskId: 'T-1', state: 'open', tickStates, checked: false }],
  }).rows[0]);
}

if (scenario === 'wantedStates') {
  const ROW_OPEN = { state: 'open', tickStates: 'done,dropped', checked: false };
  const ROW_DONE = { state: 'done', tickStates: 'open', checked: true };
  const ROW_DROPPED = { state: 'dropped', tickStates: 'open', checked: false };
  out.openTick = wantedState(ROW_OPEN, true);
  out.openUntick = wantedState(ROW_OPEN, false);
  out.doneUntick = wantedState(ROW_DONE, false);
  out.doneRecheck = wantedState(ROW_DONE, true);
  out.droppedTick = wantedState(ROW_DROPPED, true);
  out.droppedUntick = wantedState(ROW_DROPPED, false);
}

if (scenario === 'applyDraft') {
  out.result = applyDraft(PANEL.rows, input.pending);
}

if (scenario === 'applyDraftHostile') {
  const rows = [
    { taskId: '__proto__', state: 'open', tickStates: 'done,dropped', checked: false },
    { taskId: 'constructor', state: 'open', tickStates: 'done,dropped', checked: false },
    { taskId: '', state: 'open', tickStates: 'done,dropped', checked: false },
  ];
  const before = JSON.stringify(rows);
  out.result = applyDraft(rows, input.pending);
  out.rowsUntouched = JSON.stringify(rows) === before;
  out.probe = {
    protoIntact: ({}).__proto__ === Object.prototype,
    ctorIntact: Object.prototype.constructor === Object,
    noDoneKey: !('done' in {}),
    noCheckedKey: !('checked' in {}),
  };
}

if (scenario === 'applyDraftNoMutate') {
  const rows = JSON.parse(JSON.stringify(PANEL.rows));
  const before = JSON.stringify(rows);
  applyDraft(rows, input.pending);
  out.rowsUntouched = JSON.stringify(rows) === before;
}

if (scenario === 'indicatorMatrix') {
  out.zero = indicator({ pending: 0, stale: false, orphans: 0, canDraft: true });
  out.one = indicator({ pending: 1, stale: false, orphans: 0, canDraft: true });
  out.many = indicator({ pending: 3, stale: false, orphans: 0, canDraft: true });
  out.staleOne = indicator({ pending: 1, stale: true, orphans: 0, canDraft: true });
  out.withOrphans = indicator({ pending: 2, stale: false, orphans: 1, canDraft: true });
  out.staleAndOrphans = indicator({ pending: 2, stale: true, orphans: 3, canDraft: true });
  out.onlyOrphans = indicator({ pending: 0, stale: false, orphans: 2, canDraft: true });
  out.preview = indicator({ pending: 5, stale: true, orphans: 2, canDraft: false });
}

if (scenario === 'staleAndLabels') {
  out.stale = {
    diff: isStale('r1', 'r2'),
    same: isStale('r1', 'r1'),
    emptyDraft: isStale('', 'r2'),
    emptyPanel: isStale('r1', ''),
    nullDraft: isStale(null, 'r2'),
    nullPanel: isStale('r1', null),
    numbers: isStale(5, 6),
  };
  out.labels = {
    zero: tabLabel('LOG-001@k-9', 0),
    one: tabLabel('LOG-001@k-9', 1),
    many: tabLabel('LOG-001@k-9', 12),
  };
  out.unload = {
    empty: needsUnloadPrompt({}),
    zeros: needsUnloadPrompt({ 'a@1': 0, 'b@1': 0 }),
    one: needsUnloadPrompt({ 'a@1': 0, 'b@1': 2 }),
    nullish: needsUnloadPrompt(null),
  };
  const nullProto = Object.create(null);
  out.unload.nullProtoEmpty = needsUnloadPrompt(nullProto);
  nullProto['LOG-001@k-9'] = 1;
  out.unload.nullProto = needsUnloadPrompt(nullProto);
  const hostile = Object.create(null);
  hostile['__proto__'] = 3;
  out.unload.protoKeyCount = needsUnloadPrompt(hostile);
}

if (scenario === 'discardRoundtrip') {
  out.applied = applyDraft(PANEL.rows, [['T-1', 'done'], ['T-2', 'open'], ['T-3', 'open']]).rows;
  out.plan = discardPlan(PANEL.rows);
}

if (scenario === 'exports') {
  out.types = {
    panelFromRows: typeof panelFromRows,
    wantedState: typeof wantedState,
    applyDraft: typeof applyDraft,
    indicator: typeof indicator,
    isStale: typeof isStale,
    tabLabel: typeof tabLabel,
    needsUnloadPrompt: typeof needsUnloadPrompt,
    discardPlan: typeof discardPlan,
  };
}

process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path, scenario: str, seed: dict | None = None) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to run the tick pane module")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8", newline="")
    proc = subprocess.run(
        [NODE, str(harness), TICK_PANE_JS, scenario, json.dumps(seed or {})],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake non-ASCII (the middle dot in the indicator's em-dash prose)
        # on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness {scenario!r} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# -- panelFromRows: can this pane draft, and which rows can? ------------------


def test_panel_from_rows_marks_every_row_its_draftability(tmp_path):
    r = _run(tmp_path, "panelDraftable")
    panel = r["panel"]
    assert panel["canDraft"] is True
    assert panel["reason"] == ""
    assert [row["taskId"] for row in panel["rows"]] == ["T-1", "T-2", "T-3", ""]
    by_id = {row["taskId"]: row for row in panel["rows"]}
    assert by_id["T-1"]["draftable"] is True and by_id["T-1"]["reason"] == ""
    assert by_id["T-1"]["targets"] == ["done", "dropped"]
    assert by_id["T-2"]["draftable"] is True and by_id["T-2"]["targets"] == ["open"]
    # the dropped row IS draftable: Q6(b) gives it the reopening tick
    assert by_id["T-3"]["draftable"] is True and by_id["T-3"]["targets"] == ["open"]
    # an id-less row (data-refdes-task is empty in the markup) cannot be saved
    assert by_id[""]["draftable"] is False
    assert by_id[""]["reason"] == NO_ID_REASON
    assert by_id[""]["targets"] == ["done", "dropped"], (
        "targets are the parsed tickStates even on a non-draftable row"
    )
    assert all(set(row) == {"taskId", "draftable", "reason", "targets"} for row in panel["rows"])


@pytest.mark.parametrize(
    "panel",
    [
        {"rows": [{"taskId": "T-1", "state": "open", "tickStates": "done,dropped", "checked": False}]},
        {"tipKey": "", "revision": "rev-7", "rows": []},
        {"tipKey": None, "revision": "rev-7", "rows": []},
        {"tipKey": "LOG-001@k-9", "rows": []},
        {"tipKey": "LOG-001@k-9", "revision": "", "rows": []},
        {"tipKey": "LOG-001@k-9", "revision": None, "rows": []},
    ],
    ids=["no-tip-key", "empty-key", "null-key", "no-revision", "empty-revision", "null-revision"],
)
def test_a_panel_without_key_or_revision_is_preview_only(tmp_path, panel):
    """The keyless tip (the panel has no data-refdes-tip-key / data-refdes-
    revision at all -- the W5b.4a markup omits both): ticks here are
    preview-only, exactly the W5b.3 note's promise, and NO row is draftable."""
    r = _run(tmp_path, "panelIdentity", {"panel": panel})
    out = r["panel"]
    assert out["canDraft"] is False
    assert out["reason"] == PANEL_PREVIEW_REASON
    for row in out["rows"]:
        assert row["draftable"] is False
        assert isinstance(row["reason"], str) and row["reason"]


def test_targets_are_split_trimmed_and_empties_dropped(tmp_path):
    r = _run(tmp_path, "targetsParse", {"states": ["done, dropped", "open,", ",done,open,", "  ", "", "open"]})
    assert [panel["targets"] for panel in r["panels"]] == [
        ["done", "dropped"],
        ["open"],
        ["done", "open"],
        [],
        [],
        ["open"],
    ]
    # a row with no targets is not draftable (the pane has no verb for it)
    assert [panel["draftable"] for panel in r["panels"]] == [True, True, True, False, False, True]


# -- wantedState: what does a click name? -------------------------------------


def test_wanted_state_names_the_first_target_on_a_change_and_the_rendered_state_on_the_way_back(tmp_path):
    """Q6(b) ratified: open->done and open->dropped, un-tick (done->open) and
    dropped->open. A click that lands the checkbox back on its RENDERED state
    names that rendered state (the un-tick back to the original); any other
    click names the FIRST of the row's targets."""
    r = _run(tmp_path, "wantedStates")
    assert r["openTick"] == "done"        # first target of "done,dropped"
    assert r["openUntick"] == "open"      # back to rendered: the row's own state
    assert r["doneUntick"] == "open"
    assert r["doneRecheck"] == "done"     # re-ticking a rendered-done row names done
    assert r["droppedTick"] == "open"     # the reopening tick (see the markup pin)
    assert r["droppedUntick"] == "dropped"


def test_the_server_renders_a_dropped_row_unticked_with_open_as_the_only_target():
    """The markup fact wantedState's dropped case rests on, pinned from the
    server's own code (`task_pane._ticks_for`, the model behind
    `pane.html.j2`'s checkbox): a dropped row gets `checked` False (the
    template emits `checked` iff the state is `done`) and
    `data-refdes-tick-states="open"`. So ticking a dropped row names "open"
    -- a dropped row's only tick is a reopening, and the first-target rule
    gives it for free."""
    from refdes.task_pane import TICK_TARGETS, _ticks_for

    ticks = _ticks_for(
        [{"id": "T-1", "state": "open"}, {"id": "T-2", "state": "done"}, {"id": "T-3", "state": "dropped"}],
        "LOG-001",
    )
    assert [tick["targets"] for tick in ticks] == ["done,dropped", "open", "open"]
    assert [tick["checked"] for tick in ticks] == [False, True, False]
    assert TICK_TARGETS == {"open": "done,dropped", "done": "open", "dropped": "open"}


# -- applyDraft: the draft over the rendered rows ------------------------------


def test_apply_draft_marks_pending_rows_and_keeps_the_rest(tmp_path):
    r = _run(tmp_path, "applyDraft", {"pending": [["T-1", "done"], ["T-2", "open"], ["T-99", "done"]]})
    assert r["result"]["rows"] == [
        {"taskId": "T-1", "checked": True, "pending": True},
        {"taskId": "T-2", "checked": False, "pending": True},
        {"taskId": "T-3", "checked": False, "pending": False},
        {"taskId": "", "checked": False, "pending": False},
    ], "checked is (wanted state == 'done'); unmatched rows keep their rendered checked"


def test_a_draft_entry_with_no_matching_row_is_an_orphan_and_stays_in_the_draft(tmp_path):
    """An entry whose taskId matches no row is an ORPHAN: returned in input
    order, not applied, not silently dropped -- it stays in the draft (the
    indicator says so; the save sends what the draft holds)."""
    r = _run(tmp_path, "applyDraft", {"pending": [["T-99", "done"], ["T-1", "done"], ["T-98", "dropped"]]})
    assert r["result"]["orphans"] == [["T-99", "done"], ["T-98", "dropped"]]


def test_hostile_task_ids_neither_pollute_nor_crash_the_module(tmp_path):
    """Task ids are user data: `__proto__` and `constructor` are ordinary
    ids (a row with one IS draftable and IS matched by its draft entry --
    Map/null-prototype lookup, not a plain-object dictionary), `` is not
    (its entry is an orphan). Nothing lands on Object.prototype."""
    r = _run(
        tmp_path,
        "applyDraftHostile",
        {"pending": [["__proto__", "done"], ["constructor", "done"], ["", "open"], ["ghost", "open"]]},
    )
    assert r["result"]["rows"] == [
        {"taskId": "__proto__", "checked": True, "pending": True},
        {"taskId": "constructor", "checked": True, "pending": True},
        {"taskId": "", "checked": False, "pending": False},
    ]
    assert r["result"]["orphans"] == [["", "open"], ["ghost", "open"]]
    assert r["rowsUntouched"] is True, "applyDraft mutated the rows it was given"
    assert r["probe"] == {
        "protoIntact": True,
        "ctorIntact": True,
        "noDoneKey": True,
        "noCheckedKey": True,
    }, "a task id reached Object.prototype"


def test_apply_draft_does_not_mutate_the_rows_it_is_given(tmp_path):
    r = _run(tmp_path, "applyDraftNoMutate", {"pending": [["T-1", "done"], ["T-2", "open"]]})
    assert r["rowsUntouched"] is True


# -- indicator: Q8's header sentence -------------------------------------------


def test_the_indicator_is_invisible_with_nothing_pending(tmp_path):
    r = _run(tmp_path, "indicatorMatrix")
    assert r["zero"] == {"text": "", "hidden": True}


def test_the_indicator_counts_unsaved_ticks_in_plain_words(tmp_path):
    """Q8 ratified: the pane's header shows the pending count ("3 unsaved
    ticks") -- a badge the size of the editor's is easy to miss over a
    document."""
    r = _run(tmp_path, "indicatorMatrix")
    assert r["one"] == {"text": "1 unsaved tick", "hidden": False}
    assert r["many"] == {"text": "3 unsaved ticks", "hidden": False}


def test_the_indicator_adds_the_stale_and_orphan_clauses(tmp_path):
    r = _run(tmp_path, "indicatorMatrix")
    assert r["staleOne"] == {"text": f"1 unsaved tick{STALE_CLAUSE}", "hidden": False}
    assert r["withOrphans"] == {"text": "2 unsaved ticks (1 no longer match a task)", "hidden": False}
    assert r["onlyOrphans"] == {
        "text": "0 unsaved ticks (2 no longer match a task)",
        "hidden": False,
    }, "orphans keep the indicator visible with nothing pending"
    assert r["staleAndOrphans"] == {
        "text": f"2 unsaved ticks{STALE_CLAUSE} (3 no longer match a task)",
        "hidden": False,
    }


def test_a_keyless_tip_says_ticks_are_preview_only(tmp_path):
    r = _run(tmp_path, "indicatorMatrix")
    assert r["preview"] == {"text": INDICATOR_PREVIEW, "hidden": False}


# -- isStale / tabLabel / needsUnloadPrompt ------------------------------------


def test_is_stale_needs_two_different_non_empty_strings(tmp_path):
    """Q3(a): the pane notices the tip moved (the reload probe re-renders) --
    an absent side (a keyless tip, a draft with no stamp: tick-drafts drops
    the stamp with its last tick) is not staleness, it is the absence of an
    opening."""
    r = _run(tmp_path, "staleAndLabels")
    assert r["stale"] == {
        "diff": True,
        "same": False,
        "emptyDraft": False,
        "emptyPanel": False,
        "nullDraft": False,
        "nullPanel": False,
        "numbers": False,
    }


def test_the_tab_label_carries_each_tip_s_own_pending_count(tmp_path):
    """Q5(a): tab-switch UI shows each tip's own pending count, and a clean
    tip's tab says only its label."""
    r = _run(tmp_path, "staleAndLabels")
    assert r["labels"] == {
        "zero": "LOG-001@k-9",
        "one": "LOG-001@k-9 (1)",
        "many": "LOG-001@k-9 (12)",
    }


def test_the_unload_prompt_fires_for_any_tip_with_pending_ticks(tmp_path):
    """needsUnloadPrompt counts across TIPS (Q5: drafts coexist per tip in
    one tab; one prompt for the whole page), reading tick-drafts' counts()
    -- which is null-prototype (Object.create(null)) and omits empty tips,
    so a for-in over Object.keys, not prototype-chained properties."""
    r = _run(tmp_path, "staleAndLabels")
    assert r["unload"] == {
        "empty": False,
        "zeros": False,
        "one": True,
        "nullish": False,
        "nullProtoEmpty": False,
        "nullProto": True,
        "protoKeyCount": True,
    }


# -- discardPlan: Q8's reset-to-the-file ---------------------------------------


def test_discard_returns_every_row_to_the_state_the_file_says(tmp_path):
    """Q8(a) ratified (the editor's rules): Discard is the explicit release.
    Every row returns to the state the pane RENDERED from the file -- not the
    draft's state, not the opposite of the draft -- so the checkbox rows and
    discardPlan agree with a page reload (which shows the file, since the
    draft never wrote it)."""
    r = _run(tmp_path, "discardRoundtrip")
    assert r["applied"] == [
        {"taskId": "T-1", "checked": True, "pending": True},   # open -> done
        {"taskId": "T-2", "checked": False, "pending": True},   # done -> open
        {"taskId": "T-3", "checked": False, "pending": True},   # dropped -> open
        {"taskId": "", "checked": False, "pending": False},
    ]
    assert r["plan"]["rows"] == [
        {"taskId": "T-1", "checked": False},
        {"taskId": "T-2", "checked": True},
        {"taskId": "T-3", "checked": False},
        {"taskId": "", "checked": False},
    ], "discard must undo the draft, not invert it"
    assert all(set(row) == {"taskId", "checked"} for row in r["plan"]["rows"])


# -- source pins: the module is pure, self-contained, and served-clean ---------

INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")

EXPORT_NAMES = (
    "panelFromRows",
    "wantedState",
    "applyDraft",
    "indicator",
    "isStale",
    "tabLabel",
    "needsUnloadPrompt",
    "discardPlan",
)


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
    """4c-1a is the pure half: the DOM glue (4c-1b) builds the plain objects
    and owns every page touch. The harnesses above prove the same fact by
    running the module in a node process with no document/window/localStorage/
    sessionStorage globals; this scan pins it for fetch/XMLHttpRequest/eval/
    innerHTML too (fetch exists in modern node, so the runtime proof cannot
    cover it)."""
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
    """ONE self-contained module: no import graph, and every export is a
    function named exactly as pinned (the runtime scenario proves the
    typeofs; this pins the spelling of the surface)."""
    code = _pane_code()
    assert JS_IMPORT.findall(code) == [], "tick-pane.js must import nothing"
    for name in EXPORT_NAMES:
        assert re.search(rf"\bexport function {name}\b", code), f"missing export: {name}"


def test_the_module_passes_the_served_js_rules(tmp_path):
    """test_serve_static.py's js_files() lists static/*.js at collection
    time, so tick-pane.js is picked up by that module's inline-handler /
    dynamic-code / balance checks automatically the moment it lands; this
    pins the same checks (and the file's presence in the served dir) here."""
    listing = [n for n in os.listdir(STATIC) if n.endswith(".js")]
    assert "tick-pane.js" in listing, "the file is not in the served static dir"
    code = _pane_code()
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code), "no eval/new Function in the editor"
    assert "javascript:" not in code
    stack = []
    depth = {"(": ")", "[": "]", "{": "}"}
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
