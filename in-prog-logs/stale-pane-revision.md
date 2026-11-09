# Stale pane revision: the save context must describe the bytes its rows came from

Task: on a writable `refdes serve`, the preview task pane's save context
could pair a FRESH file revision with STALE task rows. The rows come from
the app's in-memory snapshot (last completed build/load); `tip_revision`
was `edit.file_revision(path)` of the tip's source file read at response
time (disk). Lead's browser probe (.scratch/pptr463/dbg481.mjs): after an
external edit changed a task (T-probe open -> dropped), the page carried
the NEW file's sha256 while T-probe's row still said `open`. The author
ticks against the old list, Save sends the new revision, the endpoint's
revision check passes -- a silent success against a change nobody saw,
and the conflict panel's "the file has ..." column can be stale.

## Fix chosen: (A), the preferred one

`Snapshot` (src/refdes/serve/state.py) already carries `hashes`: a
relpath -> sha256-of-bytes map recorded when the model was built, by
`content_hashes` -- documented in `edit.file_revision` as "the same
spelling", so a client can hold either and compare. `_pane_save_context`
now takes that dict (threaded from `_decorate`'s snapshot through
`_decorate_task_ticks`) and names `hashes[rel]` for the tip's file
instead of hashing the disk. That is exactly the bytes the rows were
folded from: a page built from old bytes names the old revision and the
save against it is a 409 Conflict from `_continue_locked`'s existing
check; no endpoint, template, JS, or state.py change. Chose A over B
because the data was already in the snapshot (B would add a fresh
disk-read + a preview-only degraded mode for a state that is exactly
what Conflict already models), and every existing pin stays true.

Key spelling: `os.path.relpath(_item_path(...), project.root)` normalised
to "/" -- the same expression `content_hashes` uses for its keys, so the
lookup matches by construction. Unreadable/missing/never-hashed tip file
-> "" -> no context, as before (keyless/id-less/escaping tips unchanged).

## Red -> green

New tests/test_task_pane_stale_revision.py (EditorApp poll_interval=60 so
the poller's first pass is a minute away; the served snapshot provably
never rebuilds; project warmed by one writable `check` load to mint keys):

- `test_a_disk_change_the_rows_never_saw_keeps_the_pages_old_revision`:
  fresh page rev == sha256(disk); external byte-edit flips
  T-thermal-model open -> done; re-GET asserts the page still names the
  OLD revision with the OLD rows, and POST /api/item/LOG-002/continue
  with the page's revision must be 409 conflict naming the disk's new
  sha256, with nothing written. RED before the fix (page carried the new
  sha: d834b073... vs 1a4818d6...); green after.
- control: no disk change -> page rev == file_revision(disk) and a save
  drafted from it applies (200, LOG-003 on disk). Green before and after.

## Verification

- New file + test_task_pane_tick_context.py (pinned, unedited) +
  test_task_pane_ticks.py: 34 passed. Note test_task_pane_tick_context.py
  `test_the_next_preview_after_a_disk_edit_carries_the_new_revision`
  (poll_interval=0.05) passes unchanged: after the poller rebuilds, the
  snapshot's hashes name the new bytes, so the page names the new
  revision again -- A keeps render-time freshness through rebuilds.
- test_serve_continue*.py, test_serve_edit*.py, the save-ui/discard/
  polish/tick-ui/idless-pane files, crossplatform lint: 493 passed;
  test_task_pane.py, test_serve_preview_task_pane.py,
  test_serve_editor_e2e.py: 52 passed.
- Full suite once: 6432 passed, 2 skipped (98 s, -n 4 --dist worksteal).
- `ruff check --select E9,F src tests` (the CI gate): clean. The one
  UP012 hit in server.py is pre-existing on HEAD, untouched.

## Notes

- tests/test_task_pane_ticks.py: one call site of the private
  `_decorate_task_ticks` updated for the new `hashes` parameter (1 line;
  no assertion touched). Only test_task_pane_tick_context.py was pinned.
- Browser behaviour is verified by the lead, not re-run here.
- An unrelated `git stash` (fix/init-gitignore-pattern-intent) exists in
  this checkout; left untouched per AGENTS.md.

Status: finished. PR: see branch fix/pane-revision-snapshot.
