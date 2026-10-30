# Browser-editor formatting bar, slice 1

Worker: `feat-editor-format-bar`.

Goal: implement the core formatting bar from
`in-prog-logs/editor-format-toolbar-design-20261029.md` and prove the
mutator behavior before the real-browser checklist.

## Done

- Wrote `tests/test_editor_format_bar.py` first. The first run failed because
  `src/refdes/serve/static/formatbar.js` did not exist.
- Added `formatbar.js` with:
  - shared Case A/B mutator through `execCommand('insertText')` first,
    splice plus one synthetic `input` event second;
  - shared session key `refdes.live-calc.fallback`;
  - fallback note: `Undo may need more than one step in this browser.`;
  - core toolbar: bold, italic, strike, code, heading, list, numbered list,
    quote, link, table, horizontal rule;
  - real buttons with `aria-label`, mousedown focus preservation, save gate,
    and the five bounded shortcuts.
- Wired `editor.js`: imports `createFormatBar`, `applyEdit`, and
  `blockInsertPlan`; creates the bar with the save-window flag; attaches it in
  `bodyControl`; converts `insertIntoBody` and `insertSourceLine` to the shared
  mutator.
- Wired `item.js`: the bar is appended immediately before the body textarea.
- Added CSS for the bar and note.
- Added static wiring checks to `tests/test_serve_static.py`.

## Verification

- `python -m pytest -q tests/test_editor_format_bar.py`
- `python -m pytest -q tests/test_serve_static.py`
- `python -m pytest -q tests/test_serve_static.py tests/test_editor_format_bar.py tests/test_editor_live_calc.py tests/test_editor_link_undo.py`

All pass.

- Real-browser checklist on Chromium and Firefox: toolbar DOM/a11y, bold
  selection with one native undo, shortcuts, live-calc coexistence, and the
  save-window gate all pass.

## Open

- None for slice 1.
