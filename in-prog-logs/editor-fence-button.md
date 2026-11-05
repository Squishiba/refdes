# editor-fence-button

Task: add a plain code-FENCE button to the browser editor's formatting bar
(Jared, 2026-11-04). One small slice; no keyboard shortcut (decided).

## What landed

- `src/refdes/serve/static/formatbar.js` (+52 lines):
  - `FENCE_EMPTY_SKELETON = '```\n\n```'` exported (the caret skeleton,
    pinned through the real build in test_editor_skeletons.py).
  - `selectionInFence(text, start, end)` -- a selection fully spanned by one
    `fenceBlocks` block lies inside a fence (refuse rule).
  - `fenceMarkerFor(text)` -- the fence a wrapped selection needs:
    max backtick run that opens any of its lines + 1, minimum 3 (CommonMark
    fence-closing rule), so an inner ``` line cannot close the block early.
  - `applyFence(area, opts)`: caret -> `blockInsertPlan(area,
    FENCE_EMPTY_SKELETON)` with the caret on the empty inside line (zero
    length); selection -> wrap as `marker\nselection\nmarker` through
    `blockInsertPlan(area, block, start, end)` with the inner text left
    selected; selection inside an existing fence -> silent no-op (the bar's
    refuse convention). After-fence landing and blank-line padding come from
    `blockInsertPlan` unchanged; the edit goes through `applyEdit` so undo
    is one step and the isSaving gate behaves like every other button.
  - `OPS.fence`; BUTTONS row `['fence', '```', 'Code block']` immediately
    after `code` (core group is now 12 buttons, bar total 20).
- No shortcut added (SHORTCUTS untouched, per Jared's decision).

## Tests (red-first, each shown FAIL pre-change)

- `tests/test_editor_format_bar.py`: new scenarios in the node harness --
  wiring (core order, ``` label, "Code block" aria, total 20, fence right
  after code), caret insert (padded own block, caret on the empty line,
  fences balanced, 1 execCommand = 1 undo step, draft), caret-inside-fence
  lands after the closing fence, wrap (padded, inner selected, 1 exec),
  multi-line wrap, wrap of a body containing a ``` line uses 4 backticks,
  refuse inside a fence (value/selection/execs/draft untouched). The
  mid-save gate sweep clicks `fence` alongside `bold`. The a11y count
  assertion moved 19 -> 20 (11 core + 8 refdes -> 12 core + 8 refdes) --
  the only legitimate count move.
- `tests/test_editor_skeletons.py`: `test_the_plain_fence_the_bar_inserts_
  builds_clean` runs the exported caret skeleton (with a typed line inside)
  through the real loader/build: no error, inner text intact in the body.
- Red evidence: pre-change both files fail (`fmt-fence` button missing /
  FENCE_EMPTY_SKELETON not exported); post-change the three editor-format
  node suites pass (test_editor_format_bar.py 4 passed,
  test_editor_refdes_buttons.py, test_editor_skeletons.py green).

## Real browsers (port 8776, own throwaway project, headless)

Recipe copied to .scratch/pptr (drive via puppeteer-core Chromium
/usr/bin/chromium, playwright-core Firefox). All PASS, Chromium and Firefox:

- (a) caret mid-paragraph -> own block with blank-line padding, caret
  zero-length on the inside line, typed text lands inside, save lands the
  body, `refdes build` exit 0 and the built page renders <pre><code>.
- (b) two-line selection -> fenced as its own block, inner text selected.
- (c) selection containing a ``` line -> 4-backtick fence, save lands,
  build exit 0, built page shows the inner ``` literally in the code block.
- (d) caret inside an existing fence -> new block lands after the closing
  fence, fences balanced (4 fence lines).
- (e) selection inside an existing fence -> nothing happens (value and
  selection untouched).
- (f) one Ctrl+Z restores the previous text.

First (d) run "failed" only because my expectation string omitted
blockInsertPlan's blank-line padding (\n\n\ntail, not \n\ntail) -- the
behaviour was correct and matches the table/calc convention; expectation
fixed, both browsers green.

## Docs

- `docs/browser-editor.md`: "Eleven buttons" -> "Twelve"; new fence row in
  the formatting table; fence named in the block-insert paragraph; fence
  listed among the no-shortcut buttons. Nothing beyond what I ran.
- `changelog.d/editor-fence-button.added.md`.
- Design record: appended the one-sentence update to section H entry 6 of
  `in-prog-logs/editor-format-toolbar-design-20261029.md` (the plain fence
  now has a button, no shortcut), per the task addendum after #415 merged.

## Scope notes

No Python under src changed. Node suites: `ruff check` on the two touched
test files is clean.

## Review round 1 (44c437b9, changes requested)

F1 (real bug, spec gap): the old refuse rule required BOTH endpoints inside
ONE fence; a selection starting inside a fence and ending past its closer
survived, and `blockInsertPlan`'s after-fence rule then dropped the range and
inserted a zero-length block -- duplicated text, save succeeds silently. New
rule: refuse when EITHER endpoint of a non-empty selection falls inside any
fence, defined off one shared `fenceAt` helper (the caret-after-fence rule's
own `caret >= block.start && caret < block.end` geometry, so the two rules
can never disagree). Caret-only behaviour unchanged. Node harness: red shown
pre-fix for start-inside/end-after (reviewer's exact input), start-before/
end-inside, endpoints in two fences; enclosing-whole-fence stays accepted
(4-tick wrapper, original text asserted to occur exactly once); every
accepted edit now asserts the fence-line-count parity invariant
(`keepsBalance`). Browser case (g) added and run in both browsers; all
(a)-(g) re-run PASS. F2: the round-1 rename of
`test_the_fence_skeleton_is_the_measured_build_error` is reverted -- the
calc-fence build-error pin is that test again, the plain-fence clean build
gets its own test. F3: design-record re-indent reverted (diff is the one
sentence). Docs row restated to the implemented rule.
