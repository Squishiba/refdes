- **`hardware@3`'s `component.status` gains `rejected`, and
  `component.check_severity` becomes status-dependent.** The component enum is
  now `[candidate, selected, rejected, obsolete]` — a part this design
  considered and did not choose is recorded as `rejected`, deliberately not
  `obsolete` (that keeps meaning "the part is no longer usable going forward"),
  and a `rejected` part never satisfies coverage. `component.check_severity`
  ships as a mapping keyed by status —
  `{ candidate: info, selected: error, rejected: info, obsolete: info }` — so a
  rejected part failing a criterion is recorded as the reason it was rejected
  (info, not a build error) while a selected part failing one stays an error.
  Projects that want the old behaviour write `check_severity: error` in their
  overlay. (The bundled `hardware@3` is itself unreleased — projects pinned at
  `v1` or `v2` see none of this.)