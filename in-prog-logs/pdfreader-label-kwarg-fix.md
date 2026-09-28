# PdfReader.extract() missing the `label` keyword

## The bug

`src/refdes/citations.py:989` `_extract_source_values()` calls
`reader.extract(path, requests, label=label)` unconditionally — every caller of
it does, whether or not it has a label to pass. `CsvReader.extract()`
(`src/refdes/sources.py:222`) takes `*, label: str | None = None` (added across
#57 and #59) and uses it as the file's name in every problem it raises, so a
caller that read bytes at a server path but serves a project-relative one never
leaks the server path. `PdfReader.extract()` was left on the old two-argument
signature, so any `.pdf`-cited source key raised
`TypeError: PdfReader.extract() got an unexpected keyword argument 'label'`
instead of the intended `SourceExtractionError`.

## Confirming it (before the fix)

`.scratch/pdf_typeerror_probe/probe.py` — a direct
`citations._extract_source_values(project, "probe-sheet.pdf", {"vout": []},
label=...)` — printed `BUG TypeError: ...`.

`.scratch/pdf_typeerror_probe/e2e.py` — a real fixture project (a `decision`
citing `docs/ds.pdf`, one calc line `P = source("docs/ds.pdf", "VOUT") | W`)
run through `cli_mod.main([... "fetch"])` — raised the `TypeError` out of
`fetch_all` at `citations.py:1417`, no report, no exit code.

## The fix

`src/refdes/sources.py` — `PdfReader.extract()` now takes
`*, label: str | None = None` and does what `CsvReader.extract()` and
`PdfReader.list_entries()` / `page_candidates()` already do:
`label = label if label else path.as_posix()`, so the refusal names the file by
whatever name the caller is allowed to say. The refusal itself is unchanged — a
PDF still extracts no values.

After the fix the same e2e probe prints:
`FAILED  .../docs/ds.pdf: the pdf reader does not extract values: ... (the
existing record for docs/ds.pdf is unchanged)` /
`1 citation(s) processed, 1 failed` / exit 1.

## Regression tests

`tests/test_sources_pdf.py`, new section "the fetch path (regression)":

- `test_a_pdf_cited_source_key_fails_fetch_as_a_source_error_not_a_crash` —
  real `refdes fetch` through `cli_mod.main` on a real project citing a real
  PDF; asserts exit 1, the reader's reason on stderr, no `TypeError` in the
  output, and no lockfile written.
- `test_the_source_value_call_site_passes_its_label_to_the_pdf_reader` —
  `citations._extract_source_values(..., label=canon)` against a loaded
  project; asserts the message is labelled with the project-relative name and
  carries no server path.

Both were run against the pre-fix signature and fail there with exactly the
reported `TypeError` (verified by temporarily reverting the signature, running
`pytest -k "pdf_cited_source_key or source_value_call_site"` → 2 failed, then
restoring the fix).

## Checks

- `pytest tests` (whole suite): **2545 passed, 2 skipped** in 182 s.
- `ruff check src/refdes/sources.py tests/test_sources_pdf.py`: 11 findings
  (10 `ISC004` in `sources.py`, 1 `RUF015` in the test file) — identical to the
  same command run against `HEAD`'s copies of both files, so nothing here added
  one. `ruff check --select I001` on the same two files — the only rule
  `pyproject.toml` adds — passes. Per AGENTS.md, `ruff check .` is not a clean
  baseline and unrelated findings were left alone.

## State

Done. Committed as `fix(sources): PdfReader.extract() accepts the protocol's
\`label\` keyword`, branch `jubilant-ostrich` pushed to origin, PR opened
against `main`.

Scratch probes left in `.scratch/pdf_typeerror_probe/` (`probe.py`, `e2e.py`,
`pr-body.md`) per AGENTS.md — gitignored, not committed.
