# Progress: inline-calc live-editor design (2026-10-20)

Task (Jared, Sol cover): produce a reviewable design for live
inline-calc recalculation in the browser editor — "recalculates while I
type". Docs-only; no product code. Deliverable:
`inline-calc-live-editor-design-20261020.md` (same directory).

## What I did

- Read the governing docs: `docs/design/inline-calc.md` (D1/D2/D3 at
  :9-16), `docs/design/inline-calc-later.md` §"Live editor updates"
  (:20-31 — the parked direction this design implements),
  `docs/design/browser-editor.md` (:425-431 plain textarea + the
  unimplemented unsaved-preview proposal, :686-687 debounce/supersede).
- Read the code the design touches: `inline_calc.py` (grammar,
  `parse_span`, `compare_stored`), `build.py`
  (`_run_inline_span` :1651 — mutates `project.diagnostics` +
  `item.calc_values` :1704, so the live route needs its own read-only
  pass; `_run_item_calcs` :1719 event pass), `calc.py` (AST-whitelist
  evaluator), the serve stack (`api.py` route registry + gates,
  `server.py` token/Origin/1 MiB, `state.py` snapshot/revision), the
  editor JS (`editor.js` insert helpers write `area.value` directly —
  the native-undo problem; `api.js` has no signal support; `app.js`
  2 s revision poll).
- Branch/PR landscape: main `d620ab5` had slice 1 (#333); #347 (slice 2,
  hash format 6) adds `code_span_ranges` — the positional view the
  design's replacement ranges need — and retires the F12-5 cross-item
  ordering error (`build.py:1581-1587`, confirmed live in a probe);
  #345 (release gate) is orthogonal; the grammar branch
  `fix/inline-calc-f12-grammar-20261020` was cut at main during the
  design work and has since merged as #351 (main `1d6d325`).
- Probed in `.scratch/inline-calc-live-20261020/probe/` (CLI via
  `PYTHONPATH=src python -m refdes.cli` — the venv `refdes` on PATH
  points at `/home/jorb/work/refdes`, a different checkout; that bit me
  once, then I switched). Confirmed: the three main-branch check
  messages verbatim; half-typed span → "stored result missing" at parse
  stage; unclosed span → silent; ~130 µs/span evaluator cost; the
  fill round-trip (replacing the stored literal with `format_value`
  output makes `compare_stored` return None — this is what makes
  auto-fill stable); `load_readonly` overlay floor 0.011 s toy project,
  and `docs/performance.md:44-51` (2.0 s @ 400 items, 19.1 s @ 1500)
  kills per-keystroke full builds → design uses a narrow per-item
  preview pass with the overlay as a test oracle.
- Wrote the design deliverable (route contract
  `POST /api/item/<ref>/calc`, read-only `build.preview_inline_spans`,
  `live-calc.js` with debounce/abort/supersede/caret-skip,
  execCommand-undo with Fill fallback, three PR slices, open questions).
- Re-verified every file:line citation in the deliverable against the
  tree (AGENTS.md rule); corrected two (`_make_calc_resolver` :1525 →
  :1538, `run_calcs` by_key :1921 → :1915).

## Key design choices (flagged as open questions in the deliverable)

- Auto-fill the stored-result slot on pause (caret-inside skip,
  last-to-first, `execCommand('insertText')`, Fill-button fallback) —
  follows the parked direction; Fill-only is the fallback answer.
- 400 ms debounce, `":="` client pre-gate, AbortController +
  text-snapshot + revision triple guard on responses.
- v1 = body spans only: no fences panel, no fields bag, no iframe
  refresh (D2), no browser grammar (D3).

## Review round 1 (CHANGES REQUESTED)

Fixed broken internal §-references (the probes are §7, slices §5, and
the `indexOf`-exception note is §3.1, not the nonexistent §4.3);
updated the sequencing premise to main `1d6d325` (#351 merged, #347/
#345 still open) and re-checked the shifted `inline_calc.py`/`build.py`
line cites against it; rephrased "no route accepts body text" (the edit
route does — what is missing is a route that *evaluates* unsaved text).
Design proposal and owner-choice questions unchanged.

## Review round 2 (2026-10-26): owner decisions + baseline refresh

Task (Jared's answers, 2026-10-25): record the decisions in the
deliverable, replace §6's open questions with them, fold each into the
affected sections, and bring the baseline to current main. Docs-only;
the PR stays held.

- Rebased the branch onto origin/main (78c8954) — conflict-free (the
  branch touches only its two in-prog-logs files); pushed
  `--force-with-lease`; confirmed 1d6d325 is an ancestor.
- Re-verified every §1 fact and file:line cite against current main.
  Shifts from #347+: inline_calc.py `contains_trigger` :89→:91,
  `code_spans` :122→:210, `parse_span` :224→:306,
  `triggered_spans` :417→:519, `compare_stored` :478→:597;
  build.py `_run_inline_span` :1651→:1683, `_run_item_calcs`
  :1719→:1752, `run_calcs` :1913→:1937, `_make_calc_resolver`
  :1538→:1588, `_make_source_resolver` :1603→:1644 (signature is
  5-arg on main — the §3.4 call shape in the design was the branch's
  6-arg form and is fixed); api.py `handle` :41→:44, `_find_item`
  :92, `edit_state` :759, `_source_propose` :946. Unchanged after
  spot-check: calc.py, server.py, state.py, loader.py, security.py,
  preview.py, editor.js, drafts.js, api.js, item.js, tests. Moved
  cites fixed: serve/edit.py overlay judge :470→:500,
  performance.md :44-51→:44-52, inline-calc.md D1/D2/D3 :9-16→:16-23,
  item.js pickers :176-191→:176-190, app.js →81,93-104,107-121,128,
  drafts.js dropAppliedOp :310-326.
- §1 "Branch dependencies" section rewritten as "Landed since the
  first draft": #347 `ba6d153` (code_span_ranges :124, F12-5 retired
  — build.py:1622-1627, HASH_FORMAT 6 at :2260), #345 `c3073c6`
  (release gate `release_gate.inline_calc_results`), #367 `3c9035b`
  (`editor_journal.py`, library-only, no importer — grep-verified),
  #372 `27c4fda` (path scrubbing at the `handle()` choke-point).
- §6 is now "Decisions (Jared, 2026-10-25)": (1) auto-fill + Fill,
  toggleable — panel-header checkbox persisted in localStorage
  (rationale for per-user-over-project in §3.5), default ON
  (one-line flip), Fill idempotent, off loses no diagnostic;
  (2) 400 ms + blur flush (§3.1) with guard/caret interactions
  specified (§3.6); (3) panel under the textarea, recorded; (4)
  fields ARE inputs — request `fields` bag + preview-pass
  `fields=None` + unknown-key forward compat (§3.2/§3.3/§3.4,
  items B1/B3), grammar explicitly out of scope.
- Verified for the new §6.5 open question (field-reference grammar,
  the one thing now needed from Jared): calc pass reads only
  `item.body` (build.py:1785/1797/1840-1844); content-hash payload =
  invalidate-mode fields (build.py:2296-2303; model.py:23-26/:181/
  :688-694) + body; `calc_hash_for` is body-arithmetic-only (:2390);
  draft field shape `drafts.js:21`/`:236-241`; scalar rule
  api.py:1100-1102; `_apply_edit` known-keys posture :1087-1116.
  §3.8 gained the journal verdict: #367 unwired library, live layer
  writes no files → save/undo assumptions unchanged.
- Slices: A adds fields-inertness + `fields`-bag HTTP + unknown-key
  tests; B's checklist grows (6)-(10) for toggle persistence/off,
  idempotent Fill, blur flush/caret, blur-fill undo. Work table B3
  ~60, F2 ~200 lines. §7 probe note flags the F12-5 record as
  historical.

## Status

Round 2 done: decisions recorded, baseline current, citations
re-verified; pushed and PR #350 commented. Still held: the §6.5
field-reference grammar is the one open question left for Jared, and
implementation slices stay unstarted by design. No product code
touched, no tests run (docs-only).
