- **The thread projection's three states it could not tell apart (living
  notes H7b review).** `branches[].verdict` now carries a `state` —
  `resolved` or `conflicting` — because a folded `status` that *refused*
  between differing equal-distance declarations used to render as the same
  null as "nothing on this branch ever declared a status"; the conflict is
  now its own explicit state, the way `tasks.state` already distinguishes
  `ambiguous` from `undeclared` (the field fold grew
  `chains.fold_field_at_tip` to report it — the same recording
  `fold_tasks` uses, and `fold_at_tip` is now a thin wrapper over it, so
  the equivalence test against `resolve_current_with_source` still pins the
  walk). A declared-but-entirely-malformed task list now stays
  `tasks.state: "declared"` with a `malformed` count instead of reporting
  the author's empty `cleared` list. Each thread view also gained
  `captured`: the members the history store holds a live capture for, with
  the event's kind and its `occurred_at` when one exists (a
  `followed` or `followed-corrected` edge deliberately carries none), so
  H7b's capture line reads it instead of opening the store itself. And the docstring's "oldest-root first" claim
  about the thread list became what the code actually does: threads are
  ordered by their root's label.
