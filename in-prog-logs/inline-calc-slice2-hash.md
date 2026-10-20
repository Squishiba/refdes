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
in `_stale_arithmetic` (verified by test, not code change).

Helpers added to `src/refdes/inline_calc.py` for later steps:
`code_span_ranges` (positional view; `code_spans` is now the content view
over it), `span_cross_ref` (whole-RHS `CROSS_REF_RE` match, same grammar
the evaluator uses), `span_source_call` (`SOURCE_START_RE` +
`parse_source_call` on the span RHS).

Tests: new `tests/test_inline_calc_hash.py` (8 tests: probe presence,
result-only fixed, edits move it, block-only byte-identical, positional
ordering, malformed probe, stale-signal silent/active). 257 passed.

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
  probe; the snapshot's `calc_refs` set is deduped while the probe covers
  every occurrence.

Docs: `HASH_FORMAT` history comment in `build.py`, `docs/lifecycle.md`
(format list + baseline examples), `docs/change-tracking.md`,
`changelog.d/inline-calc-spans-hash.changed.md`.

## Notes

- `ruff check .` has ~99 pre-existing findings; only check touched files
  with `--select E9,F` (AGENTS.md). Tree shared with concurrent sessions:
  staged by explicit paths, no stash.

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

## Round 2 + rebase onto main (#351) + AgentCoder pilot triage

Round-2 review fixes (HIGH: format-5 seal of a span item broke --
`_hash_payload` now strips `@key` from expanded span targets for formats
<=5; links `_replace_ref_target` splices at the match range instead of
`content.replace` (name/target collisions); span-only targets of items
loaded from YAML list files are excluded from expansion (markdown
geometry, `body_line is None`). Red-green: seal pair + collision + YAML
tests fail on the unfixed head, pass after; full suite 4269 passed,
4 skipped on the rebased head; golden (a) rebuilt (hash_format 5->6, only
the span item's hash moves), (b) evidence: old format-5 seal verifies
clean after expansion.

Rebase onto 1d6d325 kept #351's comment-aware scanner: merged scan into
one `_scan_body` returning positioned `(offset, start, end, content)`
spans; `triggered_spans`/`iter_triggered_spans`/`unclosed_comment_offset`
are thin views; one test-ordering conflict (span-pin fetch vs #351's
fence control) resolved in favour of both.

AgentCoder pilot (suite in tests/test_inline_calc_agentcoder_trial.py):
its 3 span failures all put a cross-item ref *inside* arithmetic
(`Vb := LOG-A.V_in * 2`), which the evaluator only resolves for a
whole-RHS ref (calc.py `CROSS_REF_RE.match(expression.strip())`) -- a
fence control with the same expression fails identically. Verdict: test
assumptions, not slice-2 defects; the suite copy was adapted to
whole-RHS form, its two `release_gate` tests carry a skip marker (that
gate is #345, unmerged -- gate code untouched). Strengthened the
review's weak assertions (span-pin now pins the content-hash move, not
the literal `5 V` in `body_html`; snapshot dedup vs probe coverage split;
malformed-span probe mutation). F1 follow-up (post-push, reproduced in
`.scratch/f1verify/`): a fetch by pre-slice-2 code rewrites the lockfile
whole and drops a span's `values:` pins -- decided as a rollout caveat in
the changelog fragment (recoverable by a new-code fetch; a compat fix
belongs to shipped code and is not ours to make here).
