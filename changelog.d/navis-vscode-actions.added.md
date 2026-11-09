- The VS Code Navis view can now archive, restore and mint keys from its
  context menu and view title: Archive shows on keyed active rows, Restore
  on archived rows that have a key, Mint on keyless rows and as a
  view-title button (and
  Mint keys stays in the command palette, asking one modal confirmation
  first — it writes marker bytes into item files). A server started with
  `--no-write` locks the write actions for the rest of the session, exactly
  as the browser panels do; a new server clears the lock.
