# f13-1 designer — blind test author

Task: write tests (no product code) for F13-1: the inline-calc release gate
fails closed on an unreadable history store but the blocked-release output
never named the cause. I am blind to the implementation; tests encode the
contract's required behavior.

## What I did

- Read `lifecycle._rule_inline_calc_results` (~819) and the surrounding
  gate/print channel: `evaluate_gate` -> `GateRuleResult.offenders` ->
  `cli._print_gate_table` (`  {status:<8} {name}  {offenders joined ", "}`),
  printed to stderr on a blocked `refdes release`. Confirmed the "channel" the
  new line must use is the rule's returned offender list.
- Store path relative to root: `history.HISTORY_DIR` = `.refdes/history`.
- Modeled fixtures on `tests/test_lifecycle.py` inline_calc helpers
  (`IC_CONFIG`, `IC_STALE_BODY`, `_ic_rebuild`), rebuilt from the on-disk
  config so line numbers match.
- Unreadable store simulated by monkeypatching `history.capture_index` to
  raise `OSError` (NOT chmod, per contract). lifecycle imports history as
  `history_mod` (same module object), so patching the module attribute is
  seen by the rule; `captured_edits`/`capture_facts` already catch OSError, so
  build/other rules don't crash.

## Tests written

`tests/test_inline_calc_gate_unreadable_history.py`, 5 cases:
- unreadable + stale span -> offenders[0] == exact contract line
  `stale inline-calc gate: cannot read the history store .refdes/history
  (simulated store failure) -- failing closed`, offender listed after;
  stamp gate_failed. (expected_on_base: fail)
- same line reaches `refdes release` stderr FAIL row. (fail)
- unreadable + NO stale span -> pass, prints nothing new, stamps. (pass)
- readable store + stale span -> one offender, no store line anywhere. (pass)
- unreadable + TWO stale spans -> store line appears EXACTLY once, both
  offenders behind it. (fail)

`tests/f13-1.cases.json` maps all 5 node ids.

## Verification

- Base (old code): 3 fail / 2 pass, exactly as intended. Base offender list is
  the OLD `history: inline calc freshness cannot be checked: history store
  unreadable (simulated store failure)` (single line, no path, offenders not
  listed) — matches the bug description.
- Satisfiability: built a scratch patch of the rule in `.scratch/f13-1/src`
  implementing the contract form and ran the cases (via a no-conftest driver,
  since `tests/conftest.py` prepends worktree `src/` to sys.path and masks
  PYTHONPATH): unreadable+stale -> [cause, offender]; unreadable+fresh -> pass
  []; unreadable+2stale -> [cause, off1, off2] with one cause. All match my
  assertions, so the tests are correctly scoped, not over-constrained.

## Notes

- Did not touch docs; contract says docs already promise naming ("names the
  unreadable store") and the required form keeps that true. The changelog
  fragment is the implementer's, not mine (I write tests only).
- Finished.
