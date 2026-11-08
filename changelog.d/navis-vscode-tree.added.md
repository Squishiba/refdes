- The VS Code extension now lists the project's Navis as a read-only
  **Refdes Navis** tree in the Explorer: active rows labelled `key6 · text`
  (the full text in the tooltip), archived rows behind a "Show all" group,
  a keyless row labelled with the Mint hint, and the active count in the
  view badge. Clicking a row opens the marker's file at its line. The rows
  are read from `GET /api/navis` on the window's `refdes serve`, which the
  view boots lazily when you expand it; the list refreshes on save, on
  **Refdes: Refresh index**, and on every snapshot-serial move. The view is
  a list only for now — Archive, Restore and Mint commands come next.
