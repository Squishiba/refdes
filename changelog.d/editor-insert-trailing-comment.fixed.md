- The browser editor's insert path no longer moves a trailing comment off its
  line. Setting a field the item does not have yet (`status: approved` on an
  item whose last field carries `# a note`) inserted the new key *before* the
  `#`, so the comment ended up attached to the new field's line -- in YAML
  list files, Markdown front matter, and on CRLF files alike. The insertion
  point now crosses the same-line comment to the end of its line, so the
  comment stays on the field the author wrote it on; `add_link` of a verb the
  item does not have uses the same path and is fixed with it.
