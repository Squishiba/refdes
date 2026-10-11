- Every writer of the citation lockfile now holds the project's cross-process
  write lock for its own read-modify-write. `serve/edit.py`'s rollback of a
  refused accept used to read `.refdes/citations.yaml`, compare it with the
  bytes its own accept had written, and restore the bytes it had read *before*,
  with no lock around the three steps; its comment said so and named the cure it
  did not apply — "a cooperating writer landing between the read and the
  restore is overwritten ... the window is microseconds ... so it is accepted,
  not closed; closing it properly means a real lock, which is a separate
  decision." The owner decided: add the real lock. `serve/edit.py` is the only
  code that was missing it: `_accept_pins`'s read of the lockfile, its
  extraction, and its whole-file replace are now one section of
  `write_lock.project_write_lock(root)`, and so are `_LockfileWrite.rollback`'s
  read, compare and restore. `project_write_lock` is re-entrant per thread, so
  the rollback that `_apply_locked` calls from inside the item's own
  check-and-replace section simply nests. `refdes fetch` was already covered —
  it runs inside `cli.main`'s whole-command
  `with project_write_lock(...)` hold (src/refdes/cli.py:2961), which is why
  `serve` is on that call's exclusion list and why the editor has
  to take the lock itself — and its read and write are one hold, so it cannot
  lose an update; that lock stays as wide as it was, because the record `fetch`
  writes at the end is derived from bytes it fetched between the read and the
  write, so narrowing it to the write alone would need a per-path merge this
  whole-file writer does not do. The compare inside the rollback stays, and is
  not redundant: it is there for a save that landed during the *candidate gate*
  — which runs unlocked on purpose, because it can take seconds and a lock held
  across it would keep every CLI writer out of the project that long — not for
  the gap between its own read and restore, which is now closed. What is still
  not promised, and the rewritten comment says so: a process killed inside the
  one `os.replace` that lands the restore (the crash window
  `docs/design/editor-source-picker.md` §4 already states), a read error or a
  lock that cannot be acquired — on which the rollback declines rather than
  writes blind, and the accept comes back as its ordinary refusal — and a
  writer that ignores the lock. `write_lock_for`'s docstring now carries the
  order the two editor locks must be taken in: in-process lock first, project
  lock inside it, never the reverse. `tests/test_citations_lockfile_locking.py`
  proves the window closed with a second writer built on a thread and an event
  rather than on sleeps — it lands after the restore, never inside it — and
  that `refdes fetch` writes while holding the lock and waits outside it while
  someone else holds it; removing the lock from either writer makes the
  corresponding test fail.
