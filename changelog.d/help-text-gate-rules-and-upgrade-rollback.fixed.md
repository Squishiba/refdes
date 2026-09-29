- `refdes release --help` now names the eight `release_gate:` rules it runs
  (draft_items, unpinned_citations, missing_kept_copies,
  uncovered_requirements, unverified_requirements, info_check_failures,
  unaccepted_board_moves, unaccepted_workspace_moves) instead of mentioning
  `release_gate:` only in passing. The rules have been documented in
  `docs/lifecycle.md` since they shipped and a typo in a rule name already
  gets the full list back in the load error, but the help for the command
  could not answer "what is it going to check?" without sending you to the
  docs. Names cross-checked against `lifecycle.RULE_NAMES`; behavior
  unchanged.
- `refdes standard upgrade --help` no longer implies the whole multi-step
  invocation is atomic. It said the command "refuses (rolling back cleanly)",
  which read as all-or-nothing; what is actually true, and what
  `docs/cli-reference.md` has always said, is that only the failing step
  rolls back and earlier steps in the chain stay applied — so the project
  is left fully valid at whatever version it reached. The help now says so
  directly. Verified on a project pinned at `hardware@1`: `standard upgrade
  --to 9` applied v1→v2, refused v2→v3 on a `text:`→`body:` merge conflict,
  exited 1, and left `standard.version: 2` with the v1→v2 rewrites
  (`constraint`→`bound`, `CON-`→`BND-`, `title:`→`text:`) still on disk and
  the project checking clean.
