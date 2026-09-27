# PDF datasheet picker — design spec (2026-09-27)

Task: write docs/design/editor-pdf-picker.md, the PDF-flavored sibling of
editor-source-picker.md, settling the editor half of calc-sources.md §1's
"picker for values in a PDF datasheet" requirement (Jared, 2026-09-21).
Docs-only; src/ and tests/ untouched.

## What I read first

- docs/design/calc-sources.md — all of it. §1's 2026-09-21 requirement block
  is the primary source: value in context on the rendered page, min/typ/max
  candidate list, nothing pre-selected, record file/page/section/quote/value
  on accept, lockfile pin + loud drift (Q2), visible "could not read this
  page", costs stated plainly (pypdf optional dep; pdf.js vs server render;
  "heaviest dependency the editor has"), sequencing after the CSV picker.
- docs/design/editor-source-picker.md — whole doc. Slice A landed 2026-09-25;
  Slice B (accept) and C (panel) design-only. Inherited: §3 confirm contract,
  §4 one-operation accept, §5 one-reader-in-Python, §6 confinement, §7
  server-composed line + no-default unit.
- docs/markdown.md "Citing a datasheet" + "Citing a section by name" — the
  shipped PDF capability; the `sections_sha256` rule ("a page belongs to the
  bytes it was read out of") became the coordinates-are-bytes-scoped rule.
- src/refdes/citations.py — `_import_pypdf()` (lazy, one site),
  `outline_titles`, `match_outline_title`, `resolve_sections`, SectionError
  kinds incl. KIND_GONE; kept copies under `.refdes/copies/`; keep_copy on a
  local path is an error (so local PDFs always have bytes; hash-only remotes
  never do — that became §10 Q4).
- src/refdes/sources.py — `SourceReader` protocol, `parse_decimal` (reused as
  the candidate grammar), `reader_for` registry, MAX_LIST_* caps.
- src/refdes/serve/sources.py — Slice A read endpoints; `propose_payload`
  exists, **no accept** → Slice B has NOT landed, so the spec says "reuse
  Slice B's accept when it lands; do not fork a second write path" (§6, §9).
- browser-editor.md — "PDF datasheet values" (verbatim rules), "no Node build
  step", security section ("no generic file-read endpoint").
- pyproject.toml — `pdf = ["pypdf>=4.0"]` optional extra precedent.

## Decisions taken in the spec (all reversible, all with recommendations)

- Dependency: reuse `refdes[pdf]`; no new mandatory or optional dep. Without
  the extra the picker offers no PDFs and shows the existing PDF_EXTRA_ERROR.
- Page view v1: server-extracted positioned text (pypdf visitor coords →
  JSON spans), NOT pdf.js, NOT server raster (poppler rejected outright).
  Bonus: no PDF bytes leave the process at all under this option.
- Candidate finding: pypdf `extract_text(visitor_text=...)`, rows by vertical
  overlap, candidates = tokens passing `sources.parse_decimal` (same grammar
  as fetch), min/typ/max = all numeric tokens of the row, none pre-selected;
  column-header guess labelled *guess*, never recorded.
- Durable key: author-named key; lockfile records reader/value/page/quoted/
  token index; re-location at fetch by exact match of the quoted row's
  NON-numeric tokens (tolerates the value changing = drift we want to see;
  row gone → KIND_GONE-idiom error; two matches → ambiguity, never a pick).
  This is the `section:` pattern applied to a row.
- Accept: reuse editor-source-picker.md §4 (Slice B) verbatim; request carries
  no value; server re-extracts; hash policy identical (changed → refuse +
  fetch --update direction).
- Hash-only remote datasheets: refuse visibly with the keep_copy hint; the
  editor does no network I/O.
- Non-goals: OCR (confidently-wrong-digit failure class), the accept
  mechanism itself, pdf.js/raster, numbers in figures, fetch --update in the
  browser, writing page:/section: into citations (matches Jared's 2026-09-26
  §9 Q2 decision for CSV).
- Phasing P-A (reads) / P-B (panel, with-or-after CSV Slice C) / P-C (accept,
  blocked on CSV Slice B).

## Cross-references added

- calc-sources.md §1: "Note (2026-09-27)" after the Sequencing paragraph,
  matching the 2026-09-25 CSV-picker note's shape.
- editor-source-picker.md §8 "PDF datasheet values" bullet: "Now proposed in
  editor-pdf-picker.md …".

## Gate

- pytest -q -x: 2427 passed, 2 skipped in 150s.
- ruff check --select E9,F src tests: All checks passed!
- Docs-only; no changelog.d fragment (precedent: 6d2d2c3 docs-design commit).
