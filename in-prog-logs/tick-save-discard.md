# fix(serve): Discard hides the Save button, and the conflict panel lists only conflicting ticks

Task: the two run-17 user-sim findings on the preview task pane's Save seam
(finding 1 Medium: Discard leaves a visible no-op Save; finding 3 Cosmetic:
the conflict panel lists ticks equal to the file as noise). Red-first in a
new file, per the brief.

## What I read first

- `.scratch/run17.md` (the report, from `origin/user-sim-run17`) + the
  evidence JSONs (`flow-a-save.json`: `saveVisible: true` after Discard;
  `flow-b-conflict.json` B5/B9b: the "yours open, the file has open" row).
- `src/refdes/serve/static/taskpane-save.js` whole, `taskpane-ticks.js`
  whole, `tick-save.js` (`describeConflict` already carries `differs`),
  `tick-drafts.js` (Discard's store shape), and the three node-harness test
  files (harnesses copied, not edited).

## Mechanisms chosen

1. Discard/Save: `wirePanel` now RETURNS its `draw`, and `initSave` returns
   the glue's `refreshPanel` wrapped: original runs, then every panel's
   draw. The glue's one-line change is the rebind
   `refreshPanel = initSave({...}) || refreshPanel` — Discard's existing
   `refreshPanel(entry)` call then recomputes the button; taskpane-ticks.js
   stays free of fetch/token/api (all pins re-verified), and refreshPanel's
   semantics are untouched (the wrapper calls it first). This is the
   "initSave wraps/receives refreshPanel" option in the task.
2. Conflict rows: `showConflict` lists a row when it is an unticked current
   row (`mine === null`) while at least one tick differs, or a tick whose
   value differs. When NO tick differs, the rows are replaced by the plain
   line 'the file changed since you opened this page, but none of your
   pending ticks conflict with it' and the three outcomes stay.

## The deviation to report (task step: "list only rows whose differs is true")

A literal differs-only filter collides with the existing pin
`test_a_conflict_refetches_the_page_and_offers_exactly_three` (unedited),
which requires the panel's text to name T-gamma — a current row the author
did NOT tick, which `describeConflict` reports as `mine: null, differs:
false` (verified with node against the pinned fixture). The task forbids
editing that file, so the filter keeps the unticked context rows and drops
only the noise rows (ticked, equal). The all-equal case matches the task's
letter exactly (no tick differs -> plain line + three buttons, no rows at
all: every listed row is a tick). New test
`test_the_conflict_panel_does_not_list_ticks_that_equal_the_file` pins
exactly this. No STOP was needed: all existing pins pass unedited.

## Tests

- New `tests/test_task_pane_save_discard.py`: node harness copied from
  test_task_pane_save_ui.py/polish (FakeNode DOM, recording fetch,
  DOMParser stub), 5 tests: glue-rebind source pin, discard-hides-Save,
  retick-shows-Save, equal-tick-not-listed, all-equal-plain-line.
- RED first: all 5 failed on b62c1e28 (visibleAfterDiscard: True; the equal
  rows printed). GREEN after the JS changes.
- Touched/related runs: test_task_pane_save_{ui,polish}.py,
  test_task_pane_tick_ui.py, test_task_pane_ticks.py, test_tick_{save,pane,
  drafts}.py, test_serve_static.py, test_crossplatform_lint.py: 273 passed.
  test_task_pane.py, test_task_pane_tick_context.py,
  test_serve_preview_task_pane.py: 58 passed. Full suite: see below.
- `ruff check tests/test_task_pane_save_discard.py`: clean (repo baseline is
  not ruff-clean; only my file scoped).

## Full suite

`-n 4 --dist worksteal`, absolute PYTHONPATH, on this branch: 6426 passed,
2 skipped in 126.70 s. The single full-suite run required by the rules.
