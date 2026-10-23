- The editor's write route saves a keyless item through the handle its own
  list hands out. In a project where surrogate keys were never minted (a
  fresh `refdes init` plus `refdes serve`, which writes nothing), the
  `/api/items` rows carry the provisional `~<relpath>:<line>` dict key as
  the row `handle`, `GET /api/item/<handle>` resolves it, and the browser
  editor posts exactly that spelling -- but `POST /api/item/<handle>/edit`
  resolved the item at the model and then handed the raw `~`-handle to
  `patcher.plan_patch`, whose aliases are the file's `id:`/`key:` values, so
  EVERY editor save in a keyless project answered 422 `refused: no item
  '~items/reqs.yaml:4' in this file (it holds: REQ-001)` (user-sim run 13;
  the third spelling of EDIT-01 #355 and EDIT-03 #358 -- item identity has
  spellings, and the patch boundary had only two of them). The write route
  now plans the save against the spelling the file carries -- the surrogate
  key when the item has one, else the display id -- in both item shapes
  (YAML list and Markdown front matter). The handle's relpath:line is
  validated, not dropped: the resolver accepts a provisional handle only by
  exact dict-key hit against the tree loaded from disk under the write lock,
  so a stale line (the file changed and the item moved) and a hand-made
  handle naming no item's definition both resolve to nothing and keep the
  ordinary "no item" refusal, patching nothing -- the route never guesses a
  target from a dead line number. A conflict under the keyless handle keeps
  its diff: the conflict screen plans the draft against the file spelling,
  as it already does for a retired id. Display-id and surrogate-key saves
  are unchanged, and so is how handles are minted and listed; the patcher's
  ref contract (a display id or key, matched against the parsed `id:`/`key:`
  values) is unchanged.
