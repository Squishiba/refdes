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
source maps (navis._live_markers/_scan_block -- round-4 symbols,
superseded by round 7's analyze_navis/_machine). Comment and code-span
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
placements x LF/CRLF = 210 cells (grew to 270 in round 6), each asserting
scan count, warning count, and rendered HTML: fences (bare, in-list,
in-blockquote), indented code, multi-line code spans, open comments, raw
html, tables, headings, links, emphasis, escapes. The open-comment +
two-markers cell pins the swallow-to-first-`-->` semantics; list-context
span cells pin the unclosed-in-new-item consequence. Two existing pins
updated to the intended new behavior: two-line closed marker now warns;
payload source rows carry `key`.
docs/markdown.md: inertness reworded renderer-driven (lazy-continuation
markers under list items now COUNT -- round 1's "write at column 0" rule
is now just a convention); span warning; blockquote-only-line drop.
docs/cli-reference.md: ASCII ordinals, document-order row.

## Round 5: rebase onto origin/main (#381 landed)

Rebased; sole conflict docs/cli-reference.md usage banner, resolved keeping
both sides. Diff scope re-verified; full suite green post-rebase.

## Round 6: mapping layer (review round, superseded by round 7)

Reviewer reproduced A3 (strip empties an inert code-span twin), B (escaped
backtick opens a phantom code span), C (`\<` escaped marker stripped, stray
backslash left), D2 (two markers in one table row scan in tokenizer
order). Fixed in round 7's rewrite; matrix 210 -> 270 cells survives.

## Round 7: deep-analysis restructuring (.scratch/sol/deep-analysis-pr382.md)

One cached `analyze_navis(body)` -> immutable `Analysis` feeds scan,
strip and projection: dedicated instrumented MarkdownIt (production
parser never decorated), per-token live ranges, table provenance grouped
by source line, last-line clip fixed. Plain `<!--` carries body-wide; an
unclosed `<!--navi:` is silent and inert; MULTILINE fires only within a
token. Fail-loud became fail-closed (`strip_markers` never raises, the
MAPPING diagnostic keeps bytes intact). Probes 79/79, differential PASS.
Added the round-6 review's pins (lone-CR, NUL, escaped-pipe, comment
syntax) + the 5,000-digit CLI ordinal -> exit 2.

## Round 8: review round (final)

Load-write announcement on stderr (stdout purity pinned for all verbs on
cold projects). Fill-row cell count escape-aware (reviewer's `\\|` repro
pinned). Fail-closed warning names the exception. Perf: bisected
`line_of`, single-join strip -- 5k markers 2.46s->1.24s, 5k-line para
2.21s->1.05s, 1k 0.12s->0.08s; 5k-strip correctness test added (no
wall-clock asserts). Ruff default rules: 0 findings on the four slice-1
files (SIM102/B023/ISC004/FURB136 fixed, BLE001 noqa'd with reason).
Design-log cites re-verified: `_scan_block` -> `scan_body`/`analyze_navis`; cli.py:60,97-108,3670-3685,3819-3844; build.py:3960-3961.
