# W5b.5 test-author slice — capture at the continue save

Slice: tests only. No `src/` change is committed here. This is the red-first
contract test for W5b.5 (docs/design/thread-workbench-w5b-plan.md §W5b.5), to
be made green by the implementation slice.

## What is pinned (tests/test_continue_capture.py)

`continue_thread`/HTTP continue saves the continuation entry AND the predecessor
`followed` capture event (history.capture_followed) in one locked operation.
The plan's acceptance line (§:351-353): "one save writes entry + event or
neither, and the announcement line prints exactly once".

Tests:
- core: one save writes the `followed` event holding the predecessor snapshot;
  Applied carries the announcement; the JSON body gains an `announcements` list.
- idempotence: a second writable load re-captures the save's edge nothing,
  announces the save's edge nothing.
- transaction "no": capture failure (HistoryError and OSError) rolls the entry
  back, reserves no id, announces nothing, Refused (plain reason, no event).
  Stale revision = Conflict; --no-write = Refused; sealed tip = Refused;
  keyless tip = Refused; id-less tip = Refused. None capture, none announce.
- growth: two saves add a second event, first untouched.
- concurrency: two saves racing land exactly one event for the winning edge.
- edge cases: CRLF thread file (object line-ending independent); non-ASCII
  project path.

## Contract assumptions the implementer must satisfy (conservative)

1. `Applied.announcements` — tuple of capture announcement strings, in
   capture order. Empty for a no-op (edge already captured).
2. `Conflict`, `Refused`, `Invalid` gain `announcements: tuple = ()` (always
   empty), so "announces nothing" is a positive, testable assertion.
3. The continue endpoint's Applied JSON gains an `announcements` list mirroring
   `result.announcements`. Existing JSON keys are ADDITIVE (path/revision/id/
   describe/handle/pinned/diagnostics stay).
4. Announcement text is exactly history.capture_followed's:
   `captured LOG-SYS-002: LOG-SYS-003 now follows it`.
5. Capture runs in the save's write lock, AFTER the entry is atomically written
   and the id reserved. On capture failure the entry rolls back and the id is
   un-reserved (file restored, ledger unchanged, no event file) — same shape as
   the existing journal/id-ledger OSError rollback in _continue_locked.

## Red evidence (unmodified src, head = 9f15af87 on main)

`tests/test_continue_capture.py` — 15 failed. Each fails on the new-behaviour
assertion, not a collection/import error:
- core capture tests: `0 == 1` events (save writes none today).
- Applied/Conflict/Refused `.announcements`: AttributeError (no field today).
- HTTP JSON `announcements`: KeyError (key absent today).
- atomicity (both params): `capture failure must roll back, got Applied(...)`
  — today the save succeeds (no capture step to fail).
- concurrency / CRLF / non-ASCII: `0 == 1` events.

## Green proof (throwaway src patch, reverted)

A minimal W5b.5 patch (capture in _continue_locked after reserve,
`announcements` on the four result dataclasses, `announcements` list in the
continue JSON) makes all 15 green, with the existing
tests/test_serve_continue.py, tests/test_serve_continue_http.py,
tests/test_history_capture.py, tests/test_thread_cli.py unchanged and green.
The patch is NOT committed; it only proves the contract is satisfiable and that
the tests do not over-constrain the implementation.

Ordering note: the green proof runs capture before the id reservation is
committed to disk, so a capture failure needs no id "un-reserve" (there is no
unreserve in ids.py) — the entry rolls back and the ledger is never written.
The implementer is free to reserve-then-unreserve; the tests pin only the end
state (no reserved id, no event, entry bytes restored).

## Two assertions I had to loosen, and why (honesty notes)

- Idempotence: the fixture's pre-existing LOG-SYS-001 -> LOG-SYS-002 edge is
  un-captured; the second writable load legitimately captures+announces IT. So
  the test pins that the SAVE's edge (successor key LOG-SYS-003) is not
  re-captured and not re-announced, not that the whole load is silent.
- The atomicity test reads `.refdes/ids.yaml` via a helper that tolerates a
  missing ledger (mint_keys does not create it; the first reservation does), so
  the red is "expected Refused, got Applied", not a setup crash.

## Checks run
- new file red: 15 failed.
- `ruff check tests/test_continue_capture.py`: clean.
- `tests/test_crossplatform_lint.py`: 26 passed (new file satisfies the rules).
- full suite once: see the final report (only the 15 new reds; nothing existing
  breaks).
