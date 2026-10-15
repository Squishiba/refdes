- A directory in the place of a `.refdes/` store file is a clean error
  naming the path, not a crash. A directory named `*.yaml` under
  `.refdes/baselines/` killed every command with a raw
  `IsADirectoryError` traceback, and the `isfile`-guarded readers of the
  seal file, the id ledger, the board/workspace membership manifest, and
  the citation lockfile silently read a directory as "absent" -- an empty
  ledger, `{}` for the lockfile. Every store reader (baselines, seals, the
  id ledger, the membership manifest, the lockfile, and the history
  store's event and object files) now raises its own error naming the
  path; `refdes keys adopt` refuses a directory marker the same way.
