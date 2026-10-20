# inline-calc slice 2: spans enter calc_hash, dependency scans, content hash

Branch `feat-inline-calc-slice2-hash`, base `main` @ `c9ecc30`, rebased onto
`1d6d325`. Owner decision 2026-10-19: change the hash format despite
baseline/seal risk. Plan: `docs/design/inline-calc.md` §3, four green steps.

## Step 1 (done, this commit)

`calc_hash_for` (`src/refdes/build.py`) now hashes inline calc spans
alongside fence blocks: events at source offsets, spans rendered
`name := rhs [| unit]` with the stored result excluded (a result-only edit
leaves the probe fixed; an arithmetic edit moves it); a malformed span
contributes its raw text. Span-free items produce the identical
`{"calc_blocks": [...]}` payload (no baseline churn); an old baseline with
no `calc_hash` for a span-only item is silent in `_stale_arithmetic`
(verified by test). Helpers added for later steps: `code_span_ranges`
(positional view), `span_cross_ref` (whole-RHS `CROSS_REF_RE` match),
`span_source_call`. New `tests/test_inline_calc_hash.py` (8 tests); 257
passed.

## Step 2 (done)

Cross-item span refs as dependency edges and hash inputs (gated
`HASH_FORMAT >= 6`): `_calc_reference_targets` includes span targets
(scheduler orders them -- F12-5 is now a passing ordering-edge test), the
"span reference not yet evaluated" branch in `_make_calc_resolver` is
gone, the ref-scan/hash helpers take `include_inline`, and
`links._calc_ref_rewrites` rewrites span target halves so expansion covers
spans. Full suite: 4196 passed, 2 skipped.

## Step 3 (done)

`source()` in spans: `citations.collect_source_uses` discovers span
`source()` calls (fetch pins them), `serve/sources.py:body_source_pairs`
shows them; the "move to the fence form" advice is retired (F12-6
rewritten as a fetch-pins-the-span test); docs updated.

## Step 4 (this commit; steps 2-3 ride in it — their build.py hunks
interleave with the bump's, and the full suite ran green at each step)

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
- (c) Editing the referenced value moves the span item's hash and fires
  the stale signal; a result-only edit moves the content hash, not the
  probe. (d) `fetch`/`fetch --update` of a span's `source()` input moves
  the item's hash. (e) Adversarial: span cycle reports the cycle path,
  missing target is a clean error, three spans on one item all enter the
  probe; snapshot `calc_refs` is deduped while the probe covers every
  occurrence. Docs: `build.py` format-history comment, `docs/lifecycle.md`,
  `docs/change-tracking.md`, `changelog.d/inline-calc-spans-hash.changed.md`.

## Review round (PR #347 head c5c3b8d)

Three cross-model reviewers (chunks: docs+build / inline_calc / links+serve);
chunks 2 and 3 returned CHANGES REQUESTED, chunk 1 no findings. Fixes, each
with a red-on-this-head test first:

- RHS-comment parity (chunk 2): `span_cross_ref`/`span_source_call` strip a
  trailing `#` comment with the evaluator's quote-aware `split_comment`
  before matching (`evaluate_block` strips it before the ref/source
  regexes) -- raw-text matching hid commented references from the scheduler
  (F12-5 AttributeError leak) and from `fetch` (F12-6 dead end).
- Span-scan geometry (chunk 3): `links._calc_ref_rewrites` takes
  `inline_start`; `plan_calc_ref_expansion` bounds the span scan to
  `item.body_line` (was `source_line`-1, the front-matter fence). A front
  matter ending in an unclosed fence marker used to hide every body span
  (silent non-expansion); a span in front matter used to be rewritten on
  disk while the in-memory pass rewrote only `item.body`.
- Direct coverage (chunk 3): `body_source_pairs` span branch tested in
  `tests/test_serve_sources_accept.py`. Stale comments/labels fixed.

Verified: the 4 new tests fail on `c5c3b8d`, pass after; full suite 4207
passed, 2 skipped; ruff `--select E9,F` clean on touched files; golden (a)
byte-identical. Scope note: a source() span with `#` before the pipe is
broken in the evaluator itself (the comment swallows the unit declaration)
-- out of scope; the fix restores discovery parity.

## Round 2 + rebase onto main (#351) + AgentCoder pilot triage

Round-2 review fixes (HIGH: format-5 seal of a span item broke --
`_hash_payload` strips `@key` from expanded span targets for formats <=5;
links `_replace_ref_target` splices at the match range instead of
`content.replace`; span-only targets of YAML-list-file items are excluded
from expansion, `body_line is None`). Red-green verified; full suite 4269
passed, 4 skipped; golden (a) rebuilt (only the span item's hash moves),
(b) old format-5 seal verifies clean after expansion.

Rebase onto 1d6d325 kept #351's comment-aware scanner: merged scan into
one `_scan_body` returning positioned `(offset, start, end, content)`
spans, with `triggered_spans`/`triggered_span_events`/
`unclosed_comment_offset` as thin views; one test-ordering conflict
(span-pin fetch vs #351's fence control) resolved in favour of both.

AgentCoder pilot (suite installed as
tests/test_inline_calc_agentcoder_trial.py): its 3 span failures all put
a cross-item ref *inside* arithmetic (`Vb := LOG-A.V_in * 2`), which the
evaluator only resolves for a whole-RHS ref (calc.py
`CROSS_REF_RE.match(expression.strip())`) -- a fence control with the
same expression fails identically. Verdict: test assumptions, not
slice-2 defects; the copy was adapted to whole-RHS form, its two
`release_gate` tests skipped (that gate is #345, unmerged). Strengthened
the review's weak assertions (span-pin pins the content-hash move;
snapshot dedup split from probe coverage; malformed-span probe mutation).
F1 (reproduced in `.scratch/f1verify/`): a pre-slice-2-code fetch
rewrites the lockfile whole and drops a span's `values:` pins --
recorded as a rollout caveat in the changelog fragment (recoverable by
a new-code fetch; a compat fix belongs to shipped code).

## Round 3 (head 7f533f6)

- Chunk 2 MEDIUM: `parse_span` splits `| unit` BEFORE stripping the
  trailing `#` comment, the evaluator does the reverse; a comment
  containing `|` (the unit class excludes `|`) lands the split on the
  comment's pipe and hides the ref/`source()` from the scans -- reviving
  the F12-5 leak (span ordered before its target, bare resolver reads
  `_env`). New `_evaluator_rhs` rebuilds the evaluator's order for
  `span_cross_ref`/`span_source_call`; parse_span's hash field text is
  untouched. Red tests: a leaked span must precede its target in file
  order (span-first a.md).
- Chunk 3 MEDIUM: the in-memory pass of `expand_missing_calc_refs`
  expanded list-file spans that the file path excludes -- first-run
  calc_hash/rendering not reproducible from the same bytes (silent
  stale-arithmetic). Gate: `include_inline=item.body_line is not None`;
  red on two-run hash stability. LOW: the fence pass recomputed from the
  stale `raw` after span edits and clobbered them while `applied` counted
  them -- re-anchors `raw` after the span write; red on a line that is
  both pipe-fence grammar and a triggered span.
- LOW/nits: gate skips now `skipif` on `refdes.release_gate` existence
  (auto-run when #345 lands); agentcoder docstring dropped its
  gitignored `.scratch` pointer; `iter_triggered_spans` renamed
  `triggered_span_events`; front-matter line-number comment corrected.

Full suite 4273 passed, 4 skipped; red-green re-verified by swapping
HEAD copies of the fixed modules in place (conftest hard-prepends src,
so a PYTHONPATH overlay is ignored under pytest).
