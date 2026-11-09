# w5b4c1a-tests — contract tests for tick-pane.js (test-author slice)

Task: pin the export surface and behaviour of the NOT-YET-WRITTEN pure module
`src/refdes/serve/static/tick-pane.js` (W5b.4c-1a). Deliverable: ONE new file,
`tests/test_tick_pane.py`. No src/ edits, no existing-test edits, no PR.

## What was verified first (per AGENTS.md, by running, not remembering)

- Fast-forwarded the worktree to `origin/main` (clean, "Already up to date",
  HEAD = cdf2dc49, the W5b.4a PR — after the size gate #402).
- Dropped-row markup: ran `task_pane._ticks_for` (venv, PYTHONPATH=src). A
  dropped row renders `checked: False` (the template emits `checked` iff the
  state is `done`), `targets: "open"`. So `wantedState(droppedRow, true)` =
  "open": ticking a dropped row is ONLY ever a reopening, and the
  first-target rule gives it. Pinned both halves: the server fact in a pure
  python test, the decision in the node harness.
- `test_serve_static.py::js_files()` globs `static/*.js` at collection time —
  the new module is auto-picked-up by that file's inline-handler /
  dynamic-code / balance checks the moment it lands. The new test file pins
  the same checks (plus the file's presence in the dir) so the implementer
  sees them in one place.

## Pinned export surface (runtime `typeof` + source-spelling pins)

panelFromRows, wantedState, applyDraft, indicator, isStale, tabLabel,
needsUnloadPrompt, discardPlan — signatures as specced in the task; the
module's docstring in the test file spells each one out.

Pinned strings (the 4c-1b glue renders verbatim; stated here as the task
requires):
- panel reason (keyless tip): "This tip has no key/revision -- ticks here
  are preview-only."
- row reason (id-less row): "This task has no id -- it cannot be saved."
- indicator: "" + hidden at 0/0; "1 unsaved tick" / "N unsaved ticks";
  stale suffix " -- this draft was made against an older version; saving
  will ask to resolve."; orphan suffix " (K no longer match a task)";
  keyless tip: "Ticks on this tip are preview-only -- nothing is saved."

Conservative choices (no question tool per task): the two free-worded
sentences above got the house `--` prose style (matching taskpane-ticks.js);
`wantedState` on a row with no targets returns the row's rendered state
(no-op click); `applyDraft` treats an empty taskId entry as an orphan and a
row with id `__proto__` as an ordinary, matchable id (Map semantics) — the
probe in the harness proves nothing lands on Object.prototype.

## Red evidence (module missing — all module-dependent tests fail)

`PYTHONPATH=<wt>/src ... pytest tests/test_tick_pane.py -q -p no:cacheprovider`
→ **24 failed, 1 passed**. Every failure is the missing module (node exits
non-zero on the import; source pins hit FileNotFoundError). The single green
test is `test_the_server_renders_a_dropped_row_unticked...` — it pins the
MERGED server code (`task_pane._ticks_for`), not the new module, so it is
green by construction; that is the honest state.

## Green proof (tests can go green, without touching src/)

The harness honours `REFDES_TICK_PANE_JS` (dev hook, CI leaves it unset). A
spec-conformant stub at `.scratch/w5b4c1a/tick-pane.js` (scratch, not
committed) runs **24 passed, 1 failed**: the remaining red is the serve-js
test's pin that the file lives in `static/` — greens ONLY when the
implementer lands the real module at its served path (by design). The stub
also passes the scan logic of every source pin (proven directly).

## Coverage list (all via one node process per scenario, skip_no_node,
utf-8 on subprocess.run, NODE timeout 120 s)

- panelFromRows: draftable panel; all three states draftable; id-less row
  not (pinned reason); keyless/revisionless panel × 6 variants; targets
  split/trim/empties; exact row key-set.
- wantedState: all six click cases (tick/un-tick × open/done/dropped),
  un-tick-to-original = rendered state (Q6b).
- applyDraft: checked=(wanted=="done"), pending flags, untouched rows,
  orphans in input order (incl. "" id), hostile ids `__proto__` /
  `constructor` matched as ordinary ids, Object.prototype probes, no
  mutation of the input rows.
- indicator: 0/1/N, stale clause, orphan clause (incl. 0-pending/2-orphans
  visible), stale+orphans combined, keyless-tip preview text.
- isStale: differs-only-when-two-non-empty-strings matrix (7 cases).
- tabLabel: 0 → bare label, N → "label (N)" (Q5 per-tip counts).
- needsUnloadPrompt: plain {} zeros one, null, and null-prototype counts()
  (incl. an own `__proto__` key) — Q1b/Q8.
- discardPlan: undoes the draft to the RENDERED states (Q8), exact key-set,
  order kept; round-trips against applyDraft in one scenario.
- source pins: imports nothing, all 8 export spellings, forbidden globals
  (document/window/fetch/XMLHttpRequest/eval/innerHTML/localStorage/
  sessionStorage/globalThis) on the comment-stripped code, served-js rules
  mirrored + file presence.

## Cross-platform

subprocess.run has encoding="utf-8" + timeout; harness write_text uses
newline=""; no relpath-as-sep asserts; ASCII test source.
tests/test_crossplatform_lint.py: green (96 passed with test_serve_static.py).
ruff check on the touched file only: clean. Full suite NOT run (per task:
test-author slice, run once by the implementer/branch owner).

## Status

Complete. Branch `feat/w5b4c1a-tick-pane-model`, tests only; the 4c-1a
implementer writes the module against the pinned surface and watches
`test_the_module_passes_the_served_js_rules` go green on file landing.
