# Inline calc span grammar, R12-F1..F3

Implements the three owner-approved span-recognition decisions from the
run-12 release-gate simulation (findings F12-1..F3 in
`in-prog-logs/user-sim-release-gate-run12.md`). Branch
`fix/inline-calc-f12-grammar-20261020`, base `d620ab5` (origin/main at
handoff). Scope: span recognition only — no hashing, no dependency-order
work (that is PR #347).

## The three changes

- **F12-1 (HTML comments).** A code span inside `<!-- … -->` is inert, the
  way fenced code is. The trigger predicate (`contains_trigger`,
  `code_spans`) was left span-local; the skipping lives in the new
  `_scan_body`, which walks a body tracking fences (re-derived, matching
  `parse.py`'s opener rule) and comments, and yields prose lines with the
  comment regions blanked. An unclosed `<!--` reports its opener offset via
  `unclosed_comment_offset`; `build._run_item_calcs` turns that into one
  warning, mirroring the unclosed-fence warning.
- **F12-2 (loud ambiguity).** `parse_span` now checks the text before the
  first `:=` against `CALC_NAME_RE` and, when it is not a name, emits
  `'<text>' is not a calc name before `:=`` naming both ways out. The
  trigger still fires on the first `:=` (`first_trigger_index`), so the
  full span text is named.
- **F12-3 (tight separator).** `_top_level_equals` (space-required) became
  `_result_equals_positions`, accepting a tight `=` and excluding
  delimiters: the `=` of a `:=`, a comparison operator (`== <= >= !=`),
  and an `=` in quotes/brackets. `_split_readings` keeps a split only when
  the tail is a whole stored result; more than one is reported ambiguous.

## Reasoning that shaped the code

- The F12-1 repro spans all use a spaced `=`, so a F12-3 change alone
  does not silence F12-1 (F12-2 does not either — `Vout` is a valid name).
  F12-1 is a genuine third change.
- F12-1/F12-3 are not fully independent: a commented span whose separator
  was tight is a double miss on main (F12-3's "missing result" wins). A
  repro pinning the fix needs the comment repro to use a spaced separator.
- The evaluator is Python `eval` mode: a bare `=` is a syntax error and a
  comparison parses as `ast.Compare` and is rejected by `_eval_node`. So an
  expression has no valid `=`, which makes the multi-split ambiguity
  structural. `_split_readings` enforces the rule and a test exercises the
  guard through the seam; no live span reaches it.
- Two `=` like `x := 1 = 2 = 3` is NOT ambiguous: only the last `=` leaves
  a result literal, so one reading (rhs `1 = 2`, an eval error).

## Verification

- Full suite: 4226 passed, 2 skipped.
- `ruff check` on touched files (`--select E9,F`): clean.
- Differential, repo project (`refdes check --no-write`, baseline src at
  `d620ab5` vs patched): byte-identical.
- Differential, synthetic project of docs prose spans + F12 fixtures: the
  only diff is the three intended changes (comment span warning gone, F12-2
  message reworded, two tight spans now valid); docs spans unchanged.

## Integration

- PR #347 (`feat-inline-calc-slice2-hash`) is unmerged on main. It rewrites
  the same `build._run_item_calcs` body-scanning loop (adding a
  `_calc_referenced_id` / dependency-scan pass) and the same `inline_calc`
  scan region. The collision is confined to that loop; the fix is to add
  the unclosed-comment warning and the dependency scan to the same loop,
  and to keep the `calc_link_spans`/dependency entry points that #347's
  scan relies on. Rebase showed no conflict against main itself (main's two
  new commits are docs-only).

## Status

Complete: implementation, 40 new tests, docs (`docs/math.md`), three
changelog fragments, differential proof, full suite. Not self-reviewed or
merged.
