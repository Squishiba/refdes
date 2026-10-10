- An orphaned seal record whose display id opens with a hyphenated type prefix
  (`REQ-TMP-002`) is now recognised as belonging to that type.
  `_orphan_is_history_backed` cut the display id at the first hyphen, so
  `REQ-TMP` truncated to `REQ` and matched no declared prefix; the orphan fell
  back to *every* append-only type, and in a project mixing a history-backed
  type with a build-sealed one it was read as build-sealed: `refdes check`
  called the deletion an error whose own advice, `refdes build --reseal`,
  then *dropped the legacy seal record* while saying "nothing was rewritten"
  -- the silent record loss `docs/design-log.md` promises cannot happen. The
  match now runs to a prefix boundary (the longest declared prefix the id
  starts with), so the orphan is classified by the type it provably came
  from: `check` reports the promised legacy-seal warning, and `--reseal`
  keeps the record. Projects with a single append-only type or
  non-hyphenated prefixes behaved correctly and are unchanged.
