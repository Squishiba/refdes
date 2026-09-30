- The design-log entry `refdes release` suggests now uses ids that look like
  placeholders. It printed `  - id: LOG-...` (and `records: [DEC-...]`), which
  pastes as a truncated-but-plausible id: `LOG-...` is not a display id —
  `ids.ID_RE` requires a trailing `-<digits>` — so the copy-paste fails the
  shape check with a diagnostic about an id nobody meant to write, on the one
  line the message invites you to copy (user-sim release gate run 2, "Lower
  severity" list). It now prints
  `- id: LOG-A-0NN  # placeholder: your log prefix, next free number` and
  `records: [DEC-A-0NN]  # the decision(s) this release turned on`: still
  invalid as ids, unmistakably blanks, and marked in place — the same posture
  `refdes new` takes with `limit:  # required -- limit`. `LOG-A-0NN` is also
  what `docs/design-log.md` and `docs/design/lifecycle.md` already showed for
  this nudge, so the CLI and its own docs now agree; `docs/lifecycle.md` was
  still quoting `LOG-...` and has been updated to match. Verified by running
  `refdes release rel-a` against a project whose gates pass. Two tests hold the
  line: one asserts both suggested ids fail `ids.split_id` and carry a `#`
  marker, the other runs the release and compares the printed block, line for
  line, against all three doc pages that quote it (`tests/test_revise_cli.py`).
