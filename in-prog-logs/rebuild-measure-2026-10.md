# docs(perf): re-measure check/build/serve-rebuild time at 25-1500 items

Report-only task: fresh numbers for the open question in
docs/design/browser-editor.md ("Re-measure the rebuild. The 1.06-second
figure predates this revision..."). Deliverable is docs/performance.md;
no changes to src/.

## What was done

- Measured on this checkout's `src/` via
  `PYTHONPATH=$PWD/src /home/jorb/work/venv-refdes/bin/python -m refdes.cli`,
  fresh subprocess per run, 3 runs, median. Machine: i9-10900X (20 CPUs),
  Python 3.13.5, Linux. No `/usr/bin/time` (RSS via child `getrusage`).
- Real projects measured as copies under `.scratch/perf/` so key minting and
  site writes never touched the worktree: `real/` (repo root project, 20
  items, exits 1 with its one deliberate failing check) and `ds/` (docs-site,
  52 pages, 0 items).
- Synthetic projects `p25/p100/p400/p1500` from `.scratch/perf/gen.py`:
  mixed hardware@3 types (requirement/bound/test/component/group/log),
  links between them, calc blocks with `checks:` in every tenth component,
  inline `:=` spans in log bodies, one generated PNG figure referenced in
  every eleventh log entry. All pass `check` (warnings only).
- CLI timings: `check`, `build`, `ls` per project (bench.py). Floor measured
  on a bare `init` project: ~0.42 s.
- Serve rebuild: serve_bench.py starts
  `serve --no-open --port 87xx --token-file <f>`, records the PID, kills that
  PID with SIGTERM at the end (no pkill), drives
  `POST /api/item/<ref>/edit` with the launch token (POST also needs the
  `Origin` header and the session cookie from the launch URL -- the 403/405s
  found on the way are documented in the page), and verifies the new text in
  `/preview/<slug>.html` after each POST. The handler's `state.refresh()`
  rebuilds model + preview before answering, so POST wall time is
  time-until-preview-reflects.
- Serve startup timed separately (up.py): launch URL first served.
- Profiles: cProfile of `build` and `check` at N=1500; `python -X importtime`
  for the import floor (367 ms self; refdes.calc 144 ms).

## Findings (all in docs/performance.md)

- rebuild: 0.23 s @20 items (the 1.06 s figure's project), 0.42 @100,
  2.0 @400, 19.1 @1500.
- build: 0.59/0.78/2.27/19.9 s at 25/100/400/1500; `build --dry-run
  --keep-going` the same.
- check/ls ~linear (~0.8 ms/item over a 0.42 s floor).
- Superlinearity is the per-page preview payload: 424 KB of a 428 KB page at
  1500 items; site 625 MB; `_unique_calc_anchors` regex pass is 15.6 s of the
  19.9 s build.

## Notes

- docs-site copy builds clean with the new page (0 errors; 4 pre-existing
  vocabulary.md citation warnings).
- Added nav entries: docs/index.md table row and docs-site
  `site.nav:`. Changelog fragment: perf-remeasure-report.added.md.
- Scripts/corpora left in `.scratch/perf/` (gitignored), listed in the page.
- Task finished.
