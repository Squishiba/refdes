- Docs: `standard-library.md` said the bundled standard ships **six** item
  types, in both the intro and the "What's in it" table, and omitted the
  `group` type (`GRP`) that `hardware@3` adds — the very type whose whole
  purpose is to be a named collection. The count is now seven, `group` is in
  the table, and the version-history list gained the `group`/`part_of:` change
  it was also missing. Verified against `refdes schema` in a scratch project
  pinned at `hardware@3`: seven types, and `part_of: [group]` authored by
  exactly `requirement`, `bound`, `decision`, `test`, and `component`, with
  `group` absent from every `satisfies:` target list. The separate claim that
  `hardware@1` has six types is correct and left alone.
