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
  ordering error (`build.py:1581-1587`, confirmed live in a probe);
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

## Review rounds (summary; reviewer-agent ids are labels, not commits)

Round 1 (reviewer agent, CHANGES REQUESTED): fixed broken internal
§-references, refreshed the sequencing premise to main `1d6d325` with
shifted cites re-checked, and rephrased "no route accepts body text"
(the edit route does — none *evaluates* unsaved text). Round 2:
recorded the owner's 2026-10-25 answers as §6 Decisions (toggle +
default-ON auto-fill, 400 ms + blur flush, panel placement, fields
as inputs) and rebased to main `78c8954`, re-verifying every §1 fact
and file:line cite (all shifts from #347+). Round 3 (reviewer agent
96ae35f CHANGES REQUESTED; 13c70b5 approved with a full-suite run):
auto-fill re-gated to `status == "stale"` after a probe-confirmed
defect (the old rule rewrote checker-accepted within-window
literals — `inline_calc.py:597`), plus the `truncated` response key,
§6 provenance, and `lifecycle.py:825`/:908 release-gate cites.
Round 4 (reviewer agent 6a6db80 CHANGES REQUESTED): blur now
evaluates only — refreshes the panel, arms Fill rows, never applies
text and never steals focus (applies only while focused;
refocus-then-insert rejected per `editor.js:102-118` analysis);
caret-skip defined inclusive of result-range boundaries; Fill
fallback split into Case A `insertText` (undo-protected) / Case B
`.value` splice (not); §7 inlined runnable reproductions of the
behavioural claims. Round 5 (reviewer agents 644f695d/02c3d871):
refocus-apply made mechanical (focus is a flush trigger, §3.1), the
~130 µs/span figure replaced by the measured 150-350 µs order,
superseded log bullets marked, and the "What I did" cites above
updated to current main; this section compressed to a paragraph per
AGENTS.md. (Round 5's log/deliverable edits were left uncommitted when
that session closed; this session committed them as-is after reading
them through — coherent, kept.) Round 6 (2026-10-29, owner decision):
§6.5's reference-syntax sub-question answered (Form A) — recorded as
§6.5a with the two-step `ITEM.$field` examples, the sigil-free check
(`calc.py` :1105/:1114-1122/:1151, `inline_calc.py:30/:67` at base
78c8954), the own-item non-cycle rule (bare own-id cycle verified
2026-10-29 by `refdes --no-write -c refdes-project.yaml check` on a
scratch copy, message at `build.py:1980`), the saved-target read
rule, and §6 item 5; the collision sub-question opened with the
bare-resolves-to-calc + WARNING proposal (error alternative
rejected — no calc sigil); unit/missing/hash sub-questions stay open
with drafting proposals inline. Slices §4/§5 updated: fields stay
accepted-and-unused until the new follow-up slice G1 ("field
references in calc spans", `calc.py` + `build.py`, ~80-120 lines
guess). Branch rebased onto origin/main (7 commits ahead of
`78c8954`), conflict-free; the doc stays verified against its stated
base 78c8954 (new cites read there), not re-baselined.
Round 7 (2026-10-29, reviewer: doc stale against main): rebased onto
origin/main `aec4dec`; baseline refreshed 78c8954→aec4dec with an
explicit re-verification record. Journal facts re-read at aec4dec:
#381 (`92ae18d`) wired the journal — `serve/edit.py:103` imports it,
`begin` :2196 / `complete` :2228 per save, CLI loads refuse while
pending (`cli.py:133`, exempt `init`/`recover` :111), `refdes
recover` exists (help run from the tree), browser-editor.md Status
line confirms. §3.8 reworked: wired state; live layer needs nothing
from it (api.py: no journal import, no writes — grep); the
pending-journal refusal of CLI/save (panel keeps rendering from the
in-memory snapshot) named. "later slice wires the journal (a §4
non-goal)" rewritten. Cite sweep: `git diff 78c8954..origin/main --
src` shows only cli.py/editor_journal.py/serve/edit.py/sources.py/
serve/sources.py changed (the agentcoder-queue PRs touch no cited
file), so the only moved cites were `serve/edit.py:500`→`:518` (two
sites) and the #367/#381 bullets; browser-editor.md shifted +1 (its
Status line) → :425-427→:426-428, :429-431→:430-432 (three sites),
re-read at aec4dec. No cite was left unverifiable. Slice B checklist
(10) fixed: now (1)-(9) incl. (6) per browser (localStorage is
per-browser storage) and (11) as stated next (no forward reference).

## Status

Rounds 1-7 done, pushed. Held: §6.5 policy sub-questions for Jared
(unit/missing/hash + the collision proposal); slices unstarted by
design. Docs-only; suite green on head.
