# Adversarial audit — PR #345 `release_gate.inline_calc_results` (release-gate freshness rule)

Independent verification lane (Claude), authorized by Jared during Sol cover.
Report-only: no product files were edited, PR #345 untouched, nothing merged.

## Pinning

- PR #345 head, before and after the run: `4e89eabfc8cdfd799670cac4850d98519a7709c2`
  (`gh pr view 345 --json headRefOid` at start and end; `refs/pull/345/head`
  fetched twice, identical). Base merge-base `d620ab5` (this worktree's HEAD).
  No probe is stale with respect to head movement.
- Source tree under audit: `git archive 4e89eab | tar -x` into
  `.scratch/pr345src` (exact PR-head tree, no git metadata).
- Interpreter pin: the machine venv's installed `refdes` is a *different*
  checkout (`/home/jorb/work/refdes/src/refdes/__init__.py`), so every run is
  `env PYTHONPATH=$PWD/.scratch/pr345src/src /home/jorb/work/venv-refdes/bin/python3 -m refdes.cli`.
  Import-path assertion printed and checked once per module:
  `refdes/lifecycle/inline_calc/build` all resolve under
  `.scratch/pr345src/src/refdes/` — verified, not assumed.
- CLI projects: `.scratch/m1` (main matrix, hardware@3 + a project-declared
  append-only type `dsn` for the build-seal case), `.scratch/mup` +
  `.scratch/cons` (import case), `.scratch/probe1` (fence-reference probe).
  Every state below was produced by shipped CLI commands
  (`init/build/check/release/revision/history capture/build --reseal`) plus
  plain text edits to item files — no invented states.

## Policy expectation (from the PR's own docs)

`docs/math.md`, `docs/lifecycle.md`, `docs/troubleshooting.md`,
`changelog.d/inline-calc-release-gate.added.md`: a stale inline-calc stored
result in an editable item fails `refdes release` by default
(`{release: true, revision: false}`); exemptions are exactly (a) an item the
build locks as a seal and (b) a capture whose live content still matches its
snapshot; a post-capture edit is editable prose again and blocks;
`refdes revision` is unaffected; the warning stays visible on exempt items;
the offender "names the item, the span, and the span's line".

## Matrix results (all at PR head, real CLI)

| # | State (how reached) | Result | Matches policy |
|---|---|---|---|
| 1 | Stale editable span, component CMP-001 (`4.52 V` stored, computes `4.436 V`) | `release rel-1` → `FAIL inline_calc_results  CMP-001: inline calc Vout (items/cmp.md:8)`, exit 1, no baseline | yes |
| 2 | Correct stored result (edit to `4.436 V`) | `release` passes, `pass` row | yes |
| 3 | Sealed item: append-only `dsn` type, sealed by `refdes build` (`.refdes/log-seal.yaml`), stale span | warning visible, not an offender, release stamps | yes |
| 4 | Captured item: `refdes history capture LOG-001` (log type, `sealing: history`), stale span, unedited | exempt, stamps (`rel-3`), warning visible | yes |
| 5 | Capture then edit (`summary:` line edited) | offender again, `rel-4` blocked, exit 1; reverting to captured content re-exempts (`rel-5` stamps) | yes |
| 6 | Capture record keyed to a key no live item owns (hand-edited `item_key`) | record inert; item treated uncaptured → offender; fails **closed** | yes |
| 7 | Cross-item dependency change: captured-unedited CMP-003 (fence `V_in = CMP-002.V_in`, inline span `3.00 V`) + upstream `12 V→11 V` | CMP-003 stale + warning, **exempt** (live text matches snapshot); release blocks only on other offenders | per policy's letter (see F3) |
| 8 | Cross-item dependency change, editable item (CMP-003 uncaptured) | offender `CMP-003: inline calc Vd2 (items/dep.md:13)`, exit 1 | yes |
| 9 | Sealed item + upstream dependency move (DSN-002 sealed at `11 V`, rail moves to `12 V`) | **floor**: `ERROR ... append-only and has been modified since it was sealed` (reference value is in the content hash), release exits 1 at the error floor, gate never consulted | yes (defense in depth) |
| 10 | No inline calc (`cons` project, plain component) | `pass` row, stamps; `--no-write` reports "would stamp" | yes |
| 11 | Ordinary check/build behavior | `refdes check` / `refdes build` with stale spans: warnings only, exit 0 (build-not-blocking), site written | yes |
| 12 | `refdes revision` with stale offender | stamps (revision half default false) | yes |
| 13 | Overlay `release_gate: {inline_calc_results: {release: false}}` with stale offender | stamps | yes |
| 14 | Overlay `{release: false, revision: true}` with stale offender | `revision` blocked, exit 1 | yes |
| 15 | `--no-write release` with stale offender | blocked, exit 1, gate table printed | yes |
| 16 | Two stale spans in one item | two offender lines (per span, per line) | yes |
| 17 | Imported upstream artifact containing a stale span (`imports:` → upstream `_site/items.json`) | span not evaluated downstream at all (no warning), release stamps; "the other project's problem" | yes (docstring posture) |
| 18 | `refdes release --help` | lists `inline_calc_results` among the rules | docs claim verified |

Offender line numbers: exact span line for markdown items (`cmp.md:8`,
`dep.md:13` verified against `cat -n`); for YAML-sourced items the reported
line is the item's entry line (`log.yaml:2`), because the build warning the
gate reads "as it is" carries that granularity. See F2.

## Findings

### F1 (P1) — the gate fails open on an unreadable history store: a stale, editable, non-exempt span stamps a release, and nothing names the skipped check

`lifecycle._rule_inline_calc_results` catches `(history_mod.HistoryError,
OSError)` from `capture_index` and returns `[]` — **all** offenders, for the
whole project, from one unreadable store file. The build's own history pass
(`build.warn_edited_after_captured`) reports the same condition as a *warning*
(exit code untouched), so the release floor passes and the gate is silently
skipped. The docstring's justification — "the build's own warning already says
the check declined" — is true only of edited-after-captured: the emitted
warning reads `edited-after-captured was not checked: the history store could
not be read (...)`, and nothing anywhere says the inline-calc freshness gate
was skipped. The user-visible docs state the default-on rule fails a release,
with only the seal/matching-capture exemptions — no store-corruption
exemption is documented in `docs/lifecycle.md`, `docs/math.md`,
`docs/troubleshooting.md`, or the changelog fragment.

Exact repro (matrix project `.scratch/m1`; state: CMP-001 stored `4.52 V`,
computes `4.436 V` — editable, never captured; LOG-001 captured; seal
entries present; no load/build errors):

```console
$ printf 'this is not: [valid: yaml\n' > .refdes/history/events/b8c421ff-8152-5931-81aa-cc32c92ee3c6.yaml
$ refdes release rel-16b
WARNING items/cmp.md:8 [CMP-001] — inline calc Vout: stored result says 4.52 V, now computes 4.436 V
WARNING items/dsn.md:8 [DSN-001] — inline calc Vrec: stored result says 9.9 V, now computes 4.436 V
WARNING items/dsn2.md:12 [DSN-002] — inline calc Vh: stored result says 5.50 V, now computes 6 V
WARNING items/log.yaml:2 [LOG-001] — inline calc Vfb: stored result says 9.9 V, now computes 4.436 V
WARNING refdes-project.yaml — edited-after-captured was not checked: the history store could not be read
  (…/events/b8c421ff-….yaml: event file does not parse …)
6 items, 0 errors, 5 warnings

release 'rel-16b' stamped: 6 items, all gates passed.
  .refdes/baselines/rel-16b.yaml
$ echo $?
0
```

Control, same tree with the event file restored byte-for-byte:

```console
$ refdes release rel-16c
…
  FAIL     inline_calc_results  CMP-001: inline calc Vout (items/cmp.md:8)
(exit 1, no baseline)
```

The stale-span warning is still in the report block, and no
`FAIL inline_calc_results` row exists in the stamped run — a false pass on
the headline default-on rule, with nothing naming the skipped gate.

Reachability, stated honestly: no *shipped CLI write path* produces a corrupt
store (writes go through `_write_store_file` with validation; `load_events`
raises loudly on malformed YAML, id/filename mismatch, unknown kind, missing
required key, duplicate edge — all HistoryError → all fail the gate open,
verified two of them: malformed YAML and an id/filename mismatch by renaming
the event file, both stamped `rel-10`/`rel-14`). The reachable route is
corruption around the tool: bad merge, truncated write, hand-edit, or an
`OSError` (verified: `chmod 000 .refdes/history/events` → `rel-11` stamped,
exit 0). The contrast with `captured_edits` is the point: that rule defaults
**off**, so its identical fail-open posture costs nothing by default;
`inline_calc_results` defaults **on**, so the same posture silently defeats a
rule the docs say runs by default. The `HistoryKeyError` class is handled
differently (build `project.error` → floor → release exits 1), which shows
the codebase already distinguishes loud-store problems from declined-check
ones; the gate's exemption list is the wider class.

Minimal expectation options (for the implementing lane, not this report):
(a) fail the rule closed (offenders unknown ⇒ block with an explicit
offender line naming the unreadable store), or (b) make the build's decline
warning name both checks, and document the exemption in
`docs/lifecycle.md`'s rule table. As shipped, the docs overpromise.

### F2 (P2) — "the span's line" is not the span's line for YAML-sourced items

`docs/lifecycle.md` (PR-touched): the offender "names the item, the span, and
the span's line ... so the failure is clickable". For `items/log.yaml` the
offender is `LOG-001: inline calc Vfb (items/log.yaml:2)` — the item's entry
line (post key-mint), not the span's line inside the `body:` block scalar
(line 8 in the same file). The gate reads the build warning's location "as it
is", and the build's location for YAML items *is* the item line
(`item.body_line is None`), so the gate is faithful and the doc sentence is
over-precise for YAML items. Markdown items are exact (verified). Cosmetic
for markdown, mis-pointing for YAML editors.

### F3 (P2, by-design consequence, recorded for the reviewer) — captured-unedited exempts staleness caused by an *upstream edit*

Row 7: capture CMP-003 fresh, then move the upstream rail (`CMP-002.V_in
12 V → 11 V`). CMP-003's live text is untouched, so the capture exemption
applies and a release stamps a page whose displayed span result (`3.00 V`)
no longer computes (`2.75 V`). This follows the docs' exemption wording
literally ("a capture whose live content still matches its snapshot is
exempt"), and the reference value is in the item's content hash, so
`captured_edits` (same store, same flag) catches it — but that rule defaults
off, so by default nothing blocks it. Contrast the sealed case (row 9), where
the seal floor *does* catch the same upstream move. Worth a one-sentence
note in `docs/lifecycle.md`/`docs/math.md` that the capture exemption covers
dependency-induced staleness, since the docs' motivation ("rewriting history
to satisfy a freshness rule is not what the rule is for") is about *edited*
frozen prose, not about an editable upstream number moving under frozen
text. Not a code fault against the written policy; flagged because the
asymmetry with the seal floor looks unintended.

## No-finding areas (bounded evidence)

- No false refusals found: revision half off by default (row 12); overlay off
  (13); `--no-write` consistent with the write path (15); no-inline-calc
  projects unaffected (10); imported spans inert (17); a capture record
  pointing at a dead key fails closed, not open (6); a sealed item edited
  after sealing hits the floor, not a gate false pass (9); a draft/clean
  baseline project's release table shows `pass inline_calc_results`
  (matches the PR's docs/lifecycle.md sample output).
- The gate is called from exactly one site (`lifecycle.py:942`, inside
  `stamp`, always after `build()` in `_run_stamp`), so there is no
  gate-runs-without-builds path.
- `item_by_id` id-shadowing by imports is not a bypass: a display-id
  collision is a build **error** (`imports._absorb`), the floor blocks the
  release first (read of `imports.py:77-90`; not exercised end-to-end).
- The offender text is built from the warning's own head
  (`message.split(": ", 1)[0]`); span labels are identifiers, so no
  observed mangling; not probed with exotic labels.
- `ruff check .` baseline is ~99 pre-existing findings per AGENTS.md; not a
  gate for this audit. Full test suite not run (report-only; PR's own
  `tests/test_lifecycle.py` additions were read, not executed).

## Probe hygiene

- Two early probes (`rel-7`, `rev-2`) ran on a project state that had become
  inline-calc clean, so they proved nothing; they were re-run with an
  explicitly stale CMP-001 (`rel-8` blocked / `rel-9` stamps with overlay
  off / `rev-3` blocked with `revision: true`) and only the re-runs are
  cited above.
- The `--no-write` probe (row 15) first ran with a live seal-floor error
  (contaminated by row 9's setup); re-run after `refdes build --reseal` —
  the cited output is the clean one.
- All corrupt-store probes restored the store afterwards (`release rel-13`
  re-confirmed the restored store blocks CMP-001 only).
