- **A key written twice in one mapping of an item file is now a build error.**
  YAML resolves a repeated key silently by keeping the last value, so a
  duplicate was never visible anywhere: not in the file, not in the build, not
  in the rendered site. The shape that causes it is a one-line deletion. In a
  list file an entry opens with `  - key: <key>`; delete that line to drop an
  item's key and the entry's `- ` marker goes with it, so the entry's remaining
  fields become the *previous* item's fields. Three items became two, and
  because YAML kept the last of the two `id:` values, one of them left the
  model with no diagnostic of its own. The only trace was whatever reference the
  vanished id left dangling somewhere else -- and, when the merged entry kept
  the original's `key:` line, no trace at all: every inbound composite resolved
  onto the item that swallowed the other one and `refdes check` reported
  `0 errors`, exit 0, ready for `refdes release` to stamp a baseline over it.
  Any repeat is now reported, not just an `id:`: a repeated `body:` loses the
  earlier text from every rendered page just as quietly. One error per repeated
  key, naming the file, the line of *each* occurrence, the key, and the id the
  entry ended up with --
  `duplicate key 'id' in one mapping (lines 14 and 17) -- YAML keeps the last,
  so 'REQ-PWR-002' is dropped for 'REQ-PWR-003'` -- plus the remedy, which names
  the shape to look for (`put the '- ' back on its own line`). A repeat inside
  a file's `defaults:` block is reported as such, since a value lost there is
  inherited by every item in the file. Covered in Markdown front matter too,
  and in a nested mapping, not only an item's own top-level keys.
- **A file that reports a duplicate key is no longer rewritten by the load.**
  `refdes check` mints `key:` lines and expands bare references on every
  writable load. Doing that to a file whose mappings are known to be lossy
  moves the very lines the author has to read, and in the merged-entry shape it
  froze live references in *other* files onto the item that swallowed the
  vanished one -- in the same load that had just discovered the merge. Such a
  file is now left byte-identical: no key minted into it, no reference written
  into it, and the items in it publish no key rather than one that exists only
  in that process. The withholding is per file, so a clean file in the same
  project is still normalised. `refdes revise apply`, `refdes keys adopt`,
  `refdes keys restore` and `refdes calc-rewrite` refuse before writing
  anything, as they do for any build error. `refdes id` is the one command that
  still writes: it allocates ids for the pending items it can see, anchored to
  each item's own entry, and exits 1 with the load errors printed.
- **What you have to do:** if your build now fails with `duplicate key`, one
  mapping spells a key twice. In a list file, look for an entry that is missing
  its `- ` marker -- the entry above it will have two `id:` lines, or two of
  whatever else the two entries shared. Put the `- ` back on its own line above
  the `id:`, or delete the line you did not mean to keep. Before this change the
  same file loaded, and an `id:` lost this way took an item out of the model
  without a word: if you have merged item files by hand, check the ones you
  touched, since a merge that dropped a `- ` is exactly what this reports and
  nothing reported it before.
