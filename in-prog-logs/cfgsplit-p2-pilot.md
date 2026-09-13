# cfgsplit-p2-pilot — Phase 2 pilot batch (backlog finding 28)

Branch `ao/refdes-49/root`, fast-forwarded onto `feat/config-split`
(`aa94058 config: split project settings and schema overlay into two files`) —
confirmed by the merge output and `git log`.

Scope: the four pilot modules `tests/test_boards.py`, `tests/test_blocks.py`,
`tests/test_nav.py`, `tests/test_pages.py`, plus this log. Nothing else touched.

## Gate result

```
python -m pytest tests/test_boards.py tests/test_blocks.py tests/test_nav.py tests/test_pages.py -q
80 passed in 3.90s
```

Before the batch: **27 failed, 53 passed** — every one of the 27 was the
`LEGACY_CONFIG_ERROR` from a fixture that wrote `refdes.yaml` (or a `-c`
pointing at one). After: 80 passed, 0 failed. No test's assertions were changed.

`grep -n "refdes\.yaml"` on the four files: **no hits** (exit 1).

## What was substituted (counts, for sizing the rest of Phase 2)

| file | write sites | load/`-c` path sites | other |
|---|---|---|---|
| tests/test_boards.py | 8 | 3 | 1 docstring mention |
| tests/test_blocks.py | 3 | 8 | 1 helper inlined (below) |
| tests/test_nav.py | 2 | 0 | — |
| tests/test_pages.py | 2 | 0 | — |
| **total** | **15** | **11** | |

All 15 writes were the plain form
`(X / "refdes.yaml").write_text(CONST, encoding="utf-8")` →
`write_project_config(X, CONST)`, with the constant (or inline literal) text
byte-identical; the multi-line literal form just lost its `encoding=` kwarg and
gained `tmp_path,` as the first argument. Each module gained
`from conftest import write_project_config`.

The 11 load sites were the plain `refdes.yaml` → `refdes-project.yaml` rename:
`load_project(config_path=str(...))` in test_boards.py (3, two of them the
`board_project` audit tests, one inside `pytest.raises`), and the seven CLI
`["-c", str(blocks_project / ...), "ls", ...]` invocations. None of them were
write-then-load pairs in the same expression, so the
`config_path=str(write_project_config(...))` one-liner form was not applicable
anywhere in this batch — the fixture wrote the config and the test only loaded
it later.

## Shapes that were NOT one of the two substitutions

1. **tests/test_blocks.py:289
   `test_ls_omits_the_board_column_when_the_project_has_no_boards`** — built its
   project through `helpers._numeric_hint_project()`, which still writes
   `tmp_path/refdes.yaml` (tests/helpers.py:113). helpers.py is off-limits to
   this batch, so the fixture construction was inlined in the test:
   `write_project_config(tmp_path, NUMERIC_HINT_SCHEMA)` + the same
   `items/r.yaml` text, then `-c str(tmp_path / "refdes-project.yaml")`.
   Assertions untouched. `NUMERIC_HINT_SCHEMA` is imported from helpers
   unchanged; `_numeric_hint_project` is no longer imported here.
   **Cross-batch consequence:** the same helper is still called by
   `tests/test_ids.py`, `tests/test_integration.py` and `tests/test_lifecycle.py`
   (and `helpers._check_severity_project`, helpers.py:~203, writes
   `refdes.yaml` too). Those modules cannot go green until helpers.py is
   migrated, so **helpers.py should be its own batch scheduled before the
   batches that contain those three modules** — otherwise they will look like
   real failures.
2. **tests/test_boards.py:120** — a docstring mention of the repo's own config
   in `test_boards_registry_absent_is_inert` ("not a copy of this repo's own
   `refdes.yaml`"). Renamed to `refdes-project.yaml`; prose only, no behaviour.
3. **tests/test_blocks.py:220** (`test_index_only_local_items_not_imports`)
   looked like a third shape — it writes `BLOCKS_SCHEMA + "\nimports: ..."`
   rather than a bare constant — but it is still substitution 1 with a computed
   constant: the appended `imports:` key starts at column 0, so the helper's
   top-level split puts it in the settings file and `types:`/`link_types:` in
   the overlay. Test passes unchanged. Worth knowing for other modules that
   concatenate a constant with an extra settings block.

No site was left unfixed; there are no deliberate legacy-rejection fixtures in
these four modules (the legacy-rejection tests live in `test_config_split.py`,
which is not in this batch).

## Full suite

Not run to green — expected, per instructions, to stay very red while other
modules are other batches. For sizing, remaining `refdes.yaml` hits per module
(after this batch and phase 1's two):

test_standards 48, test_ids 32, test_revise_migrations 32, test_citations 29,
test_parse_markdown 37, test_revise 30, test_parse 25, test_render_assets 21,
test_build 19, test_former_ids 19, test_keys_links 18, test_scaffold 17,
test_calc 16, test_keys 16, test_revise_cli 13, test_workspaces 10,
test_links 8, test_stub_tests 8, test_parts 7, test_blocked 6,
test_config_split 5 (deliberate: those name the retired file on purpose),
test_lifecycle 4, test_seal 4, test_imports 2, test_integration 3,
helpers 2, conftest 1 (a comment), test_schema_json 1 (a comment).

## Time

Roughly 20 minutes wall clock end to end: ~5 reading the two worked examples,
the helper docstring and the four targets; ~8 of mechanical edits; ~4 of test
runs (one self-inflicted collection error — an import edit dropped
`import pytest` in test_blocks.py, fixed immediately); ~3 for this log.

## Status

**Finished.** Committed locally on `ao/refdes-49/root`, not pushed (no publish
requested).
