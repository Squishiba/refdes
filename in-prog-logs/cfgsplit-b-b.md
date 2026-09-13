# cfgsplit-b-b — Phase 2 fixture migration

Modules: `tests/test_ids.py`, `tests/test_revise_migrations.py`, `tests/test_revise.py`,
`tests/test_parts.py`. Added `from conftest import write_project_config` to each.

## What changed

Mechanical, constants untouched:

- `(X / "refdes.yaml").write_text(CONST, encoding="utf-8")` → `write_project_config(X, CONST)`
  (multi-line form lost its trailing `encoding="utf-8",` line the same way).
- `load_project(config_path=str(X / "refdes.yaml"))` → `... str(X / "refdes-project.yaml")`,
  including the `cli_mod.main(["-c", ...])` args and the post-revise `read_text` read-backs
  (those assert on `standard:`/`version:`, which are settings keys).

Applied with a throwaway regex script (90 sites; `edit` can't disambiguate ~30 identical
lines), then reviewed hunk by hunk in `git diff`. Script deleted afterwards — `git status`
is clean apart from the four modules and this log.

## Sites that did not fit the two substitutions

1. **`tests/test_ids.py:39` (`temp_project` fixture)** — copies the repo's own config into a
   tmpdir. Now copies `refdes-project.yaml` *and* `refdes-schema.yaml`; the old single
   `refdes.yaml` carried both halves.
2. **`tests/test_revise.py` — the three `mutate_config` callbacks** (`bump` in
   `test_revise_renames_type_and_prefix_atomically_with_schema_via_mutate_config`,
   `_bump_label_field_to_text`, `_bump_summary_field_to_note`). `revise.apply` passes the
   callback `refdes-project.yaml`'s path (revise.py:705), but every string these rewrite is a
   `types:` declaration, which now lives in `refdes-schema.yaml`. Each callback derives
   `os.path.join(os.path.dirname(config_path), "refdes-schema.yaml")` and edits that. No
   assertion changed; without this the four tests failed with "rewritten project has
   build/parse errors -- rolled back".
3. **Docstring prose** in `test_revise.py` — two mentions retargeted (`refdes.yaml` →
   `refdes-schema.yaml` for the schema-mutation note, → `refdes-project.yaml` for the
   compound-prefix convention note). Comments only.
4. **`test_revise_refuses_a_self_contradictory_mapping`** — `os.path.join(REPO, "refdes.yaml")`
   → `refdes-project.yaml`.

## Verification

`python -m pytest tests/test_ids.py tests/test_revise_migrations.py tests/test_revise.py tests/test_parts.py -q`
→ **88 passed**. `grep -n "refdes\.yaml"` over the four modules → no matches.

## Left undone / worth a look (src-side, not mine to touch)

`revise.apply`'s rollback snapshots only `refdes-project.yaml`. A `mutate_config` that edits
`refdes-schema.yaml` — which is now the *normal* case, since that's where `types:` lives —
is not restored when the post-revision build fails, so a rolled-back revision can leave the
schema half-migrated while the settings file reverted. Same for the standard-upgrade chain:
each step's config snapshot is settings-only. Candidate backlog item against
`src/refdes/revise.py`.
