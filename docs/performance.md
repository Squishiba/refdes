# Performance

Measured numbers for `refdes check`, `refdes build`, `refdes ls`, and the
`refdes serve` post-save rebuild, at project sizes from a handful of items to
1500. This page answers the open question in
[the browser-editor design](design/browser-editor.md): the 1.06-second rebuild
figure there predates the current revision and described a project of two
dozen items — these are the fresh numbers, at several sizes.

## How this was measured

- Machine: Intel Core i9-10900X (20 CPUs), 78 GiB RAM, Linux, Python 3.13.5.
- Every CLI number is a **fresh subprocess** (`python -m refdes.cli …` against
  this checkout's `src/`), so the numbers include interpreter start and
  imports — the wall a person sees. Three runs, **median** reported.
- Peak RSS is `getrusage(RUSAGE_CHILDREN).ru_maxrss` of the child (no
  `/usr/bin/time` on this machine).
- The serve rebuild number is the wall time of
  `POST /api/item/<ref>/edit` (`op: set_body`) against a running
  `refdes serve --no-open --port … --token-file …`, from a script holding the
  launch token. The handler calls `state.refresh()` — reload the model and
  re-render the whole preview — **before answering** (see
  `serve/api.py` and `serve/state.py`), which is the design's "full rebuild
  after save". After each timed POST the script fetched
  `/preview/<slug>.html` and confirmed the new body text is there, so the
  number is time-until-the-preview-reflects-the-edit, not just time-to-200.
  One warm-up edit per project is excluded; three timed edits, median.
- Serve startup: process start until the first successful `GET` of the launch
  URL — which includes the first full preview render.

## The projects

| Name | Items | Shape |
|---|---|---|
| `real` | 20 | This repository's own project (a copy), the project the 1.06 s figure described. Exits 1: it carries one deliberately failing check on purpose. |
| `ds` | 0 | The repository's `docs-site/` (a copy): pages-only, 52 markdown pages, no items. |
| `p0` | 0 | A bare `refdes init` project — the fixed floor of every command. |
| `p25 / p100 / p400 / p1500` | 25 / 100 / 400 / 1500 | Synthetic, generated. ~40% requirements, 22% log entries (markdown bodies, some with figures), 12% bounds, 10% components (every tenth carries a calc block with a `checks:` entry against a bound), 8% tests, 8% groups; links (`refines`, `derives_from`, `verifies`, `satisfies`, `addresses`, `part_of`, `drop_in`) between them, and inline `:=` calc spans in some log bodies. No real work content. |

## The numbers

Seconds, median of 3, fresh process:

| Items | `check` | `build` | `ls` | serve rebuild (POST) | serve startup |
|---|---|---|---|---|---|
| 0 (bare init) | 0.43 | — | 0.42 | — | — |
| 20 (real) | 0.46 | 0.61 | 0.45 | **0.23** | 0.62 |
| 25 | 0.46 | 0.59 | 0.43 | **0.21** | 0.57 |
| 100 | 0.50 | 0.78 | 0.57 | **0.42** | 0.77 |
| 400 | 0.77 | 2.27 | 0.74 | **2.02** | 2.18 |
| 1500 | 1.68 | 19.9 | 1.69 | **19.1** | 18.7 |
| 0 items / 52 pages (`ds`) | 2.25 | 2.32 | 2.41 | — | — |

Peak RSS: 38 MB for `check`/`ls` at the floor, 51 MB for `check` at 1500,
64 MB for `build` at 1500, 52 MB for the 52-page docs site.

`build --dry-run --keep-going` — the proxy the design document used for its
1.06 s figure — measures the same as a plain `build` at these sizes
(0.60 / 0.56 / 0.73 / 2.11 / 18.4 s at 20 / 25 / 100 / 400 / 1500 items).

## Where the time goes

**A fixed ~0.42 s floor.** An empty project costs 0.43 s to `check`:
interpreter start plus 438 imported modules (367 ms of import self-time;
`refdes.calc` alone is 144 ms, it pulls in `pint`). Every CLI number on this
page carries that floor; the serve rebuild does not (the server is already
warm), which is why the 20-item rebuild (0.23 s) is *faster* than the 20-item
`check` (0.46 s).

**`check` and `ls` scale about linearly.** At 1500 items, 1.68 s — about
0.8 ms per item on top of the floor. A cProfile of `check` at 1500 items
shows the load dominating: `loader.load_tree` 2.06 s of 3.9 s under the
profiler, of which `image_freeze.freeze_images` (the YAML compose pass over
item bodies) is 1.84 s, with the pure-Python YAML scanner at the top of the
self-time list; `build.build`'s model pass is the next block.

**`build` is superlinear, and it is the site rendering, not the model.**
A cProfile of `build` at 1500 items (23.3 s under the profiler, 19.9 s clean):

| | seconds (cumulative) |
|---|---|
| `render.render_site` | 19.6 |
| — `render._unique_calc_anchors` per page (1509 pages), of which `re.findall` | 15.6 |
| — `jinja2` template render | 2.1 |
| `loader.load_tree` (load + check) | 2.0 |

The rendering cost per page grows with the project: every item page embeds
the whole project's hover-preview payload in a
`<script id="preview-data">` block (`templates/base.html.j2`, built by
`render.preview_payload`). At 1500 items that block is 424 KB of a 428 KB
page, and the built site is **625 MB** for 1500 items (672 KB at 25 items,
4.0 MB at 100, 48 MB at 400). Both the bytes written per page and the
regex inventory `_unique_calc_anchors` takes of each page scale with N, so
the render term is quadratic in item count. The model build behind it stays
linear and small.

**The serve rebuild is the same rendering.** The POST handler's
`state.refresh()` reloads the model and calls the same
`render_site(project, draft=True)` into a temp directory before answering, so
the rebuild column tracks the `build` column minus the process floor: 0.21 s
at 25 items, 2.0 s at 400, 19.1 s at 1500. Serve startup pays the same render
once (last column).

## Plain statement

For the sizes people are likely to run — up to a few hundred items — a save
in the browser editor rebuilds in well under a second at 100 items and
about 2 seconds at 400, and the old 1.06 s figure overstates today's cost on
the project it described (that project now rebuilds in 0.23 s). At 1500 items
a full rebuild is ~19 s and a plain `refdes build` writes ~625 MB, roughly
99% of it the preview payload re-embedded in every page; the cost is in
rendering every page with the whole project attached to each one, not in
loading, validating, or evaluating the items.

## Caveats

- Single machine, medians of 3; other worktree sessions were live during
  measurement. Treat absolutes as ±10%.
- The synthetic profile has no citations/PDFs, no imports, no workspaces, no
  board registry, and little real prose. `ds` shows pages carry their own
  cost: 52 pages with no items cost 2.2 s to `check` — page rendering at the
  floor, on top of the ~0.42 s process floor.
- The `real` project exits 1 (one deliberately failing check is part of its
  documentation); its timings are the exit-1 path, which is the same code
  path with one extra diagnostic.

Scripts and corpora live in `.scratch/perf/` (gitignored): `gen.py`
(synthetic generator), `bench.py` (median timer + child RSS),
`serve_bench.py` (token-authenticated POST-edit rebuild timing),
`up.py` (serve startup timing).
