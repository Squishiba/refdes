- **`refdes audit`'s accepted-reseal rows no longer leak the `[unboarded]`
  placeholder.** In a project with no `boards:` registry the row read
  `LOG-001 [unboarded] 2026-10-01T06:31:53+00:00 edit`; every other section of
  the report shows an absent board by leaving it out, so this one now does
  too (`LOG-001 2026-10-01T06:31:53+00:00 edit`). A declared board still shows,
  bracketed as before. Nothing is recorded differently: the seal file is
  unchanged.
- **The surrogate key in that section is now labelled.** The bare `key
  5770ky4fphv` line reads as a named field (`item key …`) and the section
  says what the key is for, because a row's id is the label as it stood when
  the event happened: a renumbering splits one entry's history across two ids,
  and the key is the only thing that ties them back together (it is also the
  half of `refdes keys restore ID@KEY` that proves which item you mean).