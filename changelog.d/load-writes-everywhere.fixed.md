- Every command that loads a project writable now says what that load wrote,
  not just `refdes id` and `refdes stub-tests`. `check`, `ls`, `index`,
  `audit`, `build`, `revision`/`release`, `fetch`, `former-ids propose` and the
  three `history` commands all minted surrogate `key:` fields and rewrote bare
  link targets into `DISPLAY-ID@key` composites on the way in
  (docs/design/keys.md §2) while reporting a clean no-op. Such a run now leads
  with `(minted 2 key(s) and rewrote 1 reference(s) while loading)` — on stderr
  for `index`, whose stdout is JSON for the editor. `check --help` no longer
  claims the command writes nothing "with one exception": it writes nothing of
  the project's own, and says plainly that loading writes keys, composites and
  `.refdes/schema.json`. Steady-state runs, and every `--no-write`/`--dry-run`
  run, print exactly what they printed before.
- A read-only tree no longer crashes the load. `refdes check` over a checkout
  it cannot write died with a `PermissionError` traceback — from the
  `.refdes/schema.json` refresh or from the key-mint write-back — before it had
  checked anything. Both sites now warn (`could not write this file (read-only
  tree?); run with --no-write to silence this`) and carry on, so a `check` that
  cannot write reports what `--no-write check` reports. A key whose write was
  refused is not applied for the run either, so nothing later in the load can
  freeze a composite naming a key that never reached disk. Commands that print
  no diagnostics of their own name the refused files in their own summary line.
  Writes you asked for — `revise apply`, `calc-rewrite`, `keys adopt`,
  `keys restore` — still fail loudly when the tree refuses them.
