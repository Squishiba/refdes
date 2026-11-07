# Inline-calc integration probe — re-run at main b9eba32, 2026-11-06

Report-only re-run of PR #352 (`inline-calc-integration-probe-20261020.md`)
and its stale first re-run (`inline-calc-integration-probe-rerun-20261025.md`,
closed PR #375) against `origin/main`
`b9eba32dea54dfe8fff225065c7a328ebff3eb16`. Main now carries the merged #345
gate (`c3073c6`), #347 HASH_FORMAT 6 (`ba6d153`), the #368 gate fail-closed fix
(`76bc1e4`), and the live inline-calc slices A–C: #386 read-only preview route
(`a78e30f`), #387/G1 `ITEM.$field` references (`f94a503`), #388 live panel +
auto-fill (`6b89e38`), #391 docs (`c2c8a87`), #392 draft-field spans (`3377090`),
plus #399 user-sim fixes. No production edits; every project is a throwaway
under `.scratch/rr-20261106/`.

## Method

Current tree: `git archive origin/main | tar -x -C .scratch/probe-main` at the
SHA above, run as `PYTHONPATH=<abs>/.scratch/probe-main/src` behind `.scratch/
rd.sh`, which asserts `refdes.__file__` resolves into that tree (every command
in this report ran through it; `rd.sh -V` → `refdes 0.5.0`,
`refdes.__file__ = .../probe-main/src/refdes/__init__.py`). Cross-version legs
use a second pinned tree `.scratch/probe-old` at the original probe's main
`d620ab5f103e65f33abc5f64327a3ef542944dd8` (`HASH_FORMAT = 5`, no
`inline_calc_results` in `model.py` — both verified by grep) behind
`.scratch/rd-old.sh`. venv python 3.13.5. Projects: p1/p1corrupt (gate
semantics, exemptions, fail-closed), p345t (custom sealed type), pdep/pdep-old
(scheduler gap, both trees), p56old/p56main/p56rev (hash 5/6, snapshot, keys),
p6 (calc_hash), p7/p7-pristine/p7u (fetch + source() span, F1), p8 (field
references), p9s (live editor over HTTP).

The serve legs drive `refdes serve` over its loopback HTTP API (token from
`--token-file`), not a browser — the task lane does not authorize browsers.
One method note for the record: an early serve leg started with the wrong cwd
and walked up to the repo's own `refdes-project.yaml`; `serve` loads
side-effect-free (its own `--help`), and `git status --porcelain` in the
worktree is empty after the whole probe — nothing was written.

## The ten original interactions, re-verified at b9eba32

| # | Interaction (original) | Result at b9eba32 | Verdict |
|---|---|---|---|
| 1 | Stale literal span × check/build/release (`Vout := 2 V * 2 = 5 V`) | check/build: `WARNING items/log.md:8 [LOG-001] — inline calc Vout: stored result says 5 V, now computes 4 V`, exit 0; `release rev-a` → `FAIL inline_calc_results  LOG-001: inline calc Vout (items/log.md:8)`, exit 1, no baselines file | **CHANGED as designed** (the gate is main; original main stamped) |
| 2 | Gate switches | `revision rev-a` (default) stamps exit 0; `release_gate: {inline_calc_results: {release: false}}` → `release rev-b` stamped exit 0; `{revision: true}` → revision blocked exit 1; `--no-write release rev-nw` blocked exit 1, baselines dir stayed empty | **PASS** |
| 3 | Gate exemptions | `history capture LOG-001` → release stamped (rev-c/rev-d) with the stale WARNING still printed; post-capture edit → release blocked exit 1 + audit `Entries edited after captured: LOG-001`; `refdes-schema.yaml` append-only `sealprobe` (default `sealing: build`): build writes `.refdes/log-seal.yaml`, release FAIL names only the unsealed `LOG-001` (v3 `log` is `sealing: history` per `standards/hardware/v3/base.yaml:290`, so it never seals at build) | **PASS** |
| 4 | Scheduler gap: dependent span cross-ref in earlier-in-glob file (`v := LOG-002.V_in = 13 V` in `dec.md`, fence in `log.md`) | current main: `2 items, 0 errors`, exit 0, span evaluated against the fence (with `rewrote 1 reference(s) while loading`); d620ab5 tree on the same project: `ERROR … LOG-002 has not been evaluated yet … keep this reference in a calc fence`, exit 1 | **FIXED at main** (merged #347; F2 resolved) |
| 5 | Hash format 5/6 carry-forward | d620ab5 stamps `hash_format: 5` `998594f530307540` (literal-span item); main's `audit` migrates the entry in place to `hash_format: 6`, hash byte-identical, `changed 0`; hand-crafted f5 entry for the composite-rewritten crossref body (`cfbc13d830d02c54`) migrates with `changed 0 (2 unchanged)` (variant-aware, no false change — live-stamping that item on the old tree is impossible, it errors on the crossref span); reverse: old tree `audit` on main's f6 baseline → `changed 0 / uncomparable 2 LOG-001, LOG-002` + the honest explainer; upstream fence `Vout 4 V → 6 V`: audit `changed 2 … LOG-002 -- referenced LOG-001.Vout: 4 V -> 6 V` and check warns the span stale | **PASS** |
| 6 | `calc_hash` probe (inline-only item) | main-stamped entry carries `calc_hash: 57d5ad57594809a5` — byte-identical to the original wt-347 probe value; stored-result-only edit (`4.5 V → 4.001 V`) leaves it fixed; verdict move (`status: accepted → rejected`) with fixed arithmetic → audit `LOG-001 -- stale arithmetic: status changed, calc block did not` | **PASS** |
| 7 | fetch + `source()` span (`v := source("datasheet.csv", "V") \| V = 5 V`, `path:` citation) | `fetch --path datasheet.csv` → `extracted datasheet.csv V = 5.0` into `values.V`; CSV 5.0→6.0 + plain fetch → `skipped … the locked source values are kept -- accept the change with 'refdes fetch --update …'`, pin kept; `--update` → `source value changed … V: 5.0 -> 6.0`, check `stored result says 5 V, now computes 6 V` | **PASS** (main is the span-aware tree) |
| 8 | Slice-1 span-advice messages removed | `grep -rn "keep this reference in a calc fence\|key discovery reads calc fences only" src/ docs/` → exit 1 (no hits); only the tombstone comment `build.py:1735` ("F12-5's … message died with the gap") | **PASS** |
| 9 | Composite-key refresh reaches into spans | `items/dec.md` span rewritten in-file to `w := LOG-001@mwabvktkrvz.Vout = 4 V` (`rewrote 1 reference(s) while loading`); stored result, prose and the `calc` fence in the other item untouched | **PASS** (now main behavior) |
| 10 | Baseline snapshot keyed by target key | `release rev-main` entry: `LOG-002: {…, hash_format: 6, calc_hash: bdb42061464f37ad, calc_refs: {mwabvktkrvz.Vout: 4 V}}` — keyed by the target's key | **PASS** |

## F1 / F2 / F3 at b9eba32

**F1 — plain `refdes fetch` prunes `values:` pins written for span `source()`
keys: STILL REPRODUCES in the cross-version direction; current main's own
fetch cycle is safe.** Exact repro (≤10 lines, projects `p7` /
`p7-pristine`):

```text
init; datasheet.csv = "key,value\nV,5.0\n"; item with path: citation and span
`v := source("datasheet.csv", "V") | V = 5 V`
main  fetch --path datasheet.csv   -> extracted datasheet.csv V = 5.0 (pin)
copy pinned project -> p7-pristine; run the d620ab5 tree's plain fetch:
  d620ab5 fetch --path datasheet.csv ->
    "skipped  datasheet.csv  sha256=7469b4c83079...  hash-only
     1 citation(s) processed, 0 failed"
  diff of .refdes/citations.yaml: the whole values: map is dropped
    <     values: / <       V: / <         reader: csv / <         value: '5.0'
  main  check -> ERROR items/log.md:10 [LOG-001] — inline calc v:
    source('datasheet.csv', 'V') has no locked value -- run
    'refdes fetch --path datasheet.csv' to extract and pin it   (exit 1)
```

Current main's own plain fetch keeps its pins (the leg-7 guard note), so the
window needs a pre-#347 tree — unchanged in kind from the original, same scope
as the 2026-10-25 re-run found. The originally suggested mitigation is
**still unimplemented at main**: hand-inserting an unrecognized
`Q: {reader: csv, value: '9.0'}` key into `values:` and running main's
`fetch --path datasheet.csv --update` rewrites the row with **only** `V`
(verified by diffing before/after) — silent prune, no report line, `check`
stays clean.

**F2 — span dead ends on the #345 head: FIXED.** The merged tree evaluates
span cross-refs (leg 4: 0 errors exit 0; the d620ab5 leg re-confirms the old
dead end), and the gate adjudicates them: `release rev-f2` on the two-span
project → `FAIL inline_calc_results  LOG-002: inline calc w (items/dec.md:8)`
exit 1 — the gate × span-reference case the original probe could only test on
a merged tree.

**F3 — advice loop (slice-1 error named a command that could not pin):
FIXED.** The unpinned-span error names `refdes fetch --path datasheet.csv`
(captured verbatim in the F1 repro's last leg), and main's fetch performs
exactly that pin (leg 7). Both dead-end messages are gone (leg 8).

## New interactions (work landed after the original probe)

All first observed at b9eba32. Gate/hash/fetch surfaces only, as scoped.

| # | Interaction | Observation | Status |
|---|---|---|---|
| N1 | `fetch --update` → gate chain | the re-pin (5.0→6.0) makes the stored `= 5 V` span stale → `release rev-g7` blocked `FAIL inline_calc_results  LOG-001: inline calc v (items/log.md:10)` exit 1; authoring `= 6 V` → release stamped exit 0 | works as designed |
| N2 | Gate × unpinned `source()` span | lockfile `values:` deleted: release exit 1 at the error floor, naming `run 'refdes fetch --path datasheet.csv' to extract and pin it` | works as designed |
| N3 | Gate × field reference (G1 #387) | moving the target's field `v_in: 13 V → 15 V` fires the stale span warning and blocks release (`FAIL … LOG-002: inline calc w (items/zz-read.md:8)`) while the referring item's content hash is untouched (`audit: changed 1 LOG-001 … (1 unchanged)`) — the build.py:2952 rule (field value out of the content hash) holds end-to-end | works as designed |
| N4 | `ITEM.$field` inside a span enters `calc_hash` | the inline-only field-reader carries `calc_hash: 57ce5b85ac3d7a85` (spans enter the probe as name/RHS/unit, `build.py:2700-2756`); the field's *value* stays out of it, per N3 | works as designed |
| N5 | Live editor preview route is read-only (slice A #386) | four `POST /api/item/<ref>/calc` calls: response carries span rows (`status/computed/result offsets/revision`) and the span-positioned `keys restore` diagnostic for a stale composite key; afterwards all 8 project files (items + `.refdes`) are byte-identical — live calc writes nothing | works as designed |
| N6 | Draft-fields overlay (slice C #392) | `x := LOG-001@<key>.$v_in = 17 V` with `fields: {"v_in": "17 V"}` → `status: ok, computed: 17 V` while the saved field is `15 V`; same draft with `fields: {}` → `status: stale, computed: 15 V` | works as designed |
| N7 | Editor save keeps results fresh for the gate (slice B #388) | `POST /api/item/LOG-002/edit` `set_body` (fixing `= 13 V → = 15 V`, composite ref preserved verbatim) → `kind: applied`; then `check` clean and `release rev-g9` stamped exit 0 — the save path feeds the gate as fresh, and the panel's computed value is what closes the offender | works as designed |
| N8 | Preview refuses non-editable bodies (slice A) | calc POST on the build-sealed `SEAL-001` → `a sealed entry is append-only: a correction is a new entry, not this edit` (the edit affordance gates evaluation); the same route on the editable item evaluates normally | works as designed |
| N9 | Gate fails closed on an unreadable history store (#368, F13-1) | corrupting one events file: release blocked with `FAIL inline_calc_results  stale inline-calc gate: cannot read the history store .refdes/history (…: event file does not parse …) -- failing closed, LOG-001: inline calc Vout (items/log.md:8)` exit 1, plus the build warning `edited-after-captured was not checked` | works as designed (fail-closed, no silent exemption) |
| N10 | Lost target key × composite span | deleting `key:` from the fence item: check reports `key deleted since baseline …` and the span's `LOG-001@mwabvktkrvz.Vout` names no live item, offering `refdes keys restore … --dry-run`; here restore **refuses** (dry-run and real) because the baseline content hash differs (the item was edited upstream) and advises `--force` — honest refusal, span text preserved | works as designed (differs from the 2026-10-25 N6, where content matched and restore succeeded) |

## Not verified

- Real-browser behavior of the live-calc panel (auto-fill in the DOM, slice-B
  UX): driven at the HTTP API level only; no browser is authorized on this lane.
- The full test suite (report-only lane; no tree under test beyond the CLI).
- xlsx/other readers, multi-board seals, imported/workspace items × gate,
  `standard upgrade` paths — out of scope, as in the original probe.
- The serve `source-picker accept` pin path (`pins` in `set_body`), the
  editor's cross-item `$` draft limit (reads saved, §3.2), and the
  `PREVIEW_SPAN_LIMIT` truncation flag — code-read only, not exercised.

## Bottom line

At `b9eba32dea54dfe8fff225065c7a328ebff3eb16` all ten original interactions
reproduce (leg 1 CHANGED by design — the gate is main), F2 and F3 are fixed,
and F1 remains exactly as the 2026-10-25 re-run left it: safe for a current
tree's own fetch cycle, silently destructive when a pre-#347 tree's plain
`fetch` touches a lockfile holding span pins, with the preserve-and-report
mitigation still unimplemented (main itself prunes unrecognized `values:` keys
silently). The post-probe work the original probe could not see — live slices
A–C, G1 field references, and the #368 fail-closed gate — behaves as designed
on every gate/hash/fetch surface probed: live calc is read-only, saves feed
the gate fresh, field values move results and the gate without moving hashes,
and a broken history store blocks rather than exempts.
