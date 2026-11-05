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
  force skips the signature gate, which cannot see `.refdes/navis/`.
- Write-lock check: `project_write_lock` is an RLock with per-thread depth
  (write_lock.py), re-entrant; `navis_archive` takes it internally and the
  handler takes `write_lock_for` (plain Lock, once) outside it -- edit.py's
  documented order. No double-take, no deadlock.
- Red evidence (this branch, before src changes): `tests/test_serve_navis_-
  write.py` -> 37 failed, 7 passed, same as the test author recorded. After:
  42 passed, 2 failed.
- The 2 failures = the test-authoring bug: the candidate assertion sorts by
  key then expects `[KEY_A, KEY_B]`, arithmetically impossible (KEY_B
  `k7f3q2zyzz…` sorts before KEY_A `k7f3q2zzzz…`). Reported, left untouched
  per the round-0 rules; fixed in round 1 (T1).
- Green: the 42 others pass; tests/test_navis_ops.py + test_navis_archive_-
  cli.py + test_serve_edit_http.py + test_serve_api.py + test_serve_state.py
  -> 142 passed. Full suite (pre-push, round 0): 2 failed, 5742 passed,
  2 skipped.
- Smoke (real `refdes serve --port 8772`, token from the launch URL):
  archive -> 200 ok changed:true, the store record created (absent before);
  preview shows `[archived]`; restore -> 200 ok, store empty, page clean;
  restore-of-active -> 409; GET on POST-only routes -> 405.
- Docs: route bullets in docs/design/editor-vscode-adapter.md's API
  inventory; changelog.d/serve-navis-write.added.md.
- Merged origin/main mid-task (PR #416 GET /api/navis): api.py conflicts
  resolved keeping BOTH hooks; the post-merge run was 59 passed / 2 failed
  (the same authored-bug pair).

## Review round 1 (both reviewers CHANGES REQUESTED; one commit)
- T1: the ambiguous-candidates test made order-independent (`by_key` dict,
  `set(...) == {KEY_A, KEY_B}`, per-key text/file/line; no zip over an
  assumed order). Mutation proof: patched the handler to emit
  `candidates[:1]` -> both params FAIL; reverted.
- T2: stale citations re-pointed by reading the files: selector ->
  `navis_ops.select` (cli `_navi_select` delegates), giant-digit guard ->
  `navis_ops.select`'s length-bound digit branch, OSError patch seam ->
  `navis_ops.apply`'s `navis_archive_mod.archive_record` call. No line
  numbers cited.
- T3: docstring reworded -- the tests import no module under test
  (`serve.navis_write`; `navis_ops` only as the monkeypatch seam of the
  unknown-kind test); EditorApp/cli/navis_archive as fixtures, stated.
- T4: new §9-row-4 HTTP test (archive, edit the marker text on disk,
  restore 200 changed=true, `GET /api/navis` shows the LIVE edited text as
  active). The §12 docstring claim narrowed to the journal refusal (no
  draft test built, per the review).
- S1: `_render`'s fallthrough is now 500 JSON naming an unknown kind (red
  first); journal_pending kept in the 409 branch (a first-cut guard dropped
  it to 500; its own run caught that).
- S2: dead `VERBS` frozenset deleted.
- S3: the two POST paths removed from the final 405 tuple (unreachable --
  the route hook catches every method on both paths). All five listed serve
  test files stay green without them; the round-0 log's "the 405 list
  carries ... the two POST paths" is superseded by this.
- Rejected on purpose: pre-lock snapshot read, the vscode-adapter citation
  range, the "1..0" wording, asserting `verb`, surfacing a failed refresh.
- Pre-push: the five listed files -> 171 passed. Full suite (once): 5746
  passed, 2 skipped (0 failed).

## Review round 2 (one accepted finding; one commit)

- `handle` now gates `read_only` FIRST (before body/selector validation),
  returning the same 403 `refused` shape via the one `_NO_WRITE_MESSAGE`
  constant shared with the `refused_no_write` render; the `allow_write=`
  pass-through stays as defense in depth. Red first: the 8 read-only
  malformed-body cases failed (400/404) and the 3 writable-parity cases
  passed; after the hoist all green. Five listed files: 182 passed; full
  suite (once): 5758 passed, 2 skipped.
