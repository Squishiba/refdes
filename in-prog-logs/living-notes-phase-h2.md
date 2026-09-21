# Living notes — Phase H2: capture at the follows: edge, announced

Implemented 2026-09-19 on `ao/refdes-125/root`.

## What landed

- `history.capture_followed(root, predecessor, successor, *,
  current_predecessor_keys=None) -> FollowCapture` — the one function the
  capture call site adds to the H1 store. Returns the announcement line
  (`""` when the edge was already captured), the event path, and exactly
  which files it created, so the caller can undo its own writes.
- `links.freeze_follows()` — after `write_rewrites_verified` succeeds and
  the in-memory edges are updated, captures every freshly frozen edge via
  `_capture_followed_edges()` and prints announcements on stderr. Behind
  the same `write` flag, so `--no-write` (and every read-only path) writes
  nothing under `.refdes/history/`.
- Tests: `tests/test_history_capture.py` (10 cases), one new case in
  `tests/test_no_write.py` (gate + positive control), fixture gained a
  `follows` link type and a LOG-002 → LOG-001 edge.
- Changelog: `changelog.d/follows-capture.added.md`.

## Resolved ambiguities (decisions, flagged for the reviewer)

1. **`occurred_at` is deliberately not written on H2 capture events.**
   §2 calls it display metadata nobody may order or gate on; a wall-clock
   stamp would make one fact hash to different bytes in two checkouts and
   break the plan's "old-branch replay writes the identical path/bytes"
   case. The explicit `history capture` command (H4) is the author moment
   that can carry a clock.
2. **Announcements go to stderr, not stdout.** `index --compact`'s stdout
   must stay parse-clean JSON (Q4); stderr is visible in a terminal and is
   where the loader's other human output already goes.
3. **Transaction scope.** If an event write raises, `_capture_followed_edges`
   deletes the events/objects it created, `freeze_follows` restores the
   edge files (`revise.restore_rewrites`), reverts the in-memory links, and
   reports a project error. `revise._run_key_ensure` also calls
   `freeze_follows(write=True)` and so captures there too; if revise later
   rolls back its *other* ensure steps, an already-captured event stays —
   an orphan event for a rolled-back edge. Noted as an H2 limitation; H4/H5
   can revisit.
4. **Correction detection uses the successor's full current edge set**, so
   a merge (two live parents) never reads as a correction. Freeze semantics
   resolve a bare edge to the *current tip*, so two bare edges authored at
   once onto the same head freeze as a chain, not a fork — capture follows
   whatever edge the freeze actually wrote (tests assert this).

## Deliberately not touched

- Sealing behavior (H5): a sealed entry with a bare edge still just warns
  and captures nothing (test asserts no `.refdes/history/` appears).
- No CLI commands (H4), no `tasks:`, no schema changes.
