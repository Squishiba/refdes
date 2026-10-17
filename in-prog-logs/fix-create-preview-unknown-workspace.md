# R9-F3 — create preview rejects an unregistered workspace

Task: fix R9-F3 from `in-prog-logs/user-sim-release-gate-run9.md` (§1.3,
§3): `GET /api/create/preview?...&workspace=<unregistered name>` silently
fell back to the unscoped suggestion instead of saying the workspace does
not exist. API-only (the editor's picker lists only registered workspaces,
and `POST /api/items/create` takes no workspace parameter — it rides in
`fields.workspace` and the overlay gate already refuses an undeclared one
with 422), so the blast radius is a direct API caller.

## Reproduced first, against a live serve

Throwaway project `.scratch/r9f3/proj` (`refdes init`, hardware@3, then
`item_layout: workspace`, boards `board-a`/`board-b`, workspaces
`product-a`/`product-b`, one item file
`items/product-a/board-a/requirements.yaml`). Served with
`refdes serve --no-open --port 8765 --token-file ../ed-token.txt`, started
with `nohup ... &`, PID recorded in `.scratch/r9f3/serve.pid`, stopped with
`kill $(sed 's/PID=//' serve.pid)`. Never `pkill -f`.

Pre-fix, verified over HTTP:

- `preview?type=requirement&board=board-a&workspace=nosuchws` → **200**
  `{"id":"REQ-001",...,"destination":"items/product-a/board-a/requirements.yaml"}`
  — product-a's file, the scope dropped without a word.
- `preview?...&board=nosuchboard` → same silent fallback (adjacent, see
  "Left alone").
- sibling `GET /api/items?workspace=nosuchws` → **400**
  `{"error":"workspace: no such workspace 'nosuchws' in this project; known
  workspaces: product-a, product-b"}`.

## How the siblings treat a bad scope

`serve/filters.py::parse_filters` validates the `type`/`board`/`workspace`/
`file` facets (`_KNOWN_FACETS`) through `_validate_facet`, whose message is
`{name}: no such {name} {value!r} in this project; known {name}s: {sorted
known}` with `FilterError.status = 400`. That is the nearest endpoint's
"no" and the shape the task asked for (names the value, lists the
registered ones), so the preview reuses that check instead of writing a
second message. The CLI's documented asymmetry is untouched:
`refdes ls --workspace nosuchws` prints `no items match` (exit 0) —
re-checked live after the change; `check --workspace ''` keeps its registry
error.

## The change

- `serve/filters.py`: `_validate_facet` → `validate_facet` (renamed public:
  definition, its call site in `parse_filters`, and the docstring reference
  to it, plus a "why public" note in its docstring).
- `serve/api.py::_create_preview`: when `workspace` is present and
  non-empty, run `validate_facet(project, "workspace", workspace)`; a
  `FilterError` is returned as `(exc.status, {"error": str(exc)})` — the
  list route's status family (400) and byte-identical error shape.
  Absent/empty `workspace` collapses to `None` first (unchanged), so
  `?workspace=` behaves exactly as before. `preview_creation` in
  `serve/edit.py` is not touched — the library function and its direct
  tests are unchanged, and validation sits in the HTTP layer with the
  route's other 400.
- The editor client cannot send an unregistered scope (the select is built
  from `/api/create/schema`'s `workspaces`), and `create.js`'s
  `refreshPreview()` already catches a failed preview into a
  `preview failed: <message>` badge, so nothing needed there.

## Tests (written first, red against unmodified main)

`tests/test_serve_create.py`, on the existing `served_workspaces` /
`served` fixtures:

- `test_http_preview_refuses_an_unregistered_workspace` — the refusal and
  its exact payload; board+workspace combination; registered workspace and
  registered board+workspace unchanged; absent and empty scope unchanged;
  nothing reserved (no ids ledger) and a byte-identical tree.
- `test_http_preview_refuses_a_workspace_where_none_are_registered` — the
  registry-less half: the preview's message is asserted equal to
  `/api/items?workspace=ghost`'s for the same project.

Both red (200 with the unscoped suggestion), both green after.

## Gates

- Full suite, foreground: `PYTHONPATH=$PWD/src … -m pytest -q` →
  **4021 passed, 2 skipped** in 5:34, exit 0.
- `ruff check src/refdes/serve/api.py src/refdes/serve/filters.py
  tests/test_serve_create.py --select E9,F` → All checks passed. (Repo-wide
  `ruff check .` is not clean on main — pre-existing, ~99 findings — and was
  not touched.)
- Post-fix live re-check on the same scratch serve: unregistered → 400 with
  the sibling's message; `workspace=product-b` (registered, empty) →
  `items/product-b/board-a/requirements.md` as in the run-9 report;
  unscoped and `workspace=` → the pre-fix answers.

## Left alone (noted, not fixed)

`?board=<unregistered>` has the same silent-fallback shape in this endpoint
(`preview?board=nosuchboard` → 200, unscoped suggestion). It is not part of
R9-F3, and the task said minimal: the same one-line call
(`validate_facet(project, "board", board)`) is the obvious follow-up, best
filed as its own finding. `suggest_destination` keeps its `board in
project.boards` guard, which is now belt-and-braces on the HTTP path for
workspace.

Status: finished. Changelog fragment
`changelog.d/serve-create-preview-unknown-workspace.fixed.md`.
