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

## Implementation (N5b)

- Merged origin/main (branch base was older); navis_ops (PR #414) landed, so
  the routes render its Outcome: no rule duplicated. `serve/navis_write.py`
  is new: validate the body selector, take `write_lock_for(root)` (the
  editor's in-process lock, per the LOCK ORDER in edit.py), build rows from
  `navis.projection(project)`, call `navis_ops.apply`, render the Outcome to
  status/JSON, force the rebuild on a changed write. api.py: a six-line hook
  in `handle` + the two paths added to the final 405 list.
- Forced rebuild: `ProjectState.refresh(force=True)` -- one keyword added to
  the save path's own mechanism (refresh -> `_build` -> preview.render);
  force skips the signature gate, which cannot see `.refdes/navis/` (the
  store is merged at load, not hashed). No second rebuild path.
- Write-lock check: `project_write_lock` is an RLock with per-thread depth
  tracking (write_lock.py), re-entrant -- `navis_archive.archive_record`
  takes it internally, and the handler takes `write_lock_for` (a plain
  Lock, taken once) outside it, the order edit.py documents. No double-take,
  no deadlock.
- Red evidence (this branch, before src changes): `tests/test_serve_navis_-
  write.py` -> 37 failed, 7 passed, same as the test author recorded. After:
  42 passed, 2 failed.
- The 2 failures are a test-authoring bug in
  `test_an_ambiguous_prefix_names_its_candidates` (both verbs), not the
  routes: it sorts candidates by key, then asserts `[KEY_A, KEY_B]`, but
  `keys.check_char` makes KEY_B `k7f3q2zyzzj` and KEY_A `k7f3q2zzzzt`, and
  `sorted()` puts zyzz before zzzz ('y' < 'z'), so the assertion can never
  hold for ANY payload ordering. Verified independently:
  `sorted([KEY_A, KEY_B]) == [KEY_B, KEY_A]`. The endpoint returns exactly
  the two candidate keys with text/file/line. Left the test untouched per
  the task rules; it needs `[KEY_B, KEY_A]` (the author's zz/zy slip).
- Green: the 42 others pass; tests/test_navis_ops.py + test_navis_archive_-
  cli.py + test_serve_edit_http.py + test_serve_api.py + test_serve_state.py
  -> 142 passed. Full suite: run once, recorded below.
- Smoke (real `refdes serve --port 8772`, venv, PYTHONPATH=src of this
  worktree, token from the launch URL): archive `{"navi":"znxbqdvcym2"}` ->
  200 `{"kind":"ok","verb":"archive","key":"znxbqdvcym2","changed":true}`,
  `.refdes/navis/znxbqdvcym2.yaml.gz` created (before: store dir absent);
  preview note-001.html then shows `[archived]` + Show all; restore -> 200
  ok changed:true, store empty, page clean; restore of the active Navi ->
  409 conflict not_archived; GET on the POST-only route -> 405. Server
  stopped by PID.
- Docs: route bullets in docs/design/editor-vscode-adapter.md's API
  inventory; changelog.d/serve-navis-write.added.md.
