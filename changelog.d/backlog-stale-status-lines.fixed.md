- Nine `Status:` lines in `docs/design/backlog.md` said work that has since
  shipped had not started, and the file's header pinned itself to a commit
  220 merges back. Corrected against the tree, each with its evidence: the
  browser editor (`src/refdes/serve/` ships, and `refdes serve` is
  registered); the thread model (`threads.md` is at "Phase 3a implemented",
  with `chains.py` landed); CSV source values (`sources.py` is a reader, and
  the `calc-sources.md` design is Reviewed — xlsx remains outstanding);
  board `includes:` (`boards.py` resolves it, with display and count kept
  deliberately separate); the CLI enumeration (which was short `serve`,
  `keys`, `calc-rewrite` and `history`); theming (`theme.py` and
  `contrast.py` shipped, in the three steps the finding ordered); the
  hand-drawn link diagram, which was deleted rather than fixed, leaving the
  generated vocabulary page; and GitHub Pages, which is live and green —
  `has_pages: true`, `"status": "built"`. Two further errors corrected while
  verifying: the theming entry's stylesheet survey described the
  pre-theming `style.css` in the present tense, and a `docs/links.md` line
  pointer had drifted.
- `docs/design/calc-sources.md` wrote its headline example in the retired
  `eff : 1 = source(...)` spelling, which the colon-unit retirement makes a
  build error — the design doc's own example would have failed its own build.
  Rewritten to the current pipe-unit form, matching what the rest of the
  document and `docs/math.md` already use.
