- The schema reference now documents the `equations:` block, `units.aliases:`,
  and the eight process settings (`sigfigs:`, `item_layout:`,
  `baseline_identity:`, `require_rejection_rationale:`, `publish_datasheets:`,
  `lint_own_tags:`, `release_gate:`, `cross_workspace_severity:`), which its
  "every key" claim previously omitted.
- The schema reference now says a `citations:` entry names a `path` **or**
  another item's `item:` id, and that `date`, `list`, and `options` fields are
  enforced alongside `enum`/`limit`, instead of calling them declarative.
- The schema reference's list-field error example now carries the real
  diagnostic text, and its `check_severity:` mapping rule matches the loader
  (cover every status, or declare `default:`).
- The generated-blocks page no longer lists a stale set of `log` fields in its
  `{{index by=...}}` failure example.
- The standard-library page's upgrade-refusal sample matches the command's real
  output, and its `refdes init` description notes that an all-covered
  `.gitignore` is not rewritten.
- The parts page describes the cross-workspace lint as walking authored links,
  which is what it reads today.
