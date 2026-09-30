- Speed up board and workspace membership drift checks on built projects. The
  verifier now indexes orphaned surrogate-keyed entries once per section while
  preserving their first-match order and the legacy display-id lookup. On a
  3,624-item synthetic project with a scalar membership manifest, `check` fell
  from 6.28s to 0.72s; coverage and membership diagnostics stayed unchanged.
