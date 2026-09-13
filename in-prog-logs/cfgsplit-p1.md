# cfgsplit-p1 — Phase 1 of the two-file config split (backlog finding 28)

Branch: `ao/refdes-48/root` (fast-forwarded onto `feat/config-split`, which held
the already-passing `refdes-project.yaml` loader).

## What the contract now is

- `refdes-project.yaml` — the project marker `find_config()` walks up looking
  for, and it holds **every project setting**: the settings it already held
  (`sigfigs`, `item_layout`, `baseline_identity`, `require_rejection_rationale`,
  `publish_datasheets`, `lint_own_tags`, `release_gate`,
  `cross_workspace_severity`) plus the ones that moved over from the retired
  file (`site`, `id`, `boards`, `workspaces`, `units`, `history`, `standard`,
  `equations`, `imports`).
- `refdes-schema.yaml` — new, **optional**, and holds only `types:`,
  `link_types:`, `field_sets:`. A project that takes its whole vocabulary from
  the standard pinned by `standard:` has no such file.
- `refdes.yaml` — retired. A directory holding only it is not a project, and a
  project carrying it beside the marker is refused too. Both raise
  `SchemaError(LEGACY_CONFIG_ERROR)`, which names both replacement files and
  says what goes in each.

Enforcement lives in `src/refdes/schema.py`: `SCHEMA_KEYS`,
`_PROJECT_SETTING_KEYS`, `LEGACY_CONFIG_NAME`, `LEGACY_CONFIG_ERROR`,
`_legacy_config_error()`, `_reject_legacy_config()`, `_validate_settings()`,
`_load_schema_overlay()`. A `types:` left in the settings file and a setting
left in the overlay are both errors naming the file the key belongs in — never
a silent partial load. `standards.resolve_schema()` is unchanged: it receives
the merged dict, whose keys are disjoint by validation.

`load_project()` still takes `config_path=`, and it now points at
`refdes-project.yaml`; `config_path` ending in `refdes.yaml` raises the legacy
error rather than being honoured.

## The conftest helper (exact signature)

In `tests/conftest.py`:

```python
SCHEMA_KEYS = ("types", "link_types", "field_sets")
PROJECT_FILE = "refdes-project.yaml"
SCHEMA_FILE = "refdes-schema.yaml"

def split_project_config(combined_yaml: str) -> tuple[str, str | None]: ...

def write_project_config(root, combined_yaml: str) -> pathlib.Path: ...
```

`write_project_config(root, combined_yaml)` is the one a fixture calls in place
of `(tmp_path / "refdes.yaml").write_text(CONST, encoding="utf-8")`, with the
module constant untouched. It splits the combined text **by top-level key on the
raw lines** — not by round-tripping YAML — so every comment and line of
formatting survives into the file its key lands in. `refdes-schema.yaml` is
written only when the config declares `types:`/`link_types:`/`field_sets:`
(a stale overlay from a previous write is removed). It returns the
`pathlib.Path` of the written `refdes-project.yaml`, so a fixture that loads by
explicit path is a one-line change too:
`load_project(config_path=str(write_project_config(tmp_path, CONST)))`.

## Gate result

```
python -m pytest tests/test_project_settings.py tests/test_schema_json.py -q
43 passed in 1.05s
```

The new safeguard module also passes (6 tests, included above only when run
together): `tests/test_config_split.py`. Its first test writes both files as
literal text and does **not** go through the helper — a helper no test bypasses
proves only that the helper works.

## Full-suite failure count after this change

```
python -m pytest tests/ -q  →  419 failed, 259 passed, 13 errors
```

Expected and correct for this phase: the ~520 fixture references to
`refdes.yaml` are Phase 2's mechanical migration, not this phase's work.

## Not finished / deliberately left

- **Phase 2:** the remaining ~28 test modules still write
  `(tmp_path / "refdes.yaml").write_text(...)`. Each needs the
  `write_project_config` substitution above. `tests/helpers.py`'s two fixture
  writers (`_numeric_hint_project` line ~113, and the `CHECK_SEVERITY_SCHEMA`
  writer at line ~203) are the same mechanical change and were left for
  consistency with that pass.
- `tests/helpers.py`'s loaders WERE migrated (`_project`, `_build_at`,
  `_build_and_render`, `_build_at_repo_schema`) — `_build_at` and
  `_build_and_render` now use `load_project(start=str(root))`, so an un-migrated
  fixture fails with the legacy error rather than a bare `FileNotFoundError`.
- `tests/test_project_settings.py` and `tests/test_schema_json.py` WERE
  migrated: the gate requires them green, and they were 6 and 12 sites.
- **Not touched (out of scope, needs a decision on phase):** `docs/*.md`
  narrative pages still describe `refdes.yaml`; `editors/vscode/extension.js`
  and its `package.json` activation events still look for `refdes.yaml`.
  `docs-site/` itself was split (its own project + schema files) and loads
  clean.
- No compatibility shim: nothing reads `refdes.yaml` any more, by design.
- Committed locally, **not pushed** (no publish requested).
