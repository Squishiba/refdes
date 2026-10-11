- **`refdes thread <ref>` (living notes H7b).** One thread's view as a
  command — header, capture line, tip(s), the authors' tasks with age, and
  the self-closing derived block — rendered from
  `refdes.threads.threads_projection()`, the same projection the `index`
  payload carries under `threads`, so the terminal and the index cannot
  disagree about the fold. Any entry on the thread names it (display id or
  surrogate key). The authored tasks and the derived rows print as two
  separate labelled blocks with separate numbering (derived rows carry no
  number and are never written back); every open task prints the entry that
  declared it and that entry's date, with a relative span only under an
  explicit `--as-of DATE` — without the flag the bytes never depend on the
  wall clock; a folded verdict prints together with its tip's open tasks;
  and a fork prints one labelled block per open tip with no single current
  status anywhere. `--json` prints the thread's projection entry. An unknown
  ref or an entry on no thread is an error with exit 2; the command itself
  writes nothing (its build never seals, like `index`/`ls`). See
  `docs/cli-reference.md`.
