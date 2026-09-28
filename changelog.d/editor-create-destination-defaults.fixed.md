- **The editor's New Item form now numbers from the destination file's own
  `defaults.prefix`** — creating a requirement into a file whose
  `defaults:` says `prefix: REQ-SYS` produced `REQ-001`, from the bare
  `requirement` type prefix, while `refdes id` gave `REQ-SYS-001` for the
  same file. The two paths disagreed, and only `refdes check` noticed, as a
  *warning*, after the wrong id was already written to the file and burned
  in `.refdes/ids.yaml`. An item about to be created inherits the
  destination's `defaults:` exactly as every item already in that file
  does, and that now includes the series it is numbered under — in a list
  file's `defaults:` block, and in a multi-item markdown file's leading
  `defaults:` block, which is where the markdown spelling of the same
  override lives. A brand-new file has no `defaults:` block yet, so its
  first item still numbers from the type. The id the form *previews*
  carries the same prefix: `GET /api/create/preview` and
  `POST /api/items/create` resolve the destination identically, which is
  what makes "the ID shown before saving is the ID the item gets" true for
  a prefixed file too. An explicit id override is now checked against the
  prefix the item will actually be numbered under, and the refusal names
  the `defaults:` it came from.
- **A field the destination file's `defaults:` already supplies is no longer
  written onto the item created into it** — the same bug in its second
  dress. A file whose `defaults:` said `status: active` collected items
  stamped `status: draft`, one explicit `status:` line per item, each one
  silently overriding the file's own setting; the created item now inherits
  `active` and carries no line to contradict it with. A value you supply in
  the form is still written, since overriding the file is what supplying
  one means. Affects both destination shapes that have a file to inherit
  from; a brand-new file has no `defaults:` and is unchanged.
