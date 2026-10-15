- `refdes audit`'s `pages unchecked` row now covers every record that has no
  page count, not only the records with a *recorded* count failure. The run-6a
  fix for F1 made a row honest when the lockfile carried a `page_count_error:`
  or a count not tied to the pinned bytes; a record with no count at all — the
  shape a plain `refdes fetch` leaves for a plain-text datasheet cited with
  `page:`, and the shape a PDF has before any count — still printed the
  byte-identical `ok  hash-only  cited by CMP-PWR-001` row (run-7 finding
  F13). Such a row now reads `pages unchecked` with the reason the record
  supports: a document that is not a PDF has no page count for any command to
  record; a PDF with no count on record yet is counted by a plain
  `refdes fetch --path <path>`. `refdes check`'s page warnings are unchanged —
  a document with no count on record at all leaves `check` silent, and the
  audit row is where that state is named. Pinned in `tests/test_run7_f13_f14_f16.py`.
