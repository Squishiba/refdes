- `refdes index` on a project with an items file that fails to parse now
  prints the load errors to stderr instead of staying silent about them. It
  deliberately still exits 0 and still prints the full `items.json` for
  whatever did load: the VS Code extension discards the whole index whenever
  `refdes index` exits non-zero, so a half-typed YAML file mid-edit would
  otherwise blank the editor on every save.
- `refdes ls` now prints load errors to stderr and exits 1. The listing
  itself is unchanged — items from files that did load are listed exactly as
  before — it just no longer passes for a complete answer.
- `refdes id` now prints load errors and exits 1 when nothing is pending,
  instead of saying "no items are missing an id" about a project whose files
  it never read; the message now says ids could not be checked in the files
  that failed to load. Allocation and its exit code are unchanged otherwise.
- `refdes audit` now prints load errors to stderr and exits 1. The audit
  report itself is unchanged.
- `refdes former-ids propose` now prints load errors on both of its quiet
  paths: "no candidate former-id mappings found" becomes that plus a note
  that files which failed to load were not searched, and exits 1; the
  `--confirm` path's exit rule is unchanged but the errors behind it are now
  actually printed.
