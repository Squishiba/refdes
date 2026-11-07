# perf-measured-spots (slice PERF-2)

Branch `perf/measured-spots`, base `b9eba32d`. Goal: measure three slow spots,
ship only what measures clearly. Box: 20 cores, load average ~10-12 during
all runs (busy shared machine; numbers are relative, no hyperfine).

## SPOT A — docs-context cold doc load — SHIPPED

`refdes_docs_context` served `/api/doc` serially: one `--help` subprocess per
command card, ~22 cards per doc. Baseline (5 cold runs of `docs/navis.md`,
port 8870, server restarted per run): median 4.86 s, min 4.53 s. Payload:
22 known cards, 6 distinct verb paths.

Change (`tools/docs_context/refs.py`): `analyze()` now prefetches the
*distinct* known command refs through a 4-worker `ThreadPoolExecutor` before
the serial resolve loop. Gates (metachar, unknown verb) stay serial; prefetch
skips entirely when there is no `src/refdes/cli.py` signature (repo fixtures);
only successful runs are cached. Same cache key, same timeout, no shell.

After (same method, port 8871): median 2.36 s, min 2.15 s — ~2.1x. Payload
byte-identical (`data["blocks"] == old["blocks"]` True). Red-first: 2 new
tests failed before the change; 144 docs-context tests pass after. Committed
as `perf(docs-context): prefetch a doc's distinct --help cards concurrently`
(264 insertions, under the 350-line src cap — tool code only, no src/). No
changelog fragment: the viewer is unshipped.

## SPOT B — CLI startup — MEASURED, NO CHANGE

10-run wall baseline `refdes --version`: median 725 ms, min 588 ms (bare
interpreter 13 ms). importtime: max cumulative 619.6 ms, 443 imports. Top
self: `refdes.calc` 155 ms (pulls pint, 91 ms, registry at import),
`refdes.build` 27 ms, `refdes.cli` 25 ms.

Lazy-import experiments: moving `Equation` in `model.py` behind
`TYPE_CHECKING` changed nothing (median 730 ms) — `calc` has five importers
(`model`, `schema`, `build`, `calc_rewrite`, `citations`/`inline_calc` fan in
via `cli.py`'s top-level imports), so no single lazy import reaches the >=80 ms
bar. A two-file experiment (model+schema) moved the median 725→713 ms, inside
noise. Reverted; no code change. A real fix means deferring `cli.py`'s own
heavy imports per subcommand — too big for this slice.

## SPOT C — serve editor save — MEASURED ONLY

Real route is `POST /api/item/<ref>/edit` (`src/refdes/serve/api.py:54`), not
`/api/items/<id>/edit-style`. Throwaway projects via
`.scratch/perf2/gen_project.py`; 5 saves per size through HTTP (port 8872):

| items | median save |
|------:|------------:|
|    50 |      250 ms |
|   100 |      365 ms |
|   200 |      631 ms |
|   400 |     1396 ms |

~3.3 ms/item + ~85 ms fixed: O(project) confirmed. cProfile of the route
(200 items, in-process `api.handle`): of ~1.41 s/save (profiler overhead
included), `state.refresh`→`_build` is 1.09 s, of which
`preview.render`→`render_site` is 0.88 s — the whole site is re-rendered, and
`render_site` builds a fresh Jinja `Environment` per call (`render.py:1267`),
recompiling ~12 templates every save (~0.33 s); `loader.load_readonly` 0.39 s,
`build.build` 0.21 s. The actual edit work (`edit.apply_edit`) is only 0.32 s.

Recommendation (not implemented — out of slice scope): (1) cache the Jinja
Environment across `render_site` calls; (2) re-render only pages whose source
hash changed instead of all pages. Both are preview-internal; no API/behavior
change.

## Status

- SPOT A shipped (one commit on the branch).
- SPOT B, SPOT C: measurements only; recommendations above.
- Full suite run once before push; `ruff check` on touched files shows only
  the 7 findings pre-existing on main in the same files.
- Scratch: `.scratch/perf2/` (measure scripts, navis before/after snapshots,
  importtime traces, probe projects).
