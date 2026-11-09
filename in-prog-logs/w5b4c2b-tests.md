# w5b4c2b-tests — SAVE half of the pane's DOM glue (test author, W5b.4c-2b)

Branch base: main at #468 (tick-save.js), fast-forwarded clean, no commits of
my own before this one. Task: write tests only. No src/ or existing test was
touched. Deliverable: `tests/test_task_pane_save_ui.py`.

## What is pinned

(a) Real server (port 0, warmed one-tip fixture, keys minted by `check`):
  - the preview response carries the taskpane-ticks.js module tag EXACTLY
    once (the save glue rides in as an import, never a second tag) — green
    guard today;
  - `GET /edit/static/taskpane-save.js` + `/edit/static/tick-save.js` serve
    200 `text/javascript`, byte-identical to the package — RED (the save
    module 404s);
  - `refdes build` ships none of: taskpane-save.js, tick-save.js, the tag,
    `.refdes-taskpane-save`, `.refdes-taskpane-conflict`, `X-Refdes-Token`,
    `?token=`, `/api/`, `/continue` — green guard;
  - preview CSS block (refdes:preview-css markers) gains
    `.refdes-taskpane-save` and `.refdes-taskpane-conflict` rules — RED;
    built `taskpane.css` == source minus the whole marked block, byte for
    byte — green guard;
  - LIVE ROUTE RUN: `POST /api/item/<ref>/continue` APPLIES under BOTH the
    tip's surrogate key (resolution step 1, dict key) and its display id
    (step 2) — both 200 `applied` against the warm fixture; the stale-replay
    is 409. The panels carry `data-refdes-tip-key`, so the glue must post
    the KEY (rename-stable, Q5a). Green guard;
  - the 409 body is exactly {kind, ok, message, path, expected_revision,
    current_revision, current_text, diff} — no `rows`/`tasks` — green guard
    (this is why the conflict branch GETs the page).

(b) Source pins (comment-stripped, test_serve_static helpers imported):
  `taskpane-save.js` imports `./tick-save.js` + `./tick-pane.js`, NEVER
  `./taskpane-ticks.js` (the glue imports it: a cycle); exactly two `fetch(`
  sites (the POST with `method:'POST'`/`credentials:'same-origin'`/JSON
  header, and the GET of `location.href`); token via
  `querySelector('meta[name="refdes-token"]')` into `X-Refdes-Token` only —
  no `?token=`, no storage of any kind, no cookie, never a textContent;
  createElement/textContent only, no inline handlers, no dynamic code;
  `writeText` inside a try/catch; NO beforeunload (the glue owns the one).
  `taskpane-ticks.js` gains the import + ONE `initSave({drafts, panels,
  refreshPanel})` call and STILL contains none of fetch/XMLHttpRequest/
  X-Refdes-Token//api/ — the old pins re-asserted, unedited.

(c) NODE run of the seam over an honest fake (the repo's posture,
  test_editor_draft_mirror.py): plain FakeNode DOM from createElement, a
  fetch recording every (url, init) answering scripted {status, json, text},
  a location counting reloads, a clipboard recording text, a DOMParser stub
  that reads `data-refdes-*` out of the page TEXT it was handed (attribute
  extraction over real page text — no layout, no CSS, no cookies, no real
  events beyond a listener fired on the node that registered it). Scenarios:
  the POST is buildSaveRequest's path `/api/item/<KEY>/continue` with the
  header + {ticks, expected_revision}; saved → discard + reload once, no
  alert; 422 → message in role=alert, draft kept, Save enabled; transport
  throw → "did not reach the server", draft kept; 409 → GET location.href,
  DOMParser, `.refdes-taskpane-conflict` with current rows + my vanished row
  appended and EXACTLY ["Keep mine","Keep theirs","Copy it out"]; keep-mine
  discards then re-stamps my surviving ticks on the current tip key with the
  CURRENT revision (REV-9) and reloads; keep-theirs discards + reloads;
  copy-it-out shows copyOut.text in a read-only textarea + clipboard tried;
  a page with no panel for the thread offers ONLY two outcomes; the Save
  gate: hidden clean, shown pending, disabled in flight, enabled after.

All pins validated GREEN against a reference implementation kept in
`.scratch/w5b4c2b-tests/refstatic/taskpane-save.js` (scratch only, never
shipped) — so the seam author writes code to a contract that demonstrably
passes. The two recorder-array aliasing bugs found in my own harness
(scenario results shared the live `gets`/`copies`; the per-tab store leaked
between scenarios) were fixed by snapshotting results and clearing the
mirror per scenario.

## Red/green today

19 RED (the 9 source pins, the served-module 404, the CSS block, the glue
hook, and all 9 node scenarios — the harness exits red: `Cannot find module
.../taskpane-save.js`), 5 GREEN guards as marked (module tag, built-site
silence, byte-identical built CSS, the live route's two ref forms, the 409
shape). Full suite once: 6351 passed, 19 failed (only this file), 2 skipped.

## Conservative choices (no question tool was allowed)

- The glue must also collect its panel entries into a `panels` array to
  pass it (validated: import + `const panels = []` + one push + one call
  keeps every old pin true) — "hooks, not the network" preserved.
- The token regex accepts both meta-selector spellings
  (`meta[name="refdes-token"]` / `meta[name='refdes-token']`).
- No changelog.d fragment: test-only slice, nothing user-visible.

## Browser-only (not pinnable here — verify in Chromium and Firefox)

Button visibility/enablement as RENDERED and the two CSS rules' visual
effect; a real `location.reload()` landing on the re-rendered page with the
continuation as tip; the real same-origin cookie + token round trip under
CSP connect-src 'self' (the fake sends no cookies and knows no CSP); a real
DOMParser over a real preview page (real `panelFromRows` input fidelity,
including a hostile tip key in the parsed attributes); the clipboard
permission prompt and a real rejected clipboard; the beforeunload prompt
firing when a draft is open at navigation; the Save click while a real
rebuild makes the POST slow (in-flight disabled state as perceived).

Status: done — tests authored, all red-for-a-real-reason, suite verified,
pushed to feat/w5b4c2b-tick-save-ui.
