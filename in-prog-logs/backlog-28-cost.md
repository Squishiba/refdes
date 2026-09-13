# backlog-28-cost — correct finding 28's cost estimate in docs/design/backlog.md

## Task

Finding 28's "Cost" paragraph claimed the config filename was "referenced in
about fourteen places," all mechanical. That counted only source references and
omitted the test suite. Fix the one paragraph; touch nothing else.

## Verified counts (measured, not copied)

All measured with `git grep` against `aa94058^` (the commit that started the
config split; `aa94058^` == `main` tip `f28e63a`, i.e. the pre-migration tree).

- Source sites: 51 lines in `src/` mentioning `refdes.yaml` or `CONFIG_NAME`
  (`git grep -n "refdes.yaml\|CONFIG_NAME" aa94058^ -- src/` counts 51),
  across 13 modules. `git diff --name-only aa94058^ 855cbb9 -- src/` shows the
  migration touched exactly those 13: boards, build, calc, cli, imports, model,
  pages, revise, scaffold, schema, schema_json, standards, workspaces.
- Test references: 489 lines across all 32 test files
  (`git grep "refdes.yaml" aa94058^ -- tests/`). (`git grep -o` gives 500
  occurrences; 489 is the line count.)
- Of the 32, 10 files carry a schema-overlay key (`types:`/`link_types:`/
  `field_sets:`) and needed a two-way fixture split rather than a rename.
- 27 files under `tests/` import `tests/helpers.py` (26 test modules +
  conftest.py), which is why the shared helper had to land before any parallel
  batch.

## Notes on the numbers in the task description

The task text quoted "source sites: ~51" (matches), "523 across 66 files" and
"60 files define types:" (did NOT match this tree — measured 489/32 and 10/32
at the pre-migration commit). The task's own suggested commands return 32 files
and 3 CONFIG_NAME lines, so the prose figures were not reproducible here; the
paragraph uses the verified numbers ("fifty-one places across thirteen
modules", "489 references across all 32 test files", "10 of those files",
"27 files under tests/").

## Edit

Single paragraph in docs/design/backlog.md (finding 28, "Cost" section):

- Kept: revise.py cannot help (rewrites item files, not config layout), needs a
  one-shot command or manual procedure, breaking change at a version boundary,
  finding 27 depends on it.
- Added: real source count (51 / 13 modules), test suite count (489 / 32
  files), the two-way-split fixtures (10), the helpers.py dependency (27
  files), the phased plan, and the lesson that the original estimate counted
  source references only.

Status line, Local model verdict, and every other entry untouched.

## Verification

- `git diff --stat` shows only docs/design/backlog.md (+/- one paragraph).
- Edited paragraph re-read; structure and voice preserved.

## Status

Finished locally; not pushed.