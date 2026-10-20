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

## Review rounds 1-5 (PR #347, three cross-model chunks each round)

Across five review rounds the findings clustered into: scan-grammar parity
(RHS comments and a comment containing `|` hid span references from the
scheduler and `fetch` -- scan helpers now reproduce the evaluator's own
strip/pipe order), span-scan geometry (bounds anchored on `item.body_line`,
front-matter fences, fence/span same-line edits), list-file items (span-only
targets excluded from expansion; the plan's crossed-reference refusal runs
*before* the skip so the warning survives), and historical-record safety
(format-5 seals of span items: `_hash_payload` strips expanded span targets
back to the display half for formats <= 5, so the bump never makes an
unchanged item look edited). Round-5 work was mostly rebase fallout after
#345 (gate-rule `skipif`, exemption-oracle adaptation) plus doc/test nits.
Every fix was red-green verified; red checks swap HEAD module copies in
place (conftest hard-prepends `src`, so a PYTHONPATH overlay is inert under
pytest). Rebases: onto #351's comment-aware scanner (merged into one
`_scan_body`), then onto #345 (`c3073c6`). Suite grew 4207 -> 4310 passed
(2 skipped) with the golden byte-identity checks green at every head.

## Round 6 (at the round-5 head; chunks 2/3 APPROVE, chunk 1 CHANGES REQUESTED)

Chunk 1 MEDIUM: a span target *authored* as a composite (`DEC-001@key.V_in`)
was hashed as-written by format-5 code, but my reconstruction strips every
composite target unconditionally -- so an unchanged authored-composite item
looked edited. Reproduced against real old code (`.scratch/r7composite.py`
drives a fixture built by archived `origin/main`): migration reported
`uncomparable` and `check` falsely reported "modified since it was sealed".
Fix is comparison-side only: `build.hash_for_format_variants` adds the
as-written reading to the legacy-format comparison (exposed as
`keys.hashes_in_format`), consumed by `migrate_hash_format`,
`seal._matches_sealed_hash`, `plan_surrogate_storage` and `key_restore`;
nothing records a variant hash, and an edited body still fails both
readings (safety test). Three of the four new tests in
`tests/test_inline_calc_hash.py` section 7 are red at the round-5 head.
Also landed: `docs/design/inline-calc.md` section 3 restated as landed facts
at `HASH_FORMAT` 6; the format-6 history in `build.py`, `docs/lifecycle.md`
and `docs/change-tracking.md` corrected (a resolvable span's `source()` fed
the source-inputs hash since format 4 -- format 6 adds span cross-item
hash inputs and `fetch` pinning, not a new source hash input);
`SourceUse` docstring widened. Targeted suites: 550 passed; full suite 4314
passed, 2 skipped.

## Round 7 (at the round-6 head; chunks 1-3 APPROVE, chunk 4 CHANGES REQUESTED)

Chunk 4 MEDIUM: round 6 accepted the stripped format-5 reading
unconditionally, so a KEY-HALF-only edit of an expansion-written composite
(`DEC-001@w4fq.V_in` -> `DEC-001@K2.V_in`) strips right back to the bare
text a pre-expansion baseline/seal recorded -- the edit was silently
carried as "content demonstrably unchanged", and my "genuine edit moves
both readings" comment was false. Fix: the stripped reading is offered only
for composites *faithful* to what the expansion writes -- key half == the
key of the item the display half names (`build._span_composites_are_-
faithful`, gating `hash_for_format_variants`); a composite failing it keeps
only the as-written reading (what the format's own code hashed), so the
edit reports as changed/uncomparable -- fail-closed, no safety overclaim.
Red-on-head test drives: bare fmt5 baseline/seal -> legitimate expansion
compares clean -> key-half edit flags (seal violation + uncomparable).
Chunk 4 LOW: set membership raised TypeError on an unhashable stored hash
(a YAML list in a corrupted record) where the old equality said
"non-match"; new `keys.stored_hash_matches` string-guards all comparison
sites (lifecycle, keys plan x3, seal; key_restore already guarded), red
test pins migration-uncomparable + seal-violation. Also: stale
`hash_in_format`-as-comparison docstrings corrected (keys.py, build.py,
key_restore.py, keys.md x2), lifecycle migrate docstring reflowed.
Targeted suites green. Task finished.

## Round 8 (at the round-7 head; chunks 1-3 APPROVE, chunk 4 CHANGES REQUESTED)

Chunk 4 MEDIUM: `keys.plan_surrogate_storage` inferred a legacy scalar
seal's format from only (HASH_FORMAT, 2, 1) and gated migration on a
(1, 2, HASH_FORMAT) allowlist, so after the bump to 6 a genuine format-5
seal of an item whose format-4/5 payload (fence cross-item references,
image bytes) differs from its format-2/1 one matched nothing: `refdes
keys adopt` reported it uncomparable, rewrote the entry to format 1, and
the adopted project's own build then failed "modified since it was
sealed" -- adoption rolled back, and a run without the post-check leaves
the record pinned to format 1. `seal._matches_sealed_hash` tries the
full range newest-first and reads the same seal clean, so the inference
must not be narrower than the check: it now tries 1..HASH_FORMAT
newest-first and a matched format migrates (out-of-range formats
reconstruct to None, so uncomparable entries stay; Mapping entries
stamped `hash_format: 5` now migrate too). Red repro: main's own code
stamped real format-5 seal hashes over a span+fence fixture. Control: a
real fence-value edit refuses adoption and stays uncomparable. Chunk 4
LOW: lifecycle baseline docstring "HASH_FORMAT -- currently 5" -> 6;
`keys.hash_in_format` opening claim "exactly as hash-format would
compute" is false for an author-composite span target (the
reconstruction strips it) -- rewritten as the canonical single
reconstruction vs the hashes_in_format comparison set. Full suite 4318 passed, 2 skipped. Task finished.
