# docs-context-cache-lock (DOCCACHE-lock slice, DC-4a review follow-up)

Task: the #433 review flagged (correctly) that `DocState._cache` in
`tools/docs_context/server.py` is read and mutated with no lock while the
server is a `ThreadingHTTPServer`, and DC-4a added a second concurrent
writer (`POST /api/focus` -> `block_at` -> `doc_payload`). Two threads at
the 32-key cap can both compute the same eviction key
(`self._cache.pop(next(iter(self._cache)))`), so the loser's `dict.pop`
raises KeyError; iterating the dict while another thread mutates it raises
RuntimeError the same way.

## What was done

- New `tests/test_docs_context_cache_lock.py`, red-first. Two tests:
  - `test_eviction_under_concurrent_writers_is_not_corrupted`: fills the
    cache to exactly `CACHE_MAX` (32 real pad docs), swaps in a
    `ProbedCache` dict subclass whose `pop` widens its window with a 10 ms
    sleep and raises `ConcurrentCacheMutation` the moment a second thread
    enters `pop`/`__setitem__` while one is active, then releases 64
    threads over 64 distinct cold paths at a barrier. On the unlocked code
    the second thread overlaps the sleep — deterministic red (61 of 64
    workers reported the overlap on the first run; 3/3 runs failed on
    main, ~0.25 s each).
  - `test_focus_and_doc_writers_hammer_the_same_key`: 12 threads hammer
    `doc_payload`/`block_at` on the served doc through the same probe and
    assert no raise and a well-formed cache. Passes on main (mutations on
    the same key are rare-overlap µs windows; it is an invariant/hammer
    test, not the red evidence).
- Fix in `server.py`: one `cache_lock` on `DocState`; in `doc_payload` the
  hit-check, the eviction and the store each run under it; `refs.analyze`
  stays OUTSIDE the lock (a rare duplicate analyze is accepted per the
  task; never a corrupt cache). No deadlock: no path takes `cache_lock`
  while holding `focus_lock` (and `block_at` runs before `accept_focus`
  takes `focus_lock`). `/api/ask` and `/api/focus` behaviour unchanged.
- Extended the UNRELEASED `changelog.d/docs-context-server.added.md`
  fragment (verified unreleased: the DC-4a focus paragraph it contains
  ships in no CHANGELOG.md release entry yet), saying so inline.

## Verification

- Red on main: `test_eviction_under_concurrent_writers_is_not_corrupted`
  failed 3/3 (61 workers with `ConcurrentCacheMutation: two threads in pop
  at once`), green 3/3 after the fix (~1.5 s — the probe's pop sleep now
  serializes under the lock, a few hundred ms total).
- `tests/test_docs_context_{server,focus,ask,refs}.py` +
  `tests/test_crossplatform_lint.py`: 201 passed.
- `ruff check` on the two touched files: clean.
- Full suite once before pushing: 6040 passed, 2 skipped (97 s,
  `-n 4 --dist worksteal`).

## Notes

- New tests call `DocState` directly (as the review finding is about the
  class); fixture repo and file-writing copied from
  `test_docs_context_server.make_repo` with `newline=""` throughout, per
  the cross-platform rules.
- Nothing outside the worktree touched; task complete.
