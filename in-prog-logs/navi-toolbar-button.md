# Navi toolbar button (feat/navi-toolbar-button-2)

Task: add a `Navi` button to the browser editor's refdes row that inserts
a keyless `<!--navi: text-->` marker. One slice, formatbar.js only.

## What landed

- `src/refdes/serve/static/formatbar.js` (+25 lines): `NAVI_SKELETON`
  export, `applyNavi` (caret: insert with `text` selected, same
  placeholder-selection style as `span`; selection: wrap leaving the text
  selected; selection containing `--` or a newline: silent no-op -- the
  bar's existing refuse convention, no new mechanism), registered in
  `REFDES_OPS`, and the button row `['navi', 'Navi', 'Navi: insert a
  <!--navi: text--> marker']` placed after `value`, before `image` (panel
  openers stay last). Undo rides the shared `applyEdit` path: one
  insertion = one `execCommand` = one native undo step (Case B splice
  keeps the existing "more than one step" note).
- `docs/browser-editor.md`: "Seven more buttons" -> "Eight", one bullet
  for `Navi` (insert/wrap/refuse/mint, nothing beyond what was run).
- `changelog.d/navi-toolbar-button.added.md`.

## Tests (red-first, each shown FAIL before the change)

- `tests/test_editor_skeletons.py`: pinned `NAVI_SKELETON ==
  "<!--navi: text-->"` (red: `formatbar.js must export the skeleton
  string NAVI_SKELETON`) and a new case running the pinned string
  through the real loader/build: no error diagnostics, scanned into
  `item.navis` as text `text` with an empty key (read-only mints
  nothing) -- a string the real grammar would not accept scans to
  nothing and fails.
- `tests/test_editor_refdes_buttons.py`: group wiring (8 buttons, exact
  class order with navi after value / openers last, label + aria text),
  caret insert (placeholder selected, one execCommand, draft commits),
  wrap (sel stays selected), refuses (`--`, `-->`, newline: value,
  selection, execs and draft all untouched), navi added to the
  mid-save gate sweep. Red: group count 7 != 8.
- `tests/test_editor_format_bar.py`: button count 18 -> 19, refdes
  presence list gains `navi`. Red: 18 == 19 assertion.

After the change: the three files green (15 passed); full suite
5632 passed, 2 skipped; `ruff check` clean on the touched test files;
`test_crossplatform_lint.py` green.

## Browsers (port 8767, recipe from .scratch/pptr, Chromium + Firefox)

Throwaway project, one DEC-001. Per browser: (a) caret insert + `text`
selected + typed replacement + save -> `refdes navis ls` (writable)
minted a key (`xrm2en...` chromium run, `mdc45r...` firefox run) and
listed the navi; (b) word selection wrapped, selection kept; (c) `a--b`
selection refused, text and selection untouched; (d) Ctrl+Z restored
the previous text in one step. All PASS in both browsers.

No Python under src/ touched. JS mints no keys.

Finished: complete.
