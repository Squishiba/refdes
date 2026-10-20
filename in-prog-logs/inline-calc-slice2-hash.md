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

## Step 2 (done)

Cross-item span refs as dependency edges and hash inputs (all gated
`HASH_FORMAT >= 6` so reconstruction of formats <= 5 ignores spans):
`_calc_reference_targets` includes span targets (scheduler orders them —
F12-5 updated to a passing ordering-edge test); the obsolete "span
reference not yet evaluated" branch in `_make_calc_resolver` is gone;
`_calc_reference_values` / `_calc_refs_hash_value` /
`calc_reference_snapshot` / `hash_payload_builder` take `include_inline`;
`links._calc_ref_rewrites` rewrites span target halves so expansion
(`plan_calc_ref_expansion`, `expand_missing_calc_refs`) covers spans.
Full suite: 4196 passed, 2 skipped.

## Step 3 (done)

`source()` in spans: `citations.collect_source_uses` discovers span
`source()` calls (so `refdes fetch` pins the keys a span names),
`serve/sources.py:body_source_pairs` shows them; the obsolete
"move to the fence form" advice in `_make_source_resolver` is retired
(F12-6 rewritten as a fetch-pins-the-span test); `docs/math.md` and the
design doc status updated. Full suite: 4196 passed, 2 skipped.

## Step 4 (this commit; steps 2-3 ride in it — their build.py hunks
## interleave with the bump's, and the full suite ran green at each step)

`HASH_FORMAT` 5 -> 6. Evidence, all green:

- (a) Golden byte-identity: `.scratch/record_golden.py` builds a fixture
  with the archived `origin/main` code (format 5), then the branch code
  rebuilds the same on-disk state — all five items' content hashes, the
  baseline, the release baseline and the seal file are byte-identical;
  the inline-span item's content hash is identical (its span is
  result-only; it gains only a probe). Committed mirror of the rule:
  `test_block_only_calc_hash_is_the_block_only_hash`,
  `test_format5_reconstruction_excludes_span_inputs`.
- (b) Old seal + old baseline (recorded by the main code, no probes,
  no span refs) verify clean under the new code: no
  `modified since it was sealed`, no new diagnostics, carry-forward
  migration silent (`_stale_arithmetic`/`_moved_refs` silent for the
  missing fields — tests in `tests/test_inline_calc_hash.py`).
- (c) Editing the referenced value moves the span item's hash and the
  stale verdict signal fires; a result-only edit moves the content hash
  (body invalidates) but not the probe
  (`test_editing_a_referenced_value_moves_the_span_item`,
  `test_result_only_edit_keeps_the_span_probe`).
- (d) `fetch` + `fetch --update` of a span's `source()` input moves the
  item's hash (`test_span_source_edit_moves_the_item`).
- (e) Adversarial: cycle via a span errors with the cycle path, missing
  span target gets the standard "does not exist" error, sealed item
  verifies clean (above), three spans on one item all enter the probe
  and snapshot (`test_span_reference_cycle_is_reported`,
  `test_span_missing_target_is_a_clean_error`,
  `test_several_spans_one_item_all_enter_the_snapshot`).

Docs: `HASH_FORMAT` history comment in `build.py`, `docs/lifecycle.md`
(format list + baseline examples), `docs/change-tracking.md`,
`changelog.d/inline-calc-spans-hash.changed.md`.

## Notes

- `ruff check .` has ~99 pre-existing findings; only check touched files
  with `--select E9,F` (AGENTS.md).
- Tree shared with concurrent sessions: staged by explicit paths, no
  stash. `origin/main` gained `c9ecc30` (docs) after branch point; rebase
  before push.

## Review round (PR #347 head c5c3b8d)

Three cross-model reviewers (chunks: docs+build / inline_calc / links+serve).
Chunk 2 and chunk 3 returned CHANGES REQUESTED; chunk 1 ended without a
verdict (no findings). Fixes, each with a red-on-this-head test first:

- RHS-comment parity (chunk 2): `span_cross_ref`/`span_source_call` now
  strip a trailing `#` comment with the evaluator's own quote-aware
  `split_comment` before matching -- `evaluate_block` strips it before
  `CROSS_REF_RE`/`SOURCE_START_RE`, so matching raw text made a commented
  reference invisible to the scheduler (span ran before its target, leaked
  an internal AttributeError) and to `fetch` (F12-6 dead end).
- Span-scan geometry (chunk 3): `links._calc_ref_rewrites` takes
  `inline_start`; `plan_calc_ref_expansion` bounds the span scan to
  `item.body_line` (was `source_line`-1, the front-matter fence). A
  front matter ending in an unclosed fence marker used to hide every body
  span (silent non-expansion, no report); a span in front matter used to
  be rewritten on disk while the in-memory pass rewrote only `item.body`.
- Direct coverage (chunk 3): `body_source_pairs` span branch tested in
  `tests/test_serve_sources_accept.py` (fence branch as control).
- Stale comments/labels fixed (`iter_triggered_spans` docstring is now an
  explicit assumption, `code_span_ranges` dead branch, `links.py` range
  justification, run-12 test header, test section renumbering, `= 24 V`).

Verified: the 4 new geometry/parity tests fail on `c5c3b8d` and pass after;
full suite 4207 passed, 2 skipped; ruff `--select E9,F` clean on touched
files; golden (a) rebuild byte-identical (all five item hashes, baseline,
release, seal).

Scope note: a source() span with `#` before the pipe (`source(...) # note
| V = 5 V`) is broken in the evaluator itself (the comment swallows the
unit declaration) -- the fix restores discovery parity; the evaluator's
unit rule for that shape is out of scope.
