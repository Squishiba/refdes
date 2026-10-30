# Live inline-calc, slice B — browser panel (2026-10-29)

Design: `in-prog-logs/inline-calc-live-editor-design-20261020.md`
(§3.1-§3.8, §4 F1+F2+F3, §5 Slice B, §6 decisions 1-4). Base: origin/main
a78e30f (slice A route). Scope: browser-side only (`api.py` untouched).

## What landed

- `api.js` (F1): `api(path, { method = 'GET', body, signal } = {})` passes `init.signal` when provided.
- `live-calc.js` (F2, new): `createLiveCalc(handle, { getRevision,
  isSaving, getFields })` → `{ node, attach, detachFrom, destroy }`.
  400 ms trailing debounce (input/focus/open-editor triggers, blur
  flushes; a text without `:=` is pre-gated client-side: no request,
  panel cleared, §3.1); `AbortController` per request (supersede aborts
  the in-flight one); two silent-discard guards (sent-text snapshot
  `area.value !== sent`, `payload.revision !== getRevision()` — never
  app.js's unassigned `openRevision`, per §3.6/§1); apply gated on focus +
  not-saving + auto-fill pref; only `stale` rows with a FULL result pair
  (`result_start` AND `result_end`) are filled — a one-boundary span is
  display-only everywhere (D1 pin: an ok-within-window `4.4 V` vs computed
  `4.436 V` is never rewritten); caret skip: collapsed caret inside the
  result range inclusive of both boundaries, a NON-collapsed selection
  skips every range it overlaps; line-relative columns converted to
  document offsets via `lineStarts` computed ONCE per response batch
  (`spanOffsets(starts, span)`), Fill path converts its own snapshot;
  last-to-first application; caret shift only for ranges ending before
  the original caret; Case A `execCommand('insertText')` (one native undo
  step), Case B `.value` splice + no-undo panel line + auto-fill stand-down
  for the SESSION (`refdes.live-calc.fallback` in sessionStorage, so every
  controller the shell rebuilds is born stood down, with its own visible
  line "auto-fill is off for this session ...; Fill still works" and a
  checkbox that reads the EFFECTIVE state) + its own `schedule()` (a
  splice fires no input event); Fill idempotent (applied-range check);
  localStorage `refdes.live-calc.autofill` (absence = ON); truncation
  footer mirrors `PREVIEW_SPAN_LIMIT` (build.py:1937, pinned in sync by
  test_serve_static).
- `editor.js` + `item.js` (F3): controller built with accessors over the
  form's live `revision` and a `saving` flag set for the saveAll round-trip
  (dropped in `finally`), constructed after the `!edit.editable` return so
  read-only views never build it; `liveCalc.attach(area)` in `bodyControl`
  (re-arm on re-render, §3.8); panel returned as `liveCalcPanel`, mounted
  by item.js under the body textarea beside the pickers; item.js's
  `destroyLiveCalc(container)` is exported and called before EVERY
  container clear — item switch, fetch error, normal swap, AND the app.js
  shell clears (create form, empty selection) (§3.8: a pending timer, an
  in-flight request and the textarea listeners die with the view that
  owned them).

## Tests

- `tests/test_editor_live_calc.py` (new, node harness, house posture),
  scenarios: debounce + fields bag (VERBATIM against a
  `setDraftField`-written draft field); pre-gate (no `:=` → no request,
  panel cleared); supersede silent discard + re-request; revision guard
  (no-apply half asserted against `T1`); abort on supersede;
  blur-evaluates-only + refocus applies; caret inclusive
  start/end/inside/outside + non-collapsed overlap left/right/outside;
  line-4 offset conversion; last-to-first; caret shift (+1 only);
  Case B (splice, no-undo line, session stand-down: the REBUILT
  controller does not auto-fill and shows the session line, flag
  persisted); half-pair span (no Fill, no mutation); item-switch teardown
  via real `renderItem` (pending timer dies, in-flight aborted, listeners
  removed, no /calc for the switched-away item) INCLUDING the fetch-error
  same-handle re-render — driven as the real case (matching handle,
  children present, so the pre-fetch clear is provably skipped and the
  catch-path destroy is what kills the request; a FakeNode `firstChild`
  gap that had made this assertion vacuous is closed and the mutation
  below proves it); ok-within-window never rewritten; save-in-flight
  suppression + post-save guard pass; toggle persistence/OFF semantics;
  Fill idempotence. Fixture texts single-sourced. Passes under node
  v22.23.3.
- `tests/test_serve_live_calc_e2e.py` (new, real server): GET item → POST
  `/calc` (revision == `file_revision`, `snapshot_tree` byte-identity) →
  faithful client-side apply (stale-only, last-to-first) → POST `set_body`
  with the form's revision → file bytes carry `Vbad := 2 V * 2 = 4 V`,
  the ok span byte-identical, post-save full build reports NO diagnostic
  for DEC-001 (`== []`); second test threads two sequential saves'
  revision chain through `/calc`.
- `tests/test_serve_static.py` (extended): CSP/brace scans strip JS
  comments first; module exists/imported/attached; panel under the
  textarea beside the pickers; `destroyLiveCalc` before every clear in
  item.js AND the two app.js shell clears (count pins); editor builds the
  controller only for editable views; guard accessors + both response
  guards; debounce/fields/signal strings; one persisted localStorage key
  + the session fallback key and its visible line; stale gate AND pair
  gate; Case B schedule; batch `lineStarts` (one call per apply path,
  `toOffsets` gone); footer limit pinned against `build.PREVIEW_SPAN_LIMIT`;
  exactly one `area.value =` write; no `openRevision`/`innerHTML` in the
  module's CODE.

## Mutation checks (`.scratch/mut-*/`, harness pointed at the mutated copy)

- (a) revision guard neutered: FAILS — "a response whose revision is not
  the form's own applied".
- (b) caret containment exclusive (`<`): FAILS — "caret start ... was
  overwritten".
- (c) offset conversion off-by-one: FAILS — "a span on line 4 was not filled at its own converted offsets".
- (d)+(f1) switch-path clear runs before destroy (the review's bug) /
  catch-path `destroyLiveCalc` removed: FAILS — teardown reports in-flight
  not aborted, listener leaked, a /calc fires for the switched-away item;
  `failAborted` proves the fetch-error scenario is non-vacuous.
- (e) pair gate reverted to result_start-only: FAILS — the half-pair
  scenario's Fill count goes 0 → 1.
- (f2) session fallback made closure-scoped (flag never written): FAILS —
  the rebuilt controller auto-fills again.

## Browser checklist (design §5 Slice B, its own numbering) — REAL browsers

Driven via puppeteer-core + headless Chromium 153 (`.scratch/pptr/drive.mjs`,
per-item incognito contexts, real keyboard/focus/blur/localStorage/undo,
CDP reload) and playwright-core + headless Firefox (`.scratch/pptr/ff.mjs`,
fresh contexts). Serve run from the worktree src over the design fixture
(stale `Vbad := 2 V * 2 = 5 V` + ok-within-window `Vout := 2.218 V * 2 =
4.4 V` + DEC-003 fence-above-a-span item); fixture reset + rebuild
confirmed before each run.

| # | item | Chromium | Firefox |
|---|------|----------|---------|
| 1 | typed stale span warns live, settles to `= 4 V` | PASS | PASS |
| 2 | Ctrl+Z once restores typed text | PASS | PASS |
| 3 | caret start/end/inside skip, outside fills | PASS (4/4) | PASS (4/4) |
| 4 | fast typing never clobbered | PASS | PASS |
| 5 | stale item warns before first keystroke | PASS | PASS |
| 6 | toggle OFF: renders, no mutation, Fill works; survives real reload + item switch | PASS | PASS |
| 7 | Fill on auto-filled span is a no-op | PASS | PASS |
| 8 | blur mid-debounce evaluates only, no focus steal; refocus applies; parked caret skips | PASS | PASS |
| 9 | Ctrl+Z undoes a Fill-click fill as one step | PASS | PASS (9c) |
| 9b | (9)'s Case B sub-case: `execCommand` forced false → splice + no-undo line + session stand-down survives a RELOAD (rebuilt controller: checkbox unchecked, session line, typing never fills) | PASS | Case B NOT PROVEN (Firefox's insertText succeeds → Case A path, undo coverage verified as 9c); the session-flag machinery itself PASSes (pre-seeded flag → stood-down controller, no mutation) |
| 10 | conjunction of (1)-(9) in both browsers | PASS | PASS (9b as above) |
| 11 | ok-within-window `4.4 V` byte-stable | PASS | PASS |
| 12 | second-tab save: old-revision response dropped silently, panel re-requests after the 2 s poll rebuild, no banner, draft intact | PASS | PASS |
| 13 | span below line 0 (fence above): fill lands on the span's own converted range (byte-exact); caret at the same column on a different line does NOT skip; caret inside the converted range skips, Fill offered and works | PASS | PASS |

## Notes / deviations

- The served JS is the static dir of the running `refdes` package: the
  editable install outside this worktree serves its own copy, so browser
  testing of this worktree needs `PYTHONPATH=<worktree>/src`.
- `page.reload`/`page.goto` time out on the editor page with the default
  load wait (the preview iframe's event stream keeps the load event open):
  drivers reload via CDP `Page.reload` / `domcontentloaded`.
- The POST `/api` routes require the `Origin` header (server.py:789) —
  probe scripts outside the browser must send it.
- Review rounds 1-3 (session-scoped fallback, §5 renumbering, app.js
  clears, batch lineStarts, teardown/pre-gate/overlap tests, editor.js NITs)
  addressed above; round-6 NIT (`createLiveCalc` for fields-only editors)
  skipped by review, left as is.

Status: complete; checklist driven in Chromium + Firefox under design §5 numbering.
