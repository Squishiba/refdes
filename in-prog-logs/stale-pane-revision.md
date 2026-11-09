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

## Follow-up: the lead's browser probe on 5280852 (2026-11-09)

The lead's probe on head 5280852 still shows rev = sha256(edited file)
with the T-probe row open, 5/5. Diagnosis: that signature is the PRE-FIX
code path, and it is unreachable on 5280852:

- rows and revision come from ONE snapshot read per response:
  server.py:944-945 (`snapshot = self.app.state.snapshot; project =
  snapshot.project`), passed together at :962 to
  `_decorate_task_ticks(..., snapshot.hashes)`; rows are folded from that
  `project` (:358) and the revision is `hashes[rel]` (:333-337). No
  response can pair one snapshot's rows with another's hashes.
- the snapshot itself pairs project+hashes from the same disk read
  (state.py:217-219) under the pre/post hash guard (:208-223, which
  rehashes the disk before and after `load_readonly` and rebuilds if the
  bytes moved in between), and is swapped by one atomic attribute
  assignment (state.py:238, :289). A response with rows=open (pre-edit
  project) therefore names sha(base), never sha(edited).
- reproduced the lead's exact numbers at transport level on the PARENT
  commit (pre-fix, git archive c5b6d58a): disk flipped open->dropped,
  page served rev = sha(edited) with rows open, for the whole
  poller-detection window (~35 ms observed at interval 0.01; seconds-wide
  at the default 1.0 + 2-poll debounce, so a fetch 3 s after the edit is
  inside it) -- the signature the probe reports.

Most likely the probe's `refdes serve` process ran pre-fix code: the
recipe's server-start pattern (`.scratch/pptr388/serve_run3.py`) does
`sys.path.insert(0, '/home/jorb/work/refdes/.scratch/d388/r5/src')` --
an old src snapshot; the venv's installed wheel is older still; and
tests/conftest.py:13 inserts `tests/../src` at sys.path[0], so an
in-process harness rooted at the main checkout imports the main
checkout's (pre-fix) src no matter what PYTHONPATH says. I tripped over
exactly this trap: a red-check run under a pre-fix PYTHONPATH printed
`server file: .../worktree/tests/../src/...` with the FIXED signature.

New test (same file, third): `test_the_live_poller_transition_never_pairs
_a_new_revision_with_old_rows` -- live poller (0.01), external
open->dropped flip of T-probe, the real `ProjectState.refresh` (the
poller's own entry) wrapped only to block on an event barrier, so the
window is held open deterministically; 20 pages sampled in the window,
20 after the real rebuild, invariant on EVERY sample (rev sha(base) ->
row open; rev sha(edited) -> row `dropped` [a dropped task stays in the
fold declaring its state]; nothing in between). RED on the parent commit
(`- dropped / + open` on window samples), green on head.

## Notes

- tests/test_task_pane_ticks.py: one call site of the private
  `_decorate_task_ticks` updated for the new `hashes` parameter (1 line;
  no assertion touched). Only test_task_pane_tick_context.py was pinned.
- Browser behaviour is verified by the lead, not re-run here.
- An unrelated `git stash` (fix/init-gitignore-pattern-intent) exists in
  this checkout; left untouched per AGENTS.md.

Status: finished. PR: see branch fix/pane-revision-snapshot.
