# fix-ask-race (slice FIX-ASK-RACE)

Status: COMPLETE (code + tests + probe; full suite green; PR open).

## The race

`tools/docs_context/server.py` `_ask` (POST /api/ask) acquired `state.ask_lock`
then wrote the 200/502/504 response INSIDE the `try` (via `self._json`) and
released in the `finally` — i.e. the release ran AFTER the response bytes
reached the socket. A client that fires its next request the instant the
response arrives (the test's sequential `ask_json` loop; a double-click in the
page) is handled on a NEW connection thread, so it can reach `_ask` while the
first handler is between the write and the release -> `ask_lock.acquire(blocking
=False)` fails -> `409 busy`. Matches the CI flake:
`test_ask_uses_its_own_analysis_for_the_given_block_and_ref - assert 409 == 200`
(py3.11 job 127667550657 on PR #435, which does not touch the ask route).

Verified the cause by reading server.py:344-357 (the only lock in the file;
`grep` confirms `ask_lock` is the sole `threading.Lock`).

## (1) red tests (appended only; no existing test edited)

`tests/test_docs_context_ask.py`:
- `test_ask_lock_is_free_at_the_moment_the_response_is_written` — monkeypatches
  `DocsContextHandler._json` and records `state.ask_lock.locked()` AT the
  response write, and fires a second ask from inside that hook. RED pre-fix:
  `locked() is True ... second ask got 409`. GREEN post-fix.
- `test_ask_lock_is_free_at_the_moment_a_502_response_is_written` — same probe
  on the LlmError->502 branch (closed-port endpoint). RED pre-fix
  (`locked() is True; racing ask: 409`), GREEN post-fix.
- `test_ask_back_to_back_asks_never_see_busy` — 300 sequential asks, each on
  its own connection (the flaky test's shape), asserts all 200. GREEN post-fix.

Red shown by running the new tests against the un-patched code first (both
lock-state tests FAIL, 300-loop passes on the idle box).

## (2) fix

Compute `(status, payload)` inside the lock, `release()` in the `finally`, then
`self._json(status, payload)` AFTER the lock is free. 409-while-genuinely-
in-flight is preserved (the model call is the in-flight work and stays inside
the lock — `test_ask_answers_one_at_a_time` stays green, unedited). Every path
releases exactly once; a non-LlmError exception propagates with the lock
released (status/payload unbound -> the response write is never reached, same
as before).

## (3) other routes

No `/api/focus` route exists in server.py. `ask_lock` is the ONLY lock; no other
route acquires a lock around a response write, so the pattern does not apply
elsewhere. NOTE (pre-existing, out of scope, reported not fixed):
`DocState.doc_payload` mutates the shared `self._cache` dict with no lock; under
`ThreadingHTTPServer` concurrent asks each call it, and the
`len >= CACHE_MAX` -> `pop(next(iter()))` eviction is a TOCTOU (two evictors,
second `pop` KeyError). Unrelated to the ask_lock race.

## (4) stress

Committed test: 300 back-to-back asks (new connection each) all 200, post-fix.
Raw loop does NOT flake on this idle dev box pre-fix (window is a few
bytecodes) — reported honestly. Probe (`.scratch/fix-ask-race/probe.py`, not
in CI) widens the release window (post-response sleep) and runs the same loop
against old (git HEAD) vs fixed handler:
- OLD, widen=0.0: 300/200; OLD, widen=0.25: 2/200, 298/409 (race reproduced)
- FIXED, widen=0.0: 300/200; FIXED, widen=0.25: 300/200
So the loop shape DOES produce 409s under the old ordering; the fix removes
them.

## verification

- docs-context files (ask/refs/server) + test_crossplatform_lint: 153 passed.
- ruff check on tools/docs_context/server.py + tests/test_docs_context_ask.py:
  clean.
- full suite once: see PR (python -m pytest -n 4 --dist worksteal).
- cross-platform: tests add no file writes, no path-sep asserts.
