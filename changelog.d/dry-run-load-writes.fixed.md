- `refdes id --dry-run` and `refdes stub-tests --dry-run` reported that they
  would write nothing while the *load* on the way in still wrote: loading mints
  every missing surrogate `key:` and expands bare link references into
  `DISPLAY-ID@key` composites, so a dry run answered "would allocate 1 id(s)"
  over an item file it had already edited. A dry run is `--no-write` for the
  whole run, not just for the work the command reports on, so `_load` now folds
  `--dry-run` into the same `write=False` `--no-write` uses — the exact path
  `--no-write` was already tested through, since both commands force `dry_run`
  from it. Every source file is now left byte-identical by a dry run.
