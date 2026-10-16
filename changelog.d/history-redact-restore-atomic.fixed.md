- History: `refdes history redact`'s rollback no longer restores removed
  files by opening each target with `open(path, "wb")` and writing. The open
  truncates the path it lands on, so a rollback whose write then faulted
  (ENOSPC, EIO) left a zero-byte event file in a store that had a valid one,
  and the faulting `OSError` escaped the rollback handler and replaced the
  failure that had triggered the rollback — the user lost the file, the
  original error, and (once the store is next read) every later history
  command. The restore now writes the bytes it holds in memory to a
  same-directory temp and lands them with one `os.replace`: the target is
  created with its full bytes or not at all, so a restore that faults leaves
  the path exactly where the removal left it (absent) instead of corrupting
  it. A faulted restore is disclosed rather than swallowed: the raised
  `HistoryError` names the original failure and every file the rollback could
  not put back, with the original preserved as its `__cause__`. (Finding from
  PR #244's review of the same truncate-then-write shape on the serve create
  path; `history.py`'s redaction loop was named there as the sibling.)
