# PERF-1: shorten the test suite wall time

## Measurement (Step 1)

Baseline, two runs, `-n 4 --dist worksteal`, `--durations`, tee'd to
`.scratch/perf1/baseline_r1.txt` / `baseline_r2.txt`:
208.44 s / 211.51 s wall; `5938 passed, 2 skipped` each;
`5940 tests collected` (bash-verified via `--collect-only`).

Box is shared (load 8.9-10.6 baseline, 15-17 during the after runs; other
agents running GPU work). PTY output crossed buffers between sessions once,
so every number here comes from a tee'd file, not a pane.

Per-file aggregates from a `--durations=0` run (`baseline_dur0.txt`, 708 s of
timed work): `test_editor_format_bar.py` 77 s (4 tests — one test is 73 s),
`test_serve_*` files 343 s aggregate (~0.2-0.4 s/test), `test_docs_context*`
66 s. The 73 s sweep is the suite's critical path.

## Clusters and fixes (Step 2)

1. **The exhaustive sweep test (73 s)** —
   `test_the_format_bar_survives_the_exhaustive_marker_selection_sweep` runs
   ~45M cases (all strings ≤6 code points over 7 chars × all selection
   pairs × 11 formatbar ops) in ONE node process, comparing the real
   `formatbar.js` OPS against an independent JS model. It is pure JS over a
   generated string list (OPS mutate only the Area stub), so it shards: the
   harness takes `[shardIndex, shardCount]` in argv, and
   `_node_json_shards` runs 4 node processes at once. The Python test's
   assertions are unchanged (`bad == []`, `cases == expectedCases`); the
   combiner sums the cases/expectedCases, concatenates bads in shard order,
   and requires the `[from, to)` ranges to tile `[0, n)` — a missing shard
   fails. File serial wall 89.06 s → 22.66 s; sweep call 73.19 s → 21.29 s
   alone, → 27.77 s in the loaded `-n 4` run (shards contend with the other
   workers). Total CPU is unchanged (~77 s) — this is a critical-path fix,
   not a work-elimination one. Shard count 4 mirrors `-n 4`.

2. **`EditorApp.stop()`'s 200 ms accept-loop tax** — `start()` (the
   background-thread entry tests and embedders use) ran
   `serve_forever(poll_interval=0.2)`, so `shutdown()` blocked up to 200 ms
   per fixture teardown; ~1500 serve tests pay it. Lowered to 0.01 **in
   `start()` only**; the foreground `serve_forever()` — the path
   `cli.py:699` runs for every real `refdes serve` — stays at 0.2 (100
   selector wakeups/second forever is a real user cost; review round 1
   caught my initial change of both). Direct cycle with only `start()`
   changed: 387 ms -> 215 ms. In-suite the gain is ~6 ms/test because
   HTTP traffic wakes the loop before the teardown does — measured, not
   assumed (serial before/after on `test_serve_pdf_sources.py` with the
   original source shadowed to `.scratch/perf1/src_orig`: 18.9/18.8 s vs
   17.6/17.8 s, small). Kept as a strict improvement.

Clusters examined and deliberately NOT touched:
- `test_serve_*` fixtures (~380 ms/test): the cost is the real
  `ProjectState.load` parse (~190 ms) + `EditorApp` per test. Tests mutate
  the project (upload/edit/apply), so widening to module scope would leak
  state across tests and break order-independence — rule 5. The parse is the
  product; not attackable from the test side.
- `test_docs_context*`: fixtures already module-scoped; per-test cost is
  real work (server builds, CLI smoke runs).
- `test_serve_cli` / navis subprocess tests: stay subprocess (rule 4); no
  shared setup found to widen.
- `test_crossplatform_lint.py`: forbidden.
- `test_editor_empty_link_target_types.served`: test 2 mutates the project
  a later test reads — module scope would break random-order runs.

## Full-suite runs (Step 3)

- Baseline: 208.44 s, 211.51 s (median 209.98), load ~9-11,
  `5938 passed, 2 skipped`.
- After: 163.10 s, 169.29 s (median 166.2), load 15.3-17.2,
  `5938 passed, 2 skipped` — identical counts, ~21% wall improvement under
  roughly 2× the external load. Durations are the load-stable measure: the
  sweep's 73 → ~28 s call is the critical-path win.

## Negative controls (rule 7)

- Sweep, serial equivalence: `_node_json_shards(..., shards=1)` reports
  `cases == expectedCases` and `bad == []` with cases = 50,890,818 — the
  runner's 1-shard path reproduces the serial sweep.
- Sweep, fault detection: injecting a wrong `hr` expectation into the model
  (scratch copy of the harness) → the 4-shard run reports 4 bad entries
  (one per shard, shard order preserved), first problem
  `block result not expected` — the assertions fire.
- Sweep, tiling: a gapped shard-report list fails the
  `[from, to)` tiling check (dropped shard cannot silently shrink
  coverage).

## Notes / risks

- Shards use 4 extra node processes only during the sweep test (~20 s);
  on a 2-core CI box `SWEEP_SHARDS=4` oversubscribes mildly — serial is
  73 s there, sharded ~37 s. Acceptable.
- ruff: 1 pre-existing UP012 in server.py (untouched line), per AGENTS.md
  baseline is not clean.
