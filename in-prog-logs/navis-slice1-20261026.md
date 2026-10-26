# Navis slice 1 -- grammar, body scan, model, read-only CLI

Task: implement slice 1 of in-prog-logs/navis-design-20261025.md.
Branch: feat/navis-slice1, base = main (design-doc commits included).

## Approach

Test-first as required: wrote tests/test_navis.py (grammar, inertness,
stripping, build integration, hash invariants, rendering, index payload)
and tests/test_navis_cli.py (ls/all/show, exit codes, help) before the
implementation. RED recorded on the base: test_navis.py collection failed
with `ImportError: cannot import name 'navis' from 'refdes'`; the CLI
file ran 11 failed / 1 passed (argparse `invalid choice: 'navis'`).

## What landed

- src/refdes/navis.py -- closed grammar
  (`<!--navi: [key ]text-->`, one closed comment per line), a scanner
  that reuses inline_calc's fence regexes and comment/backtick rules so
  fenced code, indented code, code spans, and open comments stay inert;
  parse_marker (closed family: no-text and key-shaped-head-outside-the-
  alphabet are warnings, never absorbed); strip_markers (render-local);
  scan(project) populates Item.navis; projection(project) is the one
  shared row service for the payload and the CLI.
- model.py: Navi dataclass; Item.navis (deliberately outside
  _hash_payload's type/fields/links/body, so the scan cannot move a hash).
- build.py: scan step after compute_hashes/seal.verify; render_bodies
  strips markers from the render-local copy before md.render.
- render.py: top-level `navis` key in items_json, absent-key convention.
- cli.py: `refdes navis ls|all|show <selector>`; exit 0 clean, exit 2
  unknown selector, malformed markers on stderr.
- docs/markdown.md (Navis markers section), docs/cli-reference.md
  (navis section), changelog.d/navis-slice-1.added.md.

## Hard invariant proof

Full suite: 4935 passed, 2 skipped. Differential gate in
.scratch/navis-slice1-diff/ (old code = main merge-base 78c8954 via
`git archive`, nasty fixture: CRLF file, list-file body, fence/inline-
code/page markers, malformed markers, unicode, inline calc on a marker
line, plus a marker-free twin):
- plain project: check/index/build byte-IDENTICAL (minted keys
  normalized -- keys.mint uses secrets, run-local in both trees);
- marker project: the ONLY diffs are the `navis` payload key, the
  malformed-marker warnings in check/diagnostics, and marker bytes
  consumed from item pages (whole-file normalized equality proves every
  html delta is navi-explained). content_hash values identical with
  markers present (index `items` unchanged).

## Notes / decisions

- Keyless markers today; the key half is nullable in the payload and
  "keyless" in show output (minting is slice 2 per design).
- `all` names the archive's absence honestly (no store in slice 1).
- Marker line for a list-file body falls back to source_line (the
  body_line-is-None precedent).
- ruff scoped to touched files: clean (repo-wide baseline has ~99
  pre-existing findings, untouched).

## Review round (PR #382, head 8a1b835)

Four reviews: 00c8317 (docs chunk, CHANGES REQUESTED), 992a913 (build/cli/
model, CHANGES REQUESTED), 7c53fb1 (navis.py/tests, CHANGES REQUESTED),
800855c (render, APPROVE). `gh pr checks 382`: all green.

Fixed:
- cli.py cmd_navis: show resolves a full 11-char key before reading the
  selector as an ordinal (all-digit keys are legal grammar); show now
  returns 1 on load errors (matches ls/all, `thread`, and the
  cli-reference claim). RED first: two new tests in test_navis_cli.py
  (all-digit key; show with a broken items file) -> green.
- tests/test_navis.py test_scan_changes_no_hash was vacuous (build never
  resets Item.navis, so stubbing scan on an already-scanned project
  compared navis-populated against navis-populated). Stub goes in before
  the first build now; added a direct payload pin (the builder's dict has
  no "navis" key on an item whose navis ARE populated) because the scan
  runs after compute_hashes, so the on/off build comparison alone is
  insensitive to a payload regression. Proof harness in
  .scratch/pr382-review-fixes/verify_scan_hash_test2.py: unpoisoned
  passes, poisoned _hash_payload trips the pin. The probe project builds
  before the monkeypatch is in force.
- navis.py: deleted dead _WSP; scan() docstring said project.warn, build
  appends to project.diagnostics.
- cli-reference.md: usage banner gained navis; show row documents
  key-first selectors. The exit-1-on-parse-failure claim is now true for
  all three verbs (code fixed, not docs weakened).
- markdown.md: malformed markers' bytes are consumed from the page (the
  text disappears until the warning's fix is applied); index payload
  "carries it" grammar; line-based indented-code rule noted (a marker
  indented under a list item is inert -- write markers at column 0).
- design doc: Status line was stale ("Nothing is implemented") -- now
  names slice 1 implemented, slices 2-4 not; build.py/cli.py/render.py
  line cites re-verified and shifted to head (the +1 import shifts and
  the navis insertions).

Rejected (PR comment): design doc placement (in-prog-logs, deliberate --
the design commits ride here; docs/design/ move is a docs-only follow-up
like #377/#379 territory); NBSP-after-key reads keyless (visible in ls,
design grammar says key + space, inline_calc precedent); duplicate
delivery with merged #377 (informational, now moot -- rebased onto main);
list-continuation inertness as code (design-adopted region rules,
inline_calc parity; documented in markdown.md instead).

## Rebase onto merged #377

#377 merged as squash b839a80; branch rebased with
`git rebase --onto origin/main 1d01356` so the diff is slice-1 files only.
One conflict: the design doc's §4 marker-table cell (main's #377 review
rewrote the "invisible" row) -- kept main's wording, applied the
build.py:1798-1804 cite shift. Diff scope verified file-by-file; targeted
49 green, diff gate PASS, full suite 4937 passed / 2 skipped; pushed
--force-with-lease (head 8ce86b3), PR body updated, disposition comment
posted.

## Review round 2 (head 75f0c0d, 1307f94a: one P3)

Docs/markdown.md said "one marker per line"; the scan yields one Navi per
marker (adjacent markers on a line are two Navis). Design §4 says "One
line, always" -- that binds a marker to a line (CRLF safety, exact line
reporting), it does not bind a line to one marker, and §4's closed-family
grammar closes each marker at the first `-->`; the scan matching the
grammar is right, the doc over-constrained. Fixed the doc to state the
accepted grammar (two closed markers on one line are two Navis at the
same line; one-per-line is convention, not enforcement), added
test_scan_two_markers_on_one_line pinning scan + strip of the adjacent
case, and appended a twin-marker line to the differential fixture's
marker project (gate PASS: both Navis in the payload at line 13, both
marker lines consumed from the page; plain project byte-identical).

Round 3 (orchestrator differential, head 56bb74a): behavioural defect.
A marker alone on its own line inside a paragraph split the paragraph:
strip_markers removed the marker bytes, leaving an EMPTY line, and a
blank line is a paragraph break. Old code (markers visible as escaped
text) kept one paragraph; new code broke it. Fix: strip_markers is now
structural -- a line of whitespace + markers only is dropped whole,
terminator with it (CRLF-safe: the per-line `\r` rides along); a marker
sharing a line with text is removed with the whitespace runs on its
sides, collapsed to one space where text remains both sides (no double
space, no leading-space line, no trailing-whitespace hard break). Line
numbers unchanged: scan runs on the original body, strip is render-local
(pinned by test_payload_lines_name_the_original_body_lines). Tests first
(RED with the exact repro, 9 failed): repro + paragraph-join, between
paragraphs, body start/end, CRLF, list item, table row, blockquote,
render-level single-<p>. Three pre-existing strip assertions (double
space, leading space, blank-line residue) updated to the new documented
rule. docs/markdown.md documents the removal rule. Differential fixture
gained the exact repro paragraph; its normalizer now drops marker-only
lines too, mirroring the fix; gate PASS (plain byte-identical, marker
deltas all explained, payload lines 16/17 name the original lines).
Targeted 59 passed; full suite 4947 passed, 2 skipped; ruff clean on
touched lines (one pre-existing E501 left alone).
