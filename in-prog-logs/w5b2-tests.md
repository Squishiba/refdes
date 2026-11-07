# W5b.2 contract tests: POST /api/item/<ref>/continue

Task: test-author only. Create `tests/test_serve_continue_http.py` pinning
the HTTP contract of the W5b.1 operation `edit.continue_thread`, red-first.
No source changes, no CLI, no browser. Branch `feat/w5b2-continue-endpoint`,
base `27614050` (W5b.1 merged).

## Deliverable

`tests/test_serve_continue_http.py` — 38 tests (30 parametrized cases +
8 routes of gates/malformed bodies). Fixtures use `serve_support.Client`
(port 0), `newline="\n"` writes, `read_bytes()` comparisons, per the
cross-platform rules; `tests/test_crossplatform_lint.py` passes clean
(26 passed) and `ruff check` on the file is clean.

## Pinned request shape

`POST /api/item/<ref>/continue` with JSON body
`{"ticks": [["T-a", "done"], ...], "expected_revision": "<sha256>"}`.

- `expected_revision` copies the `/edit` key spelling
  (`src/refdes/serve/api.py:1173-1175`); plan Q2 ratified the
  whole request as "ticks pairs + expected_revision"
  (`docs/design/thread-workbench-w5b-plan.md` lines 456-458, 479-482).
- `ticks` is a list of 2-element pairs (not a mapping) — plan lines
  259-263; unknown/duplicate/non-string-in-pair entries are refused 422,
  never 400 (400 stays reserved for non-JSON / non-object bodies).
- `who` reaches the operation as `"local"`, copied from
  `_apply_edit` (`src/refdes/serve/api.py:1214`); pinned by monkeypatching
  the op with a recording stub.

## Pinned response shapes (from `_apply_edit`/`_create_item` neighbours)

- 200 applied: `{kind, ok, message, path, revision, describe, id, handle,
  diagnostics}`; 409 conflict: `{kind, ok, message, path,
  expected_revision, current_revision, current_text, diff}`; 422
  refused/invalid: `{kind, ok, message, reason, path}` (+diagnostics for
  invalid); 400 malformed body `{error}`.
- Gates: missing/wrong token 403, foreign host 403, bad/missing/null
  Origin 403, non-JSON content type 415, non-POST 405, `--no-write`
  server 403 naming `--no-write`.
- Refusal postures (plan lines 268-271): ambiguous, undeclared, cleared
  fold, unknown task, state outside vocabulary, duplicate tick, unknown
  ref, sealed tip → 422 refused, bytes unchanged; delta-diagnostic gate
  → 422 invalid.
- Percent-encoded ref decodes like the neighbours; hostile refs (dot-dot,
  NUL, 300-char) are refused cleanly, never 500.

## Evidence

- RED: `PYTHONPATH=<worktree>/src ... pytest -q tests/test_serve_continue_http.py`
  → `32 failed, 6 passed`. The 6 passing are the server-level gates
  (token, host, Origin ×3, content-type) which in
  `src/refdes/serve/server.py` run before routing; every route-behaviour
  test is red because the route does not exist (POST → 405
  `{"error": "method not allowed"}`).
- GREEN (contract satisfiability only): a throwaway route + `_continue_item`
  handler in `src/refdes/serve/api.py` — modelled on `_create_item` — made
  all 38 tests pass (`38 passed in 1.87s`). The patch was then reverted;
  `git status` shows the source clean. The implementer owns the real route.

## Spec ambiguities / findings

- The plan (`docs/design/thread-workbench-w5b-plan.md` lines 259-263) names
  the body fields at a glance level; exact key spellings were pinned from
  the neighbours: `expected_revision` from `/edit`, the 200/409/422 shapes
  from `_apply_edit`'s tails. Q2's "the body carries the tick pairs and
  expected_revision" (lines 456-458) is the authority for the shape.
- Q10 (lines 632-633): no CLI in W5b — pinned by absence: no CLI test,
  and plan lines 273-274 keep the route on the existing content types and
  CSP, so nothing new to allow.
- Echo test finding: response text passes `_write_outcome` →
  `_relative_paths` (api.py:664-760), which scrubs path-shaped tokens, so
  a hostile task id containing `/script>` comes back scrubbed — that is
  neighbour behaviour, not a continue-route bug. The echo test uses an
  HTML-ish id with no slash so it pins the repr-in-JSON echo, and the
  scrubbing of the slash-shaped case is noted here rather than pinned.
- `fold_tasks` returns a fold for any item (NOTE-001 → undeclared
  posture), so the operation's "empty folds" refusal (edit.py
  `not folds` branch) is not reachable through the route with the test
  project's types; the route test pins the undeclared posture instead.
- The W5b.1 fixture's `date_format: DD/MM/YYYY` in the schema is load-
  bearing for the delta gate (dates like `01/09/2026`); copied into the
  test project, matching `tests/test_serve_continue.py`.

## Status

Finished: tests authored, red-first, contract verified satisfiable,
lint-clean, committed and pushed. No PR (per task), no browser surface
touched.
