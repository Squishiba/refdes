- `GET /api/create/preview?workspace=<name>` now refuses a workspace the built
  project does not know: a name that is neither registered in the project's
  `workspaces:` registry nor the resolved workspace of any of its items --
  the exact set `GET /api/items?workspace=` has always accepted, checked by
  the same function (`serve.filters.validate_facet`, made public for this one
  call site) and answered with the same `400` and message: `workspace: no
  such workspace 'nosuchws' in this project; known workspaces: product-a,
  product-b`. (An item counts by its *resolved* workspace, which
  `workspaces.resolve()` only ever assigns from the registry, so on a built
  snapshot the accepted set is the registry's.) It used to ignore the unknown
  name and answer `200` with the *unscoped* suggestion, so a direct API
  caller asking about a workspace that does not exist was pointed into some
  other workspace's file tree with nothing said about the scope it ignored
  (run-9 finding R9-F3). The gate is on the scope itself, so an unknown
  workspace paired with an explicit `destination` is the same `400` -- that
  pairing used to answer `200`, the named file winning and the ignored scope
  going unmentioned. The browser editor cannot send an unknown name -- its
  New Item form lists only registered workspaces -- so this is the
  scripted-caller path. Unchanged: a known workspace (with and without
  `board`, with and without `destination`), an absent or empty `workspace`,
  every other preview parameter, and `refdes ls --workspace <unknown>`,
  which keeps printing `no items match`.
