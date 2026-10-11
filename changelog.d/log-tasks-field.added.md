- **`tasks:` on the `log` type (living notes H6), and a new field type to
  declare it with.** A log entry may carry the thread's task list as
  `tasks:` rows — each a mapping with a stable `id`, the task's `text`, and
  its `state` of `open`, `done` or `dropped`. Task ids must be unique within
  a list and an unknown state is a build error naming the row and, when a
  known word was close, saying so. The list lives at the thread, not the
  entry: `chains.fold_tasks()` folds it under the living-notes §5 rules —
  the nearest own declaration wins (inherited `defaults:` do not declare),
  an omitted `tasks:` preserves the prior list, an explicit `tasks: []`
  clears it, a declared list replaces it whole, differing equally-near
  declarations are reported as ambiguous instead of one being picked, and an
  unmerged fork resolves to one labelled list per tip — never a union. The
  field is declared `on_change: log`, which is what makes a task *tick* a
  log event rather than a content change: it moves the semantic/history
  digest while leaving `content_hash`, seals, and baseline diffs untouched,
  so ticking a task never marks downstream items suspect. The two read
  commands (`refdes thread`, `refdes work`), the index projection, and the
  release-gate rules are later phases.
