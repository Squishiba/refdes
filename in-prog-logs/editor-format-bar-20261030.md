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
- Review round 2: implemented inline toggle-off for caret, selected inner
  text, marker-inclusive selections, marker runs, triple nesting, astral
  characters, and line-break guards.
- Strengthened the node harness with the requested toggle, save-gate,
  placeholder, caret, draft, fence, and localStorage checks. It red-first on
  the missing toggle behavior, then failed on a duplicated Case A insertion
  found by the harness.
- Strengthened static checks to pin the exact five shortcuts, their modifier
  conditions, every button against `OPS`, and the formatbar's own save gates.

## Verification

- `python -m pytest -q tests/test_editor_format_bar.py`
- `python -m pytest -q tests/test_serve_static.py`
- `python -m pytest -q tests/test_serve_static.py tests/test_editor_format_bar.py tests/test_editor_live_calc.py tests/test_editor_link_undo.py`
- `python -m pytest -q`
- `node format-bar-e2e.mjs chromium`
- `node format-bar-e2e.mjs ff`

All pass. The browser probe covers all 11 base button cases, native undo,
persistence, caret placeholder/toggle, double-click, marker-inclusive
selection, nested triple cases, astral characters, markers across a line
break, Case B fallback wrap/toggle, Ctrl+I, and Ctrl+B in Chromium and
Firefox. The PR body has the case-by-case table.

## Open

- None for slice 1.
