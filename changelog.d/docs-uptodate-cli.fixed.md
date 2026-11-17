- `docs/cli-reference.md`'s `refdes release` sample now lists all eleven
  `release_gate:` rules in the order the command prints them (it was missing
  `unaccepted_workspace_moves`, `open_tasks`, `captured_edits` and
  `inline_calc_results`); the text no longer implies `release_gate:` trims
  the printed list -- it always prints all eleven and the config decides
  which run -- and the success text no longer calls the design-log reminder
  a "one-line nudge" (it prints a starter entry).
- The same page's `--no-write` summary now names `navis archive` and
  `navis restore` among the commands that refuse to run, and the
  "files the tool writes" table has the `.refdes/navis/` archive store,
  naming both its CLI and `serve` API writers.
- `refdes check --refresh` is described as re-fetching pinned **remote**
  citations only; a local citation is re-hashed against its pin on every run.
- `refdes fetch` is no longer called the only writer of lockfile records
  (`refdes serve`'s editor accept writes them too), and `.refdes/copies/`
  is no longer said to be written only by `fetch --path` -- a plain
  `refdes fetch` writes kept copies as well.
- `refdes keys restore` refuses a **current** key recorded in history, not a
  replacement key, matching the command's own help.
- `refdes new` no longer promises a did-you-mean for every unknown type (it
  appears only when a real type is close), and `refdes former-ids propose`
  notes that a project with no candidates exits 0 rather than reporting a
  `--confirm` name as a refusal.
