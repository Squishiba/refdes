- The citation severity table in `docs/markdown.md` no longer implies a
  `check --require-citations` flag that does not exist. Its intro said
  verification was "checked at every `build` and `check`" and four of its six
  rows ended with a bare "(error with `--require-citations`)", so a reader
  tightening citation policy for CI or pre-commit would reach for it on
  `check` -- the command the docs recommend for both -- and get
  `refdes: error: unrecognized arguments: --require-citations` (exit 2). The
  diagnostics themselves were always reported at both commands; only the
  promotion to a hard error is `build`-only, since
  `refdes build --require-citations` is the sole caller of
  `citations.verify(require=...)`. Each affected row now names the command
  (`refdes build --require-citations`), and the intro says plainly that only
  `build` can escalate, so the soft rows stay warnings at `check`. The two
  `**error, always**` rows fail either command and are unchanged.
