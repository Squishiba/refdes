# AUDIT-B: lazy pint unit registry (perf/audit-lazy-pint)

Task: audit §3.2 — `calc.py` built `pint.UnitRegistry()` at import, and
`cli -> adopt -> boards -> keys -> ids -> model -> calc` puts it in every
command's import chain. Make it lazy; unit-free commands must not import
pint; calc behaviour byte-identical.

## What changed (src/refdes/calc.py, one file)

- `import pint` + `UREG = pint.UnitRegistry()` + `Q = UREG.Quantity`
  (old lines 20-23) replaced by a single-flight `_registry()`:
  double-checked lock on a module-level `_UREG`, `import pint` inside it
  binding the module-global `pint` (which the `except pint.*` handlers
  read — safe: no quantity exists before the registry that built it).
  Lock chosen over PEP 562 alone because serve builds previews on worker
  threads (audit WATCH 1).
- `UREG`/`Q` stay importable via PEP 562 `module __getattr__` resolving
  through `_registry()` (tests/test_calc.py uses `calc.Q(...)`).
- All internal `Q(...)` sites -> `_Q(...)`; `UREG.parse_expression` ->
  `_registry().parse_expression` (`is_known_unit`, preferred units).
- `set_preferred_units` stored names, resolved lazily by `_preferred()`
  (it parsed units at import — the last registry-at-import caller).
  Same drop-invalid-name semantics.
- `_simplify`'s `from pint.util import UnitsContainer` was already
  in-function; untouched.

## Measurements (this box, load ~9.5 1-min both runs, median of 7)

| command | before | after | delta |
|---|---|---|---|
| refdes --version | 738 ms | 244 ms | −494 (−67%) |
| refdes ls | 888 ms | 519 ms | −369 (−42%) |
| refdes schema | 789 ms | 272 ms | −517 (−66%) |
| refdes build (docs-site, calc-heavy) | 3027 ms | 2539 ms | −488 |
| refdes build --dry-run (root, 20 items) | 921 ms | 720 ms | −201 |
| importtime refdes.calc cumulative | 219 ms | 8.9 ms | |
| importtime refdes.cli cumulative | 574 ms | 225 ms | |

`'pint' in sys.modules` after `import refdes.cli`: True -> False.
Build of the calc-heavy docs-site got *faster*, not slower — first-calc
cost (~220 ms once/process) is inside noise of the ~2.5 s build.
Reproduction: audit's "~273 of 445 ms" measured as 219 of 574 here
(pint import+registry ~90 ms + calc self ~130 ms); same shape, box
busier. Reproduced.

## Byte-identity proof (before = `git archive HEAD` tree)

- root project site (`build --dry-run -o`): `diff -r` clean.
- docs-site site: `diff -r` clean.
- generated project (init + one `log` item with a calc block, id, build):
  sites identical except the randomly minted surrogate key in
  items.json/front matter (per-project randomness, not a code diff);
  `check`/`ls` text identical; ids ledger identical.
- CLI `ls`/`schema`/`index`/`check` outputs on the root project: identical.

## Tests (red-first)

New tests/test_calc_lazy_registry.py, 7 tests. Red on HEAD: 6 failed /
1 passed (the UREG/Q-attribute guard passes on eager code by design).
Green after: 7 passed. Covers: `import refdes.cli` leaves pint out of
sys.modules (subprocess); calc evaluation imports it on demand; 16-thread
barrier race on first `_registry()` -> one instance; deepcopy/pickle
round-trip on the one registry; `calc.UREG`/`calc.Q` attributes;
isinstance vs pint.Quantity. One test assertion was wrong at first
(pickle of a Quantity lands on a registry copy — true of pint itself,
old code measured identical); fixed the test to pin the real invariant
(same-process accessor is one instance; deepcopy stays on it).

- Touched-module files (test_calc*, test_compare_block,
  test_crossplatform_lint): 290 passed.
- Full suite ONCE: 5945 passed, 2 skipped (skips not in files I touched).
- `ruff check --select E9,F src tests` (the CI gate): clean. Broader
  default-rule findings in calc.py are the pre-existing BLE001/S112 set.
- Cross-platform: new tests use subprocess with sys.executable only;
  test_crossplatform_lint.py passes.

Status: complete. Not verified: Windows timing (ubuntu box only; CI
runs the suite on windows).
