# Inline-calc integration probe — independent end-to-end verification, 2026-10-20

Report-only lane (authorized by Jared during Sol cover). No production edits;
#345/#347 and the grammar worker's branch were inspected read-only.

## SHAs — heads moved during the probe; evidence is tied to the OLD SHAs

| Tree | SHA probed (all evidence below) | Head at end of probe |
|---|---|---|
| origin/main | `d620ab5f103e65f33abc5f64327a3ef542944dd8` | `21da58cc38b3797c96d7727cc821385835cadfad` (docs-only #348/#349) |
| PR #345 `release_gate.inline_calc_results` | `4e89eabfc8cdfd799670cac4850d98519a7709c2` | `c1c6afb68c3432a5a05c28cda6ba0f7f7eb62fa7` (adds `1f0a7c3 fix(release): resolve id-less inline-calc offenders by source location`) |
| PR #347 hash format 6 | `c5c3b8de00e492fd6b0a537ad517f951a9c0f12d` | `8c57eb7c342f180953cd9df4e53cfd81d0d35b40` (adds `fix(calc): evaluator comment parity for span refs, body-bounded span …`) |

No claim of current-head coverage. In particular #345's id-less-offender fix
(`1f0a7c3`) and #347's `8c57eb7` fix are NOT covered here.

## Method

Each source tree ran with `PYTHONPATH=<tree>/src` plus an import-time
`refdes.__file__` assertion (`.scratch/rd.sh`), venv python 3.13.5. Isolated
`refdes init` projects under this worktree's `.scratch/` (p1, p345, p345t/u,
p347a–h, p347s, pdep1/2, pfence, pm1/2). Real commands: `init`, `id`, `check`,
`build`, `release`, `revision`, `audit`, `fetch`, `history capture`. Trees
`d620ab5`, `4e89eab` (wt-345), `c5c3b8d` (wt-347) live under `.scratch/`.

## Verified interactions (each observed, not inferred)

1. **Stale span × check/build/release on main.** `Vout := 2 V * 2 = 5 V`:
   check/build warn (`inline calc Vout: stored result says 5 V, now computes
   4 V`) exit 0; `release` stamps (no gate). Slice-1 baseline confirmed.
2. **#345 gate.** Same project: release FAILs —
   `FAIL inline_calc_results  LOG-001: inline calc Vout (items/log.md:10)`,
   exit 1, nothing stamped; revision (default) passes. `release_gate:
   {inline_calc_results: {release: false}}` → release stamps; `{revision:
   true}` → revision blocked exit 1. `--no-write release` on the offender →
   blocked, zero files written.
3. **#345 exemptions.** `history capture LOG-001` (unedited) → release passes,
   warning still printed. Editing the item after capture → gate offender again
   (exit 1; audit shows it under "Entries edited after captured").
   Build-sealed item → exempt: needs a custom `append_only` type (hardware@3's
   only append-only type, `log`, is `sealing: history`, so `is_sealed` is
   False for every v3 type); with `refdes-schema.yaml` adding an
   append-only `sealprobe` type, only the unsealed item appears in FAIL.
4. **#347 closes the slice-1 scheduler gap.** Dependent item (file `dec.md`,
   earlier in glob order) with span-only `v := LOG-009.V_in`: main → 2 errors
   ("has not been evaluated yet — … keep this reference in a calc fence" +
   cascade "unknown name 'v'"), exit 1; wt-347 → 0 errors, exit 0.
5. **#347 content hash + format 5/6 carry-forward.** Baseline stamped on main
   (hash_format 5): literal-only span item → byte-identical content hash under
   format 6 (`ad74039a58c2e15c`); wt-347 `audit` migrates its entry 5→6 in
   place. The span-cross-ref item's payload *differs* under 6 → migration
   leaves it at 5, and audit reports it `uncomparable` — never a false
   "changed". Reverse direction (wt-347-stamped format-6 baseline read by
   main): `uncomparable 1`, honest. After a wt-347 release (entries stamped
   6), an upstream fence change `V_in = 13 V → 14 V` → audit
   `changed 2 … LOG-002 -- referenced LOG-001.V_in: 13 V -> 14 V` and check
   warns the span stale. (The format stamping in `audit` is main's own
   documented one-time migration — `cli.py:1672` comment; a hand-set
   `hash_format: 4` entry migrates the same way on main. Not a #347 change.)
6. **#347 calc_hash probe.** Inline-only item (no calc fence): main-stamped
   entry has no `calc_hash`; wt-347-stamped entry has one. Editing only the
   stored result (`= 4.5 V` → `= 4.001 V`) leaves `calc_hash` fixed
   (`57d5ad57594809a5` in rev-c and rev-d). A verdict move with fixed span
   arithmetic (status → rejected) fires
   `LOG-001 -- stale arithmetic: status changed, calc block did not` in audit
   — the signal now covers inline-only items. Pre-probe baselines stay silent
   (grandfathered), as designed.
7. **#347 fetch + source().** Span
   `v := source("datasheet.csv", "V") | V = 5 V` with a `path:` citation:
   wt-347 `fetch --path datasheet.csv` extracts/pins `values.V` (check clean);
   changing the CSV 5.0→6.0 + plain fetch keeps the pin (guard note) and the
   item's hash; `fetch --update` re-pins → audit `changed 1` and check
   `stored result says 5 V, now computes 6 V`. Main/#345 on the same project:
   fetch extracts nothing; the span keeps the slice-1 "never pinned" dead end.
8. **#347 removes the slice-1 span advice messages** —
   "keep this reference in a calc fence" and "key discovery reads calc fences
   only" are absent from `wt-347/src`.
9. **#347 composite-key refresh reaches into spans.** A bare `LOG-009.V_in`
   inside a span was rewritten in-file to `LOG-009@arj2c05cvqt.V_in`
   ("rewrote 1 reference(s) while loading"), stored result and surrounding
   prose preserved, fences untouched.
10. **Baseline snapshot.** The format-6 stamp records
    `calc_refs: {7rgfftzwvba.V_in: 13 V}` (keyed by target key) for the
    span-ref item.

## Findings (reproducible)

**F1 — cross-version `refdes fetch` prunes #347-pinned span source values
(stack/rollout hazard, medium).**
Repro: wt-347 fetch on the project above pins
`values: {V: {reader: csv, value: '5.0'}}` in `.refdes/citations.yaml`
(verified in `p347s`). Copy the project (pristine) to `pmain-s`;
`main refdes fetch --path datasheet.csv` → prints
`skipped datasheet.csv … hash-only / 1 citation(s) processed, 0 failed` and
rewrites the row **dropping the whole `values:` map** (diff against the
pristine copy). A subsequent check from the #347 tree then hard-errors:
`source('datasheet.csv', 'V') has no locked value`. Main's fence-only flow is
unaffected (its keys are re-discovered; a second main fetch keeps them —
verified in `pfence`), so the prune is of keys main cannot discover, i.e.
exactly span keys. Impact: in any window where main/#345 users run plain
`fetch` beside #347 pins, #347 builds break until a #347 fetch re-pins.
Suggested: have fetch preserve unrecognized `values:` entries (reporting
them), or state the rollout ordering (#347 fetch is authoritative) in the
#347 release notes.

**F2 — stack interaction (expected by branch base, low).** On #345 head
`4e89eab`, span cross-refs/source() keep the slice-1 dead ends (F12-5 ordering
error, F12-6 never-pinned), so the gate can only ever see literal-arithmetic
stale spans; gate × span-reference items is testable only on a merged tree.
`git merge-tree` of the two heads is text-clean (tree `25abc1aa…`); the
build.py hunks are in disjoint regions. If gate span-tests are wanted, merge
#347 before/with #345.

**F3 — cosmetic, on main (note).** The slice-1 F12-6 error advises running
the exact `refdes fetch --path …` that can never pin span keys — an advice
loop. #347 deletes the message, so this only matters if the release train
ships main-only docs quoting it.

## Not exercised (explicitly out of scope)

serve source-picker span pairs (`serve/sources.py` on wt-347; code-read only),
full test suite on the merged tree, imported/workspace items × gate,
multi-board seal files.

## Bottom line

At the probed SHAs, the gate rule and hash-format-6 integration behave as
designed in all ten end-to-end interactions tried; the only new cross-version
hazard found is F1 (fetch prune). All evidence above is tied to the old SHAs;
re-run against `c1c6afb`/`8c57eb7` before release decisions that depend on
span gate cases.
