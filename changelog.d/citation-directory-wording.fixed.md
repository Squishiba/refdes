- A citation that names a directory gets one sentence from `refdes check`
  and `refdes fetch`: `cited local file 'sources/adir' is a directory, not
  a file` (fetch adds its `(cited by ...)` list as usual). It used to be
  two. `check` reported `does not exist` — its `isfile` gate in
  `citations._resolve_local` never looked at what the path *was* — and
  `fetch` reported the OS's phrasing of its `open()` failure, `cannot be
  read: Is a directory`. Both half-false: the directory is there, and
  nothing about it is unreadable. One condition, one true wording
  (DIAG-WORD-002); the `state` stays `"missing"`, whose row in
  `docs/output.md` now names the directory case. A path that is genuinely
  absent keeps `does not exist` on both commands, an existing file that
  cannot be read keeps `cannot be read: Permission denied`, and the
  accept/outline family's `is not on disk` messages are untouched. All
  pinned by `tests/test_citation_path_hygiene.py`.
