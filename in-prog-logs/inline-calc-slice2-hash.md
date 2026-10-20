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
"span reference not yet evaluated" resolver branch is gone, the
ref-scan/hash helpers take `include_inline`, and `links._calc_ref_rewrites`
rewrites span target halves so expansion covers spans. Full suite: 4196.

## Step 3 (done)

`source()` in spans: `citations.collect_source_uses` discovers span
`source()` calls (fetch pins them), `serve/sources.py:body_source_pairs`
shows them; the "move to the fence form" advice is retired (F12-6
rewritten). Docs updated.

## Step 4 (this commit; steps 2-3 ride in it — their build.py hunks
interleave with the bump's, and the full suite ran green at each step)

`HASH_FORMAT` 5 -> 6. Evidence, all green:

- (a) Golden byte-identity: `.scratch/record_golden.py` builds a fixture
  with the archived `origin/main` code (format 5), then the branch code
  rebuilds the same on-disk state — all five items' content hashes, the
  baseline, the release baseline and the seal file are byte-identical
  (the result-only span item gains only a probe). Committed mirror:
  `test_block_only_calc_hash_is_the_block_only_hash`,
  `test_format5_reconstruction_excludes_span_inputs`.
- (b) Old seal + old baseline (recorded by the main code) verify clean
  under the new code: no `modified since it was sealed`, no new
  diagnostics, carry-forward migration silent (tests).
- (c) Editing the referenced value moves the span item's hash and fires
  the stale signal; a result-only edit moves the content hash, not the
  probe. (d) `fetch`/`fetch --update` of a span's `source()` input moves
  the item's hash. (e) Adversarial: span cycle reports the cycle path,
  missing target is a clean error, three spans on one item all enter the
  probe; snapshot `calc_refs` is deduped while the probe covers every
  occurrence. Docs: `build.py` format-history comment, `docs/lifecycle.md`,
  `docs/change-tracking.md`, `changelog.d/inline-calc-spans-hash.changed.md`.

## Review round 1 (at the first review head of PR #347)

Three cross-model reviewers (chunks: docs+build / inline_calc / links+serve);
chunks 2 and 3 CHANGES REQUESTED, chunk 1 none. Fixes, each with a
red-on-this-head test first:

- RHS-comment parity (chunk 2): `span_cross_ref`/`span_source_call` strip a
  trailing `#` comment with the evaluator's quote-aware `split_comment`
  before matching -- raw-text matching hid commented references from the
  scheduler (F12-5 leak) and from `fetch` (F12-6 dead end).
- Span-scan geometry (chunk 3): `links._calc_ref_rewrites` takes
  `inline_start`; the plan bounds the span scan to `item.body_line` (was
  `source_line`-1, the front-matter fence). An unclosed fence marker at
  front-matter end hid every body span; a front-matter span was rewritten
  on disk while the in-memory pass rewrote only `item.body`.
- Direct coverage (chunk 3): `body_source_pairs` span branch tested in
  `tests/test_serve_sources_accept.py`. Stale comments/labels fixed.

Verified: the 4 new tests fail on the round-1 head, pass after; full suite
4207 passed, 2 skipped; ruff clean on touched files; golden byte-identical.

## Round 2 + rebase onto main (#351) + AgentCoder pilot triage

Round-2 review fixes (HIGH: format-5 seal of a span item broke --
`_hash_payload` strips `@key` from expanded span targets for formats <=5;
links `_replace_ref_target` splices at the match range instead of
`content.replace`; span-only targets of YAML-list-file items are excluded
from expansion, `body_line is None`). Red-green verified; full suite 4269
passed, 4 skipped; golden (a) rebuilt, (b) old format-5 seal clean.
Rebase onto 1d6d325 kept #351's comment-aware scanner: merged scan into
one `_scan_body` returning positioned spans, with
`triggered_spans`/`triggered_span_events`/`unclosed_comment_offset` as
thin views.

AgentCoder pilot (suite installed as
tests/test_inline_calc_agentcoder_trial.py): its 3 span failures all put
a cross-item ref *inside* arithmetic (`Vb := LOG-A.V_in * 2`), which the
evaluator only resolves for a whole-RHS ref (calc.py
`CROSS_REF_RE.match(expression.strip())`) -- a fence control fails
identically. Verdict: test assumptions, not slice-2 defects; adapted to
whole-RHS form, gate tests deferred to #345. Strengthened the review's
weak assertions. F1 (reproduced in `.scratch/f1verify/`): a pre-slice-2
fetch rewrites the lockfile whole, dropping a span's `values:` pins --
changelog rollout caveat.

## Round 3 (at the round-2 head; chunks 1-2 APPROVE at the next head)

- Chunk 2 MEDIUM: a comment containing `|` hid the ref/`source()` from
  the scans (parse_span splits the pipe before the comment is stripped,
  the evaluator's reverse), reviving the F12-5 leak; `_evaluator_rhs`
  rebuilds the evaluator's order for the scan helpers. Red needs
  span-before-target in FILE order (probe project pinned it).
- Chunk 3 MEDIUM: the in-memory pass of `expand_missing_calc_refs`
  expanded list-file spans the file path excludes -- first-run probe
  not reproducible from the same bytes; gated on `body_line`. LOW: the
  fence pass clobbered span edits on a line that is both shapes;
  re-anchor on the span-edited line.
- LOW/nits: gate skips `skipif` rule presence (see round 5); agentcoder
  docstring dropped its gitignored `.scratch` pointer;
  `iter_triggered_spans` -> `triggered_span_events`; front-matter
  line-number comment.

## Round 4 (at the round-3 head; chunk 3 CHANGES REQUESTED)

The round-2 list-file span skip ran BEFORE `_planned_target` in
`plan_calc_ref_expansion`, and that call is where the crossed-reference
refusal-and-warn (keys.md §3 case 2) is emitted -- a stale composite span
target in a YAML-list-file item lost the warning its fence-line twin
keeps (build resolves by key: page shows the key's item, source says
another; only the warning flags the bad merge). Call now runs first, skip
only suppresses the WRITE. Red on the round-3 head, green after. Red-green
method all rounds: swap HEAD module copies in place (conftest hard-prepends
`src`, so a PYTHONPATH overlay is inert under pytest).

## Round 5 (round-4-head findings; #345 merged, rebased)

#345 merged to main (c3073c6); rebased, resolving the design-doc status
block. The round-3 `find_spec` gate skip keyed on a module #345 never
adds -- it skipped forever; now `skipif` on
`"inline_calc_results" in RELEASE_GATE_DEFAULTS`, and the pair RUNS
green against the merged rule (18 passed). Blind exemption oracle
adapted to #345's implemented narrow exemption (capture taken IN the
stale state, no edit after). Control fence made valid calc so exit 1 can
only be the citation rule, which the test now names. Ordering test
observes the resolved value via the stale-result warning.
`named-calc-blocks.md` node-id/HASH_FORMAT citations re-pinned at 6;
`body_source_pairs` docstring covers the span walk;
`_replace_ref_target` span arg typed; long docstring line rewrapped;
branch-self SHAs stripped from this log (AGENTS policy).
