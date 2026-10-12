- History: a command that records a history event (a thread capture, a
  revision, a legacy-seal write) onto an edge whose event file already
  exists but is corrupt — one stray non-UTF-8 byte, or YAML that does
  not parse — now fails with the store's usual loud `HistoryError`
  naming the file, instead of crashing with a raw `UnicodeDecodeError`
  or YAML parser traceback. The event *reader* took this path for a
  malformed record; this was the same open-and-parse in the append path
  with no wrap at all, so one corrupt file crashed the command over one
  stray byte.
