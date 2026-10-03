- An unknown key inside a `checks:` entry is a diagnostic now, not silence.
  `checks: [{rule: ..., value: P_dens, against: BND-PWR-001, exrta: ...}]`
  checked green (`2 items, 0 errors, 1 warnings`, exit 0) with neither key
  mentioned, while the schema this tool writes for the editor declares that
  sub-mapping `additionalProperties: false` with `required: [value, against]`
  -- so the editor squiggled the key the moment it was typed and the CLI, the
  thing CI runs, said nothing. The two tiers are the ones an unknown key in an
  item's own front matter already gets (`parse.py`, `docs/authoring.md`'s
  "An unknown field whose spelling is close to one the type declares is a
  build **error**" / "An unknown field with nothing close to it stays a
  **warning**, and the value is kept"): a confident near-miss is an error
  naming the key it means (`unknown key 'values' in a checks: entry -- did you
  mean the key 'value'?`), anything else is a warning naming the legal pair.
  An entry that *lost* `value:` or `against:` outright is still refused by the
  existing shape error alone, so one keystroke is never reported twice, and an
  entry with only the two legal keys is still silent.
