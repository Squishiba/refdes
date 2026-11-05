# serve-navis-write (N5b-tests): contract tests for POST /api/navis/archive|restore

Test author only, slice N5b-tests. Deliverable: `tests/test_serve_navis_write.py`
(red by design -- the routes do not exist yet). No src/ file touched. The tests
are black-box over HTTP: no import of `navis_ops` (planned) -- state is seeded
with the shipped CLI and read back with `navis_archive.load_records`.

Spec mirrored from in-prog-logs/navis-design-20261025.md sections 6, 7.3, 9,
11, 12 and the CLI verbs (cli.py `_navis_write_verb`/`_navi_select`, verified
by reading them, plus server.py `_api` for the gates).

## Red evidence (this state)

`PYTHONPATH=<worktree>/src ... -m pytest -q tests/test_serve_navis_write.py`
-> 37 failed, 7 passed. Every failure is the route-missing 404
(`{'error': 'not found'}` from api.py's fall-through): 200/400/409/405/500/403
status asserts, and the 4 not-found-selector cases (generic 404 lacks
`kind: not_found`). ruff clean on the new file; tests/test_crossplatform_lint.py
passes (R1 hygiene: newline="" on every fixture write, read_bytes compares).

## The 7 that pass now (honest pins, not weakening)

- PUT/DELETE 405 x4: answered by server.py:656-659 generically, before routing.
- missing body -> 400: server's JSON gate (server.py:826) runs before routing.
- giant digit selector in (400,404): generic 404 is an accepted answer.
- token gate vs /api/items/create: the gate is in server._api, route-agnostic;
  the test compares status+body bytes, so it pins that the new routes do not
  weaken it.

## Notes for the implementer

- OSError test patches `refdes.navis_archive.archive_record` / `restore_record`
  as module attributes (how cli.py:3028/3062 calls them). If the implementation
  calls through `navis_ops`, move the patch target there -- the test is the
  contract, the target is the implementer's.
- Freshness test (preview page shows `[archived]` after the write, and clean
  after restore) assumes the handler rebuilds synchronously before answering,
  like the save path (api.py `app.state.refresh()` in the Applied branch).
  poll_interval=60 rules out the watcher. If the rebuild is made async, this
  test races -- keep it synchronous. Note: ProjectState.refresh is
  signature-gated on top-level .refdes project files, so a bare refresh() is
  a no-op for .refdes/navis writes; the handler must force the rebuild.
- Ordinal tests pin projection order: active first, archived appended,
  orphans last (navis.projection).
- Ambiguity is constructed deterministically: two valid keys sharing a 6-char
  prefix, check chars computed with keys.check_char (no mint loop).

Status: task finished (tests authored, red for the right reason, committed and
pushed on feat/serve-navis-write; no PR opened).
