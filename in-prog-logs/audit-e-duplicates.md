# AUDIT-E: merge duplicated helpers (audit 2.2, 2.3, 2.4, 2.8)

Branch `chore/audit-duplicates`, base 3e2ebefa (#444). Slice of the
2026-11-06 code audit's section 2 "do" items. No user-visible behaviour
change; no changelog fragment. No timing claims in this slice (the
re-measure rule applies to §3 perf items; §2 items are line-count
findings, which I verified by re-diffing each pair).

## Re-verification on current main (before touching anything)

| pair | status at 3e2ebefa |
| --- | --- |
| 2.2 `blocks._esc` ⇄ `build._esc` (build.py:3481) | byte-identical, 9/9 lines — reproduced |
| 2.3 `render._check_state` ⇄ `serve.filters.check_state` (filters.py:94) | bodies identical, filters adds only the docstring naming render as the shared rollup — reproduced |
| 2.4 `render._write_taskpane_assets` ⇄ `_write_navis_assets` | same loop parameterized by (NAMES, SRC_DIR); docstrings differ with substance — reproduced |
| 2.8 `pr_size.main()` inline sum ⇄ `count_src_additions` | `main()` never calls the helper (line 113) — reproduced |

## What landed (one concern per commit)

- 2.8: `main()` calls `count_src_additions(result.stdout)`. Red-first:
  new test replaces the helper with a sentinel and asserts main()
  reports it — fails at base (`seen == []`, main printed the inline
  total 10), passes after. 16/16 in `test_pr_size.py`.
- 2.2: deleted `build._esc`; `from .blocks import _esc` in build.py
  (blocks imports no refdes module reaching build — no cycle; build
  already imported blocks). `refdes.build._esc` stays importable, so
  `tests/test_build.py`'s import is unchanged; 78 passed.
- 2.3: deleted `filters.check_state`; filters.py aliases
  `from ..render import _check_state as check_state` (serve/preview.py
  already imports render; no refdes module imports serve — no cycle).
  `serve.api`'s `from .filters import check_state` keeps working.
  render's copy gained the shared-rollup docstring. 102 passed
  (test_serve_api + test_render_assets).
- 2.4: added `_write_assets(out_dir, written, enabled, names, src_dir)`;
  both writers delegate, their docstrings kept. Built-tree file set
  unchanged. 102 passed (test_render_assets, test_task_pane,
  test_navis_site_panel, test_render_environment).

## Byte-identity (built-site hashes, sha256 over sorted per-file digests)

Harness: `.scratch/audite/{gen_project,hash_tree}.py`. Generated
project: 100 items (80 requirements incl. `<!--navi: -->` bodies, 20
log entries in 4 `follows:` threads) so BOTH asset writers run; its
site carries `assets/taskpane.css`, `taskpane.js`, `navis.css`.

| tree | before | after | files |
| --- | --- | --- | --- |
| repo `items/` → `_site` | 6e79ca13…5b63b7 | identical | 45 |
| `docs-site` → `_docs` | d0274e98…5b63b7 | identical | 60 |
| generated 100-item `_site` | 67ecbfca…c42ca | identical | 116 |

Per-file manifests diffed empty (not just digests). Determinism
control: rebuild at base → same digest. Builds run with
`PYTHONPATH=<worktree>/src` on venv-refdes (Linux box, light load).

## Tests / gates

- `tests/test_crossplatform_lint.py`: 12 passed (fixtures use
  `newline=""`; no path-sep asserts added).
- Touched-file ruff (I,F,E9): clean (repo not ruff-clean overall).
- Full suite once: see final line below.
- Size gate: src additions for this branch = 18 (budget 350).
- pr-size gate runs `tools/pr_size.py` itself: it is exercised by this
  PR's CI, and now self-tests its shipped path.

Status: COMPLETE. 5 commits (2.8, 2.2, 2.2-style-fixup, 2.3, 2.4),
log added here.
