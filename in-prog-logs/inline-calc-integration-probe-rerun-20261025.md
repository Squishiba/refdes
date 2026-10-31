# Inline-calc integration probe — re-run at main 78c8954, 2026-10-25

Report-only re-run of the 2026-10-20 probe
(`inline-calc-integration-probe-20261020.md`) against current `main`
`78c8954`. Main now contains the merged #345 gate (`c3073c6`) and #347
HASH_FORMAT 6 (`ba6d153`), plus the intervening #341/#351 calc fixes. The
old-main tree `d620ab5` (the original probe's main, HASH_FORMAT 5, no
gate, fetch span-blind) is kept as a detached worktree `.scratch/
rr-20261025/wt-old` for the cross-version legs.

## Method

Current-tree runs: `PYTHONPATH=<worktree>/src
/home/jorb/work/venv-refdes/bin/python -m refdes` behind a wrapper
(`.scratch/rr-20261025/rd.sh`) asserting
`refdes.__file__.startswith(<worktree>/src)`; the old-main tree uses the
same wrapper (`rd-old.sh`) with its own assertion. `refdes.__file__`
resolved into this worktree in every run (the assertion is in the exec
path, so a violation aborts the command). Probe projects under
`.scratch/rr-20261025/`: p1 (gate semantics), p345t (custom sealed type),
pdep / pdep-old (scheduler gap, both trees), p56 (hash 5/6), p6 (calc_hash),
p7 / p7u / p7-pristine (fetch + source() span, F1), p9 (keys).

## Interaction verdicts

| # | Interaction | Original result (old SHAs) | Current result at 78c8954 | Verdict |
|---|---|---|---|---|
| 1 | Stale literal span × check/build/release on main | check/build warn exit 0; **release stamps (no gate)** | `refdes check`/`build`: `WARNING … inline calc Vout: stored result says 5 V, now computes 4 V`, exit 0; `refdes release slice-1` → `FAIL inline_calc_results  LOG-001: inline calc Vout (items/log.md:11)`, exit 1, nothing stamped | **CHANGED** (expected: #345 merged, gate default-on for release) |
| 2 | Gate switches | release blocks offender exit 1; `release: false` stamps; `revision: true` blocks exit 1; `--no-write release` blocked, zero files written | identical in all four legs (p1: `release: false` → stamped exit 0; `revision: true` → revision blocked exit 1; `--no-write release rev-nw` blocked exit 1, baselines dir gained nothing) | **PASS** |
| 3 | Gate exemptions | history capture (unedited) → release passes, warning printed; edit-after-capture → offender again + audit section; build-seal exemption needs custom append-only type (v3 `log` is `sealing: history` → never sealed) | identical: capture → release stamped exit 0; post-capture edit → release exit 1, audit `Entries edited after captured: LOG-001`; p345t with `refdes-schema.yaml` append-only `sealprobe`: build seals SEAL-001 (`log-seal.yaml`), release FAIL names only SEAL-002, exit 1; v3 `log sealing: history` confirmed in `standards/hardware/v3/base.yaml` | **PASS** |
| 4 | Scheduler gap: dependent span cross-ref in earlier-in-glob file | old main: 1 error `LOG-002 has not been evaluated yet … keep this reference in a calc fence` exit 1 (original counted 2 incl. cascade); wt-347: 0 errors exit 0 | current main: 0 errors exit 0, span evaluated against the fence's `V_in`; wt-old leg re-confirmed the dead-end (1 error exit 1; no `unknown name 'v'` cascade this time — the message set changed with #341) | **FIXED at main** (merged #347; F2 resolved) |
| 5 | Hash format 5/6 migration | wt-old-stamped f5 entry migrates to 6; literal-span hash byte-identical; crossref payload-differs → left at 5, `uncomparable`; reverse (f6 baseline, old tree) → `uncomparable 1`, honest; upstream fence change → audit `changed … referenced X: 13 V -> 14 V` + check warns span stale | wt-old stamps f5 (`88040bd8aa65ccc6`); main's `audit` migrates in place to `hash_format: 6` with the **hash byte-identical**; hand-crafted f5 entry for the crossref-span item (f5 hash `331224d6f8321b39` of the composite-rewritten body) migrates to 6 with **no false change** (`changed 0`, `(2 unchanged)`) — main's migration is variant-aware; reverse leg on wt-old: `uncomparable 2 LOG-001, LOG-002` with the honest explainer; upstream fence change `4 V → 6 V`: audit `changed 2 … LOG-002 -- referenced LOG-001.Vout: 4 V -> 6 V`, check warns both spans | **PASS** (payload-differs-stamped-at-5 leg: **NOT REPRODUCIBLE** as a live stamp — old main errors on the crossref span so it cannot stamp it; reconstructed by hand-craft, marked as such) |
| 6 | `calc_hash` probe (inline-only item) | main-stamped entry has no `calc_hash`; wt-347-stamped has one = `57d5ad57594809a5`; stored-result-only edit leaves it fixed; verdict move with fixed arithmetic → audit `stale arithmetic: status changed, calc block did not` | main-stamped entry carries `calc_hash: 57d5ad57594809a5` — **byte-identical to the original wt-347 probe value**; result-only edit (`4.5 V` → `4.001 V`) leaves it fixed; `status: accepted → rejected` → audit `LOG-001 -- stale arithmetic: status changed, calc block did not` | **PASS** (calc_hash now on main, as slice 2 promised) |
| 7 | fetch + source() span | wt-347: `fetch --path` pins `values.V`; file change + plain fetch keeps the pin (guard note); `--update` re-pins → audit `changed 1` + check warns; old main: extracts nothing, never-pinned dead end | current main reproduces the wt-347 leg exactly: `extracted datasheet.csv V = 5.0` into `values.V`, check clean; CSV 5.0→6.0 + plain fetch → `skipped … the locked source values are kept -- accept the change with 'refdes fetch --update …'`, pin and hash kept; `--update` → `source value changed … V: 5.0 -> 6.0`, audit `changed 1`, check `stored result says 5 V, now computes 6 V` | **PASS** (main is now the span-aware tree) |
| 8 | Span-advice messages removed | absent from wt-347 src; present on old main | `grep -rn "keep this reference in a calc fence|key discovery reads calc fences only" src/ docs/` → no hits (only a tombstone comment `build.py:1627`) | **PASS** |
| 9 | Composite-key refresh reaches into spans | wt-347 rewrote bare `LOG-009.V_in` in a span to `LOG-009@arj2c05cvqt.V_in` in-file, prose/fences preserved | current main: pdep `items/dec.md` span rewritten `LOG-002.V_in` → `LOG-002@x9ytga83fwd.V_in` with `(rewrote 1 reference(s) while loading)`, stored result and prose preserved, the `calc` fence in `log.md` untouched | **PASS** (now main behavior) |
| 10 | Baseline snapshot keyed by target key | format-6 stamp records `calc_refs: {7rgfftzwvba.V_in: 13 V}` | p56 rev-b: `calc_refs: {sax1ymy0y5s.Vout: 4 V}` — keyed by the target's key, beside `hash_format: 6` and `calc_hash` | **PASS** |

## F1 — plain `refdes fetch` prunes `values:` pins written for span source() keys

**STILL PRESENT in the cross-version direction; NOT REPRODUCIBLE on
current main itself.** Repro at 78c8954 (p7/p7-pristine): the current-main
fetch pins `values.V` for the span `source("datasheet.csv", "V")` (leg 7);
copying the project and running the **old main `d620ab5`** fetch prints
`skipped datasheet.csv … 1 citation(s) processed, 0 failed` and rewrites
the lockfile **dropping the whole `values:` map** (diff vs the pristine
copy); the next current-tree check hard-errors
`source('datasheet.csv', 'V') has no locked value`. Current main's own
plain fetch keeps its pins (guard note, leg 7), so the prune needs a
pre-#347 tree in the window — the rollout hazard is unchanged in kind,
narrower in scope (only users on the old tree). The originally suggested
mitigation — preserve-and-report unrecognized `values:` entries — is NOT
implemented at main: hand-inserting an `Q: {reader: csv, value: '9.0'}`
key and running `fetch --update` on current main **prunes it silently**
(no report line, `check` stays clean). Suggested: implement the
preserve-and-report mitigation, or state the rollout ordering (post-#347
fetch is authoritative) in the release notes.

## F2 — span dead ends on #345 head (gate blind to span-reference items)

**FIXED at main.** The merged tree evaluates span cross-refs (leg 4:
0 errors exit 0), and the gate now adjudicates them: `release` on p56
(two stale spans, one literal one crossref) reports
`FAIL inline_calc_results  LOG-001: inline calc Vout (items/log.md:8),
LOG-002: inline calc w (items/xref.md:8)` exit 1 — the
gate×span-reference case the original probe could only test on a merged
tree is now a main-observable behavior.

## F3 — advice loop (slice-1 error named a command that could not pin)

**FIXED at main.** The unpinned-span error names
`refdes fetch --path datasheet.csv`, and current-main fetch now performs
exactly that pin (verified, leg 7). The `keep this reference in a calc
fence` text is gone from `src/` and `docs/` (leg 8).

## New interactions (gate × hash format 6 × fetch × source() spans)

All first observed at 78c8954; none is covered by the original report.

| # | Interaction | Observation | Status |
|---|---|---|---|
| N1 | fetch --update → gate | p7: `--update` re-pin (5.0→6.0) makes the stored `= 5 V` span stale → `release rev-g7` blocked `FAIL inline_calc_results  LOG-001: inline calc v (items/log.md:11)` exit 1; authoring `= 6 V` → release stamped exit 0. The fetch→gate chain is closed and recoverable | works as designed |
| N2 | Gate × crossref span (was F2-blocked) | release offender list includes the crossref-span item, keyed `LOG-002: inline calc w (items/xref.md:8)` — the gate reads the build's own warnings, span kind included | works as designed |
| N3 | Unpinned source() span × release | p7u (lockfile `values:` deleted): release is blocked at the error floor, exit 1, with the actionable advice `run 'refdes fetch --path datasheet.csv' to extract and pin it`; after the gate rule's row would apply, the citation cannot pass silently | works as designed |
| N4 | Variant-aware f5→f6 migration of a crossref entry | hand-crafted f5 entry for the composite-rewritten crossref body migrates to 6 with `changed 0` (old behavior class: honest non-report, via variant matching rather than `uncomparable`) | works; differs in mechanism from the original `uncomparable` story — worth noting for whoever reads the old report |
| N5 | f6 baseline read by old tree | wt-old `audit` on the main-stamped baselines: `uncomparable 2 LOG-001, LOG-002` + explainer; no false `changed` | honest (same story as original, both entries now) |
| N6 | Lost target key × composite span | deleting `key:` from the fence item: load reports `key deleted since baseline` + the span's composite reference `LOG-002@x9ytga83fwd.V_in` names no live item, with `refdes keys restore LOG-002@x9ytga83fwd` offered (dry-run first); the dependent item is audit-`changed` (1 changed, 1 unchanged) without an author body edit; restore returns `check` clean, span text unchanged | works as designed |
| N7 | Format 6 hashes the composite span text | stamped f6 hash of the composite-rewritten crossref body `bf354d6471ca2394` differs from its f5 hash (`331224d6f8321b39`, composites stripped per `build.py:2844 strip_inline_composite = hash_format < 6`) — i.e. the in-file key refresh is hash-visible under 6, hash-invisible under 5; `calc_refs` snapshot keys the target by key (leg 10) | as designed; the migration in N4 must (and does) variant-match this |
| N8 | `refdes id` mints surrogate keys | key minting at `id`/load (`key:` front-matter lines, `(minted N key(s) while loading)`) is now normal main behavior — the original probe's projects predate it; `keys adopt`/`keys restore` present (`refdes keys --help`) | context change vs the original probe |
| N9 | Span grammar requires a stored result | `v := LOG-002.V_in` with no `= <quantity>` is an **error** at main: `stored result missing; write '= <quantity>'` (`#351` tight result separator); the original probe's span-only cross-ref form cannot be written as-is at main | CHANGED (grammar tightening; shaped the leg-4 repro) |

## Not exercised

serve lanes (source picker, editor), full test suite, imported/workspace
items × gate, multi-board seals, `#351` grammar edge grammar beyond N9,
`standard upgrade` paths.

## Bottom line

At `78c8954` all ten original interactions reproduce (leg 1 CHANGED by
design: the gate is main now), F1 is fixed for current main's own fetch
cycle but the old-tree prune remains (mitigation unimplemented —
new leg: main also prunes unrecognized `values:` keys silently), F2 and
F3 are fixed, and the merge's promised cross-behaviors (gate × span refs,
fetch → gate chain, key-keyed `calc_refs`, variant-aware migration,
composite-in-hash under 6) hold end-to-end. The one asymmetry worth
release-note air time is F1's rollout direction: a pre-#347 tree's plain
fetch still silently prunes span pins from the shared lockfile.
