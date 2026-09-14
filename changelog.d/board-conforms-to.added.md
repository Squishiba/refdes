- **A board can declare `conforms_to: [GRP-…]`** — per-(item, board) coverage
  for cross-cutting contracts. A platform-wide requirement ("every board with an
  ARM MCU uses the standard 10-pin debug header") is a single item, so coverage
  reported it `satisfied` the moment *any one* board complied. Name a
  `hardware@3` `group` in a board's registry entry and every member of that
  group gets its coverage computed again for that board, counting only that
  board's own satisfiers — a satisfier with no board counts for no board, while
  still satisfying the item for the project as a whole. Every pair still short
  of `satisfied` is a warning naming the board; `coverage-<board>.html` gains a
  **Conforming contracts** table listing those members with their stage on that
  board even when the requirement lives elsewhere, and `coverage.html` marks the
  item with `not yet satisfied on boards: …`. A `conforms_to:` target that is
  not an existing group item is a **build error**, never a silently empty
  obligation set — the same posture as an unregistered `board:`. A project with
  no `conforms_to:` anywhere builds and renders exactly as before.
  (docs/design/backlog.md finding 24; see
  [multiple boards](../docs/multi-board.md#conforming-to-a-shared-contract).)
- **`conforms_to:` must be a list of group ids** — `conforms_to: GRP-001` was
  iterated character by character, so a missing pair of brackets surfaced as a
  "does not exist" error per letter. A non-list value, or a non-string element,
  is
  now one configuration error naming the board and the key. And the
  not-satisfied-on-board warning only appends its `— see
  coverage-<board>.html` pointer when that page will actually be rendered: a
  board with no items of its own gets no report pages, and its warning no
  longer points at one.
