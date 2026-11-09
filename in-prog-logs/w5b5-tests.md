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

## Implementer round (W5b.5-impl) — shipped

Merged origin/main into the branch (plain merge, clean; main at #467).
Implemented in `src/refdes/serve/edit.py` + `src/refdes/serve/api.py` only,
exactly the pinned shapes: `history` module-imported (the test's monkeypatch
targets it); `announcements: tuple = ()` on Applied/Conflict/Refused/Invalid;
in `_continue_locked` the capture runs after the entry lands and the id is
reserved, with the ledger bytes snapshotted first (`_read_existing`) so a
capture failure rolls back entry AND ledger via `_rollback` (the ledger has no
unreserve; the snapshot restore is the un-reserve — the reserve-then-unreserve
option the log above explicitly allows), mirroring the id-ledger failure path
(journal clear, plain reason, recover hint on rollback failure). The
announcement is `capture_followed`'s own string, passed through — no second
wording. Changelog fragment added.

First full-suite run: 3 failed, 6300 passed — three pre-existing tests
conflicted with the contract, so the round STOPPED (no PR) and reported them:
`test_serve_continue.py::test_the_id_comes_from_the_destination_files_own_prefix_series`
and
`test_serve_continue_http.py::test_a_continuation_applies_with_the_new_entry_id_handle_and_revision`
(closed-set file-delta claims that predate W5b.5 and cannot survive the
capture's 1 event + 1 object under `.refdes/history/`), and
`test_serve_edit_response_paths.py::test_applied_response_shape_path_and_non_path_text_are_unchanged`
(closed-set claim on the applied JSON keys, which the shared `_apply_outcome`
would widen for every `/edit`).

Authorised round: (1)/(2) widened exactly as proposed — closed-set claim kept
over non-history paths, history delta pinned as exactly 1 event + 1 object,
with a why-comment naming W5b.5. (3) resolved WITHOUT touching
`test_serve_edit_response_paths.py`: `_apply_outcome` takes
`continuation=True` only from `/continue`, and the `announcements` key is
emitted only there — the plain `/edit` response stays byte-identical (the new
test file requires the key on the continue JSON only; a new key on every
`/edit` response is wider than W5b.5 asked).

Evidence: new file 15 red → 15 green; the three previously-conflicting tests +
`test_continue_capture.py` + the continue/history/response-paths files: 331
passed; `test_thread_cli.py` + `test_crossplatform_lint.py`: 55 passed; full
suite once: 6303 passed, 2 skipped. ruff on every touched file: only
pre-existing findings (DTZ011s; api.py's SIM114/UP037/UP032/FURB188 all predate
the change — import line wrapped by scoped `--fix I001`). pr_size: 72/350
src additions.
