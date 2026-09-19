- `{{tree}}` block with `board=`, `workspace=` and `depth=` parameters,
  rendering the containment forest in any page. `via=` is deliberately
  not a tree parameter -- nesting by an arbitrary relation is
  `{{cascade}}`'s job -- so it surfaces as an unknown-parameter check
  error.
- Scoped tree pages: `tree-<board>.html` and `tree-<workspace>.html` join
  the scoped report set and the sidebar. A board's tree shows every item
  it displays, including `includes:` members under a node marked
  "shared, via GRP-..."; a scope with nothing in it gets no page. The
  once-expanded invariant now holds per scope.
- On a scoped tree page the board node's count tallies only what the
  board owns, shared members counted apart ("1 own, 2 shared") -- a
  board's numbers count only what it owns (finding 33). Group nodes and
  the project-wide tree keep their counts as they are.
