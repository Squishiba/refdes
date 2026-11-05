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

Status: tests done (test-author phase). Branch `feat/serve-navis-read`,
test file committed.

## Implementation (implementer phase)

Task: make the 12 red tests green; src only, tests untouched.

Red re-confirmed on the branch after merging origin/main (post-#414):
12 failed / 5 passed, every failure `404 == 200` (or `404 == 405`) on
`{"error": "not found"}` — the missing route, as the test author recorded.

Changes (all verified by running, per AGENTS.md):
- `navis_panel.panel_model`: each row gains `key` (full key, "" for a
  keyless marker). The site template renders only `key6`, so the published
  site is unchanged — `tests/test_navis_site_panel.py` (byte-differential
  vs origin/main) passes.
- `serve/navis_read.py` (new): `navis_payload(app)` =
  `panel_model(snapshot.project, navis.projection(snapshot.project))`,
  rows = model rows (they carry `key`), counts tallied off the rows;
  None model (Navi-free) → empty rows, zero counts. One projection per
  request, read-only; the archive store is merged inside `projection` at
  request time, which is what makes the freshness test pass.
- `serve/api.py`: 2-line GET/HEAD hook next to `/api/items` + `"/api/navis"`
  added to the final 405-path list. Tiny/self-contained for the sibling's
  POST archive/restore rebase. PUT/DELETE never reach `handle` (the
  transport refuses first), so the gate/method tests pass by construction.

Green: `tests/test_serve_navis_read.py` 17 passed. Guard/neighbour:
`tests/test_navis_site_panel.py tests/test_serve_api.py
tests/test_crossplatform_lint.py` 87 passed. Full suite once:
5700 passed, 2 skipped.

Smoke (real server, port 8771, `--token-file`, venv python, absolute
PYTHONPATH): GET `/api/navis` → 200
`{"navis":[{"key":"","key6":"","text":"A reminder with no key yet","item":
"NOTE-001","href":"note-001.html","file":"items/note-a.md","line":7,
"archived":false,"changed":false,"orphan":false}],"counts":{"active":1,
"archived":0}}` (keyless: serve's load never mints, matching the
read-only contract); POST → 405 `{"error":"method not allowed"}`; no
token → 403. Server stopped by its own PID; token file removed on clean
stop.

Docs: route bullet + table row in
`docs/design/editor-vscode-adapter.md` §3 (the page listing the served
`/api/*` routes); `changelog.d/serve-navis-read.added.md`.
`ruff check` clean on the touched src files.
