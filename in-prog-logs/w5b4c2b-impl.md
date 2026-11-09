# w5b4c2b-impl — SAVE seam of the task pane (implementer, W5b.4c-2b-impl)

Branch: feat/w5b4c2b-tick-save-ui, continuing the test author's commit (the
19 red / 5 green of tests/test_task_pane_save_ui.py, their log, and the
structure decision in the test header). First action was a plain
`git merge origin/main` (main had moved: #469, #470); no conflict, no rebase.

## What was built

- NEW `src/refdes/serve/static/taskpane-save.js` — the pane's only network
  module, `initSave({ drafts, panels, refreshPanel })`. It imports the pure
  model (`./tick-save.js`) and `./tick-pane.js` (panelFromRows for the
  current page's rows) and never the glue (the glue imports it: a cycle).
  Save button per draftable panel: hidden with no pending tick, disabled in
  flight; POST to buildSaveRequest's path with `credentials: 'same-origin'`,
  JSON content type and `X-Refdes-Token` read from
  `meta[name="refdes-token"]` at save time — never a URL, storage, DOM text.
- `taskpane-ticks.js` gained ONLY the import, `const panels = []`, `panelEl`
  on the entry, one `panels.push(entry)`, and one
  `initSave({ drafts, panels, refreshPanel })` call after the panels are
  built. Its old purity pins (no fetch/token/api, one beforeunload) re-run
  green, unedited.
- CSS for `.refdes-taskpane-save` / `.refdes-taskpane-conflict` (+ the
  role=alert line, the read-only textarea, the outcome buttons) INSIDE the
  `refdes:preview-css` markers only; the built stylesheet stays byte-identical
  (the byte-identity test proves the whole block is still stripped).

Behaviour follows the test header exactly: saved → `drafts.discard` +
`location.reload()`; refused/invalid/forbidden/error → the server's own
(capped) text in a `role="alert"` element via textContent, draft kept, Save
re-enabled; a fetch that throws → the model's status-0 line; conflict (409,
which carries no rows) → GET `location.href`, DOMParser, the panel whose
`data-refdes-tip-key` matches, `panelFromRows` over it, `describeConflict`
rows, and exactly the `conflictChoices` three. Keep mine re-stamps my
surviving ticks on the CURRENT tip key at the CURRENT revision and reloads;
keep theirs discards and reloads; copy it out shows `copyOut.text` in a
read-only textarea and tries `navigator.clipboard.writeText` inside a
try/catch. A page with no panel for the thread says so and offers only
Keep theirs + Copy it out. Nothing merges.

## Budget

pr_size (added lines under src/, comments counted, against origin/main):
265 (taskpane-save.js) + 9 (taskpane-ticks.js) + 64 (taskpane.css) = 338,
under the 350 gate. First draft was 404 (verbose header + a wider CSS block);
the header, the defensive `hostOf` fallbacks and several CSS declarations were
cut to land inside the gate — the module's behaviour did not change.

## Red / green

Red first (recorded before any src/ change): 19 failed, 5 passed — exactly the
test author's split, the node harness exiting red on the missing module. After
the change: `tests/test_task_pane_save_ui.py` 24 passed. The named neighbours
(tick_ui, ticks, tick_context, tick_save, tick_pane, tick_drafts,
serve_static, crossplatform_lint) pass with it: 279 passed. `node --check`
clean on both touched .js files. Full suite run once before the push (see the
PR): no failures.

## Not verified by me (for the lead, Chromium + Firefox)

Everything the fake cannot see, which the test docstring lists in full: the
Save button and the CSS as RENDERED; a real `location.reload()` landing on the
re-rendered page with the continuation as tip; the real cookie + token round
trip under CSP `connect-src 'self'`; a real DOMParser over a real preview page
(including a hostile tip key in the parsed attributes); the clipboard
permission prompt and a real rejected clipboard; the beforeunload prompt with a
draft open; the in-flight disabled state as perceived while a rebuild makes the
POST slow. The rendered UI/flows are NOT browser-verified by me.

## Notes for the lead

- The pane's W5b.3 sentence under the title still reads "ticking a row changes
  this page only -- nothing is saved" (pinned in test_task_pane_ticks.py). It
  is now beside a Save button, so it should become e.g. "nothing is saved
  until you press Save" — a test-author edit, not mine.
- A 403 (stale token / `--no-write`) renders the model's generic
  relaunch-the-server line: the token seam answers text/plain, so there is no
  JSON `error` to echo. Verbatim-and-capped applies to the JSON refusals
  (422 refused/invalid, 400) — where the server's own text is readable.
- Keep mine stamps my ticks against the CURRENT row state as baseline, so a
  tick that now matches the file leaves no draft entry (the store's Q6b rule).

Status: done.
