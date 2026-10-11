- **`refdes thread`'s derived block is grouped and re-ordered (living
  notes H7c, owner decisions 2026-10-11).** The rows of the
  `Derived (auto clears when fixed)` block now print under one small
  heading per kind that has rows (`Coverage:`, `Blocked:`,
  `Failing checks:`, `Citations:` — verdict/fork kinds cannot appear in a
  per-thread block), and a row's kind column is gone: the heading names
  the kind, the row is just `ref  detail`. The kind order is the one
  order `refdes work` uses — coverage, verdict, blocked, check, citation,
  fork, kept in a single shared constant — which for this command visibly
  means `Blocked:` now prints **before** `Failing checks:`. A kind with
  no rows prints no heading; a wholly empty block still prints `(none)`.
  `--json` and the `index` payload keep their exact **shape** — grouping
  and the ref-only rendering are presentation, not structure — but their
  derived arrays follow the one shared **order**: e.g. `blocked` rows now
  precede `check` rows where the pre-H7c listing had them the other way
  round (`refdes thread --json` and `index`'s `threads[].derived` both
  carry it; pinned by a test).
