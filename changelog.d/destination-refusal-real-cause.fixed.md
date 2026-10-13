- A full disk is no longer reported as a read-only tree. `refdes id`'s
  write refusals are built from a bare `except OSError`, so ENOSPC, EIO
  and friends all landed in the sentence meant for permissions and
  answered "disk full" on a fully writable tree with
  `cannot write items/reqs.yaml (read-only tree?)` plus "make the tree
  writable" — a claim refdes cannot make and a pointer to a permission
  that was never the problem (the same reasoning `docs/cli-reference.md`
  already gives for `build`'s site refusal and `keys adopt`). A refusal
  that carries the failing `OSError` now keeps the `(read-only tree?)`
  marker only while the failure could be one (EACCES/EPERM/EROFS, or the
  `PermissionError` the atomic writer's own guards raise without an
  errno), and otherwise prints the operating system's own reason —
  `(No space left on device)` — with a remedy that says fix the reported
  failure. Read-only refusals are byte-identical, so CI filters written
  against the marker still catch every failure a read-only tree could
  produce. Pinned by injection tests in
  `tests/test_readonly_explicit_writes.py`.
