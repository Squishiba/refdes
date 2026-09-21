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
