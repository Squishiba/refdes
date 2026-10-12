- **`refdes revise` is now `refdes rename`** (docs/design/vocabulary-review.md
  P12). `revise` and `revision` are two letters apart and do unrelated things,
  and what the command applies has always been an explicit old->new vocabulary
  mapping (type names, scoped field names, link verb names, id prefixes) to
  every item file -- a rename. `refdes revise …` keeps working until the next
  minor release with identical behaviour and exit codes, printing one line to
  stderr naming the new name; stdout is untouched, so a script reading the
  command's report sees the same bytes either way. A `--dry-run` plan is the
  same either way too, except for the surrogate keys it mints to show the plan
  with, which are drawn per run and so differ between any two runs. The old
  name is gone from `refdes --help`, usage line included. Error and help text
  that named the command now says `rename` -- the retired name survives only
  in the alias's own note and in argparse's unknown-subcommand choice list,
  which reflects what still parses; the engine module is still
  `src/refdes/revise.py`.
