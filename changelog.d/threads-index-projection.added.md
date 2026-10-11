- **The thread-view projection, and a `threads` key in `items.json` (living
  notes H7a).** `refdes.threads.threads_projection()` is the one per-thread
  worklist every surface reads instead of reconstructing the chain: one entry
  per `follows:` thread, and for an unmerged fork one branch per open tip —
  each branch carries its own `tasks:` list (the `chains.fold_tasks` fold
  verbatim, keeping `declared` / `cleared` / `undeclared` / `ambiguous`
  distinct) and its own branch-local folded `status` with the
  `satisfying_statuses:` question answered beside it, so nothing in the
  payload can read as a single current status a fork never has. Every open
  task carries `open_since`: the entry that declared it and *that* entry's
  authored date, absolute — the module reads no clock, so the same project
  produces the same bytes at any time on any machine. The thread's `derived`
  rows (uncovered/unverified coverage, failing checks, `blocked_by:` chains,
  unpinned or cache-missing citations) are computed from what already blocks
  a release, carry no task id, and self-close when the gap is fixed.
  `items_json()` gains the `threads` key only when the project has threads at
  all, so a project with no `follows:` anywhere keeps a byte-identical
  payload; nothing here writes. The `refdes thread` and `refdes work`
  commands are later chunks.
