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

Fixed broken internal §-references; updated the sequencing premise to
main `1d6d325` (#351 merged) with shifted cites re-checked; rephrased
"no route accepts body text" (the edit route does — none *evaluates*
unsaved text). Design proposal unchanged.

## Review round 2 (2026-10-26): owner decisions + baseline refresh

Task (Jared's answers, 2026-10-25): record the decisions in §6, fold
each into the affected sections, bring the baseline to current main.

- Rebased the branch onto origin/main (78c8954) — conflict-free (the
  branch touches only its two in-prog-logs files); pushed
  `--force-with-lease`; confirmed 1d6d325 is an ancestor.
- Re-verified every §1 fact and every file:line cite against current
  main (line-number shifts from #347+ across inline_calc.py/build.py/
  api.py; §3.4's resolver call shape fixed to main's 5-arg
  `_make_source_resolver`; moved cites fixed in serve/edit.py,
  performance.md, inline-calc.md, item.js, app.js, drafts.js). The
  round-3 reviewer independently re-verified this list — all matched.
- §1 "Branch dependencies" section rewritten as "Landed since the
  first draft": #347 `ba6d153` (code_span_ranges :124, F12-5 retired
  — build.py:1622-1627, HASH_FORMAT 6 at :2260), #345 `c3073c6`
  (release gate `release_gate.inline_calc_results`), #367 `3c9035b`
  (`editor_journal.py`, library-only, no importer — grep-verified),
  #372 `27c4fda` (path scrubbing at the `handle()` choke-point).
- §6 became "Decisions (Jared, 2026-10-25)": (1) auto-fill + Fill
  behind a localStorage toggle, default ON, Fill idempotent, off loses
  no diagnostic; (2) 400 ms + blur flush (§3.1/§3.6); (3) panel under
  the textarea; (4) fields ARE inputs — request `fields` bag +
  preview-pass `fields=None` + unknown-key forward compat (§3.2-§3.4),
  grammar out of scope. New §6.5 open question (the field-reference
  grammar) grounded in verified facts: calc reads only `item.body`;
  content hash = invalidate-mode fields + body; `calc_hash_for` is
  body-arithmetic-only; draft field shape + scalar rule cited. §3.8
  journal verdict: #367 unwired → live-layer assumptions unchanged.
- Slices: A adds fields-inertness + `fields`-bag + unknown-key tests;
  B's checklist grew (6)-(10); work table B3 ~60, F2 ~200 lines; §7
  flags the F12-5 probe record as historical.

## Review round 3 (2026-10-26): 96ae35f CHANGES REQUESTED

(13c70b5 approved: full suite on head 4888 passed / 2 skipped; CI
green incl. Windows — nothing to fix.)

- F1 (high, probe-confirmed defect): auto-fill keyed on
  `computed != stored` across ok+stale spans rewrote within-window
  literals the checker accepts (`compare_stored` → None,
  `inline_calc.py:597`; `Vout := 2.218 V * 2 = 4.4 V` is ok at
  computed `4.436 V`). Gate is now `status == "stale"` (§3.5, §6.1,
  F2 row); checklist (11) = byte-identical regression pin.
- F2: §6 provenance paragraph (in-session answers 2026-10-25; §6 is
  the first tree record; transcription into inline-calc.md offered).
- F3: `truncated` schema key (sibling of `spans`, omitted when not
  cut) + guard: source order, excess omitted, panel footer line.
- F4: release-gate cites → `lifecycle.py:825`/:908; §7 reproducibility
  paragraph. Rejected: `docs/math.md`/`changelog.d/` exist (ls) —
  slice C accurate. F5: PR body reconciled (`gh pr edit` aborts on
  the projects-classic GraphQL deprecation; `gh api PATCH` works).

## Review round 4 (2026-10-26): 6a6db80 CHANGES REQUESTED

- F1 (high): blur-time apply needs the focused host
  (`execCommand('insertText')`; `insertIntoBody` focuses first,
  `editor.js:102-118`) — as written, blur fills no-op or splice.
  Per the owner's exact answer ("evaluate on blur", not
  apply-on-blur): blur flushes + refreshes the panel + arms Fill
  rows, **never applies text, never calls focus()**; applies only
  while focused (§3.1, §3.5 focus-rule bullet — refocus-then-insert
  rejected; §3.6, §6.2); checklist (8)/(9) rewritten.
- F2: caret-skip defined inclusive, `result_start <= caret <=
  result_end` — pausing after a partly-typed `= 5` never overwrites
  (§3.5, §3.8, checklist (3); the old "unfocused *and* caret-in-span"
  clause is subsumed by the focus rule).
- F3: Fill fallback = one path per case: Case A `insertText`
  (undo-protected) / Case B `.value` splice (**not**
  undo-protected, panel says so, entered only after `insertText`
  proves false in the session; §3.5, §3.8).
- F4: §7 inlines a runnable reproduction of the ok/stale/parse/
  unclosed claims + fill round-trip (verified from the tree).
  Citation fixes: `run_calcs` edges cited as docstring :1941-1948;
  footer states AGENTS.md's deliverable-report exemption.

## Status

Rounds 3+4 done, pushed. Held: §6.5 grammar question for Jared;
slices unstarted by design. Docs-only; suite green on head.
