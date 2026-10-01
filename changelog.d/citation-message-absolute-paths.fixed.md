- **No citation diagnostic prints an absolute path any more.** Two of them
  did, and one of the two reached the browser. A cited local file that is not
  there was reported by `refdes fetch` as the raw
  `[Errno 2] No such file or directory: '/home/you/your/project/datasheets/nope.pdf'`
  — the server's own directory, and no citing item id, while `check` reported
  the same condition correctly. `fetch` now uses `check`'s sentence and names
  its citers: `cited local file 'datasheets/nope.pdf' does not exist (cited by
  CMP-PWR-001)`. Any other `OSError` on the same read gets the same treatment
  (`cited local file '…' cannot be read: Permission denied`), built from the
  OS's own reason rather than the error's text, which is the one string that
  carries the path back in.

  The `source()` re-location message was the other, in three places rather than
  one: the `SOURCE FILE CHANGED` warning, the calc line the build stores and
  renders next to the number (`build.py`'s `calc-source-drift`), and two
  `refdes fetch` `FAILED` lines. All four named the file by the path the reader
  was handed instead of the path the project declared. That last one matters
  beyond style: `refdes serve` renders the same site into `/preview/`, so the
  sentence was served to anyone holding the launch URL, and a plain
  `refdes build` wrote it into `_site/`, where a published static host carries
  no token at all. Every reader call now names the file by its canonical
  project-relative path, and the CSV reader's own open failure stopped
  composing `str(exc)` — the one string that undoes the label it was given.
  Messages are otherwise unchanged: same conditions, same remedies, same
  exit codes.