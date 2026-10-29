# Live inline-calc, slice B — browser panel (2026-10-29)

Design: `in-prog-logs/inline-calc-live-editor-design-20261020.md`
(§3.1-§3.8, §4 F1+F2+F3, §5 Slice B, §6 decisions 1-4). Base: origin/main
a78e30f (slice A route). Scope: browser-side only; no Python source touched
(`src/refdes/serve/api.py` untouched, route from slice A).

## What landed

- `api.js` (F1): `api(path, { method = 'GET', body, signal } = {})` passes
  `init.signal` when provided.
- `live-calc.js` (F2, new): `createLiveCalc(handle, { getRevision,
  isSaving, getFields })` → `{ node, attach, detachFrom, destroy }`.
  400 ms trailing debounce (input/focus/open-editor triggers, blur
  flushes); `AbortController` per request (supersede aborts the in-flight
  one); two silent-discard guards (sent-text snapshot
  `area.value !== sent`, `payload.revision !== getRevision()` — never
  app.js's unassigned `openRevision`, per §3.6/§1); apply gated on focus +
  not-saving + auto-fill pref; only `stale` rows with a FULL result pair
  (`result_start` AND `result_end`) are filled — a one-boundary span is
  display-only everywhere (D1 pin: an ok-within-window `4.4 V` vs computed
  `4.436 V` is never rewritten); caret skip inclusive of both result-range
  boundaries; line-relative columns converted to document offsets via
  `lineStarts`; last-to-first application; caret shift only for ranges
  ending before the original caret; Case A `execCommand('insertText')`
  (one native undo step), Case B `.value` splice + no-undo panel line +
  auto-fill self-disable for the session + its own `schedule()` (a splice
  fires no input event); Fill idempotent (applied-range check);
  localStorage `refdes.live-calc.autofill` (absence = ON).
- `editor.js` + `item.js` (F3): controller built with accessors over the
  form's live `revision` and a `saving` flag set for the saveAll round-trip
  (dropped in `finally`); `liveCalc.attach(area)` in `bodyControl` (re-arm
  on re-render, §3.8); panel returned as `liveCalcPanel`, mounted by
  item.js under the body textarea beside the pickers; one
  `destroyLiveCalc()` helper called before EVERY container clear (§3.8:
  item switch, fetch error, normal swap — a pending timer, an in-flight
  request and the textarea listeners die with the view that owned them).
- `style.css`: `.live-calc` block (head, chips ok/stale/error, rows,
  Fill, warn note) in the file's existing one-rule-per-line style.

## Tests

- `tests/test_editor_live_calc.py` (new, node harness, house posture):
  17 scenarios — debounce + fields bag (asserted VERBATIM against a
  `setDraftField`-written draft field), supersede silent discard +
  re-request, revision guard (no-apply half asserted against `T1`),
  abort on supersede, blur-evaluates-only + refocus applies, caret
  inclusive start/end/inside/outside, line-4 offset conversion,
  last-to-first, caret shift (+1 only), Case B (splice, no-undo line,
  self-disable, Fill works, splice SCHEDULES its own recalculation),
  half-pair span (one boundary: no Fill, no mutation), item-switch
  teardown via real `renderItem` (pending timer dies, in-flight aborted,
  live-calc listeners removed, no /calc fires for the switched-away item,
  fetch-error path clears the same way), ok-within-window never
  rewritten, save-in-flight suppression + post-save guard pass
  (form revision `rev-1`), toggle persistence/OFF semantics (pref reset
  after the scenario), Fill idempotence. Fixture texts single-sourced
  (Python constants injected into the harness). Passes under node v22.23.3.
- `tests/test_serve_live_calc_e2e.py` (new, real server): GET item → POST
  `/calc` (revision == `file_revision`, `snapshot_tree` byte-identity) →
  faithful client-side apply (stale-only, last-to-first) → POST `set_body`
  with the form's revision → file bytes carry `Vbad := 2 V * 2 = 4 V`,
  the ok span byte-identical, post-save full build reports NO diagnostic
  for DEC-001 at all (`== []`); second test threads two sequential saves'
  revision chain through `/calc`.
- `tests/test_serve_static.py` (extended): CSP/brace scans now strip JS
  comments first (the naive scanner used to bend production prose;
  code, not prose, is the assertion surface); module exists/imported/
  attached; panel under the textarea beside the pickers;
  `destroyLiveCalc` before the first clear + a call per clear (count pin);
  guard accessors + both response-path guards (`area.value !== sent`,
  `area.value !== snapshotText`); debounce/fields/signal strings;
  `init.signal = signal` in api.js; one persisted localStorage key; the
  auto-fill stale gate AND the pair gate (`span.result_end !==
  undefined` ×2); Case B schedule; exactly one `area.value =` write; no
  `openRevision`/`innerHTML` in the module's CODE.

## Mutation checks (`.scratch/mut-*/`, harness pointed at the mutated copy)

- (a) revision guard neutered: FAILS — "a response whose revision is not
  the form's own applied".
- (b) caret containment exclusive (`<`): FAILS — "caret start ... was
  overwritten".
- (c) offset conversion off-by-one: FAILS — "a span on line 4 was not
  filled at its own converted offsets".
- (d) switch-path clear runs before destroy (the review's bug): FAILS —
  harness teardown scenario reports in-flight not aborted, listener
  leaked, a /calc fires for the switched-away item.
- (e) pair gate reverted to result_start-only: FAILS — the half-pair
  scenario's Fill count goes 0 → 1.

## Browser checklist (design §5 Slice B) — driven in REAL browsers

Driven via puppeteer-core + headless Chromium 153 (`/usr/bin/chromium`,
`.scratch/pptr/drive.mjs`, per-item incognito contexts, real keyboard/
focus/blur/localStorage/undo stack) and playwright-core + headless
Firefox (`.scratch/pptr/ff.mjs`, fresh contexts). Serve run from the
worktree src over the design fixture (stale `Vbad := 2 V * 2 = 5 V` +
ok-within-window `Vout := 2.218 V * 2 = 4.4 V`); fixture reset and
rebuild confirmed before each run.

| # | item | Chromium | Firefox |
|---|------|----------|---------|
| 1 | typed stale span warns live, settles to `= 4 V` | PASS (row + settled text) | PASS |
| 2 | Ctrl+Z once restores typed text | PASS (key events, real stack) | PASS |
| 3 | caret start/end/inside skip, outside fills | PASS (4/4 cases) | PASS (4/4) |
| 4 | fast typing never clobbered | PASS (tail + fill kept) | PASS |
| 5 | stale item warns before first keystroke | PASS (open flush) | PASS |
| 6 | toggle OFF: renders, no mutation, Fill works; survives real reload + item switch | PASS (checked=false after both) | PASS |
| 7 | Fill on auto-filled span is a no-op | PASS (pref=null, text stable) | PASS |
| 8 | blur mid-debounce evaluates only, no focus steal; refocus applies; parked caret skips, Fill offered | PASS (activeElement=BODY) | PASS |
| 9 | Ctrl+Z undoes a Fill-click fill as one step | PASS | PASS |
| 10 | Case B (`execCommand` forced false): splice, no-undo line visible, self-disable | PASS | NOT RUN (Chromium-only driver pass) |
| 12 | ok-within-window `4.4 V` byte-stable | PASS | PASS |
| 13 | second-tab save: old-revision response dropped silently, panel re-requests after the 2 s poll rebuild, no banner, draft text intact | PASS | NOT RUN (single-browser pass) |

Item 11 (both browsers pass (1)-(9)) is the conjunction of rows 1-9:
PASS. 10/13 Firefox runs NOT RUN: the Firefox driver covered (1)-(9)+(12);
extending it is mechanical, not run this round.

## Notes / deviations

- The served JS is the static dir of the running `refdes` package: an
  editable install at /home/jorb/work/refdes serves its own copy, so
  browser testing of this worktree needs `PYTHONPATH=<worktree>/src`.
- `page.reload`/`page.goto` with the default load wait time out on the
  editor page (the preview iframe's event stream keeps the load event
  open): the drivers reload via CDP `Page.reload` / `domcontentloaded`.
- Full-suite run and `refdes check` byte-identity: see PR checks.

Status: complete; browser checklist driven in Chromium + Firefox above.
