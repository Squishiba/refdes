- `refdes standard add-preset` / `remove-preset` no longer destroy
  `refdes-project.yaml` when the write fails partway. Both wrote the config
  through a truncate-on-open, so a full disk (ENOSPC) destroyed the real
  config before the failure was noticed: the add-preset refusal claimed the
  presets line was "exactly as it was" while the file's tail was already
  gone, and the remove-preset refusal said "Nothing changed." while leaving
  a truncated `refdes-project.yaml.scratch` in the project root — its
  cleanup never runs when the write itself is what raised. The config write
  and the simulation's scratch copy now go through the same atomic write as
  the id ledger: a temp in the same directory, fsynced, renamed into place,
  unlinked on any failure. A refused write leaves the config byte-identical
  and the project root clean, which is what the refusals have always
  claimed; their wording and exit 2 are unchanged, and a successful write
  preserves the config's file mode.
- A `refdes-project.yaml` that is a symlink to a real file in the project
  keeps being a symlink, and the change lands in the file behind it. The
  atomic write resolves the link and renames onto the target, because a
  plain rename into the link's path replaces the link itself with a regular
  file — which is exactly how the atomic switch initially regressed
  symlinked configs (found in review, fixed in the same PR).
