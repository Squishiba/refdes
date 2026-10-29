# Progress: inline-calc live-editor design (2026-10-20)

Task (Jared, Sol cover): produce a reviewable design for live
inline-calc recalculation in the browser editor — "recalculates while I
type". Docs-only; no product code. Deliverable:
`inline-calc-live-editor-design-20261020.md` (same directory).

## What I did

- Read the governing docs: `docs/design/inline-calc.md` (D1/D2/D3;
  :16-23 on current main), `docs/design/inline-calc-later.md`
  §"Live editor updates" (:20-31 — the parked direction this design
  implements),
  `docs/design/browser-editor.md` (:425-431 plain textarea + the
  unimplemented unsaved-preview proposal, :686-687 debounce/supersede).
- Read the code the design touches: `inline_calc.py` (grammar,
  `parse_span`, `compare_stored`), `build.py`
  (`_run_inline_span` — mutates `project.diagnostics` +
  `item.calc_values`, so the live route needs its own read-only
  pass; `_run_item_calcs` event pass; current-main lines :1683/
  :1736/:1752), `calc.py` (AST-whitelist
  evaluator), the serve stack (`api.py` route registry + gates,
  `server.py` token/Origin/1 MiB, `state.py` snapshot/revision), the
  editor JS (`editor.js` insert helpers write `area.value` directly —
  the native-undo problem; `api.js` has no signal support; `app.js`
  2 s revision poll).
- Branch/PR landscape: main `d620ab5` had slice 1 (#333); #347 (slice 2,
  hash format 6) adds `code_span_ranges` — the positional view the
  design's replacement ranges need — and retires the F12-5 cross-item
  ordering error (now the F12-5 retirement comment, `src/refdes/build.py:1622-1627`, confirmed live in a probe);
  #345 (release gate) is orthogonal; the grammar branch
  `fix/inline-calc-f12-grammar-20261020` was cut at main during the
  design work and has since merged as #351 (main `1d6d325`).
- Probed in `.scratch/inline-calc-live-20261020/probe/` (CLI via
  `PYTHONPATH=src python -m refdes.cli` — the venv `refdes` on PATH
  points at `/home/jorb/work/refdes`, a different checkout; that bit me
  once, then I switched). Confirmed: the three main-branch check
  messages verbatim; half-typed span → "stored result missing" at parse
   stage; unclosed span → silent; per-span cost of the order of
   150-350 µs (measured 158/200/358 µs for evaluate / +format /
   +compare); the
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
  tree (AGENTS.md rule); corrected two (the :1525→:1538 and
  by_key :1921→:1915 fixes were against the pre-#347 tree; those
  symbols are at :1588/:1957 on current main, cited as such in the
  deliverable).

## Key design choices (as first drafted — all superseded by the §6 decisions, recorded below)

- Auto-fill the stored-result slot on pause (caret-inside skip,
  last-to-first, `execCommand('insertText')`, Fill-button fallback) —
  follows the parked direction; Fill-only is the fallback answer.
- 400 ms debounce, `":="` client pre-gate, AbortController +
  text-snapshot + revision triple guard on responses.
- v1 = body spans only: no fences panel, no fields bag (superseded:
  decision (4) makes fields inputs, carried in a `fields` bag), no
  iframe refresh (D2), no browser grammar (D3).

## Review rounds

Rounds 1-10 (2026-10-20 → 2026-10-29): the owner's decisions landed
as §6 items 1-6 (auto-fill + toggle default ON, 400 ms debounce +
blur/focus flush, panel placement, fields bag, §6.5a grammar, §6.5b
field-reference policy); reviewers verified ~126 file:line cites
across rounds and the substantive findings all got fixed — auto-fill
re-gated to `status == "stale"` (a probe showed the old rule rewrote
checker-accepted within-window literals), blur reduced to
evaluate-only, the §3.6 revision guard re-keyed off the form's own
revision after grep proved `app.js`'s `openRevision` is never
assigned, the journal section re-baselined at `aec4dec` (#381 wired
it), the performance-table figures re-attributed to the whole
`POST /edit` handler with a direct `load_readonly(overlay=...)`
measurement added, and the §3.5 apply/skip spec pinned to
line-relative→document-offset conversion (round 10, with two
reviewer-found spec defects). Cite-level detail per round lives in
the deliverable's sections, not here.

## Status

Rounds 1-10 done, pushed. Nothing in §6 is open; slices unstarted
by design. Docs-only; suite green on head.
