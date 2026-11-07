# perf-audit-render — SLICE AUDIT-A (render performance)

Branch `perf/audit-render`, base d8bcbecb (main, audit PR #434). Implements
audit §3.1 (guard + finditer micro) and §3.3 (shared Jinja Environment).
Status: DONE — 3 commits, full suite green, pushed for PR.

## Commits (one concern each)

1. `perf(render): skip the calc-anchor scan on pages without calc tables`
   — `_CALC_TABLE_MARKER = 'class="calc"'` literal kept adjacent to
   `_CALC_TABLE_ID_RE` with a drift comment; guard returns early in
   `_unique_calc_anchors`.
2. `perf(render): scan the id inventory with finditer plus a char check`
   — lookbehind `(?<![-\w])id="` → plain `id="` finditer + Python check of
   the preceding char (`prev != "-" and not (prev.isalnum() or prev == "_")`,
   exactly `[-\w]` for str). New test `test_inventory_is_attribute_bounded_
   like_the_rename` first, sabotaged lookbehind-dropped inventory = RED,
   green on both old and new forms.
3. `perf(render): reuse one Jinja Environment per process` — `_environment()`
   keyed `(TEMPLATE_DIR, autoescape, trim_blocks, lstrip_blocks)`, double-
   checked under a lock; `auto_reload=True` explicit (Environment default
   None would serve a stale template in a long-lived serve). No on-disk
   cache (rejected per task: new on-disk state, cross-process staleness).
   `tests/test_render_environment.py` (3 tests): reuse (red against a
   sabotaged fresh-env-per-call render_site), keying, template-edit freshness.

## Measurements (this box, load ~8-9 during runs, other sessions active;
median of 5 renders per point, 3 rounds reported)

| metric | baseline | §3.1 guard | §3.3 env (all three) |
| --- | --- | --- | --- |
| syn200 render_site (in-proc) | 448–518 ms | 209–249 ms | 110–123 ms (compiles 0 after 1st) |
| syn200 CLI `build --dry-run` (subprocess) | 1307–1357 ms | 817–881 ms | 811–851 ms (one render/proc) |
| repo site render_site (in-proc) | 185–203 ms | 149–152 ms | 26 ms |
| serve preview rebuild (PreviewManager loop, syn200) | 431–607 ms (12 compiles/rebuild) | — | 86–128 ms (0 compiles/rebuild) |
| `_unique_calc_anchors` id-inventory, 3 calc pages of repo site | 0.895 ms/page (lookbehind) | — | 0.030 ms/page (finditer+check, 30x) |

Audit re-measurement: §3.1 guard precheck 55–69x cheaper than the findall
pass (audit said 62x) — reproduces. §3.3 12 compiles per render_site
~150 ms — reproduces. §3.1 A/B on 200-item site −49% render (audit said
−76% on 800 items; mine is a smaller site, same direction, no numeric claim
carried over).

## Byte-identity proof

Full built-site trees diffed `diff -r` (all IDENTICAL, repo/docs on HEAD's
render.py, after on branch):

- repo project (items/, 45 files, 3 pages WITH calc tables): base-repo vs
  after1/after2/after3 → identical.
- docs-site (pages-only, `_docs`): identical.
- generated syn200 project (213 files, 0 calc pages): identical.
- `_id_attr_values` vs lookbehind findall: equal as sets on all 40 repo
  pages incl. the 3 calc pages (the generated `data-where-id=` case).

## Tests

Touched-file runs green throughout; full suite ONCE before push:
5942 passed, 2 skipped (215.63 s, -n 4 --dist worksteal, load ~8.5).
ruff on touched files: only the pre-existing SIM103 in render.py (present
on HEAD), no new findings. test_crossplatform_lint green.

## Notes

- Serve freshness: with a shared Environment, `auto_reload=True` is load-
  bearing — the Environment default (None) serves the cached template with
  no disk check; the per-call Environment got freshness by being new. Test
  3 of test_render_environment.py pins it.
- Concurrency: serve serialises renders (`PreviewManager._lock`); CLI is
  single-threaded; shared `env.globals` mutation per call is therefore
  race-free, and every global `render_site` reads is written every call.
- Not carried out of scope: §3.2 (pint import) — different slice.
- Scratch scripts: `.scratch/audit-a/` (gen_project.py, measure.py, ab.py,
  rebuild.py, micro.py, cli_time.py, before-src/ = HEAD render.py copy).
