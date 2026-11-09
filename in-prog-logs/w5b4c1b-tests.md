# w5b4c1b-tests — DOM glue tests for the tick pane (test-author slice)

Slice: W5b.4c-1b-tests. Tests only: one new file,
`tests/test_task_pane_tick_ui.py`, pinning the glue that will wire
`taskpane-ticks.js` to `tick-drafts.js` (4b) and `tick-pane.js` (4c-1a).
No src/, no templates, no existing tests touched.

## Read first

Plan §4 W5b.3/W5b.4 and §6 Q1/Q3/Q5/Q6/Q8 (all ratified), the merged
modules, the pane template, `_decorate_task_ticks`/`_TICKS_TAG`/`_static`
(server.py), the W5b.3/4a test pins (module keeps NO fetch/token/API
surface), `test_serve_static.py` (js rules — imported, not re-typed).

## What is pinned

- Real server: the threaded preview response carries the module tag;
  GET /edit/static/{taskpane-ticks,tick-drafts,tick-pane}.js each 200,
  text/javascript, byte-equal to the packaged file (so the glue's
  relative imports resolve to served URLs). The served glue bytes
  themselves must contain the two relative imports (pinned on the wire).
- R3/Q9 pair: `refdes build`'s tree contains none of the three modules,
  the tag, any token string, `/api/`; built CSS strips the WHOLE marked
  block (byte-identity vs source, W5b.3's regex approach) — including the
  selectors this slice adds to the block.
- Source pins on the comment-stripped glue: imports both siblings
  relatively and every import target exists; calls the whole pure
  surface (createTickDrafts/setTick/setRevision/pendingCount/
  pendingTicks/counts/discard + all eight tick-pane exports);
  sessionStorage touched only inside a try/catch; exactly ONE
  `beforeunload` listener, condition `needsUnloadPrompt` over `counts`,
  preventDefault + returnValue; no fetch/XMLHttpRequest/token/`/api/`/
  eval/new Function/innerHTML/outerHTML/insertAdjacentHTML/document.write/
  javascript:/inline handlers; textContent present; the
  test_serve_static.py parseability rules.
- CSS: the preview-only block of taskpane.css grows rules for
  `.refdes-taskpane-tick-pending`, `.refdes-taskpane-tick-status`,
  `.refdes-taskpane-discard` (comments stripped before matching).
- The DOM contract (docstring spells it fully): markup read —
  `.refdes-taskpane-panel` + `data-refdes-tip-key`/`data-refdes-revision`,
  checkbox `data-refdes-task`/`-task-state`/`-tick-states`/`-tip`,
  `.refdes-taskpane-head`, `.refdes-taskpane-tab`; elements created —
  indicator class `refdes-taskpane-tick-status` (role=status,
  aria-live=polite, textContent-only), pending class
  `refdes-taskpane-tick-pending` on the label, Discard button class
  `refdes-taskpane-discard` (textContent "Discard"), id-less row
  `disabled` + title reason.

## Red evidence (run BEFORE any src change)

`pytest -q tests/test_task_pane_tick_ui.py` -> 7 failed, 4 passed.
RED: test_the_served_glue_module_imports_its_two_siblings,
test_the_preview_css_block_carries_the_glue_styles,
test_the_glue_imports_both_pure_modules_by_relative_path,
test_the_glue_uses_the_whole_pure_surface,
test_the_glue_touches_session_storage_only_inside_a_try,
test_the_glue_registers_exactly_one_beforeunload_listener,
test_the_glue_names_the_dom_contract.
GREEN guards (declared, pass today by design): the three-modules-are-
served test (all three files exist and _static serves them), the built-
site absence walk, the built-CSS strip byte-identity, and the clean-file
guard (the pre-glue file already ships no network/token/eval/markup
parsing — W5b.3's pin, which the task says STAYS true).

`tests/test_serve_static.py + this file` collected together: 75 passed
+ 7 red (the import of test_serve_static's helpers does not disturb
collection). test_crossplatform_lint.py: 26 passed. ruff on the touched
file only: clean. Full suite NOT run (task says "no full suite").

## Node run of the glue: SKIPPED, deliberately

The task makes the node fake-DOM run optional and warns that
querySelectorAll over a hand-built node tree is not honest. The glue is
built on closest(), label/for semantics, createElement/classList,
change-event dispatch and window.sessionStorage/beforeunload — faking
those faithfully IS writing a DOM engine, and a fake that passes says
nothing about real engines. No node harness written. Conservative
choice, recorded.

Browser-only behaviours (for the Chromium + Firefox Playwright pass):

1. restore: stored draft -> applyDraft -> checkbox `checked` set,
   pending rows labelled, isStale -> stale wording in the indicator.
2. change: wantedState -> setTick -> setRevision -> panel refresh
   (indicator shows "N unsaved ticks").
3. un-tick back to rendered state: draft entry closes, class gone,
   indicator hides (Q6b).
4. lifetimes: reload same tab recovers; tab close discards; tab 2 on
   the same tip has its own draft; two tips of a fork keep separate
   drafts (Q1b/Q5a).
5. indicator element: role/aria-live present, text via textContent,
   hidden exactly when indicator().text is "".
6. tab labels via tabLabel: dirty tab shows " (N)", clean tab bare
   (Q5a; fork markup only).
7. Discard: visible iff active panel has pending ticks; click clears
   the draft and the checkboxes return to their RENDERED state.
8. beforeunload: prompts with pending ticks (preventDefault +
   returnValue), silent when clean, condition evaluated AT EVENT time.
9. id-less row: checkbox disabled, title/aria carries the model's
   plain-string reason, cannot be toggled.
10. keyless panel: boxes toggle locally, nothing is drafted, indicator
    says ticks here are preview-only.
11. throwing storage (blocked/private): pane keeps working, boxes
    toggle, no crash, no prompt loss.

## Cross-platform

No subprocess in the new file; fixtures written as bytes; reads
utf-8; byte comparisons via rb reads; relpath normalised to "/" in the
walk; no POSIX-only tools; ephemeral ports via EditorApp, 10 s client
timeouts. ASCII test source.

## Status

Test-author slice complete: 11 tests, 7 red / 4 declared-green guards,
red shown against the untouched src. Branch feat/w5b4c1b-tick-pane-ui,
tests only — the 4c-1b implementer writes the glue against this pinned
surface.
