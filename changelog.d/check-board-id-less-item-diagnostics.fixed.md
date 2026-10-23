- `refdes check --board NAME` showed a diagnostic of an id-less item — an
  item file with no `id:`, reported with the display id `[?]`, such as an
  `unknown field` warning — under *every* board: the display id matches no
  item, so the board filter skipped the diagnostic entirely, and board B's
  report was padded with board A's warnings. Those diagnostics are now
  attributed by the item's own file path, so `--board` shows only the
  id-less items on that board. An id-less item under a path that names no
  registered board — a stray `items/<unregistered>/` directory — is not
  attributable to any scope, and its diagnostics stay visible under every
  `--board`, like the project-level "item has no id" error (which carries
  no item id at all). `refdes check` without `--board` is unchanged.
