- An orphaned seal record whose display id opens with a hyphenated type prefix
  (`REQ-TMP-002`) or with one of a type's *legacy* prefixes (`DEC-001` of
  `hardware@3`'s `log`, whose `legacy_prefixes: [DEC]` `refdes check` already
  accepts as that type's own) is now recognised as belonging to that type.
  `_orphan_is_history_backed` cut the display id at the first hyphen, so
  `REQ-TMP` truncated to `REQ` and matched no declared prefix; the orphan fell
  back to *every* append-only type, and in a project mixing a history-backed
  type with a build-sealed one it was read as build-sealed: `refdes check`
  called the deletion an error whose own advice, `refdes build --reseal`,
  then *dropped the legacy seal record* while saying "nothing was rewritten"
  -- the silent record loss `docs/design-log.md` promises cannot happen. A
  match on `spec.prefix` alone still missed every legacy-prefixed record,
  landing it in the same fallback by a different spelling. The match now runs
  to a prefix boundary over each type's `prefix` *and* `legacy_prefixes` --
  the longest declaration the id starts with wins, so nested prefixes like
  `REQ` and `REQ-TMP` classify to the type that actually owns the id -- and
  the orphan is classified by the type it provably came from: `check` reports
  the promised legacy-seal warning, and `--reseal` keeps the record. Projects
  with a single append-only type and no legacy prefixes behaved correctly and
  are unchanged.
