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

## Pinned export surface (exact export key-set + source-spelling pins)

panelFromRows, wantedState, applyDraft, indicator, isStale, tabLabel,
needsUnloadPrompt, discardPlan — signatures as specced in the task; the
module docstring in the test file spells each one out. The `exports`
scenario pins the module's export key-set EXACTLY (nothing more, nothing
less).

Pinned strings (the 4c-1b glue renders them; stated here as the task
requires):
- indicator count text is pinned EXACTLY: "1 unsaved tick" / "N unsaved
  ticks" (Q8's ratified header), "" + hidden at 0-pending-0-orphans.
- The free-worded sentences are pinned by content substrings (conservative:
  leaves the implementer the wording, pins the meaning): keyless-panel
  reason and keyless indicator contain "preview-only"; id-less row reason
  contains "no id" + "saved"; stale clause contains "older version" +
  "resolve"; the orphan clause is pinned exactly: "(K no longer match a
  task)".

Conservative choices (no question tool per task): `wantedState` on a row
with no targets returns the row's rendered state (no-op click);
`applyDraft` treats an empty taskId entry as an orphan and a row with id
`__proto__` as an ordinary, matchable id (Map semantics) — the probe in the
harness proves nothing lands on Object.prototype; duplicate pendingTicks
entries resolve last-wins (Map.set semantics, pinned).

## Red evidence (module missing — all module-dependent tests fail)

`PYTHONPATH=<wt>/src ... pytest tests/test_tick_pane.py -q -p no:cacheprovider`
→ **22 failed, 1 passed**. Every failure is the missing module (node exits
non-zero on the import; source pins hit FileNotFoundError). The single green
test is `test_the_markup_renders_a_dropped_row_unticked_with_open_only` —
it pins the MERGED server code (`task_pane._ticks_for`), not the new
module, so it is green by construction; that is the honest state.

## Green proof (tests can go green, without touching src/)

A spec-conformant reference module at
`.scratch/w5b4c1a/greencheck/static/tick-pane.js` (scratch, not committed)
with a scratch copy of the test file (STATIC redirected to the scratch
dir) runs **23 passed** — every pin, including the served-js rules and the
export key-set, is satisfiable by a natural implementation. The deliverable
test file contains no dev-override hook; it points at the served path only.

## Coverage list (all via one node process per scenario, skip_no_node,
utf-8 on subprocess.run, NODE timeout 120 s)

- exports: exact key-set of the module namespace.
- panelFromRows: draftable panel (all three states draftable, exact row
  key-set); keyless/revisionless panel × 4 variants (missing key, empty
  key, missing revision, nullish) all preview-only; id-less row reason;
  targets split/trim/empties (incl. "done, dropped", "open,,", " ").
- wantedState: all six click cases (tick/un-tick × open/done/dropped),
  un-tick-to-original = rendered state (Q6b).
- applyDraft: checked=(wanted=="done"), pending flags, rows stay as
  rendered, orphans (incl. "" id never matches), hostile ids `__proto__` /
  `constructor` matched as ordinary ids, Object.prototype probe,
  duplicates last-wins.
- indicator: 0/1/N exact count text, stale clause, orphan clause (incl.
  0-pending/1-orphan visible), keyless-tip preview text.
- isStale: differs-only-when-two-non-empty-strings matrix (8 cases).
- tabLabel: 0 → bare label, N → "label (N)" (Q5 per-tip counts).
- needsUnloadPrompt: {} / zeros / one, null-prototype counts() with zero
  and with a pending tip — Q1b/Q5/Q8.
- discardPlan: returns every row to the RENDERED state (Q8), exact shape.
- source pins: imports nothing (no import of tick-drafts.js either),
  forbidden globals (document/window/fetch/XMLHttpRequest/eval/innerHTML/
  localStorage/sessionStorage/globalThis) on the comment-stripped code,
  served-js rules mirrored + file presence.

## Cross-platform

subprocess.run has encoding="utf-8" + timeout; harness write_text uses
newline=""; no relpath-as-sep asserts; ASCII test source.
tests/test_crossplatform_lint.py: green (96 passed with test_serve_static.py).
ruff check on the touched file only: clean. Full suite NOT run (per task:
test-author slice, run once by the implementer/branch owner).

## Status

Test-author slice complete. Branch `feat/w5b4c1a-tick-pane-model`, tests
only; the 4c-1a implementer wrote the module against the pinned surface.

## Implementer pass (4c-1a-impl)

Wrote `src/refdes/serve/static/tick-pane.js` — the pure module, eight named
exports, imports nothing, no page globals. No test, template, taskpane-ticks
or tick-drafts edits (the glue is 4c-1b).

- Red first (module missing, as committed): `tests/test_tick_pane.py` ran
  22 failed, 1 passed (the markup pin, green by construction).
- Green after the module: the file ran 23 passed; with
  `tests/test_tick_drafts.py tests/test_serve_static.py
  tests/test_crossplatform_lint.py` added, 151 passed.
- `node --input-type=module --check` on the module: clean (a plain
  `node --check` reads .js as CJS and rejects `export`, so the module form
  is the right gate).
- Decisions the pins left open, taken as the author's log stated them:
  `wantedState` with no targets returns the rendered state; keyless panel
  rows carry reason `""` (the panel reason governs); the no-id reason names
  "no id" + "saved"; the stale clause carries "older version" + "resolve";
  the orphan clause is the exact `(K no longer match a task)`.
- Hostile ids: `applyDraft` builds a `Map` + `Set` and never indexes an
  object by id, so `__proto__`/`constructor` match as ordinary keys and
  `Object.prototype` stays clean (the harness probe passes).
- Strings are ASCII, hyphens not em dashes (the harness decodes UTF-8, but
  plain is cheaper); the purity scan's forbidden words never appear in code
  (comments are stripped first, so the header prose is free to name them).
- pr_size: see the PR report; changelog fragment
  `tick-pane-model.added.md`. Full suite: one run before push (see PR).
