- `refdes revise` now refuses a mapping file with an unrecognised top-level
  section instead of silently ignoring it. Every section it reads is `.get()`-ed,
  so anything else in the file vanished: `ids:` — the obvious thing to reach for
  when you want to rename one item, which `revise` cannot do, since it renames
  ids only as part of a `prefixes:` rename — made it print `nothing to do --
  mapping doesn't apply to this project` and **exit 0** having renamed nothing
  (verified). A file mixing a recognised section with an unrecognised one was
  worse: the recognised half was applied and the rest dropped without a word
  (verified). Both now stop before any project load, with a one-line `error:`
  naming the section and listing the five that are accepted — `types:`,
  `fields:`, `links:`, `prefixes:`, `citation_keys:` — and exit 2, the
  configuration-error class the exit-code table in the CLI reference gives a bad
  input file, through the same handler that already turned a missing or
  unparseable mapping file into that exit. `--dry-run` refuses identically, so
  the plan can no longer read as "nothing to do". An `ids:` mapping is also
  pointed at what does rename a single item: edit the item's `id:` by hand,
  after a writable `refdes check` has expanded references to composite form so
  they follow the rename. `refdes revise --help` and the CLI reference now list
  `citation_keys:` too, which both had been omitting while the bundled
  standard's own `migration.yaml` uses it.