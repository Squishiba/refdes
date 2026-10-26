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
