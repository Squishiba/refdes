# cfgsplit-b-c — Phase 2 batch B/C (backlog finding 28)

Branch fast-forwarded onto `feat/config-split`; `git log -1` is
`855cbb9 tests: migrate the shared helpers fixtures to the two-file config`.

Scope: `tests/test_citations.py`, `tests/test_parse.py`,
`tests/test_render_assets.py`, `tests/test_build.py`,
`tests/test_blocked.py`, plus this log. Nothing else touched — no `src/`,
no `conftest.py`, no `helpers.py`, no other test module.

## Gate result

```
python -m pytest tests/test_citations.py tests/test_parse.py tests/test_render_assets.py tests/test_build.py tests/test_blocked.py -q
136 passed in 8.12s
```

Before the batch (verified by stashing the five files and re-running):
**119 failed, 17 passed** — every failure was the `LEGACY_CONFIG_ERROR` from a
fixture writing `refdes.yaml`, or a `-c`/`load_project` path naming one. After:
136 passed, 0 failed. No assertion in any test was changed.

`grep -n "refdes\.yaml"` on the five modules (excluding
`refdes-project.yaml`/`refdes-schema.yaml`): **no hits** (exit 1).

## Substitution counts

| file | `write_project_config` sites | `refdes-project.yaml` path sites |
|---|---|---|
| tests/test_citations.py | 7 | 24 |
| tests/test_parse.py | 8 | 18 |
| tests/test_render_assets.py | 9 | 12 |
| tests/test_build.py | 6 | 14 |
| tests/test_blocked.py | 2 | 4 |

Constants were left byte-identical; the helper splits them by top-level key.
The multi-line literal write (test_citations.py
`test_items_json_citations_empty_for_items_without_citation_fields`) just lost
its `encoding=` kwarg and gained `tmp_path,` as the first argument. Each module
gained `from conftest import write_project_config`.

## Shapes that were not the two plain substitutions

All five were resolvable from context; none left as a straggler.

1. **`tests/test_citations.py` `_enable_publish_datasheets`** — used to write a
   one-key `refdes-project.yaml` *beside* the fixture's `refdes.yaml`. That file
   is now the settings file itself, so overwriting it would have deleted
   `site:`/`id:`/`history:`/`units:`. Now appends `publish_datasheets: true` to
   the file the fixture wrote. Same for the assertion side: nothing changed
   there.
2. **`tests/test_parse.py` `_lint_tags_project(..., enabled=True)`** — identical
   shape with `lint_own_tags: true`; now appends instead of replacing.
3. **`tests/test_parse.py` `test_per_item_prefix_overrides_file_defaults_in_a_list_file`
   / `..._in_markdown`** — copied *this repo's own* config with
   `shutil.copy(REPO/refdes.yaml, ...)`, and that file no longer exists. Both
   now call a module-local `_copy_repo_config(tmp_path)` that copies
   `refdes-project.yaml` and `refdes-schema.yaml`.
4. **`tests/test_render_assets.py` `test_pages_get_the_same_image_resolution_and_copy`**
   — read the repo's `refdes.yaml` as text and wrote it out. Now reads the two
   repo files concatenated and hands the combined text to
   `write_project_config`, which splits it back into the same two files.
5. **`tests/test_build.py` `test_satisfying_statuses_requires_a_status_field`**
   — built the path first (`path = tmp_path / "refdes.yaml"`) and wrote through
   it. Now `write_project_config(tmp_path, NO_STATUS_FIELD_SCHEMA)` +
   `load_project(config_path=str(tmp_path / "refdes-project.yaml"))`. Writing
   the constant straight to the settings file would have raised the
   "`types` does not belong here" half-migration error instead of the
   `satisfying_statuses` error the test asserts on.

Also mechanical, matching the pilot's precedent in `tests/test_blocks.py`:
every `cli_mod.main(["-c", str(X / "refdes.yaml"), ...])` now points at
`refdes-project.yaml`.

## Stragglers

**None.** Every `refdes.yaml` reference in the five modules is gone.

## Notes for the next phase

- The "write a one-key settings file to turn a setting on" fixture idiom
  (`_enable_publish_datasheets`, `_lint_tags_project`) is the one shape that
  silently *changes meaning* under the split rather than failing loudly: the
  settings file is the config now, so anything writing it wholesale clobbers the
  fixture. Worth grepping the remaining batches for
  `refdes-project.yaml").write_text(`.
- The full suite is still red (~388 failures) — other modules are other
  workers' batches; untouched here.
