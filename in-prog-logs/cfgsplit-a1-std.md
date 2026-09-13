# cfgsplit-a1-std -- tests/test_standards.py

Phase 2 of the config split. Module: `tests/test_standards.py` only.

## What was done

All 48 `refdes.yaml` references migrated to the two-file layout, matching
`tests/test_boards.py` / `tests/test_ids.py` and the
`write_project_config` docstring in `tests/conftest.py`.

- 28 `(X / "refdes.yaml").write_text(CONST, encoding="utf-8")` sites became
  `write_project_config(X, CONST)` -- constants unchanged, the helper splits
  them by top-level key (`types:` / `link_types:` / `field_sets:` to
  `refdes-schema.yaml`, everything else to `refdes-project.yaml`).
- 20 `load_project(config_path=str(X / "refdes.yaml"))` sites became
  `... str(X / "refdes-project.yaml")`.
- Added `from conftest import write_project_config` to the module imports.

No assertion in any test was changed. No filename appears in an error-message
`match=` in this module, so no assertion needed the new name.

## The trap (one site, not a plain substitution)

`test_require_rejection_rationale_false_drops_the_condition` wrote the config
and then wrote `refdes-project.yaml` with only
`require_rejection_rationale: false`. Under the old layout that second file was
a secondary settings file and the write was harmless; now it is the marker, so
overwriting it would drop `standard: { base: hardware, version: 1 }` and the
test would exercise a different project. It now appends the setting to the
marker returned by `write_project_config` (the `_write_minimal_project` shape
from `tests/test_project_settings.py`) and loads through that returned path.

## Verification

- `python -m pytest tests/test_standards.py -q` -> 31 passed, 0 failed.
- `grep -n "refdes.yaml" tests/test_standards.py` -> no hits.

Stragglers: none.
