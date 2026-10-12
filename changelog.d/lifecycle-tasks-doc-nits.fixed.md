- Docs: three corrections in the lifecycle/design-log pages, no behaviour
  change. `docs/lifecycle.md` cited `open_tasks` and `captured_edits` as one
  and the same living-notes rule (§5 rule 5); §5's binding rule 5 is
  `open_tasks` only, and `captured_edits` is §3's allow-and-detect decision
  (§9 decision 2) — each now cites its own source. The same page says what
  the release gate does for real: ticking a task on a captured entry is an
  edit that trips `captured_edits` (task rows are part of the fields the
  history digest covers). `docs/design-log.md` documented every task row as
  carrying a stable `id`; in fact a row may omit `id` or leave it empty —
  validation accepts it — and the `open_tasks` gate names such an open row
  by its position in the list (`#1`). Nothing to do.
