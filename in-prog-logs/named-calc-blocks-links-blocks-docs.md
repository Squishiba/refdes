# named-calc-blocks-links-blocks-docs

Docs-only follow-up to named-calc-blocks Phases 1–4 (merged as #24, #25,
#26). Branch: ao/refdes-162/named-calc-blocks-docs, off main. Opened as
PR #28 against main (no merge).

## What changed

- docs/links.md — `#calc:name` fragment paragraph alongside `#field`:
  envelope (`[[DEC-PWR-001#calc:losses]]` / custom text), link-only-never-
  inline, required `calc:` prefix with the bare-fragment warning, and the
  warning-on-miss posture; plus one line in the fig/cite paragraph that a
  `#calc:` fragment is the same warning there.
- docs/blocks.md — new `## {{calcblock}}` section (parameter table, renders-
  never-evaluates, local-items-only, no empty state) + six failure-mode
  examples with real messages + one non-goal line (absence of `all=` is the
  no-wildcard rule at the calc boundary).
- docs/design/thread-workbench.md — one D1 note: `CalcLine.block` already
  tags each row with its block's name, so the inline attribution has which
  named calculation a value came from for free.
- docs/design/stale-arithmetic-signal.md — one sentence: the fence's
  `id="..."` sits outside the hashed calc text, so a rename moves
  `content_hash` but not `calc_hash`.
- changelog.d/named-calc-blocks-links-blocks-docs.added.md — fragment.
- in-prog-logs/named-calc-blocks-links-blocks-docs.md — this log.

## Name collision with the Phase 5 docs PR (#27)

While this branch was in flight, #27 "docs(calc): document named calc blocks
(Phase 5)" landed on main (24d1dbc), covering docs/math.md ("Naming a calc
block"), docs/markdown.md (fence info string validation), and
docs/troubleshooting.md — and it had already created
`changelog.d/named-calc-blocks-docs.added.md` and
`in-prog-logs/named-calc-blocks-docs.md`, the exact two filenames this task's
instructions asked for. That made PR #28 conflict with main.

Resolution: renamed this PR's two files to
`changelog.d/named-calc-blocks-links-blocks-docs.added.md` and
`in-prog-logs/named-calc-blocks-links-blocks-docs.md` and rebased the whole
change onto main as a single clean commit. #27's files stay untouched. No
content overlap: #27 documented the fence attribute/naming grammar in
math/markdown/troubleshooting; this PR documents the two *pointers* to named
blocks (`#calc:` fragments, `{{calcblock}}`) in links/blocks plus the design
notes. links.md/blocks.md now href `math.md#naming-a-calc-block` for the
naming grammar.

## Verified against a real build (not memory)

Scratch project `.scratch/calcblock-docs/` (imports upstream.json, items
DEC-PWR-001 with blocks supply+losses, CMP-PWR-001 with no calcs,
DEC-THM-009 unnamed-only, DEC-THM-010 rowless named block, CMP-X-001
imported):

- `[[DEC-PWR-001#calc:losses]]` → `<a class="ref"
  href="dec-pwr-001.html#calc-losses">`; custom text works; bare
  `[[DEC-PWR-001#losses]]` warns "reference to 'DEC-PWR-001' names field
  'losses', which type 'decision' does not declare".
- Fragment misses warn (exit 0): named-but-wrong (`(it names: supply,
  losses)`, fence order), unnamed-only ("add id=..."), no-calcs ("computes
  nothing").
- `#calc:` on fig:/cite: warns ("which figure references do not have").
- `{{calcblock}}` renders calcblock-caption + owner-identical
  `<table class="calc" id="calc-losses">`; all six failure messages captured
  verbatim (unknown block lists names sorted — "losses, supply"); item in the
  directive body renders literal text with no error); failing owner's error
  row passes through unchanged, no verdict of the directive's own.
- Hash claim: renaming `id="losses"`→`id="dissipation"` moved content_hash
  a7dde1eec2a46b05→5b697027ff0c8d28, calc_hash unchanged
  (684eec9089a10172); fence name restored afterwards.
- `CalcLine.block` field exists (model.py:440) — basis for the
  thread-workbench note.

Empty-state honesty: design §5.4's "empty state that is a paragraph" was
deliberately NOT implemented (per named-calc-blocks-phase3-impl.md); blocks.md
states that every nothing-to-render case is a build error with `⚠`.

## Status

Finished. Tests before rebase: 2112 passed; ruff E9,F clean. Docs build on
the rebased tree re-checked (no errors/warnings for touched files; the only
build ERROR is a pre-existing bound violation in the repo's own item data,
items/decisions/dec-pwr-001-... line 2, untouched by this branch). PR #28
open against main; no merge.