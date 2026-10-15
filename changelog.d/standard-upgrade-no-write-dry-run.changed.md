- `refdes standard upgrade --no-write` now reports the plan and exits 0,
  like every other command with a `--dry-run`, instead of refusing the
  command with exit 2. The refusal justified itself by the command having
  no `--dry-run` to point at; it has one now, so `--no-write` selects it.
  `refdes standard upgrade --dry-run` has the same effect explicitly.
  Commands that fundamentally write (`fetch`, `init`, `standard
  add-preset`, `history capture`, and the rest) still refuse under
  `--no-write` exactly as before.
