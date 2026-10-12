- The browser editor's routes report a lock failure as a refusal instead of
  crashing. `serve/edit.py` documents that a project write lock the filesystem
  will not host becomes an ordinary refusal on every editor writing route, but
  the item-creation route had no handler at all — an unwritable project root
  turned a create into an unhandled `LockUnavailable` (a 500 from the editor
  route) — and the source-pin accept caught only `LockUnavailable`, so any
  other `OSError` the lock raises on its way in escaped the same way. Both now
  come back as `refused: could not lock <project> for writing: ...`, the
  spelling every editor save already used. Tests in
  `tests/test_citations_lockfile_locking.py`.
