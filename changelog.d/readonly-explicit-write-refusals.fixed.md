- Six more commands no longer print a `PermissionError` traceback when the
  checkout is read-only. `refdes stub-tests`, `refdes revise mapping.yaml`,
  `refdes calc-rewrite`, `refdes standard upgrade`, `refdes id`, and
  `refdes standard add-preset` / `remove-preset` each reached a raw
  `textio.write_text` whose only guard was that the filesystem would take it.
  Each now says `cannot write <path> (read-only tree?)` and what that cost,
  exits non-zero, and leaves nothing half-applied — which is what
  `docs/cli-reference.md` has claimed since the read-only work landed, and
  what run 4's F1 found to be false.

  Exit codes follow each command's existing convention rather than one new
  rule: `revise`/`calc-rewrite`/`standard upgrade`/`stub-tests`/`id` exit `1`,
  and `standard add-preset`/`remove-preset` exit `2`, the code they already
  used for "your config is not what you asked for it to be".

  `revise`, `calc-rewrite` and `standard upgrade` roll the whole rename back,
  not just the part that was refused. That meant two fixes inside the
  transaction: the item files are now written with the same refusal the
  carry-forward seal used to raise, *before* the rollback is defined (a
  rollback that only exists for the refusals discovered further down cannot
  answer for the first one), and every restore compares the file against what
  it would put back, so a rollback does not re-attempt the write the
  filesystem has just refused. Without that second fix the refusal came back
  out of its own rollback as a `PermissionError` again.

  `stub-tests` is the one command that cannot be all-or-nothing, and does not
  pretend to be. Its files are independent — one `stub-tests.md` per
  workspace/board, each holding only its own scope's stubs — and a stub that
  has been written is the author's from that moment, so what landed stays. The
  refusal names the files that did not, and re-running after the tree is
  writable picks up exactly the missed ones: deduplication is by declared
  link, so a stub already on disk is never emitted twice. The command still
  exits `1`, and still prints the summary of what it did write, so the
  account of a partial run is on the screen rather than in a traceback.

  `id` reports the same way and, as it already did for an id it could not
  place, allocates nothing for a file whose write-back was refused — the
  number stays free. The id ledger gets its own refusal, in its own words,
  because by the time it is written the ids are already in their source files
  and there is nothing left to roll back; the report says which half is
  missing rather than claiming an allocation it could not record.

  `docs/design/keys.md` §2 and `docs/cli-reference.md`'s destination table now
  list all of these instead of leaving the reader to infer them, and the
  "any other explicit write raises, as before" row is corrected: `keys adopt`
  and `keys restore` are the commands that still let the refusal propagate,
  and they are now documented as the one family of explicit writes whose
  message does *not* carry `(read-only tree?)` — so a CI filter written on
  that marker will miss exactly those two, which is worth knowing before you
  rely on it.
