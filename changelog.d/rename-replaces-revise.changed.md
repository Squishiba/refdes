- **`refdes revise` is now `refdes rename`** (docs/design/vocabulary-review.md
  P12). `revise` and `revision` are two letters apart and do unrelated things,
  and what the command applies has always been an explicit old->new vocabulary
  mapping (type names, scoped field names, link verb names, id prefixes) to
  every item file -- a rename. `refdes revise …` keeps working until the next
  minor release with identical behaviour and exit codes, printing one line to
  stderr naming the new name; stdout is untouched, so a script reading the
  command's report or a `--dry-run` plan sees the same bytes either way. The
  old name is gone from `refdes --help`, usage line included. Error and help
  text that named the command now says `refdes rename`; the engine module is
  still `src/refdes/revise.py`.
