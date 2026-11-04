# serve navis read — N5a contract tests (test author only)

Task: write the contract tests for `GET /api/navis` (design
`navis-design-20261025.md` §11) before the implementation exists. Tests
only — nothing under `src/` touched. A second agent implements on this
branch.

Done: `tests/test_serve_navis_read.py`, 17 tests, derived from the spec:
rows = `navis_panel.panel_model` rows + `key` (spec's stated reuse),
order = `navis.projection` order; expectations are computed in the test
from those two functions over `loader.load_readonly(config)` (serve's own
load), so they are contract, not implementation. Fixtures: the site-panel
fixture (`test_navis_site_panel._navi_project`) on a writable
`EditorApp(poll_interval=60)`, plus a read-only server over a
keyless-marker + hostile-text project.

Red evidence (absolute `PYTHONPATH=<worktree>/src`, venv python,
`pytest -q -p no:cacheprovider tests/test_serve_navis_read.py`): 12 failed,
5 passed, every failure `assert 404 == 200` (or `404 == 405`) on
`{"error": "not found"}` — the missing route — never an import/fixture error.

- RED (12): the four shape/order/flags/counts tests,
  `test_navis_free_project_returns_empty_rows`, `test_head_is_answered`,
  `test_post_is_method_not_allowed` (405 expected, route gives 404),
  `test_get_works_on_a_read_only_server`, `test_get_changes_nothing_on_disk`,
  `test_archive_on_disk_is_visible_on_the_next_get`, the keyless and the
  hostile-text tests — all fail on the endpoint's status.
- GREEN NOW (5): `test_writing_methods_answer_exactly_like_the_items_route`
  (PUT, DELETE) and `test_the_route_is_behind_the_items_token_gate` (×3) —
  comparisons against `/api/items` (the gate lives in the transport, ahead
  of routing: 405 plain-text / 403 today). They stay green as the
  implementation lands; that is the point of comparing.

Notes for the implementer: the archive store (`.refdes/navis/*.yaml.gz`)
is NOT a `state.project_inputs` entry, so the poller never rebuilds on an
archive — the endpoint must read records at request time via
`navis.projection` on the snapshot project (the freshness test calls
`app.state.refresh()` for the item-key mint the CLI archive also makes,
which IS an input). Probe findings: a writable CLI load mints ITEM keys
and rewrites item files (fixture note-c loses its `key:` line to the
fixture's own rewrite; the next writable load mints it back) — the
freshness test asserts by navi key, not by line.

Checks: `ruff check tests/test_serve_navis_read.py` clean;
`tests/test_crossplatform_lint.py` green (fixture writes pass
`newline=""`; no raw-byte asserts; paths come from the projection, never
from a hand-built separator). Full suite NOT run (red by design, task override).

Status: done. Branch `feat/serve-navis-read`, test file committed.
