# edit-03 designer: retired-id resolution on the write route

Role: blind test designer for EDIT-03 (the editor's write route does not
resolve retired ids the way the read route does). No product code delivered.

## Deliverables

- `tests/test_serve_edit_retired_ids.py` — 11 HTTP-level tests (live
  `EditorApp` + `serve_support.Client`, the shape of `test_serve_edit_http.py`).
- `tests/edit-03.cases.json` — per-node expectations: 5 pass on base
  (controls), 6 fail on base (new behavior).

## Contract decisions taken in the tests

- Response reporting: the applied 200 payload reports the item's current
  handle under `"handle"` — the same field name `GET /api/item/{ref}` hands
  back (surrogate key when the project has keys, display id when not).
  Pinned keyless and keyed.
- Parity is pinned as: every spelling `GET /api/item/{ref}` answers with 200
  must be RESOLVED by the write route — a find-stage refusal is the exact
  words "no item ... in this project" (edit.py:402); the patcher's "in this
  file" refusal (patcher.py:629) is a different fact and allowed (the `~`
  provisional handle stays patcher-refused, as test_serve_edit_http pins).
  Covering all three docstring spellings + retired, keyless and keyed.
- Ambiguity trap: on a double claim, `ids.collect_former_ids` records
  `former_ids[REQ-900] -> first claimant` (files load alphabetically) and
  reports the second claim as a build error on the second claimant's item —
  so a shared resolver built on `project.former_ids` alone silently picks
  the first claimant. The test pins the loud refusal: 422, byte-identical
  tree (neither claimant written), and the project's "declared by both"
  diagnostic visible through the item views.
- Live-wins trap: `former_ids: [REQ-001]` naming a live id is a build error
  and never resolves as retired; the write by REQ-001 lands on the live
  item, the claimant's file byte-identical. Passes on base — a control that
  the precedence must not regress.

## Findings while validating against a reference fix (reverted, not committed)

- The write path's `before` snapshot comes from `loader.load_tree`
  (edit.py `_load_before`, non-pin path), which does NOT run the build pass
  — `project.former_ids` is EMPTY there. A shared resolver that reads the
  `project.former_ids` dict (what api._find_item does today) resolves
  nothing at the write route. The retired step must scan
  `item.former_ids` on `project.local_items` directly (which is also what
  makes double-claim detection possible).
- Rebinding `ref = item.id` for every resolved spelling breaks
  `test_the_keyless_provisional_handle_still_refuses_and_writes_nothing`
  (200 instead of the pinned 422): the provisional handle must stay a
  model-only spelling the patcher declines. Rebind only when the ref
  resolved through the retired step.
- Validation: with the reference fix, all 11 tests pass and
  756 passed / 1 skipped across every test_serve_* / editor / no_write
  suite. On the base, exactly the 6 new-behavior tests fail.
- `former_ids` entry order note: collision diagnostics attach to the item
  loaded SECOND (the claim found later), the `former_ids` dict entry belongs
  to the FIRST — the tests scan both claimants' views for the diagnostic.

## Hardening rounds (base-run contradictions, twice)

Round one: the executor's base run hit `RuntimeError: can't start new
thread` on `app.start()` for every test (9 ERROR + 2 FAILED — a control
that ERRORs is a control that cannot be graded). Mitigation: bounded
retry on exactly that failure + module-scoped apps (2 live threads
instead of nine apps). Probed under `RLIMIT_NPROC` pinned to the user's
live thread count +1 (probe kept in .scratch/edit-03/limit_probe.py):
app starts.

Round two: that box is *persistently* thread-starved — the retried run
spent its whole budget (30.94s) and every app still failed to start.
No live server can be gradeable there. Redesign, test-side only: every
test now drives `api.handle` itself — the exact handler the socket layer
dispatches to (server._dispatch), the exact (status, JSON payload)
contract the browser consumes — over the real `ProjectState` (synchronous
load/refresh). Zero threads, zero sockets; the token/origin gate stays
pinned through the real socket by test_serve_edit_http. All 11 test
bodies kept verbatim in assertions; per-test fresh projects (function
scope) removed the shared-fixture order coupling entirely. File runs in
0.35s.

Re-validated after the redesign: base 6 fail / 5 pass (assertion
failures, no ERRORs — matches cases.json exactly); with the reference
fix (reverted, not committed) all 11 pass and 220 serve/edit/no-write
sibling tests stay green; ruff clean.

## Status

Finished. Tests, cases.json, and this log are the commit; product code
untouched (validated reference fix reverted via git checkout).
