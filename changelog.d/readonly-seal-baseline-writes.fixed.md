- `refdes build`, `refdes revision` and `refdes release` no longer die with a
  Python traceback when the checkout is read-only — a frozen CI tree, a
  read-only bind mount. Each write they make is now reported in the terms of
  what that write was for, and no command prints a traceback because a
  destination isn't writable.

  `build` still runs every check and still renders the site; a seal file or
  membership manifest it could not write becomes an error naming the file and
  saying the entries are not sealed, and the run exits `1` rather than
  reporting a clean build over entries it did not protect. (`.refdes/boards.yaml`
  is included — same write, same call, same command.) If the site's own output
  directory is what will not take the write, `build` refuses instead, naming the
  directory, and exits `2`: there is no partial site worth printing.

  `revision` and `release` exist to write one file, so a refused baseline is a
  refusal rather than a degraded success — exit `2`, `.refdes/baselines/<name>.yaml`
  named, and never a line reading "stamped". Nothing partial is left behind, so
  re-running against a writable tree stamps for real.

  `refdes audit` and `refdes former-ids propose` also stopped crashing when a
  baseline needed its stored-hash format rewritten; that rewrite is now named
  and the comparison it feeds is unaffected.

  `refdes history capture`, `redact` and `migrate-seals` no longer traceback
  either — they refuse with the store file named, which is the same refusal
  they already gave under `--no-write` arriving from the other direction.

  `refdes revise`, `calc-rewrite` and `standard upgrade` refuse too, naming the
  file, exiting `1`, and rolling the whole operation back. The seal hash or
  baseline entry they carry forward is the only record that a rename was not an
  edit to a sealed entry or a stamped baseline — so a rewrite that could not
  record it must not be left standing, reporting a carry-forward that never
  happened.

  All of it says the same thing in the same words as the load-time warning that
  was already there (`could not write this file (read-only tree?); run with
  --no-write to silence this`), so one filter catches every case.
  `--no-write` is unaffected: it never attempts the write, so it behaves the
  same whether or not the tree would have taken it.

  `keys adopt` and `keys restore` still raise on a read-only tree, which is the
  long-standing contract: the tolerance belongs to writes nobody asked for.
