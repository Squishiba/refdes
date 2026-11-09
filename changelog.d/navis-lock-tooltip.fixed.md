- The VS Code extension's read-only status line keeps its tooltip across
  index repaints: after a `refdes.navisRefreshIndex` (which repaints the
  status bar to the index's face), a lock set by a refused write used to
  come back with its text restored and its tooltip erased, so the
  sentence that names the `--no-write` refusal -- the one place a click
  on the lock explains itself -- was gone until the next refusal. The
  lock's tooltip is now remembered alongside the lock's text and
  re-applied with it, refreshed by each new refusal and cleared at every
  lock reset, which is the lifetime the plan asked for.
