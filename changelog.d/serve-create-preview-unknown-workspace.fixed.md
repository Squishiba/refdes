- `GET /api/create/preview?workspace=<name>` now refuses a workspace the
  project's `workspaces:` registry does not register: `400` with
  `workspace: no such workspace 'nosuchws' in this project; known workspaces:
  product-a, product-b` -- the exact answer `GET /api/items?workspace=nosuchws`
  has always given, from the same check (`serve.filters.validate_facet`, made
  public for this one call site). It used to ignore the unknown name and
  answer `200` with the *unscoped* suggestion, so a direct API caller asking
  about a workspace that does not exist was pointed into some other
  workspace's file tree with nothing said about the scope it ignored (run-9
  finding R9-F3). The browser editor cannot send one -- its New Item form
  lists only registered workspaces -- so this is the scripted-caller path.
  Unchanged: a registered workspace (with and without `board`), an absent or
  empty `workspace`, every other preview parameter, and
  `refdes ls --workspace <unknown>`, which keeps printing `no items match`.
