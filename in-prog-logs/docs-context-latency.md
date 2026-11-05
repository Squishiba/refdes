# DC-2b: memoize docs-context --help cards

Task: the docs-context viewer (DC-2, #425) took ~12 s per page edit because
every `/api/doc` re-resolve spawned a `python -c ... <verbs> --help`
subprocess per command ref (~20 on docs/navis.md); only the argparse
known-verb check (`_KNOWN_CACHE`) was memoized.

Done:
- `tools/docs_context/refs.py`: new `_HELP_CACHE` keyed by
  (realpath(repo_root), tuple(verbs), cli-signature) where the signature is
  (mtime_ns, size) of `<repo>/src/refdes/cli.py`; missing file -> signature
  None -> no caching at all. `_help_subprocess` now returns
  (help, ok) and only ok (returncode 0) outputs are cached, so timeouts and
  failures always re-spawn. Safety rules untouched: known verb paths only,
  list argv, no shell. `clear_caches()` empties both caches.
- `tests/test_docs_context_refs.py`: autouse fixture clears both caches
  before each test (the spawn-counting tests need it once the cache is
  process-wide); appended 5 tests: cached repeat (1 spawn, identical card),
  per-verb-path keys, invalidation on cli.py change, timeout/failure not
  cached, clear_caches(). All 5 shown RED before the refs.py change.
  Assertions of existing tests untouched. No change needed in
  test_docs_context_server.py: no test there counts spawns and the cache
  keys are per-test unique tmp repos.
- `changelog.d/docs-context-server.added.md` extended (fragment still
  unreleased there).

Measurements (real server, docs/navis.md copy under .scratch/, port 8820,
venv python, this box):
- cold first /api/doc: 4.21 s (orchestrator measured ~12 s on their box)
- after appending a paragraph with no command: 0.041 s (target < 2 s)
- unchanged repeat: 0.0015 s (DocState mtime cache, unchanged behavior)
- warm payload verified: new paragraph present, 21 known command cards all
  with populated help.

Browser (Chromium, puppeteer-core, own port 8820): 59 blocks rendered;
appended a marker paragraph -> visible in the page 1814 ms later (1.5 s
poll); command card pane shows the usage line after the refresh; no page
errors. Server stopped via the PID it was spawned with (socket owner pid
matched); /proc/<pid>/cwd was not readable in this sandbox, so identity was
proven by spawn-pid == listener-pid instead.

Tests: refs+server+crossplatform lint files 98 passed; full suite once
green; ruff clean on the touched code (test file carries 7 pre-existing
findings on untouched lines only; refs.py clean). Not shipped: maintainer
tool only.
