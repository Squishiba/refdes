- A refused write is now announced with one sentence in both of the shapes it
  arrives in. Commands that print diagnostics said
  `could not write this file (read-only tree?); run with --no-write to silence
  this`, one line per refused file; commands that print only their own output
  (`ls`, `index`, `audit`, the `history` commands) had a separate summary line
  that named the same files in a near-copy of that wording — so a CI log filter
  written against the first silently missed every command in the second group.
  The summary line is now built from the same
  `refdes.model.read_only_refusal()` the per-file diagnostics use, and both
  shapes carry that sentence byte for byte. The split between them is
  unchanged: a command that reports still prints one line per file and no
  summary, and a command that does not still prints one summary and no
  per-file lines, so neither shape is ever printed twice in a run.

  If you filter refdes output for read-only refusals, match on
  `(read-only tree?)`. It is the one string every read-only refusal carries,
  including the ones that name a destination you asked for
  (`revision`/`release` baseline stamps, `history capture`, and a
  `revise`/`calc-rewrite` carry-forward), which put the path before it and so
  do not contain the longer `could not write this file (read-only tree?)`.
  That longer string still works and is the more precise filter if you only
  care about load-time writes. `build`'s refusal for the site output directory
  is deliberately outside both: it reports the operating system's own reason,
  because that write can be refused for reasons that have nothing to do with a
  read-only tree.

  Exit codes, the per-file/summary split, and every other word of these
  messages are unchanged. `docs/cli-reference.md` documents both shapes
  verbatim, under "Matching a read-only refusal in a log".
