# Live inline-calc, slice B — browser panel (2026-10-29)

Design: `in-prog-logs/inline-calc-live-editor-design-20261020.md`
(§3.1-§3.8, §4 F1+F2+F3, §5 Slice B, §6 decisions 1-4). Base: origin/main
a78e30f (slice A route). Scope: browser-side only; no Python source touched
(`src/refdes/serve/api.py` untouched, route from slice A).

## What landed

- `api.js` (F1): `api(path, { method = 'GET', body, signal } = {})` passes
  `init.signal` when provided — verified by reading the file.
- `live-calc.js` (F2, new): `createLiveCalc(handle, { getRevision,
  isSaving, getFields })` → `{ node, attach, detachFrom, destroy }`.
  400 ms trailing debounce (input/focus/open-editor triggers, blur
  flushes); `AbortController` per request (supersede aborts the in-flight
  one); two silent-discard guards (sent-text snapshot,
  `payload.revision !== getRevision()` — never app.js's unassigned
  variable, per §3.6/§1); apply gated on focus + not-saving + auto-fill
  pref; only `stale` rows with a result range are filled (D1 pin: an
  ok-within-window `4.4 V` vs computed `4.436 V` is never rewritten);
  caret skip inclusive of both result-range boundaries; line-relative
  columns converted to document offsets via `lineStarts`; last-to-first
  application; caret shift only for ranges ending before the original
  caret; Case A `execCommand('insertText')` (one native undo step),
  Case B `.value` splice + no-undo panel line + auto-fill self-disable
  for the session; Fill idempotent (applied-range check);
  localStorage `refdes.live-calc.autofill` (absence = ON).
- `editor.js` + `item.js` (F3): controller built with accessors over the
  form's live `revision` and a `saving` flag set for the saveAll round-trip
  (dropped in `finally`); `liveCalc.attach(area)` in `bodyControl` (re-arm
  on re-render, §3.8); panel returned as `liveCalcPanel`, mounted by
  item.js under the body textarea beside the pickers; teardown sweep
  destroys the controller before the container is cleared.
- `style.css`: `.live-calc` block (head, chips ok/stale/error, rows,
  Fill, warn note) in the file's existing one-rule-per-line style.

## Tests

- `tests/test_editor_live_calc.py` (new, node harness, house posture):
  14 scenarios — debounce + fields bag, supersede silent discard +
  re-request, revision guard, abort on supersede, blur-evaluates-only +
  refocus applies, caret inclusive start/end/inside/outside, line-4
  offset conversion, last-to-first, caret shift (+1 only), Case B
  (splice, no-undo line, self-disable, Fill works), ok-within-window
  never rewritten, save-in-flight suppression + post-save guard pass
  (form revision `rev-1`), toggle persistence/OFF semantics, Fill
  idempotence. Passes under node v22.23.3.
- `tests/test_serve_live_calc_e2e.py` (new, real server): GET item → POST
  `/calc` (revision == `file_revision`, `snapshot_tree` byte-identity) →
  faithful client-side apply (stale-only, last-to-first) → POST `set_body`
  with the form's revision → file bytes carry `Vbad := 2 V * 2 = 4 V`,
  the ok span byte-identical, post-save full build reports no
  "stored result says" diagnostic; second test threads two sequential
  saves' revision chain through `/calc`.
- `tests/test_serve_static.py` (extended): module exists/imported/attached,
  panel placed under the textarea beside the pickers, teardown sweep
  before `restoreFocus`, guard accessors read the form's live revision +
  save window (`saving = false` in `finally`), debounce/fields/signal
  strings, `init.signal = signal` in api.js, one persisted localStorage
  key, stale-gate, `execCommand` + ≤2 `area.value =` writes, no
  `openRevision`/`innerHTML` in the module.

## Mutation checks (`.scratch/mut-*/`, harness pointed at the mutated copy)

- (a) revision guard neutered (`if (false) return;`): FAILS — "a response
  whose revision is not the form's own applied".
- (b) caret containment exclusive (`<` instead of `<=`): FAILS — "caret
  start: a result range containing the caret ... was overwritten".
- (c) offset conversion off-by-one (`starts.push(i)`): FAILS — "a span on
  line 4 was not filled at its own converted offsets".

## Headless chromium smoke (real browser, real server from worktree src)

`.scratch/smoke/` project served via `PYTHONPATH=src refdes serve`,
`chromium --headless=new --virtual-time-budget=15000 --dump-dom` on
`/edit/?token=…#/items/DEC-001`: panel node mounted in the live DOM
(`.live-calc-head`, title, autofill checkbox) and the open-flush round
trip rendered the stale row (`calc-chip-stale`, "stored result says 5 V,
now computes 4 V", Fill button). NOT exercised by the smoke: clicks,
typing, Ctrl+Z, blur/focus, Firefox (headless dump-dom runs no
interaction).

## Manual browser checklist (design §5 Slice B) — NOT RUN (no interactive browser in this environment)

1. type `Vbad := 2 V * 2 = 5 V` → panel warns live, settles to `= 4 V`
   after pause. NOT RUN (node-pinned: debounce + apply).
2. Ctrl+Z once restores typed text (undo-merged). NOT RUN (execCommand
   path only; real undo stack unpinned).
3. caret inclusive both boundaries blocks auto-fill. NOT RUN (node-pinned).
4. fast typing never clobbers typed text (supersede). NOT RUN in-browser
   (node-pinned; network panel not observed).
5. stale item opened → panel warns before first keystroke. SMOKE-PINNED
   (dump-dom shows the row after open flush, real chromium).
6. toggle OFF: renders, no mutation, Fill works; survives reload/item
   switch. NOT RUN (node-pinned; per-browser localStorage unchecked).
7. Fill on an auto-filled span is a no-op. NOT RUN (node-pinned).
8. blur mid-debounce fires; no mutation, no focus steal; refocus applies;
   caret-parked span stays skipped, Fill stays offered. NOT RUN
   (node-pinned).
9. Ctrl+Z undoes a fill as one native step. NOT RUN.
10. Case B via devtools: splice, no-undo line, self-disable. NOT RUN
    (node-pinned).
11. Firefox + Chromium both pass (1)-(9). NOT RUN (Chromium smoke above
    covers the open-flush mount/render only; Firefox not available).
12. ok-within-window literal never rewritten. NOT RUN in-browser
    (node + e2e pinned).
13. revision guard with second-tab save: silent discard, re-request
    after re-render. NOT RUN in-browser (node + e2e revision-chain
    pinned).

## Notes / deviations

- The served JS is the static dir of the running `refdes` package: an
  editable install at /home/jorb/work/refdes serves its own copy, so
  browser testing of this worktree needs `PYTHONPATH=<worktree>/src`.
- Comments in live-calc.js avoid possessive apostrophes and words starting
  `eval`: `test_serve_static.py`'s naive string scanner and `\beval` CSP
  regex scan whole files including comments.
- Full-suite run and `refdes check` byte-identity: see PR checks.

Status: complete (browser-interactive checklist recorded above as NOT RUN).
