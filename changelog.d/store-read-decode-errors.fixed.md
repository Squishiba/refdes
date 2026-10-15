- A `.refdes/` store file that is not valid UTF-8, or does not parse as
  YAML, is now a loud error naming the file everywhere it is read, not a
  raw `UnicodeDecodeError` or YAML parser traceback. This finishes what
  the history event files got (#207/#209) for the rest of the store:
  history *object* files (a capture that must save that exact snapshot --
  `refdes history capture` of that content, say -- now fails with a
  `HistoryError` naming it; a build, check, or serve with no capture
  pending never reads the file),
  log seals, the board/workspace manifest, the id ledger, baselines, and
  the citation lockfile's non-UTF-8 half. A corrupt
  `.refdes/keys-adopted.yaml` is no different: `refdes keys adopt`
  refuses with the file named and says to repair or delete it, and the
  marker's usual posture holds elsewhere -- an unreadable marker still
  simply means "not adopted".
