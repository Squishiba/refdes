# calc-sources V1 (finding 26) -- progress log

Task: implement docs/design/calc-sources.md section 10 V1 scope (CSV only).
Branch ao/refdes-121/root. Not pushed; orchestrator (refdes-2) lands.

## Decisions recorded
- Q2 (Jared 2026-09-21): changed source file WARNS LOUDLY; build uses the
  lock-pinned value; `fetch --update` is the acceptance gate;
  `--require-citations` promotes to error. Commit 03e6d92 updates the doc.

## Chunk 1 -- CSV reader (done)
- src/refdes/sources.py: SourceExtractionError, SourceRequest/ExtractedSource,
  SourceReader protocol, CsvReader, extension registry.
- tests/test_sources_csv.py: named tests 1-7 at reader level.
- Choices where the doc is silent: fully blank physical lines are skipped
  (no fields, cannot shift a column); a row with a blank key cell anywhere in
  the file is an error (doc: "Error for that row"); only key/value headers must
  be unique, duplicate context headers are harmless.
- Full suite: 1413 passed.

## Chunk 2 -- source() in calc, lockfile values, fetch, Q2 drift, hash, render (done)
- calc.py: `source("path","key")` recognised as the WHOLE right-hand side
  (`parse_source_call`, quote-aware `split_comment` so a key may hold `#`),
  resolved through `SOURCE_RESOLVER_KEY` (lock-only); mandatory `| unit` (`| 1`
  dimensionless); `± tol` on the line works via the shared `apply_tolerance`.
  `source` is reserved and rejected inside project equations (section 9).
- **Unit semantics deviation worth knowing**: the doc says annotations "convert/
  assert" but its own example (`1850` under `| W` shows `1850 W`) needs the
  unit to LABEL the bare number, not convert a dimensionless value. Implemented
  as labelling (`quantity(text, unit)`); `| mW` shows `1850 mW`.
- citations.py: `authorize_source_path` (same-item, local-only; shared by fetch
  and evaluation), `collect_source_uses`, lock `values:` map, fetch extraction
  atomic per file (extract first; failure leaves old record; pin+values
  written together), no-update refresh only while file == pin, `--update`
  diffs `old -> new`, advisory exact-1000x warning, `_source_drift` for Q2.
- Q2 drift: verify() replaces the generic "local citation changed" note with
  `SOURCE FILE CHANGED: ...` naming file, key, locked vs file-now, users and the
  exact accept command; also on `CalcLine.source_drift` -> rendered under the
  row (`.calc-source-drift`); `--require-citations` makes it an error. Reading
  the live file there is diagnostic only -- the value evaluated comes from the
  lock (test: reader monkeypatched to raise, value still resolves).
- build.py: hash payload `source_values` (format >= 4 only; absent for items
  with no source(); HASH_FORMAT stays 4). Render badge `source: path · key = v`.
- Tests: tests/test_calc_sources.py (named tests 1,8,9,10-16,22 + Q2 + units),
  no-write fixture in tests/test_no_write.py now has a drifted source item.
- Docs: docs/math.md section, docs/cli-reference.md fetch, changelog.d x2.

## Open / needs Jared (not guessed)
- **Q5 source-level tolerance**: decided "allowed and optional; source tol +
  RHS tol together is an error", but the doc never says WHERE a source-level
  tolerance lives (a CSV column? a citation field?). V1 supports only the
  RHS `± tol` on the source() line. No second location invented, so the
  "both -> error" rule has nothing to fire on yet.
- Blank-key rows anywhere in a CSV are an extraction error (doc: "error for that
  row"); a spreadsheet export with a trailing `,,` row would therefore fail.
  Left strict per the doc; loosen only if a real file needs it.
