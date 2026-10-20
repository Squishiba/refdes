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
  `_RULES`. Reads `project.warnings` (the build already ran), resolves stale
  warnings by display id, with body-range location lookup for id-less
  continuations, skips imported items, and exempts build-sealed items.
  Captures are exempt only when `capture_index` reports their edited flag
  false; an edit after capture leaves the live text editable and blocks.
  With a stale span in play, an unreadable history store fails the gate
  closed and names the store. Offenders use
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
  The release gate is fail-closed for an unreadable store because a missing
  store cannot prove the frozen-text exemption.
- Imported items skipped (their stale spans are the other project's
  problem), like every other rule.
- Offender carries the warning's own file:line (span line in Markdown;
  list-file `body:` keys report the item-entry line) and the span name from
  the warning head.

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

## Review rounds (PR #345)

- Review 1: mere capture presence included edited-after-capture items. Fixed
  to use `capture_index`'s edited flag; only unedited captures are frozen.
- Review 2: id-less continuation has `item_id=""`, so display-id lookup missed
  it. Added empty-id location fallback and surrogate-key naming.
- Review 3: Markdown continuation diagnostics are emitted at the span line,
  which can be deeper in the body. Exact source/body-line matching missed
  them. The fallback now inverts the build's location rule: body range for
  Markdown, source line for list-file bodies.
- Independent P1: unreadable history store produced no offenders, letting a
  stale never-captured item stamp. The gate deliberately fails closed now and
  names the store. Multiline parser context is collapsed into one gate row.
  Sealed and readable unedited-capture exemptions remain.
- P2 assessments documented: list-file bodies report the item-entry line;
  capture exemption follows captured text, not later upstream moves.
- P2 healthy-store resolver miss: public build emits stale warnings only
  from local items, and id/body-location invariants return the emitting item.
  The gate now fails closed on an unresolved coded warning while imported
  items remain skipped. Added an all-resolve control over first/later Markdown
  and list-file body emissions.
- P3 dead local/external branches: lookup returns local-only items, and the
  unreadable-store path uses the same resolver. Imported skip is explicit.
- Final docs polish removed a truncated lifecycle-table sentence and named
  `RETIRED_UNIT_SPELLING` in the `Diagnostic.code` comment.
- Clarified the inline-calc design header and section statuses against `main`,
  this PR, and open PR #347.
- Qualified id-less inline-calc release offenders as keyed only when a
  surrogate key has been minted, with file-and-line as the cold fallback.

## Review verification

- Snapshot at the prior round: location fallback and unresolved-warning
  fail-closed controls ran 14 inline-calc lifecycle tests.
- Snapshot: combined lifecycle/settings/docs ran 20 tests.
- Snapshot: full suite and ruff results are recorded in the PR body.
