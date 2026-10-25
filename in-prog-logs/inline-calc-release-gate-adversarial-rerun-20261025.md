# Adversarial release-gate audit — re-run at main `78c8954` (`release_gate.inline_calc_results`)

Report-only re-run of the PR #345 adversarial audit
(`in-prog-logs/inline-calc-release-gate-adversarial-20261020.md`, branch
`report/inline-calc-release-gate-adversarial-20261020`) against current
main. #345 has since merged (`c3073c6`), together with
`76bc1e4` = F13-1 / #368 (the gate names the unreadable history store when
failing closed) and `ba6d153` = #347 (HASH_FORMAT 6: inline spans enter
`calc_hash`, the dependency scans and the content hash). No production,
test or docs-site file was edited here.

## Pinning

- Tree under audit: this worktree's HEAD `78c8954` (clean tree at start;
  `git status` empty apart from gitignored `.scratch/`).
- Interpreter pin (the trap from the original report, re-verified): the
  machine venv's installed `refdes` is a *different* checkout, so every run
  is `env PYTHONPATH=src /home/jorb/work/venv-refdes/bin/python -m
  refdes.cli`, and the import path was asserted, not assumed:
  `python -c "import refdes; print(refdes.__file__)"` →
  `<worktree>/src/refdes/__init__.py`. (`python -m refdes` itself fails on
  this tree — the package has no `__main__`; `-m refdes.cli` is the shipped
  entry point, same as the original audit used.)
- Projects: every probe ran in an isolated project under `.scratch/rerun/`
  (`m1` matrix, `m2` unused, `m3`/`m4` continuations, `mup`/`cons2`
  imports, `cons` no-calc, `atk` attack surface). States were produced by
  shipped CLI commands (`check/build/release/revision/history capture/
  build --reseal`) plus plain text edits to item files.
- Invocation note: projects were addressed with the global `-c
  <project>/refdes-project.yaml` from the worktree root (identical
  semantics to `cd`-ing in; output paths stay project-relative).
- Corroboration: `tests/test_inline_calc_gate_unreadable_history.py
  tests/test_lifecycle.py` at this tree → 58 passed. Full suite not run
  (report-only); `ruff check .` is the documented ~99-finding baseline and
  is not a gate.

## Matrix re-run (18 rows, same commands, adapted where the CLI changed)

Row 1 was first run with LOG-001 uncaptured (it then appears as a second
offender — correct, but not the original row-1 state); the cited row-1 run
re-captures LOG-001 first, matching the original project state.

| # | State | Original result (PR head) | Current result (`78c8954`) | Verdict |
|---|---|---|---|---|
| 1 | Stale editable span CMP-001 (`4.52 V` stored, computes `4.436 V`) | FAIL `CMP-001: inline calc Vout (items/cmp.md:8)`, exit 1, no baseline | identical: FAIL row, exit 1, no baseline written | PASS |
| 2 | Correct stored result (`4.436 V`) | release passes | `rel-2` stamped, exit 0 | PASS |
| 3 | Sealed item (append-only `dsn` type, sealed by `refdes build`) with stale span | warning visible, not an offender, stamps | `dsn2.md:11` warning visible in every m1 run, DSN-002 never an offender, `rel-2` stamps | PASS |
| 4 | Captured (`history capture LOG-001`) stale unedited | exempt, stamps, warning visible | identical (rel-2 / rel-5b stamp with `log.yaml:3` warning visible) | PASS |
| 5 | Capture then edit (`summary:` edited) | offender again; reverting re-exempts | `rel-5` blocked exit 1 (`LOG-001: inline calc Vfb (items/log.yaml:3)`); revert → `rel-5b` stamps | PASS |
| 6 | Capture record keyed to a dead key (hand-edited `item_key`) | record inert, item treated uncaptured, fails closed | identical (`rel-6` offender exit 1; restore → `rel-6-ctl` stamps) | PASS |
| 7 | Captured-unedited CMP-003 + upstream rail `12 V→11 V` | stale+warning, exempt (live text matches snapshot); blocks only on other offenders | identical: warning `3.00 V → 2.75 V` visible, `rel-7` stamped (no other offenders present) | PASS |
| 8 | Rail moves under uncaptured editable CMP-003 | offender `CMP-003: inline calc Vd2 (items/dep.md:13)`, exit 1 | offender `CMP-003: inline calc Vd2 (items/dep.md:12)`, exit 1 (line 12 vs 13: my dep.md scaffold is one line shorter; exact span line verified) | PASS |
| 9 | Rail moves under sealed DSN-002 (resealed at `11 V`, rail → `12 V`) | floor `ERROR ... append-only and has been modified since it was sealed`, exit 1, gate never consulted | identical (ERROR floor, exit 1, no gate table) | PASS |
| 10 | No inline calc (`cons`) | pass row, stamps; `--no-write` reports "would stamp" | `rel-10` stamped; `--no-write` → "would stamp 1 items", exit 0 | PASS |
| 11 | `check`/`build` with stale spans | warnings only, exit 0, site written | identical (`check` exit 0 with 4 stale warnings; `build` exit 0, `_site/` written) | PASS |
| 12 | `revision` with stale offender | stamps (revision half default false) | `rev-12` stamped, exit 0 | PASS |
| 13 | Overlay `{release: false}` with stale offender | stamps | `rel-13` stamped, exit 0 | PASS |
| 14 | Overlay `{release: false, revision: true}` | `revision` blocked, exit 1 | `rev-14` blocked, exit 1, FAIL row printed | PASS |
| 15 | `--no-write release` with stale offender | blocked, exit 1, gate table printed | identical (`rel-15` blocked, exit 1, full table) | PASS |
| 16 | Two stale spans in one item | two offender lines (per span, per line) | `... Vout (items/cmp.md:8), ... Vrec2 (items/cmp.md:10)`, exit 1 | PASS |
| 17 | Imported upstream artifact with stale span (`imports:` → upstream `_site/items.json`) | span not evaluated downstream (no warning), release stamps | identical (`cons2` check: 2 items, 0 warnings; `rel-17` stamped) | PASS |
| 18 | `refdes release --help` | lists `inline_calc_results` among the rules | lists it (help text names the rule and its posture) | PASS |

No row regressed. Offender line granularity unchanged from the original:
exact span line for Markdown, `body:`-key/entry line for list-file YAML
(`items/log.yaml:3` while the span text sits on line 7 — verified against
`cat -n`).

## Focus findings

### F1 (P1, gate failed open on an unreadable history store) — FIXED

Fixed on main by `76bc1e4` (F13-1, #368). Reproducer on `.scratch/rerun/m1`
(stale editable CMP-001 in play; LOG-001 captured-unedited; DSN entries
sealed):

```console
$ printf 'this is not: [valid: yaml\n' > .refdes/history/events/3ba80f26-….yaml
$ refdes -c …/m1/refdes-project.yaml release f1-corrupt
  FAIL  inline_calc_results  stale inline-calc gate: cannot read the history
  store .refdes/history (…events/3ba80f26-….yaml: event file does not parse
  …) -- failing closed, CMP-001: inline calc Vout (items/cmp.md:8),
  LOG-001: inline calc Vfb (items/log.yaml:3)      # exit 1, no baseline
$ chmod 000 .refdes/history/events    # OSError variant (original rel-11 stamped)
  FAIL  inline_calc_results  stale inline-calc gate: cannot read the history
  store .refdes/history ([Errno 13] Permission denied: '…events') -- failing
  closed, CMP-001: …, LOG-001: …                    # exit 1
```

Restoring the store re-exempts LOG-001 and leaves CMP-001 as the sole
offender (`f1-ctl` blocked — control proves the run is not simply
always-failing). Matches the F1 minimal-expectation option (a) the original
report asked for, and the shipped rule docstring + `docs/lifecycle.md` /
`docs/math.md` sentences ("If an editable, unsealed stale span is in play
and the history store cannot be read, the release gate fails closed and
names the unreadable store"). The captured-unedited span joins the offender
list under corruption ("the gate could not prove the exemption") — that is
the fix's stated design, not a false refusal: the release is blocked either
way while CMP-001 is stale.

### F1b (P1, id-less continuation bypass) — FIXED (both variants)

- **List-file variant** (`.scratch/rerun/m3`, `items/log.yaml`:
  `LOG-001` + id-less `follows:` continuation whose stale span is in the
  `body:` block):
  `FAIL inline_calc_results  16cr8bt0b74: inline calc Vfb (items/log.yaml:7)`,
  exit 1. Blocked, named by minted surrogate key, at the `body:`-key line
  (the original's exact shape, key `q7g3jpd0qfs` there).
- **Markdown variant with the span NOT on the first body line**
  (`.scratch/rerun/m4/items/notes.md`, id-less `follows:` continuation,
  stale span on body line 13 — the variant that survived `1f0a7c3` and
  `bbfd400` in the original):
  `FAIL inline_calc_results  cvqykwzdaey: inline calc Vfb (items/notes.md:13)`,
  exit 1. The body-range match (`body_line <= line < body_line + len(body)`)
  is on main in `lifecycle._inline_calc_local_items`.

### F2 (P2, "the span's line" is the entry line for YAML-sourced items) — FIXED (docs)

Behavior unchanged (by design): Markdown offenders carry the exact span
line (`cmp.md:8`), list-file offenders the entry/`body:`-key line
(`log.yaml:3`). The docs now say so: `docs/lifecycle.md` ("the span's line
in Markdown, falling back to the item's entry line for a list-file `body:`
key") and `docs/math.md` carry the same sentence. The original's over-precise
promise is corrected.

### F3 (P2, capture exemption covers dependency-induced staleness; `captured_edits` does not backstop) — behavior STILL PRESENT (by design), docs note FIXED

Reproducer on `m1` (`release_gate: {captured_edits: {release: true}}`,
CMP-003 captured-unedited at rail `12 V`, span stored `3.00 V`): move the
rail to `11 V`, `build --reseal` (the sealed rail-reference DSN-002 needs
the reseal), then
`refdes … release f3-move` → warning `inline calc Vd2: stored result says
3.00 V, now computes 2.75 V` visible, `captured_edits` **pass**, release
**stamps**, exit 0. Reproduced identically at `78c8954`. The docs now state
the consequence explicitly ("The exemption follows the captured text, not
upstream values that move afterward" — `docs/math.md`, and
`docs/lifecycle.md`'s rationale paragraph), which is exactly what F3 asked
for. No gate backstop at any setting (unchanged); recorded as by-design.

## Fresh attacks (this re-run's own cases, same CLI)

| # | Attack | Result | Verdict |
|---|---|---|---|
| A1 | Corrupt store, **no** stale spans in play, `captured_edits` overlay on (`cons` project, captured item) | inline-calc gate silent (`pass`), release stamps, exit 0; the build's warning names the decline ("edited-after-captured was not checked: the history store could not be read (…)") | PASS as designed (rule docstring: "a broken store with no inline-calc work is not this rule's business"); `captured_edits`' fail-open-when-enabled posture is the one the original report documented as its default-off tradeoff |
| A2 | `:=` lines inside a fenced code block (```python fence) | inert — no span extracted, no warning, gate silent | PASS (docs: spans scanned in prose only) |
| A3 | Unclosed `<!--` swallowing a stale span | one warning at the comment's line ("spans under this line are not checked"); the swallowed span is not a warning and not an offender | PASS as documented |
| A4 | Stale span inside a closed HTML comment | inert, no warning, gate silent | PASS |
| A5 | Span name duplicating a fence name in the same item | `ERROR … 'x' is assigned twice` at the span line → error floor, release exits 1, gate table never printed | PASS (floor precedes gate; no false gate pass) |
| A6 | Bare-id cross-item span `Vb := CMP-004.V_in | mV = 11000 mV` in a Markdown item | writable load rewrites to the composite `CMP-004@jkawnsjkpfg.V_in`; renaming the target (`id: CMP-004` → `CMP-006`) refreshes the handle on next load; reference resolves, 0 errors | PASS (hash-6 / key machinery keeps span refs live) |
| A6b | Rail moves under that bare-ref span **after** the rename | offender `CMP-005: inline calc Vb (items/cmpy.md:10)` on the span line, exit 1 | PASS (renames do not strand offenders) |
| A8 | Stale span in `pages/guide.md` (a page, not an item) | not evaluated: `check` reports no warning for it; gate silent; release blocks only on item spans | PASS as designed (spans live in item bodies) — recorded for the pages-vs-items coverage question |
| A9 | Unit forms: stored `4520 mV` vs computed `4436 mV`; bare cross-ref with unit assertion; stored `4.4 V` vs computed `4.436 V` | stale offender shown in the stored unit (`stored result says 4520 mV, now computes 4436 mV`); the unit-asserted bare ref is a legal fresh span; `4.4 V` accepts `4.436` — no warning, gate silent | PASS (window/units per docs/math.md) |
| A10 | CRLF-terminated Markdown item file with a stale span | warning and offender at the exact span line (`items/crlf.md:8`), exit 1 | PASS (line arithmetic unaffected) |
| A11 | Capture-exempt stale span + store corrupted (`atk`, CMP-003 captured) | with store readable: exempt, not an offender; corrupt the capture event: offender list = store line + the previously-exempt span ("could not prove the exemption"); restore store: re-exempted | PASS — the F13-1 fix's stated design, round-trips cleanly |
| A12 | `--no-write release` with the store corrupted | identical FAIL row (store line first), exit 1 — no write-path asymmetry | PASS |
| A13 | Non-ASCII span name (`` `Voüt := 1 V * 2 = 9 V` ``) | ERROR at the span line quoting the full span text ("not a calc name before `:=`", suggests the double-backtick hatch) → floor, gate never consulted | PASS (no offender-text mangling is possible: exotic labels are errors, not stale warnings) |
| A14 | Id-less continuation with **no minted key** (read-only load, `--no-write`, key line stripped from `m4/items/notes.md`) | release blocked (fails closed) — offender renders as `: inline calc Vfb (items/notes.md:12)` with a **leading colon and empty label** | CHANGED-minor — new finding **F-R1** below; not a bypass |
| A16 | Same display `id:` in two files | `ERROR … duplicate id 'CMP-001' (also defined at …)` → floor, exit 1, gate not consulted | PASS (the original's "id-shadowing not a bypass" reading, now exercised: the floor blocks first) |

### F-R1 (P3, cosmetic, new at `78c8954`) — offender label is empty for an id-less item whose key is not yet minted

`_rule_inline_calc_results` builds the offender as `f"{item.id or
item.key}: {span}{location}"`; a permanently id-less continuation with no
key on disk and no writable-load minting produces the offender row
`: inline calc Vfb (items/notes.md:12)` — a bare `": "` prefix. The
information promised by `docs/lifecycle.md` (file and line "otherwise") is
all present in the parens, so the failure is still actionable; the label is
just empty. A normal writable run (`refdes release` with write) mints the
key first and names the offender by key (re-verified in the same project:
`ehdg2ky1pdr: inline calc Vfb (items/notes.md:13)` — the line shifts by one
because the inserted key line moves the body, correctly). Cosmetic docs/
polish note for the implementing lane: name the label
`file:line`-style when both id and key are empty.

## No-finding areas (bounded evidence, this re-run)

- The 18-row matrix shows no behavioral drift from PR head to `78c8954`
  (rows 3/4/7 exemptions, rows 5/6 fail-closed paths, rows 9/16 offender
  shapes, rows 10–15 overlay/`--no-write`/revision posture, rows 17–18
  scope/docs).
- The hand-fabricated key incident (see hygiene) is evidence the key floor
  is loud: a forged `key:` line yields `ERROR … check character mismatch`
  plus a baseline-key-comparison ERROR, both floor-level.
- `stamp`'s single gate call site is unchanged in shape (rule table printed
  only on the block path, `pass` rows visible in the blocked table).

## Probe hygiene

- Two self-inflicted states were detected and disclosed rather than papered
  over: (1) an A1-setup restore overwrote m1's second event file (CMP-003's
  capture) with a copy of the first event — the store's own validator raised
  `event id … does not match its filename` and the gate failed closed on it
  (visible in the F3 first attempt). Recovery: deleted the file, re-captured
  CMP-003 via the shipped CLI, re-ran F3 on the clean store (cited result is
  the clean run). (2) Row 16's first attempt hand-wrote a bogus `key:` line
  on CMP-001, poisoning it against the `rev-12` baseline; restored the real
  key (named by the baseline/error) per the error message's own instruction;
  the cited row-16 run is the clean one.
- Row 8/row-16 line numbers cited are this scaffold's lines (my files differ
  from the original's by a line here and there); the claims verified are
  *exactness*, not the numbers themselves.
- All corrupt-store probes restored their stores; final `m1` state blocks
  only on CMP-001.
- Not run / not claimed: the full test suite (only the two gate/lifecycle
  test files), `ruff check .` (documented ~99-finding baseline, not a gate),
  the id-shadowing-via-imports end-to-end path (unchanged area, original
  lane's reading stands), offender text with exotic *span labels* that parse
  (A13 shows such labels cannot reach the stale-warning path).
