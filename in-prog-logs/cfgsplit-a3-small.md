# cfgsplit-a3-small — phase 2 fixture migration

Branch base: `4c4b8ea` (fast-forwarded onto `feat/config-split`).

Modules touched (only these): `tests/test_lifecycle.py`, `tests/test_seal.py`,
`tests/test_imports.py`, `tests/test_integration.py`, `tests/test_links.py`,
`tests/test_stub_tests.py`.

## What was done

The two mechanical substitutions, applied everywhere they fit:

1. `(X / "refdes.yaml").write_text(CONST, encoding="utf-8")` →
   `write_project_config(X, CONST)` (constants untouched; the helper splits
   them by top-level key). `from conftest import write_project_config` added
   to each module that needed it.
2. `load_project(config_path=str(X / "refdes.yaml"))` (and the CLI `-c`
   equivalents) → `... / "refdes-project.yaml"`.

Per file:

- **test_lifecycle.py** — two inline `write_text` + `load_project` pairs
  (`test_stamp_records_the_pinned_standard_version`,
  `test_baseline_written_before_this_field_existed_loads_as_none`) collapsed
  into `load_project(config_path=str(write_project_config(tmp_path, ...)))`.
  Plus the overwrite trap below.
- **test_seal.py** — two fixture-path loads, two inline schema writes.
- **test_links.py** — `typo_link_project` fixture and the
  `test_unrecognized_field_far_from_any_link_still_only_warns` write use
  `COVERAGE_SCHEMA` through the helper; the two hand-rolled inline schemas
  (constraint rename, hardware v1) go through the helper too; four load paths
  renamed.
- **test_stub_tests.py** — `stub_project` fixture and
  `test_no_verifier_type_is_an_error` through the helper;
  `test_ambiguous_verifier_type_requires_type_flag` builds `STUB_SCHEMA + an
  extra type` and now hands that whole text to `write_project_config`;
  `_stub_build` and the four CLI `-c` paths renamed (the CLI calls were
  re-wrapped onto multiple lines to stay readable after the longer filename).
- **test_imports.py**, **test_integration.py** — see the REPO-copy adaptation
  below.

## The overwrite trap (found and fixed)

`tests/test_lifecycle.py::test_unverified_requirements_when_explicitly_enabled_excludes_draft`
did

    (lifecycle_project / "refdes-project.yaml").write_text(
        "release_gate:\n  unverified_requirements: { release: true }\n", ...)

Harmless while `refdes-project.yaml` was only the secondary settings file; now
that it is the marker it would have thrown away `site:`/`types:` and tested a
different project. Changed to append to the marker (the same idiom as
`tests/test_project_settings.py::_write_minimal_project`), with a comment
saying why. `LIFECYCLE_SCHEMA` declares no `release_gate:` of its own, so the
appended key is not a duplicate.

No other test in these six modules overwrites `refdes-project.yaml`.

## Shapes that were not the two substitutions (adapted, obviously)

Both read the repo's own config from `REPO`, which no longer ships a
`refdes.yaml`:

- `tests/test_imports.py::importing_project` read `REPO/refdes.yaml`, appended
  an `imports:` block, and wrote it as the project config. Now copies
  `REPO/refdes-project.yaml` **and** `REPO/refdes-schema.yaml` into the temp
  project (the `tests/test_ids.py` pattern) and appends the `imports:` block to
  the marker. `import shutil` added.
- `tests/test_integration.py::_io_check_project` `shutil.copy`'d
  `REPO/refdes.yaml`; now copies both repo config files.

## Stragglers

None. `grep -n "refdes.yaml"` over the six modules returns nothing.

## Verification

    python -m pytest tests/test_lifecycle.py tests/test_seal.py tests/test_imports.py \
      tests/test_integration.py tests/test_links.py tests/test_stub_tests.py -q
    -> 66 passed

Before the migration the same command was 29 failed / 32 passed / 5 errors.

Full suite (`python -m pytest tests -q`): 43 failed, 642 passed, 6 errors —
none in the six modules above (checked by filtering the FAILED/ERROR lines);
those belong to modules outside this batch's scope.

No assertion was changed.
