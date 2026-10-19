# inline-calc slice 2: spans enter calc_hash, dependency scans, content hash

Branch `feat-inline-calc-slice2-hash`, base `main` @ `c9ecc30`. Owner
decision 2026-10-19: change the hash format despite baseline/seal risk.
Plan is the design doc's section 3 (`docs/design/inline-calc.md`), executed
in four steps, each its own commit + green full-suite check.

## Step 1 (done, this commit)

`calc_hash_for` (`src/refdes/build.py`) now hashes inline calc spans
alongside fence blocks: events at source offsets, spans rendered
`name := rhs [| unit]` with the stored result excluded (a result-only edit
leaves the probe fixed; an arithmetic edit moves it); a malformed span
contributes its raw text. Items with no spans produce the identical
`{"calc_blocks": [...]}` payload as before, so existing baselines don't
churn. An old baseline with no `calc_hash` for a span-only item is silent
in `_stale_arithmetic` (existing `continue` on missing field — verified by
test, not code change).

Helpers added to `src/refdes/inline_calc.py` for later steps:
`code_span_ranges` (positional view; `code_spans` is now the content view
over it — one scanner, no drift), `span_cross_ref` (whole-RHS `CROSS_REF_RE`
match, same grammar the evaluator uses), `span_source_call`
(`SOURCE_START_RE` + `parse_source_call` on the span RHS).

Tests: new `tests/test_inline_calc_hash.py` (8 tests: probe presence for
inline-only items, result-only fixed, RHS/name/unit edits move it,
block-only hash byte-identical to the blocks-only formula, positional
ordering, malformed-span probe, stale-signal silent/active). Full affected
suites: 257 passed.

## Remaining steps

2. Cross-item span refs as dependency edges: `_calc_reference_targets` /
   `_calc_reference_values` / `_calc_refs_hash_value` (gated format >= 6),
   `links._calc_ref_rewrites` span-aware.
3. `source()` spans: `citations.collect_source_uses` span discovery, retire
   the obsolete span source advice, docs.
4. `HASH_FORMAT` 5 -> 6 with golden no-inline-span byte-identity recorded
   from `origin/main` code via `.scratch/main-src`, old baseline/seal
   survival, adversarial (cycle/missing/sealed/multi-span) tests, changelog.

## Notes

- `ruff check .` has ~99 pre-existing findings; only check touched files
  with `--select E9,F` (AGENTS.md).
- Tree shared with concurrent sessions: staged by explicit paths, no
  stash. `origin/main` gained `c9ecc30` (docs) after branch point; rebase
  before push.
