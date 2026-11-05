# editor-draft-revision (slice ED-1-tests, test author only)

Task: write failing tests pinning the data-loss bug in the browser editor's
draft/revision handling. No src/ changes; the implementer continues on this
branch.

## Root cause (confirmed by reading + harness evidence, not the browser)

`editor.js:42`: `let revision = draft.revision || edit.file_revision ||
item.revision;`. `draft.revision` is written ONLY by `dropAppliedOp`
(drafts.js:323, after a save op applied) and reset by `clearDraft`, so it is
null for a fresh dirty draft. When app.js `renderRoute` re-renders on
`refdes:rebuilt` (app.js:127), `createEditor` re-runs with the refetched
item; the dirty draft survives (it lives in drafts.js) but carries no
revision, so the form adopts the NEW `edit.file_revision` and Save posts
`expected_revision` = the external writer's revision -> the server (correctly)
matches and accepts -> last-write-wins, external change lost.

Evidence at first keystroke (node harness, scenario `stamp`): after typing a
body change, `drafts.getDraft(handle).revision === null` (expected 'rev-0');
scenario `rebuildChanged`: `editor.getRevision() === 'rev-1'` on reopen and
the Save POST carried `set_body@rev-1` -> 200, `saved:true`,
`conflictVisible:false` — exactly the reported data loss.

## Tests written

- tests/test_editor_draft_revision.py (new, node harness in the style of
  test_editor_draft_mirror.py). Scenarios: stamp (body), stampField (field),
  rebuildChanged (Save must post the OPENING revision -> 409 -> conflict
  screen), rebuildClean (no-draft form adopts the new revision),
  saveThenStamp (post-save edit records the NEW revision; next rebuild
  conflicts), rebuildSameRevision (unrelated change: no false conflict).
  RED today: stamp revision null (not 'rev-0'); stampField null;
  rebuildChanged reopenedAt 'rev-1', posts set_body@rev-1, saved true,
  conflict hidden; saveThenStamp stamp null, posts set_body@rev-2.
  GREEN guards (pin the fix against over-correction): rebuildClean and
  rebuildSameRevision already pass today.
- tests/test_serve_edit_http.py: two server-level tests.
  test_a_stale_revision_on_a_body_edit_is_409_and_changes_nothing (RED? no —
  the server is correct today; GREEN pin for the body op: the existing
  test_a_stale_revision_is_409_with_diff_and_changes_nothing covers
  set_field only).
  test_an_external_edit_to_another_items_file_does_not_conflict_this_save
  (GREEN pin of contract 5: edit.py checks `file_revision(path)` of the
  EDITED ITEM'S OWN file, not the project serial — verified by running it).

## Notes

- The 409/conflict screen (editor.js showConflict) itself is untouched and
  already tested (test_serve_edit_http/test_vscode_adapter_contract); the
  harness's conflict scenario exercises it end-to-end from the client side.
- No changelog fragment: tests only, no user-visible change.
- Status: done. Full suite run once before push (see final reply).

# ED-1-impl (implementer)

Merged `origin/main` into the branch; `git merge --ff-only` was impossible
(the branch carries the test-author's commit on top of base `ff078148`,
which is recent — not the old-base failure mode), so a normal merge was
made.

## The fix (44 inserted lines, all under src/refdes/serve/static/)

- `drafts.js`: new exported `stampRevision(handle, revision)` — a dirty
  draft records the form's opening revision (idempotent, persists to the
  session mirror); a clean draft resets the stamp to null.
- `editor.js`: import + call `stampRevision(handle, revision)` from
  `writeDraft`, `writeBody`, `insertSourceLine`; pass a stamp callback to
  `createLinksSection`. The stamp is the closure revision at the moment of
  the first edit, so post-save edits stamp the NEW revision.
- `links.js`: `verbPicker`/`createLinksSection` take an `onDraftChange`
  callback, fired on add/undo-add/remove/undo-remove.
- Live-calc's `revisionFromDraft: () => !!draft.revision` guard (kept in
  tests/test_editor_live_calc.py) keeps a dirty form riding its draft
  revision through rebuilds (no stale-model drop) — the stamp makes that
  posture real, not theoretical.

## Verification

- Red/green: `tests/test_editor_draft_revision.py` red (`stamp.revision`
  None != 'rev-0') -> green after the fix. Editor/calc/serve-edit family
  (880 tests incl. live-calc, drafts_corruption, static, e2e) green.
- Full suite: 5938 passed, 2 skipped (`-n 4 --dist worksteal`).
- Real browsers (puppeteer-core Chromium + playwright-core Firefox, own
  throwaway project on port 8850, `.scratch/pptr/`), all four required
  cases PASS in BOTH browsers: (a) dirty draft + external append -> Save
  shows the conflict screen, the POST carried the draft's opening revision
  (409), disk keeps the external line; Keep mine then writes the draft;
  (b) external change to a different item's file -> normal save, no
  conflict; (c) clean form adopts the rebuilt file (textarea shows the
  external line), typed edit saves, disk has both; (d) `POST /api/navis/
  mint` mints NOTE-005's marker while the draft is open -> Save -> conflict
  screen, minted key stays on disk, draft survives. The one Chromium false
  negative was a harness selector bug (the image picker mounts its own
  `.conflict` box; scope to `.edit-block .conflict`), not a fix bug.
- Status: done.

