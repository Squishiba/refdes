- `refdes rename <mapping-file>` (and `refdes revise`) crashed with a raw
  `AttributeError` traceback when a section of the mapping file was not the
  mapping it assumes: the flat `fields:` shorthand (`fields:` with
  `history: on_change` directly under it, instead of under a type name), a
  `types:` written as a list, a scalar `links:` — every section was read with
  `.items()` on whatever the YAML happened to parse to. Each is now refused
  with a one-line `error:` naming the file, the section, and the shape it
  wants (e.g. `fields: must map a type name to {old_field: new_field}, e.g.
  `constraint: {title: text}``), with the offending type entry named for
  `fields:`, and exit 2 — the configuration-error class the exit-code table
  gives a missing or unparseable mapping file, through the same handler.
