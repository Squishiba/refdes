- The VS Code extension's **Refdes Navis** view is complete: Archive and
  Restore on the row menu (no body bytes — an archive is one gzip record
  under `.refdes/navis/`), project-wide **Mint keys** behind one
  confirmation (clean editors of the keyed files reload; dirty buffers get
  the editor's own prompt), a **Refresh Navis** command, a `Mint keys (N)`
  row above the list, an inline **Open Navi in editor** deep link, and a
  read-only indicator that survives index refreshes.
- A `refdes --no-write serve` lists Navis and locks the write actions for
  the rest of the session, exactly as the browser panels do. The extension's
  version goes to 0.2.0 for this feature set.
