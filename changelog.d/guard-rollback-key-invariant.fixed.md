- The invariant "a key whose write did not reach disk is not a key for this
  load" now covers the parse guard's own rollback, not just the two refusal
  channels it already wired. `revise.write_rewrites_verified` guards every
  load-time write and hands callers the set of files whose rewrite did not
  land, which is how `keys.mint_missing` keeps rolled-back items keyless and
  how the link-expansion passes drop their planned rewrites. The guard's
  rollback branch — a rewrite that parses worse than the original, restored
  to its original bytes with an error — never joined that set, so a forced
  guard failure left the rolled-back item holding its minted key in memory,
  and the next step of the same load wrote a sibling's `part_of:` into a
  `DISPLAY-ID@key` composite naming a key that exists in no file: every
  subsequent load, even read-only `refdes check`, then errored "points at key
  ... which no item declares", cleared only by hand-editing an item file.
  The rollback branch now reports its file like the filesystem refusals do,
  and the whole chain falls out: the item stays keyless in memory, no
  composite is planned or written for it, and the next load is clean.
  Ordinary input could not reach this (the guard is defence-in-depth; forcing
  it needs a corrupting writer injected), so no visible behaviour changes on
  any tree the guard never trips. (`revise.write_rewrites_verified`, finding
  KEY-GUARD-001, PR #113 review.)
