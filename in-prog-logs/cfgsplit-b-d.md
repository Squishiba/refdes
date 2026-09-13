# cfgsplit-b-d — Phase 2 batch D (backlog finding 28)

Branch `ao/refdes-54/root`, fast-forwarded with `git merge --ff-only
feat/config-split` onto `855cbb9` ("tests: migrate the shared helpers fixtures
to the two-file config"). Merge output confirmed `Updating e2a04eb..855cbb9`,
so the base contains 855cbb9.

Scope: `tests/test_calc.py`, `tests/test_former_ids.py`,
`tests/test_keys_links.py`, `tests/test_scaffold.py`, `tests/test_keys.py`,
`tests/test_revise_cli.py`, `tests/test_workspaces.py`, plus this log. Nothing
else touched — no `src/`, no `conftest.py`, no `helpers.py`, no other test
module, no CHANGELOG/changelog.d/backlog.

## Gate result

```
python -m pytest tests/test_calc.py tests/test_former_ids.py \
  tests/test_keys_links.py tests/test_scaffold.py tests/test_keys.py \
  tests/test_revise_cli.py tests/test_workspaces.py -q
221 passed in 4.20s
```

`grep -n "refdes.yaml"` on the seven modules: **no hits** (exit 1).

## What was substituted

| file | write sites | path renames | other |
|---|---|---|---|
| tests/test_calc.py | 8 (1 single-line, 7 multi-line) | 8 | 3 test names, 1 write→load pair |
| tests/test_former_ids.py | 6 | 13 | — |
| tests/test_keys_links.py | 3 (1 + 2) | 15 | — |
| tests/test_scaffold.py | 1 | 16 | 1 `.scratch` filename |
| tests/test_keys.py | 3 (1 + 2) | 13 | — |
| tests/test_revise_cli.py | 2 (1 + 1) | 11 | 4 lines re-wrapped |
| tests/test_workspaces.py | 4 (2 + 2) | 6 | 2 shapes below |
| **total** | **27** | **82** | |

All 27 writes were substitution 1 — `(X / "refdes.yaml").write_text(CONST,
encoding="utf-8")` → `write_project_config(X, CONST)` — with the constant or
inline literal byte-identical. The multi-line form lost its `encoding=` kwarg
and gained `tmp_path,` as the first argument, matching the shape in
`tests/test_boards.py`. Each module gained `from conftest import
write_project_config` in the isort position the migrated modules use (with
`import pytest` / `from helpers import ...`).

The 82 renames were the plain `refdes.yaml` → `refdes-project.yaml` filename
change at `load_project(config_path=...)`, CLI `["-c", ...]`, `read_text`,
`is_file`, `open()`, and one `assert path == str(tmp_path / ...)` in
test_scaffold.py.

## Shapes that were NOT one of the two substitutions

1. **tests/test_workspaces.py, `workspace_project` fixture** — wrote
   `refdes.yaml` (the whole config) *and* `refdes-project.yaml` (just
   `item_layout: workspace`), which was correct when the marker was a sibling
   settings file and is a clobber now. Merged into
   `config = write_project_config(tmp_path, WORKSPACE_CONFIG)` plus
   `item_layout: workspace` appended to the returned marker — the
   `_write_minimal_project` idiom from test_project_settings.py.
2. **tests/test_workspaces.py, `test_cross_workspace_severity_is_configurable`**
   (~line 252) — same clobber: it overwrote the sibling settings file with
   `item_layout` + `cross_workspace_severity`. Now appends
   `cross_workspace_severity: error` to the marker. This was the batch's only
   real failure (the severity never fired, because the overwrite had dropped
   `workspaces:`/`boards:` along with the settings), caught by the first test
   run and fixed; assertions untouched.
3. **tests/test_workspaces.py, `test_lint_ignores_imported_items_on_either_end`**
   (~line 286) — reads the marker back, appends an `imports:` block, writes it
   again. Kept as a plain `write_text` on `refdes-project.yaml` instead of
   `write_project_config`: the text is *already split* settings, and the helper
   removes `refdes-schema.yaml` when the text it is given declares no schema
   keys — so routing it through the helper deleted the fixture's own `types:`
   and broke the test. A read-modify-write of the marker is the honest shape
   here.
4. **tests/test_calc.py, `_equation_config`** — wrote then immediately loaded,
   so it uses the helper's return value:
   `config = write_project_config(...)` / `return load_project(config_path=str(config))`.
5. **tests/test_calc.py, three test *names*** named the retired file:
   `test_equations_load_from_refdes_yaml`,
   `test_a_builtin_equation_name_in_refdes_yaml_is_an_error`,
   `test_an_equation_cycle_in_refdes_yaml_is_an_error` → `..._the_project_config...`.
   Names only; no assertion changed. Renamed rather than logged as a straggler
   so `grep "refdes.yaml"` stays clean (the `.` in the pattern matches the `_`).
6. **tests/test_scaffold.py** — 15 of its 16 renames are not fixtures at all:
   they assert on the filename `scaffold.init` writes, read it back, or point
   `-c` at it. All became `refdes-project.yaml`, including the scratch file
   `refdes.yaml.scratch` → `refdes-project.yaml.scratch` (scaffold.py builds it
   as `config_path + ".scratch"`). Its one fixture-shaped write
   (`test_init_refuses_to_overwrite_an_existing_config`) went through
   `write_project_config`, which is what makes init's "already exists" refusal
   fire.
7. **tests/test_revise_cli.py** — four `cli_mod.main(["-c", ...])` calls passed
   100 columns after the rename; re-wrapped across three lines. No semantic
   change.

## Stragglers left in place (1 finding, 2 sites)

- **tests/test_revise_cli.py:136 and :152** (`test_git_identity_success`,
  `test_git_identity_failure_falls_back_and_warns`) overwrite
  `lifecycle_project / "refdes-project.yaml"` with a single
  `baseline_identity: git_identity` line, discarding every other setting the
  fixture wrote. They pass only because their assertions touch
  `outcome.stamped_by` and the absence of a `baseline_identity` warning, and
  `load_project` does not require `site:`. Not a config-rename failure and not
  what either test asserts, so left as-is per instructions — flagged for the
  lifecycle-fixture owner as the same clobber shape as item 2 above.

No site in these seven modules still points at `refdes.yaml`.

## Verification notes

- `python -m ruff` is not installed in this environment, so import order was
  matched by hand against the migrated worked examples (test_boards.py,
  test_schema_json.py, test_project_settings.py).
- The full suite was not run: per instructions it stays red while the other
  Phase 2 batches are in flight, and none of its failures are in scope here.
- `git status --short` before commit: the seven modules and this log.

## Status

**Finished.** Committed locally on `ao/refdes-54/root`, not pushed.
