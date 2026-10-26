# xlsx-picker-listing

Task: `XlsxReader.list_entries` so the editor source picker lists `.xlsx`
citations (defined names, qualified sheet-scoped keys), + the
`calc-sources.md` §11 Q2 `refdes fetch --update` acceptance gate proven with
tests and a scripted isolated-project run. Branch `feat/xlsx-picker-listing`
off main at 703f0bd. Tree clean at start; no stash used.

## RED (recorded on the unimplemented baseline, before any src change)

`PYTHONPATH=src /home/jorb/work/venv-refdes/bin/python -m pytest -q
tests/test_sources_xlsx_list.py` -> 10 failed, 1 passed. Every failure was
the dispatch refusal (src/refdes/sources.py `list_entries`, line 1587
then): "the xlsx reader can extract named keys but cannot list a file's
entries" -- recorded e.g. at tests/test_sources_xlsx_list.py:261
(missing-extra test). The one pass (encrypted-workbook test) passed
trivially because its `"encrypted" in message` assert matched the filename
in the dispatch refusal; tightened the test to assert "the workbook is
encrypted" and "password" before implementing.

`... pytest -q tests/test_serve_sources_xlsx.py` -> 7 failed. Files payload
omitted the cited xlsx (problem: "can extract named keys but cannot list"
from serve/sources.py:704); entries/propose 422; e2e gate
IndexError on the empty listing (tests/test_serve_sources_xlsx.py:241).

## Implementation

src/refdes/sources.py:
- Factored the xlsx reader's shared pieces into module helpers used by both
  `extract()` and the new `list_entries()`: `_xlsx_module` (install hint),
  `_xlsx_open` (error mapping + OLE-magic probe for encrypted workbooks,
  which openpyxl would else report as "not a zip file"), `_xlsx_destination`
  (the one-cell-destination grammar, messages verbatim-identical to
  `extract()`'s), `_xlsx_defined_names` (scope order: workbook-scope bare,
  sheet-scoped qualified `Title!name`; bare spellings of sheet-scoped names
  deliberately NOT listed -- unqualified resolution is a fact about the
  whole name set, not one row).
- `XlsxReader.list_entries`: same open/grammar as `extract()`; a workbook
  `fetch` cannot open (corrupt/encrypted/over cap) raises; a name `fetch`
  would refuse (range, external, blank, text, uncached formula, sheet title
  containing '!') is listed with the problem, marked unselectable. Hidden
  sheets included and marked in context. Merged ranges show what `extract()`
  sees (top-left = value, inside = blank). Byte cap before opening; row cap
  stops the parse and sets `truncated`. Listing path never writes.

src/refdes/serve/sources.py: module docstring updated (xlsx is listed).
Line-701 check left as-is: it's a generic "reader has no list_entries"
defense; no registered reader hits it now (tests/test_sources_list.py
covers the dispatch refusal with a stub reader).

tests/test_serve_sources.py: one test rewritten --
`test_the_file_list_says_why_a_cited_file_is_not_listable` used the xlsx
gap as its "not listable" case; that premise is what this task removes, so
the case is now a cited `.py` (no reader), asserting "no source reader".

## RED-after-impl fixes (test expectation, not product)

- wide range: openpyxl parses `'Sheet1'!$A$1:$B$2` to one destination; the
  refusal is "must refer to one cell: not a single cell", not "exactly one
  cell". Asserted "one cell".
- byte-cap test forgot to pass `label`, so the default full path legitimately
  carried tmp_path. Passed label="big.xlsx".
- e2e body-insert forgot the YAML block-scalar indentation. Fixed.
- row-cap test key expectation (qualified "Sheet!k0").

## Acceptance gate (calc-sources.md §11 Q2)

- tests/test_serve_sources_xlsx.py::
  test_a_picked_xlsx_key_fetches_and_fetch_update_is_the_acceptance_gate:
  picker listing -> proposal read composes the line -> line saved into the
  item -> `refdes fetch --update` pins 1.85 -> cell drift -> plain fetch
  keeps the pin -> `fetch --update` accepts 2.3, sha256 changes, workbook
  bytes unchanged by the listing/proposal.
- Scripted run: .scratch/xlsx-picker-probe/run.sh (author's worktree only;
  `.scratch/` is gitignored, so the in-repo e2e gate test is the shippable
  proof), isolated project, real `refdes fetch --update` CLI; the run
  printed GATE PASSED (first pin 1.85, drift keeps, --update -> 2.3, bytes
  4844 -> 4845 only from the openpyxl edit).

## Docs / changelog

- docs/markdown.md picker section: xlsx listing described, removed from the
  cannot-offer list.
- docs/math.md: picker pointer in the xlsx paragraph.
- docs/design/editor-source-picker.md: §6 "only a file with a registered
  reader" (csv+xlsx), §8 xlsx bullet marked landed 2026-10-26, §11 Later
  paragraph updated.
- changelog.d/xlsx-picker-listing.added.md.

## Verification

- tests/test_sources_xlsx_list.py 12 passed;
  tests/test_serve_sources_xlsx.py 8 passed.
- Neighbours: test_sources_xlsx.py, test_sources_list.py,
  test_serve_sources.py, test_serve_pdf_sources.py,
  test_serve_sources_accept.py, test_sources_pdf.py, test_sources_csv.py,
  test_citations.py, test_fetch_size_warning.py, test_calc_sources.py
  (subset runs green; full suite at final head: 4908 passed, 2 skipped).
- ruff: `ruff check` on the four new/touched test files clean.
  src/refdes/sources.py: 11 ISC004, of which 9 pre-exist at HEAD; the two
  new ones are the same implicit-concatenation-in-collection style the file
  uses throughout (not claimed clean, per AGENTS).
  tests/test_serve_sources.py RUF059 x4 all pre-exist at HEAD.
- openpyxl 3.1.5 present; skip-on-missing behavior kept (importorskip in
  tests; install-hint message path shared with extract via `_xlsx_module`).

## Review round 1 (1 CHANGES REQUESTED, 1 APPROVE)

Accepted 4 findings (chunk-2 review): a workbook-scope defined name
containing '!' was listed selectable -- the key grammar reads the first '!'
as the sheet separator, so no key addresses it, and when the crafted name
collides with a sheet-scoped key's qualified spelling the picker shows a
value fetch can never pin (pairing invariant, the dangerous direction;
RED recorded at tests/test_sources_xlsx_list.py:179, fixed by a guard in
list_entries mirroring the '!'-sheet-title guard); `_xlsx_defined_names`
docstring misstated its yield; the '!'-sheet-title message overclaimed
("no key can name this name" -- extract's unqualified fallback can resolve
a bare key, the picker just never offers bare spellings; reworded);
`_strings` duplicated `strings` in test_serve_sources.py (imported now).
Rejected 1: "merged-range claim untested" -- the fixture merges D4:E5
(tests/test_sources_xlsx_list.py:38), the top-left raw/value pair is
asserted at :129 and the inside cell's "is blank" refusal at :149, both
inside the pairing loop's coverage. CI was all-pass (ubuntu, py3.13,
windows).

## Review round 2 (2 CHANGES REQUESTED)

Accepted all: the proposal read resolved the FIRST listing row for a key,
so a crafted workbook-scope `!` name listed ahead of the real sheet-scoped
row made the selectable row unproposable (`propose_payload` now prefers a
selectable match, marked match answers the refusal; RED at
tests/test_serve_sources_xlsx.py:265). Design-doc fixes: the dead
`sources.py:233-243` line refs dropped (both occurrences), §8 attribution
narrowed to destination-class refusals + `parse_decimal`. Log fixes:
own-commit sha dropped, stale counts refreshed, and the scripted gate
cited here lives in `.scratch/` (gitignored, author's worktree only --
the in-repo e2e gate test is the shippable proof).

Finished: yes.
