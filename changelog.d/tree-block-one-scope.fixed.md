- `{{tree}}` now reports a build error when given both `board=` and
  `workspace=`: the pair silently intersected the two scopes, rendering a
  set no scoped report page has. `docs/blocks.md` always said "at most one
  of the two" — the block now enforces it. Give one, or give neither.
