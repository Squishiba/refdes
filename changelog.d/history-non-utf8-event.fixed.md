- History: an event file in `.refdes/history/events/` that is not valid
  UTF-8 is a `HistoryError` naming the file, instead of a raw
  `UnicodeDecodeError` traceback. The store's contract is to be loud but
  graceful about a malformed record — an unparseable event, an unknown
  kind, an id that disagrees with its filename each raise a `HistoryError`
  that every reader catches and turns into its own "the history store
  could not be read" sentence. But the file is opened with
  `encoding="utf-8"` and decoded on the first read inside the loader, and
  a `UnicodeDecodeError` is not a `YAMLError`, so it escaped the one `try`
  that wraps the read and crashed every command that touches history
  (`refdes thread`, `refdes work`, anything building over a store with
  captures) over one stray byte. Now it takes the same path as the other
  malformed records: `refdes thread` still prints its thread with the
  captured lines missing, says the store sentence on stderr naming the
  file, and exits as before.
