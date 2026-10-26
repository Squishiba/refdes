- Four Status lines in `docs/design/` still described shipped work as
  not started, as recorded in section 3 of the 2026-10-26 backlog audit.
  Corrected against the tree, each with its evidence: `living-notes.md`
  moves decided -> implemented (the plan landed H1 `d84e123` .. H8 #193,
  `refdes thread` #191 / `refdes work` #194 in `cli.py`, `tasks:` in
  `v3/base.yaml`; optional H9 not landed); `vocabulary-review.md` §1.7's
  "(not implemented)" heading and "both documents are unshipped" premise
  are marked stale, with the shipped-name note that the plan's
  `recorded_edits` rule shipped as `captured_edits` (`model.py:123`);
  `item-search-hover.md` keeps the search proposed but stops claiming
  "no code written" about the VS Code adapter it builds on (Slice V−1
  `da2e44b`/#58 and Slice V0 `0f38619`/#66 landed, as its own §3.5
  already said); `seal-marker-identity.md` keeps the proposal unlanded
  (`history.py` has no `deleted:` namespace) but drops "history.py and
  its tests are untouched" — the file has commits #212/#271/#272/#323/#330
  since drafting and the display-id fallback §1 names is live code.
  Design content untouched; docs-site builds with 0 warnings.
