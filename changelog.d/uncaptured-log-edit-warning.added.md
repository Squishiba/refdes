- **An edit to an uncaptured history-backed entry is now warned about**
  (run-5 finding B3). A `sealing: history` type keeps no build-time lock, so
  an entry with no capture in `.refdes/history/` could be rewritten wholesale
  with `refdes check`, `refdes build` and `refdes release` all silent, and the
  next release stamped the rewritten text as the recorded truth -- the only
  trace of it was a `refdes audit` line, visible only once you already knew to
  look. Its legacy seal record still holds the hash it was sealed under, so
  the edit is detectable, and `check` and `build` now say so:
  `LOG-001: edited while uncaptured -- the current content no longer matches
  the hash <old> recorded in .refdes/log-seal.yaml, and nothing in
  .refdes/history/ holds a snapshot of this entry, so the edit leaves no trace.
  Run `refdes history capture LOG-001` to record the current text; an edit
  after that is reported as edited after captured.` It is a warning and
  nothing more: no gate, no changed exit code, no write to `.refdes/`, and no
  change to any type's `sealing` default. An entry that has a capture is left
  to `edited after captured` (never both), and an entry no record names at all
  stays silent -- nothing recorded its prior content, so there is no edit to
  report.
