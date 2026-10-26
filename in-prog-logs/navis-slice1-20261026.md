# Navis slice 1 -- grammar, body scan, model, read-only CLI

Task: implement slice 1 of in-prog-logs/navis-design-20261025.md.
Branch: feat/navis-slice1, PR #382.

## Approach

Test-first: tests/test_navis.py (grammar, inertness, stripping, build
integration, hash invariants, rendering, index payload) and
tests/test_navis_cli.py (ls/all/show, exit codes, help) before the
implementation; RED recorded on the base (no `navis` module, argparse
`invalid choice: 'navis'`).

## What landed

- src/refdes/navis.py -- closed grammar
  (`<!--navi: [key ]text-->`, one closed comment per line), a scanner,
  parse_marker (closed family: no-text and key-shaped-head-outside-the-
  alphabet are warnings, never absorbed), strip_markers (render-local),
  scan(project) populating Item.navis, projection(project) as the one
  shared row service for the payload and the CLI.
- model.py: Navi dataclass; Item.navis (outside _hash_payload, so the
  scan cannot move a hash).
- build.py: scan step after compute_hashes/seal.verify; render_bodies
  strips markers from the render-local copy before md.render.
- render.py: top-level `navis` key in items_json, absent-key convention.
- cli.py: `refdes navis ls|all|show <selector>`; exit 0 clean, exit 2
  unknown selector, malformed markers on stderr.
- docs/markdown.md, docs/cli-reference.md,
  changelog.d/navis-slice-1.added.md.

## Hard invariant proof

Differential gate in .scratch/navis-slice1-diff/ (old code = main
merge-base via `git archive`, nasty fixture: CRLF file, list-file body,
fence/inline-code/page markers, malformed markers, unicode, inline calc
on a marker line, marker-splitting-paragraph repro, plus a marker-free
twin):
- plain project: check/index/build byte-IDENTICAL (minted keys
  normalized -- keys.mint uses secrets, run-local in both trees);
- marker project: the ONLY diffs are the `navis` payload key, marker
  warnings in check/diagnostics, and marker bytes consumed from item
  pages (whole-file normalized equality proves every html delta is
  navi-explained). content_hash values identical with markers present.

## Notes / decisions

- Keyless markers today; the key half is nullable in the payload and
  "keyless" in show output (minting is slice 2 per design).
- `all` names the archive's absence honestly (no store in slice 1).
- Marker line for a list-file body falls back to source_line (the
  body_line-is-None precedent).
- ruff scoped to touched files (repo-wide baseline has ~99 pre-existing
  findings, untouched; one pre-existing E501 in test_navis.py left).

## Review rounds 1-3 (condensed)

Three CHANGES-REQUESTED review rounds on PR #382. Round 1 fixed:
key-first `show` selector + show's exit-1 on load errors; a vacuous
scan-changes-no-hash test (stub placed before the first build, direct
payload pin added); dead code and a stale docstring; docs (usage banner,
key-first selector row, malformed-marker consumption, payload grammar).
Design-doc Status line and line cites refreshed. Rejected: design-doc
relocation, NBSP-after-key semantics, list-continuation inertness as
code (documented instead). Then rebased onto merged #377 (design-doc
§4 table-cell conflict; diff scope verified). Round 2: docs said "one
marker per line" -- the grammar yields two Navis for two closed
markers on a line; doc corrected, scan + strip pinned, fixture gained
the twin-marker line. Round 3: behavioural defect -- a marker alone on
its line inside a paragraph split the paragraph (strip left an empty
line = paragraph break). strip_markers became structural: marker-only
lines dropped whole (CRLF-safe), shared lines collapsed; docs, tests,
and the fixture/normalizer follow.

## Round 4: renderer-driven scan (root cause of review round 4)

Fourth review (two reviews, CHANGES REQUESTED) found the hand-rolled
line scanner diverging from the renderer in seven ways: Unicode-digit
`show` selectors crashing (str.isdigit accepts `²`); marker-only line
inside a blockquote splitting the quoted paragraph (bare `>` residue);
projection sorting by (file, line, TEXT) reordering same-line markers
(design §11 says document order); inline code spans closing on a later
line not inert; fences inside blockquotes not inert; a closed marker
spanning lines silently ignored; CRLF fences breaking inertness after
the fence. Plus projection rows must carry the item key (design §10:
resolve by key).

Root-cause fix, not per-case patches: the scan is now driven by the
project's own renderer -- `build._markdown_parser` token stream with
source maps (navis._live_markers/_scan_block). Comment and code-span
state carry across an inline token's newlines exactly as the renderer
reads them; markers outside the token stream (fences, indented code,
html blocks, tables structure) are inert by construction; a closed
marker spanning lines is a warning naming the opening line (unclosed
stays the existing unclosed-comment machinery). strip_markers maps the
scan's content spans onto raw lines (container prefixes shift columns;
validated span, text-locate fallback) and drops lines left as only
`>` prefixes. CLI: ASCII-digit ordinals. Projection: stable
(file, line) sort; source gains `key`.

Pinned by tests/test_navis_matrix.py: 21 Markdown contexts x 5 marker
placements x LF/CRLF = 210 cells, each asserting scan count, warning
count, and rendered HTML. Contexts include fences (bare, in-list,
in-blockquote), indented code, multi-line code spans, open comments,
raw html, tables, ATX/setext headings, link text, emphasis, escaped
backslash; placement alone/leading/trailing/two/span. The
open-comment + two-markers cell pins the swallow-to-first-`-->`
semantics; list-context span cells pin the unclosed-in-new-item
consequence. Two existing pins updated to the intended new behavior:
two-line closed marker now warns; payload source rows carry `key`.
docs/markdown.md: inertness reworded renderer-driven (lazy-continuation
markers under list items now COUNT -- behavior change from round 1's
documented "write at column 0" rule, which is now just a convention);
span warning; blockquote-only-line drop. docs/cli-reference.md: ASCII
ordinals, document-order row. Log itself trimmed per the same review
(no commit shas, rounds condensed, no stale pass counts -- CI is the
record).

## Round 5: rebase onto origin/main (#381 landed)

Branch rebased onto origin/main; sole conflict docs/cli-reference.md usage
banner, resolved keeping both sides (main's `recover`, branch's
`navis`). Diff scope re-verified (slice-1 files only); full suite green
post-rebase.

## Round 6: mapping layer (review round)

Reviewer reproduced A3 (strip empties an inert code-span twin, leaves
the live marker), B (escaped backtick opens a phantom code span), C
(`\<` escaped marker stripped, stray backslash left), D2 (two markers
in one table row scan in tokenizer order). One root cause:
text-search fallback + content-relative columns. Fix: `_scan_block`
honours backslash escapes; `_live_markers` maps content offsets to
absolute raw (line, col) through `_raw_prefix` (per-line cursors,
paragraph-then-cell matching) and validates each span's bytes;
`strip_markers` cuts the validated spans and collapses maximal
whitespace+marker runs (one space only between words, nothing before
punctuation); a mapping failure raises `NavisMappingError` (fail loud,
never guess). Bare bullets/`>`/ordered prefixes left on a line drop
with it. Matrix 210 -> 270 cells (A3/B/C/D2 contexts, inert-twin
placements, text-order assertions); full suite and gate green.
