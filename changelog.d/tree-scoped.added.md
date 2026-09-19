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
