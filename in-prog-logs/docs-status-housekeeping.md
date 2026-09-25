# Docs housekeeping: design-doc status lines vs shipped reality

Task: verify four claims against the repo and correct the status lines in
four design docs. One PR, minimal edits.

## Chunk 1 — verification (done)

Claims checked with real commands, not memory:

- **candidate-parts.md**: all five phases in §12 have merged.
  - Phase 1 (standard): `62d5f79` "rejected component status and
    status-keyed check_severity (phase 1)". Verified in
    `src/refdes/standards/hardware/v3/base.yaml`: `component.status` choices
    are `[candidate, selected, rejected, obsolete]` (line 264) and
    `check_severity: { candidate: info, selected: error, rejected: info,
    obsolete: info }` (line 259).
  - Phase 2 (severity engine): `73967a1`.
  - Phase 3 (block): `7544a38`. Verified: `{{compare}}` is in
    `src/refdes/blocks.py` (`_render_compare`, `"compare": BlockSpec(...)`
    registry entry, line 864).
  - Phase 4 (layout): `a361b98`. Verified: `refdes new --list` in
    `src/refdes/cli.py` (line 798 calls `scaffold.new_list_text`; parser
    option at 1566-1579), `scaffold.new_list_text` in scaffold.py.
  - Phase 5 (docs & tests): `tests/test_compare_block.py`,
    `tests/test_check_severity_status.py`, `tests/test_component_rejected.py`
    all exist.
- **browser-editor.md**: `.github/workflows/tests.yml` exists (pytest +
  E9,F ruff gate, ubuntu + windows matrix); added by `28e874d`. The old
  sentence claiming "no test CI today: `.github/workflows/` contains only
  `docs.yml`" is stale.
- **thread-workbench.md**: W1 `8818df7` ("preview auto-reload probe and
  item-view preview link") and W2 `4ac9898` ("preview diagnostics panel and
  image provenance") landed. W3 ("values") in progress per task.
- **named-calc-blocks.md**: all five phases (§13) landed: phases 1+4
  `4d1a9c0`, phase 2 `e1ed2f2`, phase 3 `4d1597d`, phase 5 `24d1dbc` +
  `ea6199e`. Test files `test_calc_block_names.py`, `test_calcblock.py`,
  `test_calc_block_hash.py`, `test_calc_block_refs.py` all exist.

## Chunk 2 — edits (done)

- `git merge origin/main` -> already up to date (HEAD == origin/main).
- Branch `ao/refdes-166/docs-status-housekeeping` created as a sibling of
  `ao/refdes-166/root`.
- Four doc edits (diff is +14/-9 across 4 files, nothing else touched):
  1. candidate-parts.md status -> "shipped (2026-09-25)" with what landed.
  2. browser-editor.md: replaced the one no-test-CI sentence with the
     tests.yml fact; surrounding sentences untouched.
  3. thread-workbench.md status -> W1/W2 landed, W3 in progress.
  4. named-calc-blocks.md status -> "All five phases (§13) have landed",
     rest of the status paragraph untouched.
- changelog.d/design-doc-statuses.fixed.md added (format per
  changelog.d/README.md and existing fragments).

## Chunk 3 — gates and PR

- Gate: `python -m pytest -q -x` then `python -m ruff check --select E9,F src
  tests` then `git push -u origin ao/refdes-166/docs-status-housekeeping`.
- PR: `gh pr create --base main`, not merged.
- Report to refdes-2 at each chunk boundary via
  `ao send --session refdes-2 --message ...`.

## Chunk 3 — done (PR open)

- `python -m pytest -q -x` -> 2112 passed (235.8 s).
- `python -m ruff check --select E9,F src tests` -> clean.
- Pushed `ao/refdes-166/docs-status-housekeeping` with `-u`.
- PR opened, base main, not merged:
  https://github.com/Squishiba/refdes/pull/29
- Progress reported to refdes-2 at the chunk boundaries and at PR open.

## Status

Finished.