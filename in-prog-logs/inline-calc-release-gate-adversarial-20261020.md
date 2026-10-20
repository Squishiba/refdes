# Adversarial audit — PR #345 `release_gate.inline_calc_results` (release-gate freshness rule)

Independent verification lane (Claude-lane work performed by Qwen — the
model named in the commit trailer), authorized by Jared during Sol cover.
Report-only: no product files were edited, PR #345 untouched, nothing merged.

## Pinning

- PR #345 head at start of probing: `4e89eabfc8cdfd799670cac4850d98519a7709c2`
  (fetched `refs/pull/345/head`; base merge-base `d620ab5` = this worktree's
  HEAD). **The head moved during the audit**: the final check shows
  `c1c6afb68c3432a5a05c28cda6ba0f7f7eb62fa7` (branch rebased onto newer main
  incl. #348/#349, plus `1f0a7c3 fix(release): resolve id-less inline-calc
  offenders by source location`). All matrix rows below were probed at
  `4e89eab`; between the two heads the only `src/` change is
  `lifecycle.py`'s offender-lookup refactor (`git diff 4e89eab..c1c6afb
  --stat`), which is exactly the subject of finding **F1b** below. F1 was
  re-verified at `c1c6afb` (stamped, exit 0); matrix rows 1/3/4 were
  re-checked at `c1c6afb` through the `m1-ctl` control run (blocked on
  CMP-001, as at `4e89eab`); the remaining rows are unaffected by a diff that
  touches nothing else in `src/`. Probes not re-run at `c1c6afb` are marked
  stale-with-respect-to-the-id-lookup only. Round-2 finish check: head moved
  to `bbfd40053a25a965d181f639453a16b68cd2d977`; round-3 check: head moved
  again to `742b757effa314aa2fc1cccb33139ba82ea8cafb` (OPEN, unmerged both
  times) — see "Current disposition" under Findings.
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

### Current disposition (round-3 re-check, at finish)

PR #345 is **OPEN, unmerged**, head now
`742b757effa314aa2fc1cccb33139ba82ea8cafb`: `bbfd400 fix(release): fail
inline-calc gate on unreadable history` over `c1c6afb`, then
`742b757 fix(release): match Markdown inline-calc span lines`
(`git log --format="%h %s" c1c6afb..742b757`). The head had moved again
before this round's push; the round-2 text below pins what was verified at
each head. F1's and F1b's historical reproductions at `4e89eab`/`c1c6afb`
stand as written, unchanged.

- F1 (unreadable-store fail-open): confirmed fixed at `bbfd400` (pinned
  tree `.scratch/pr345head3`, real CLI, `.scratch/m1`, stale editable
  CMP-001): corrupting `b8c421ff-…yaml` → `release bbfd-corrupt` blocked,
  `FAIL inline_calc_results  history: inline calc freshness cannot be
  checked: history store unreadable (… event file does not parse …)`, exit
  1; the same corrupt state at pre-fix `c1c6afb` stamped (`bbfd-old2`, exit
  0); clean-store control blocks CMP-001 (`bbfd-ctl`); restored store +
  fresh CMP-001 stamps (`bbfd-restored2`). Fix shape = option (a) below,
  scoped to "stale spans in play" (sealed/imported/no-stale exemptions
  kept, docstring rewritten). Re-verified fixed at `742b757` (`f1-head4`
  blocked, exit 1), where the offender is additionally collapsed to one
  gate row (`_unreadable_history_offender`).
- F1b (id-less continuation): confirmed **not fully fixed until `742b757`**
  (reviewer 80e93711; my round-2 "fixed at `c1c6afb`/`bbfd400`" claim held
  only for the list-file reproduction). Verified: a **Markdown**
  continuation with the stale span on a later body line (`.scratch/m4`:
  `items/notes.md`, id-less `follows:` continuation, span line 10)
  **stamped** at both `c1c6afb` (`m4-c1c6`, exit 0) and `bbfd400`
  (`m4-bbfd2`, exit 0) — exact `source_line`/`body_line` equality misses a
  span on a non-first body line — and **blocked** at `742b757`: `FAIL
  inline_calc_results  qzymeef7f99: inline calc Vfb (items/notes.md:10)`,
  exit 1. The **list-file** reproduction (`.scratch/m3`,
  `q7g3jpd0qfs: … (items/log.yaml:7)`) is blocked at `c1c6afb` *and*
  `742b757` (`m3-c1c6`, `m3-head4`, exit 1) — that half was genuinely
  fixed by `1f0a7c3`.
- Tests at pinned trees: `tests/test_lifecycle.py` native → 48 passed at
  `742b757`, 47 at `bbfd400`; running `742b757`'s test file against the
  older trees (per-tree conftest, so each tree's own `src` — a plain
  `PYTHONPATH` override from a foreign rootdir is ignored by conftest's
  `sys.path.insert(0, …/src)`) → 2 failures at `bbfd400` (the Markdown
  continuation test — expected — and the one-row-offender assert) and 3 at
  `c1c6afb` (+ the two store tests, expected pre-fix). The same commit took
  F2's docs point (changelog: "the warning's reported source line … falling
  back to the item's entry line for a list-file `body:` key") and an
  F3-adjacent sentence ("The capture exemption follows the captured text,
  not upstream values that move later.").

### F1 (P1; historical at `4e89eab`/`c1c6afb`, fixed at `bbfd400` — see Current disposition) — the gate fails open on an unreadable history store: a stale, editable, non-exempt span stamps a release, and nothing names the skipped check

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
Resolved at `bbfd400` by option (a) — see Current disposition.

### F1b (P1 at `4e89eab`; list-file variant fixed at `c1c6afb`, Markdown variant live through `bbfd400`; FIXED at `742b757`) — a stale span in a permanently id-less continuation escaped the gate entirely

Reachable through shipped CLI with no corruption: a `log` continuation entry
(`follows: LOG-001`, no `id:` — continuations are permanently id-less, so
`require_ids` does not catch them) carrying a stale span. The build warns
with an empty display id (`WARNING items/log.yaml:7 — inline calc Vfb:
stored result says 9.9 V, now computes 4.436 V`), and at `4e89eab` the rule's
lookup was `project.item_by_id(diagnostic.item_id) if diagnostic.item_id
else None` → `item is None` → `continue`, so the offender vanished.

```console
# .scratch/m3/items/log.yaml: LOG-001 (id) + continuation (no id, follows:
# LOG-001, stale body span). Keys minted by `refdes check` (writable load).
$ refdes release m3-rel-a          # tree at 4e89eab
release 'm3-rel-a' stamped: 2 items, all gates passed.
$ echo $?
0                                   # .refdes/baselines/m3-rel-a.yaml written
$ refdes release m3-rel-b          # same tree, code at c1c6afb (1f0a7c3)
  FAIL     inline_calc_results  q7g3jpd0qfs: inline calc Vfb (items/log.yaml:7)
$ echo $?
1
```

The current head's `_inline_calc_items` resolves the empty-id diagnostic by
exact source location (`source_line`/`body_line` equality in the warning's
file), names the offender by surrogate key, and blocks — verified above, and
the docs at `c1c6afb` (`docs/lifecycle.md`, `docs/math.md`,
`docs/design/inline-calc.md`, changelog fragment) were updated in the same
commit to promise exactly that. This lane's `4e89eab` probes had not covered
the id-less path (a `require_ids=True` reading of the release load path,
which the continuation exemption disproves); the mid-audit fix landed under
this audit, so it is recorded as found-live-at-old-head / fixed-at-current-
head, with both runs shown, rather than claimed as a fresh find at the head.
No false refusal observed from the new lookup: in `m3` the offender set is
exactly the continuation's key — the plural location match needs two items
at one line, and in a list file a later entry's line is always after the
earlier item's body ends (span lines live inside the body).

Round-3 correction (reviewer 80e93711): the "`c1c6afb` blocks" claim above
is true of the **list-file** reproduction — a YAML list entry whose
`body:` key makes the warning's line the item's source line. A **Markdown**
continuation is different: the warning carries the span's absolute line, so
when the span is not the first body line, exact `source_line`/`body_line`
equality misses the item and the bypass is live. Verified: `.scratch/m4`
(`items/notes.md`, id-less `follows:` continuation, stale span on body line
10) stamps at `c1c6afb` (`m4-c1c6`, exit 0) and at `bbfd400` (`m4-bbfd2`,
exit 0), and blocks at `742b757` (`m4-head4b`, exit 1, naming
`qzymeef7f99`), whose `_inline_calc_items` matches the whole body range.
The historical `4e89eab` finding and the `m3` list-file reproduction above
stand unchanged; see Current disposition.

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
exempt"), and there is **no gate backstop at any setting**: `captured_edits`
enabled does not catch it. Verified at `c1c6afb` (`.scratch/probe2`,
`release_gate: {captured_edits: {release: true}}`, CMP-003 captured
unedited): upstream `12 V → 11 V` → warning `inline calc Vd2: stored result
says 3.00 V, now computes 2.75 V` visible, and `release p2-move` stamped,
exit 0, `captured_edits` passing. The mechanism is the two digest layers:
the *content hash* (seals, baselines) includes resolved cross-item calc
reference values (`build.py` hash format 4, "what an item's cross-item calc
references contribute to its content hash"), which is why the seal floor
*does* catch the same move (row 9) — but the history digest that
`captured_edits` reads (`history.semantic_payload`: type/fields/links/body,
authored text only) does not, so an authored-text-unchanged item with a
moved reference value is not "edited after captured". The only signal left
is the visible stale warning. A correction to this paragraph in an earlier
revision claimed `captured_edits` catches the move when enabled (conflating
the content-hash layer with the history digest); reviewer `e02b0027`
live-reproduced the enabled-rule pass, and the run above confirms it. Worth
a one-sentence note in `docs/lifecycle.md`/`docs/math.md` that the capture
exemption covers dependency-induced staleness and that `captured_edits`
does not cover it, since the docs' motivation ("rewriting history to
satisfy a freshness rule is not what the rule is for") is about *edited*
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
  gate for this audit. The full repo suite was not run (report-only);
  `tests/test_lifecycle.py` was executed at pinned trees: 47 passed at
  `bbfd400`, 48 at `742b757`, plus the cross-tree runs in Current
  disposition.

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
- Head moved mid-audit (`4e89eab` → `c1c6afb`, detected at the finish
  check). F1 re-verified at `c1c6afb` (`m1-corrupt` stamped, exit 0, with
  the same stale editable CMP-001; `m1-ctl` control blocked); F1b was
  produced by probing both heads on the same project. Matrix rows 2, 5–18
  were probed only at `4e89eab` — the head-to-head `src/` diff is confined
  to the offender lookup, so those rows are marked stale-with-respect-to-
  the-id-lookup, not re-verified.
- Round-3: F1b was re-probed as a Markdown continuation (`.scratch/m4`)
  after reviewer 80e93711 showed the Markdown variant survived `1f0a7c3`;
  the `m3` list-file probe is retained as the historical reproduction.
  Cross-tree test runs from a foreign rootdir first appeared to pass
  everywhere — conftest's `sys.path.insert(0, <rootdir>/../src)` wins over
  `PYTHONPATH`, so those runs tested the wrong tree and were discarded;
  the cited cross-tree results re-run each tree's own conftest+tests.
