# feat(release): release_gate.inline_calc_results

Task: implement the owner-decided inline-calc freshness gate rule
(docs/design/inline-calc.md §2, open question 2 decided): stale stored
results in editable items fail `refdes release`; sealed/captured entries
are exempt and keep their warning; default `{release: true, revision: false}`.

## What landed

- `src/refdes/model.py`: new diagnostic code constant
  `INLINE_CALC_STALE = "inline_calc_stale"` (the gate reads the build's stale
  warning by code, never by prose), and the rule entry appended to
  `RELEASE_GATE_DEFAULTS` (order = gate-table order, last position).
  Header comment updated.
- `src/refdes/build.py`: the stale-result `project.warn` in
  `_run_inline_span` now tags `code=INLINE_CALC_STALE`.
- `src/refdes/lifecycle.py`: `_rule_inline_calc_results` registered in
  `_RULES`. Reads `project.warnings` (the build already ran), resolves the
  item by `item_id`, skips imported items, and exempts build-sealed items.
  Captures are exempt only when `capture_index` reports their edited flag
  false; an edit after capture leaves the live text editable and blocks.
  History-store read failures return no offenders, matching the fail-open
  posture of `_rule_captured_edits`. Offenders use
  `ID: inline calc <span> (file:line)`.
- `src/refdes/schema.py`: nothing to change — validation is
  `RELEASE_GATE_DEFAULTS`-driven, so `{release, revision}` mapping accepted,
  unknown subkey rejected, rename/difflib errors keep working. Verified by
  hand and by the new test in `tests/test_project_settings.py`.
- `refdes release --help` picks the rule up from `RULE_NAMES` automatically.

## Judgment calls

- Exemption = frozen text, read from the live seals/history store, not from
  type metadata. Build seals are immutable while the release build checks
  them. Captures are frozen only while their live digest matches the
  snapshot; `capture_index`'s edited flag makes that distinction explicit.
  Fail-open posture copied from `_rule_captured_edits` (store unreadable =>
  no offenders), per the task's fail-open rule.
- Imported items skipped (their stale spans are the other project's
  problem), like every other rule.
- Offender carries the warning's own file:line (the span line, clickable)
  and the span name from the warning head.

## Hand-run (./.scratch/inline-gate-log/demo, hardware@3)

    $ refdes check
    WARNING items/notes.md:9 [CMP-001] — inline calc Vout: stored result says 4.52 V, now computes 4.436 V
    1 items, 0 errors, 1 warnings
    $ refdes release rel-a; echo "blocked exit=$?"
    ...
      FAIL     inline_calc_results  CMP-001: inline calc Vout (items/notes.md:9)
    blocked exit=1
    $ printf 'release_gate:\n  inline_calc_results: { release: false }\n' >> refdes-project.yaml
    $ refdes release rel-b
    WARNING items/notes.md:9 [CMP-001] — inline calc Vout: stored result says 4.52 V, now computes 4.436 V
    1 items, 0 errors, 1 warnings

    release 'rel-b' stamped: 1 items, all gates passed.
    # overlay removed; LOG-001 (log type, captured via `refdes history
    # capture LOG-001`) carries a stale span:
    $ refdes release rel-d
    WARNING items/log.yaml:2 [LOG-001] — inline calc Vfb: stored result says 9.9 V, now computes 4.436 V
    1 items, 0 errors, 1 warnings

    release 'rel-d' stamped: 1 items, all gates passed.
      .refdes/baselines/rel-d.yaml

## Tests

- `tests/test_lifecycle.py`: 6 new tests (stale editable span blocks +
  names item/span/line + revision stamps through it; rule off passes;
  fresh span passes; unedited capture exempt; captured-then-edited span
  blocks; build-seal exempt); the full-gate-block baseline assert now
  includes `"inline_calc_results": "pass"`.
- `tests/test_project_settings.py`: defaults dict updated; new test asserts
  the `{release, revision}` mapping is accepted for the new rule and an
  unknown subkey errors like the others.
- Docs: `docs/math.md` (inline-calc section), `docs/lifecycle.md` (defaults
  block, rule table, why-on paragraph, example tables, baseline gate block),
  `docs/troubleshooting.md` (Math section entry),
  `docs/design/inline-calc.md` (§2 proposal text -> landed text).
- Changelog: `changelog.d/inline-calc-release-gate.added.md`.

## Verification

- Full suite: `PYTHONPATH=$PWD/src ... pytest -q` — 4186 passed, 2 skipped.
  One anchor failure surfaced mid-run (`docs/math.md` linked
  `lifecycle.md#the-configurable-layer`; the heading is "The readiness
  gate") — fixed, anchors test green.
- `ruff check <touched files> --select E9,F` — clean.

Task finished: yes.

## Review round 1 (PR #345, reviewer 46737de9)

- Finding: presence in `capture_index` included edited-after-capture items,
  so a stale span added after capture was exempt. Fixed by using the index's
  edited flag; only unedited captures are frozen.
- Added a regression test that was red on head `575d4fe` and passes after
  the fix; unedited capture and build-seal tests remain green.
- Rebased on `origin/main` and reran focused/full tests; results recorded
  below.

## Review round 2 (PR #345, reviewer 13709193)

- Finding: the gate resolved stale warnings by display id only. A valid
  id-less continuation emits `item_id=""`, so `item_by_id("")` returned None
  and the stale span bypassed the release gate.
- Reproduced on the pre-fix head through real `refdes release`: the stale
  warning was visible and the release stamped.
- Fix: resolve by display id first; for an empty id, match the diagnostic's
  exact file and source/body line to a local item with the same empty id.
  Sealed and unedited-capture exemptions remain applied per resolved item.
- Added `test_inline_calc_results_id_less_continuation_span_blocks_release`,
  red on the pre-fix head and green after the fix. Docs/changelog now name
  the surrogate-key offender shape.
- Rebased on latest `origin/main` and reran required gates; see below.

## Review-round verification

- Round 1 regression test was red on `575d4fe` and green after the fix.
- Round 2 regression test was red on `4e89eab` (gate `pass`, expected `FAIL`)
  and green after the source-location fix.
- Focused rebased run: 7 inline-calc lifecycle tests, 7 release-gate
  settings tests, and 2 docs-anchor tests passed.
- Full rebased suite: 4194 passed, 2 skipped.
- `ruff check <touched files> --select E9,F`: clean.
