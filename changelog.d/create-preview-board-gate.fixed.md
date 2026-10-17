- `GET /api/create/preview` no longer ignores an unregistered `board`
  (finding R11-F4 of the run-11 release-gate simulation, the parameter next
  to the one #326 fixed). `?workspace=` has been gated against the list
  route's facet rule since #326, and `board` kept its lenient reading:
  `?board=nosuchboard` answered 200 with a suggested destination nothing in
  the project pointed at (a new file at the workspace root the layout does
  not use), while `/api/items?board=nosuchboard` refused the same value
  400. The preview checks `board` with the same `validate_facet` call and
  the list route's exact message, alone and paired with a workspace. A
  registered board, an absent scope, an empty scope, and the
  board+workspace pair preview exactly as before.
