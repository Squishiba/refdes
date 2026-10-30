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
    and the four bounded shortcuts.
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
- Strengthened static checks to pin the exact four shortcuts, their modifier
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

## Review round 3

Merged `origin/main` locally (`be0b078`), preserving the font-setting feature
and DOM order. Reproduced the marker-only tab freeze on the detached
`2f6db3e` worktree: Node and browser marker cases timed out, and the exhaustive
sweep timed out. Red fence cases showed generic fences not being respected.

Fixed `formatbar.js`:

- bounded leading/trailing/interior marker-run scans;
- exact marker-only semantics, including `~~~` strike and `***` cases;
- CommonMark-shaped fence scan with blockquotes, longer closers, nested fences,
  and unclosed fences;
- code-point boundary snapping to avoid splitting astral surrogate pairs;
- block insertion at the caret start so it preserves selected text;
- documented the three deliberate `isSaving()` gates.

Added permanent node tests for marker-only cases, fence shapes, and a
50,890,818-case exhaustive sweep. Updated the shortcut audit to allow the
design-carved-out `Ctrl/Cmd+Alt+C` code binding.

## Round 3 verification

- Targeted formatbar, static, and font-setting tests: 67 passed.
- Exhaustive Node sweep: `{"cases":50890818,"bad":[]}` in about 55 seconds.
- Real-browser Chromium and Firefox: all main cases plus marker-only
  no-hang cases and font-setting coexistence pass.
- `python -m pytest -q`: 5552 passed, 2 skipped.

## Open

- Awaiting round 4 CI.

## Review round 4

Fixed the astral test escapes and added a surrogate-pair guard. The generated
JavaScript had literal Python `\U0001F600` text; it now uses `\u{1F600}`. A
scratch mutation that treats UTF-16 offsets as code-point offsets makes the
astral wrap/unwrap cases fail, proving the guard is not vacuous.

Resolved the design's Ctrl/Cmd+Alt+C contradiction by removing that shortcut
from slice 1. The bound set is Ctrl+B, Ctrl+I, Ctrl+K, and Alt+Shift+5; the
fence shortcut is deferred to slice 2 pending Jared. Updated the design table,
changelog, static audit, and code comments.

Fixed `lineRange()` at caret 0 and blank first lines. Replaced the link scan
with a bounded balanced scan that rejects unbalanced brackets and wiki-ref link
text. Red cases showed blank-line ops hitting the second line, wiki refs
leaving a stray bracket, and nested links collapsing to `[a b`.

Removed the dead `handle` parameter. The sweep harness derives its expected
case count. Added node coverage for all four line ops at caret 0 and blank
first lines, plus wiki, nested, and ordinary links. Browser coverage now tests
all four bound shortcuts, records `defaultPrevented` and textarea focus, and
checks line caret behavior.

## Round 4 verification

- Main format-bar node test: passed.
- Format-bar static audit: 5 passed.
- Format-bar/font-targeted suite: 9 passed.
- Exhaustive sweep: 50,890,818 cases, expected count derived, no failures.
- Chromium and Firefox: all main, marker-only, shortcut, line-caret, and font
  coexistence cases pass.
- `python -m pytest -q`: 5552 passed, 2 skipped.
- CI: pending at the time this round's code was staged.

## Review round 5

Fixed the heading first-cycle caret. Red: `Title here` at caret 3 became
`# Title here` with caret 1, so typing `x` produced `#xTitle here`. The first
cycle now puts the caret at 2; node expects `[2, 3, 4, 5, 6, 7, 0]`, and
Chromium/Firefox type `X` after the first click and get `# XTitle here`.

Capped fence openers and closers at three spaces. Red with the old unbounded
closer: a line indented four spaces or by a tab closed the fence, so an HR
inserted at content caret `x` landed after that line. Green: a three-space
closer still closes; four spaces and a tab are fence content, moving the
insert after the whole block. The sweep's local expected fence rules changed
in lockstep.

Added browser assertions for empty `execCommand('insertText')` toggles.
Marker-only and list toggle-offs produce the expected empty/marker-stripped
text with `refdes.live-calc.fallback` null and the fallback note hidden in
both browsers. The three-newline after-fence block-insert nit is intentionally
left as is: it follows the existing block-padding rule.
