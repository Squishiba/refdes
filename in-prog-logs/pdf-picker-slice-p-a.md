PDF source picker — Slice P-A (docs/design/editor-pdf-picker.md §12)
====================================================================

Task: implement Slice P-A — the read-only service half. `sources.page_candidates()`
(pypdf visitor extraction, row grouping, candidate-grammar reuse, caps), the
import-gated `pdf` reader registration, the page read endpoint, opening at the
cited `page:`/`section:` from the lockfile, and the extraction + endpoint tests.
No UI, no writes. Status at the end: landed, suite green, PR open.

What was built
--------------

`src/refdes/sources.py`

- `PageSpan` / `PageToken` / `PageRow` / `PageListing` — the page's data
  structures. A `PageToken` carries `value` (what `parse_decimal` pins) and
  `numeric_index` (0-based among the row's candidates, the number a lockfile
  record would name the value by), so the CSV reader's "raw + canonical + a
  problem" row shape survives into the page shape.
- `PdfReader.page_candidates(path, page, *, label, max_bytes, max_spans,
  max_candidates)` and the module-level `sources.page_candidates()` dispatcher
  (mirrors `list_entries`: `reader_for` first, a reader without pages raises
  rather than returning an empty page, `label` reaches the reader).
- Extraction is `page.extract_text(visitor_text=...)`; runs are grouped into rows
  by vertical proximity with a tolerance derived from the font size; tokens are
  the runs split on whitespace, ordered by x; a token is a candidate iff
  `sources.parse_decimal` accepts it — the same function the CSV reader uses, so
  the picker cannot offer a value `fetch` would refuse.
- Caps, named beside `MAX_LIST_ROWS`/`MAX_LIST_BYTES`: `MAX_PDF_BYTES` 32 MiB
  (refuses before the file is opened), `MAX_PAGE_CANDIDATES` 200 (stops the page
  and names what it did not read — the CSV row cap's posture),
  `MAX_PAGE_SPANS` 1000 (reports the page as too dense to browse and shows none
  of it, per §4's "rather than truncated into a lie").
- `PdfReader.extract()` and `PdfReader.list_entries()` both raise, loudly and
  for the right reason. `extract()` is §6's quoted-row re-location, which is
  Slice P-C; `list_entries()` is present-but-refusing rather than absent because
  an absent method would be reported as "the pdf reader can extract named keys
  but cannot list a file's entries", which is the wrong half of the story while
  `extract()` is unimplemented too.
- Registry: `_GATED` (extension → reader name) plus `register_pdf_reader()`,
  called at import. A gated extension is refused with the extra's install hint
  instead of "no source reader for '.pdf' files". The availability probe is
  `importlib.util.find_spec`, which does not import pypdf, so importing
  `refdes.sources` cannot pull the extra in and cannot trip over a
  half-imported `citations`; the one real import stays
  `citations._import_pypdf()`, called per read.
- `_positions_missing()` refuses a page whose runs are mostly on the page origin
  — the pre-6.19 pypdf symptom, see below — with the installed version quoted.

`src/refdes/serve/sources.py` / `serve/api.py`

- `GET /api/item/<ref>/sources/page?path=&page=` → the page as positioned text:
  `spans` (text + x/y/size/estimated width), `rows` (verbatim text, `labels`,
  `candidate_count`, tokens with `value`/`numeric_index`/`candidate`/
  `header_guess`), `prev`/`next`/`pages`, `open_at`, `cited`, `detail`, the three
  caps, and `sha256`/`pinned_sha256`/`drifted` (§4's "a page belongs to the
  bytes it was read out of", at the read boundary).
- `GET /api/item/<ref>/sources` now lists a cited `.pdf` with `reader: "pdf"`,
  `browse: "pages"` and `open_page` (§2.1's page-mode marker). A remote
  datasheet is listable when the fetch kept the bytes: the kept copy is read and
  checked against the lockfile's own sha256, and a hash-only remote citation is a
  `problem` with the fix in it (§10 Q4 option A).
- `_cited_pdf()` is the confinement: local goes through
  `citations.authorize_source_path` unchanged; remote answers two questions of
  its own (is this URL on *this* item — refused with `authorize_source_path`'s
  own sentence when not — and are the pinned bytes on this disk).

`tests/helpers.py` gained a real-PDF fixture: `pdf_run` / `pdf_page` /
`pdf_bytes` build a minimal, valid, uncompressed PDF (catalog, page tree, one
Type1 font, one content stream per page, correct xref). Shared by two test
modules, which is what `helpers.py` is for. `tests/test_citation_sections.py`
keeps using pypdf's own writer — it needs only bookmarks.

Tests: `tests/test_sources_pdf.py` (26, the extraction half of §11) and
`tests/test_serve_pdf_sources.py` (17, the endpoint half), both against real PDF
bytes. Nothing about the extraction is stubbed: the point of the slice is what
pypdf makes of a page, and a stubbed visitor would only prove this module can
read its own dict. The one stand-in is the position-gate test, which replays
the *old pypdf callback sequence* through a fake page object — the symptom, on
purpose, not a mocked "success".

Verified
--------

- `python -m pytest -q` (repo venv, `pip install -e ".[dev]"`): **2499 passed,
  2 skipped** (baseline on this branch before the change: 2456 passed, 2
  skipped; 43 new tests, none skipped).
- `ruff check src/refdes/sources.py tests/test_sources_pdf.py
  tests/test_serve_pdf_sources.py --select I`: clean. Also
  `ruff check --select E9,F src tests` (the CI gate): clean.
- `ruff check .` reports 247 findings on this tree vs the ~99 in AGENTS.md, which
  is the installed ruff 0.16.9 default set rather than `pyproject.toml`'s
  `[tool.ruff]`; the only findings in the new code are ISC004 (implicit string
  concat inside a list literal, the pre-existing style in this file — 3 of them
  are on main) and RUF015/RUF059 in tests, none of which are in a gate rule.
- The new tests were also run on **pypdf 6.19.0** in a second venv (the floor
  this change sets): 69 passed there too, including `test_citation_sections.py`.
- `release.py`'s `assemble_fragments` folds both new changelog fragments
  (checked on a read-only copy of `CHANGELOG.md`; the file was not written).

The thing worth knowing about
-----------------------------

**pypdf did not report text positions before 6.19, and the design's floor was
`pypdf>=4.0`.** Found by running the finished extraction against pypdf 4.0.0 and
bisecting the version: `visitor_text` is handed `(text, cm, tm, font_dict,
font_size)`, but up to and including 6.18 the `tm` is **zeroed** for every run
pypdf inserted a space in front of — which is most of a table's cells — with the
real position delivered on the *empty* callback immediately before it:

```
pypdf 6.18.0:  ('VOUT Efficiency', (72.0, 700.0))
               ('', (72.0, 700.0))            <- the space, with the real position
               (' MIN', (0.0, 0.0))           <- the run, with a zeroed matrix
pypdf 6.19.0:  (' MIN', (200.0, 660.0))      <- both correct
```

A datasheet table therefore came back with most of its cells on the page's
bottom-left corner: rows merged into one, and a page view drawn in the corner.
That is the exact failure class this feature exists to prevent, and no test
written against a modern pypdf would have caught it — which is why the tests
run on a real pinned floor and not just on whatever pip installs.

Fixed three ways:

1. `pyproject.toml`: `pdf = ["pypdf>=6.19"]` (and `dev` with it), with the
   reason in the comment. An optional extra's floor is not a new dependency, and
   `section:` resolution works on every version.
2. The reader refuses a page whose runs are mostly at the exact origin
   (`_positions_missing`), naming the installed version and the fix, instead of
   drawing it. Tested by replaying the old callback sequence through a stand-in
   page — the symptom, not a version number.
3. A second test asserts the other half: a page with one run genuinely on the
   origin is read, because a refusal there would cost more than it protects.

Decisions the design left to the code, and what was decided
---------------------------------------------------------

1. **One new route, not two.** §12 says "the page/candidate read endpoints"
   (plural) while §2.2 says "A new endpoint" (singular). Read as: that route plus
   `GET /api/item/<ref>/sources`, which now lists PDFs. One route
   (`/sources/page?path=&page=`) carries a page's runs, rows and candidates
   together, because a page's candidates *are* a property of the page and a
   row-scoped second route would re-extract the PDF to answer a question the
   first answer already contains. Recorded in the design doc's status block.
2. **The quote is space-joined.** §6's illustrative quote
   (`"VOUT Efficiency, VOUT=3.3 V, 12 V in, ..."`) shows comma separators, which
   reads as the panel's rendering of a row. `PageRow.text` is the row's tokens
   joined by one space, verbatim, and `PageRow.labels` (its non-numeric tokens) is
   the identity re-location matches on. **Open for P-C:** the join has to be
   fixed before anything is written to a lockfile, and re-location matches the
   token sequence, so P-C should record the space-joined form.
3. **`header_guess` on the wire, `tokens` not a separate `candidates` list.** §4
   wants the min/typ/max list to be "a property of the data structure"; a
   `candidate: true` flag plus `numeric_index` on every token is that, and at
   1000 runs a page a second copy of every token dict would double the payload
   for nothing. Nothing in the payload or in the dataclasses is named
   `selected`/`chosen`/`picked` — asserted on the *types*, not just on a payload,
   so a future consumer cannot find a selection to read.
4. **Page-endpoint read failures are 422, panel states are 200.** A page that
   cannot be read (unparseable, out of range, missing extra) is a failed
   request, in the existing `refused` vocabulary; "this page has no text" and
   "this page has no numbers" are 200s with `detail` and nothing to pick (§3).
   The CSV entries endpoint's 200-with-`problems` shape is for a *file* that is
   browsable but empty, which is a different question.
5. **A cited page the document does not have opens page 1 and says why**, rather
   than refusing the document — a stale `page:` is worth showing the document
   with the discrepancy named. An explicitly requested `?page=99` is a 422.
6. **The remote-kept-copy branch is PDF-gated.** A remote CSV with `keep_copy:
   true` is still refused as a remote citation, because `source()` reads only a
   committed file and widening that is a change to a shipped slice.
   **Open:** that asymmetry is deliberate but is a real inconsistency; worth a
   follow-up decision rather than leaving implicit.
7. **The install hint is a shared constant.** `citations.PDF_EXTRA_ERROR` is
   unchanged byte-for-byte and is now composed from a new
   `citations.PDF_EXTRA_HINT`, which the pdf reader's refusal uses. §11's test
   name says "the `PDF_EXTRA_ERROR` wording verbatim"; inlining the whole
   `section: needs the optional PDF extra: …` sentence into a *picker* message
   would have been literally verbatim and actively confusing, so the hint
   sentence is what both now share. The test asserts
   `PDF_EXTRA_HINT in PDF_EXTRA_ERROR` so they cannot drift.

Things I hit, and what they cost
--------------------------------

- **A `TJ` array with kerned words and no space characters arrives glued.** pypdf
  reports `[(VOUT) -120 (0.93)]` as the single run `VOUT0.93`, so a number glued
  to a label is not a number. Left as-is and pinned by a test: inventing the gap
  would mean guessing where a word ends, which is the one thing this feature
  exists not to do. The cost is a *missing* candidate, never a wrong one, and the
  row shows the glued text.
- **pypdf prepends a space to a run that starts a line of text away from the
  last**, so a run's own text can begin with whitespace with no glyph behind it.
  Token offsets are therefore counted from the first non-space character, which
  puts a run's first token exactly on the run's origin (a fact) while an interior
  space still takes its share of the estimated width.
- **pypdf's visitor reports no glyph widths.** A run's and a token's width is
  estimated at a nominal half-em per character, documented as an estimate at both
  the constant and the dataclass. It is used for token positions and the column
  guess, never for a number, which comes out of the token's own text.
- **Rotated runs.** pypdf reports a rotated run's baseline in its own frame, so
  rotated text groups wherever that lands. The row carries the text it grouped,
  so a merge is visible on the panel. Documented, not second-guessed.
- **The row tolerance is a proposal** (§10 Q7 says the numbers are guesses). A
  2pt baseline difference groups; a 6pt one does not, at 9pt. Pinned by a test so
  a wrong tolerance for a real table shows up there.

Test-fixture decisions worth knowing
------------------------------------

- The endpoint fixture's remote datasheet is pinned by hand (`citations.
  save_lockfile` plus a blob under `.refdes/copies/`), and `refdes fetch` is
  scoped with `--path datasheets/sheet.pdf`. A test that let fetch reach the
  network would fail when the network is down, and one that succeeded would be
  fetching bytes nothing pinned.
- Two existing assertions in `tests/test_serve_sources.py` used `.pdf` as the
  example of an extension with *no* reader. That is no longer true, so both now
  use `.xlsx` / `.pptx`, which is what those tests are actually about (dispatch
  by extension, no fallback text parse).
- `test_without_the_pdf_extra_…` monkeypatches `sys.modules["pypdf"] = None` and
  re-runs `sources.register_pdf_reader()`, then restores it. Making the gate
  re-runnable rather than a one-shot at import is what lets the "what does a
  server without the extra do" question be answered by running the decision
  instead of arguing about it.

Not done, deliberately
----------------------

- No UI, no positioned-text drawing, no confirm panel (Slice P-B).
- No accept, no `extract()`, no quoted-row re-location (Slice P-C, blocked on
  CSV Slice B by design).
- No `page:`/`section:` writes, no unit inference, no OCR, no pdf.js.
