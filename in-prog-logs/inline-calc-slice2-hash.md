# inline-calc slice 2: spans enter calc_hash, dependency scans, content hash

Branch `feat-inline-calc-slice2-hash`, base `main` @ `c9ecc30`, rebased onto
`1d6d325`. Owner decision 2026-10-19: change the hash format despite
baseline/seal risk. Plan: `docs/design/inline-calc.md` §3, four green steps.

## Steps 1-4 (done)

Step 1: `calc_hash_for` (`src/refdes/build.py`) hashes inline calc spans
alongside fence blocks -- events at source offsets, spans rendered
`name := rhs [| unit]` with the stored result excluded (a result-only edit
leaves the probe fixed), a malformed span contributes its raw text.
Span-free items produce the identical `{"calc_blocks": [...]}` payload.
Helpers for later steps: `code_span_ranges`, `span_cross_ref`,
`span_source_call`. New `tests/test_inline_calc_hash.py`.

Step 2: cross-item span refs as dependency edges and hash inputs (gated
`HASH_FORMAT >= 6`): `_calc_reference_targets` includes span targets
(F12-5 is now a passing ordering-edge test), the ref-scan/hash helpers take
`include_inline`, `links._calc_ref_rewrites` rewrites span target halves so
expansion covers spans.

Step 3: `source()` in spans -- `citations.collect_source_uses` discovers
them (fetch pins them), `serve/sources.py` shows them; the "move to the
fence form" advice is retired (F12-6 rewritten).

Step 4: `HASH_FORMAT` 5 -> 6 (steps 2-3 ride in it; full suite green at
each step). Evidence (all green at every head since):

- (a) Golden byte-identity: `.scratch/record_golden.py` builds a fixture
  with archived `origin/main` code (format 5), the branch rebuilds the same
  on-disk state -- all five items' content hashes, the baseline, the release
  baseline and the seal file byte-identical (the result-only span item gains
  only a probe). Committed mirrors: `test_block_only_calc_hash_is_the_block_only_hash`,
  `test_format5_reconstruction_excludes_span_inputs`.
- (b) Old seal + old baseline (main-recorded) verify clean under the new
  code; carry-forward migration silent (tests).
- (c) Editing the referenced value moves the span item's hash and fires the
  stale signal; a result-only edit moves the content hash, not the probe.
  (d) `fetch`/`fetch --update` of a span's `source()` input moves the hash.
  (e) Adversarial: span cycle reports the cycle path, missing target is a
  clean error, three spans on one item all enter probe and snapshot.

Docs: `build.py` format-history comment, `docs/lifecycle.md`,
`docs/change-tracking.md`, `changelog.d/inline-calc-spans-hash.changed.md`.

## Review rounds 1-5 (PR #347, three cross-model chunks each round)

Findings clustered into: scan-grammar parity (RHS comments and a comment
containing `|` hid span references -- scan helpers now reproduce the
evaluator's strip/pipe order), span-scan geometry (bounds anchored on
`item.body_line`, front-matter fences, fence/span same-line edits),
list-file items (span-only targets excluded from expansion; the
crossed-reference refusal runs before the skip), and historical-record
safety (format-5 seals of span items: `_hash_payload` strips expanded span
targets for formats <= 5, so the bump never makes an unchanged item look
edited). Round 5 was mostly rebase fallout after #345. Every fix red-green
verified; red checks swap HEAD module copies in place (conftest
hard-prepends `src`, so a PYTHONPATH overlay is inert under pytest).
Rebases: onto #351's comment-aware scanner, then onto #345.

## Round 6 (chunk 1 CHANGES REQUESTED)

MEDIUM: a span target *authored* as a composite (`DEC-001@key.V_in`) was
hashed as-written by format-5 code, but my reconstruction stripped every
composite target unconditionally -- an unchanged authored-composite item
looked edited. Reproduced against real old code
(`.scratch/r7composite.py`): migration reported `uncomparable`, `check`
falsely reported "modified since it was sealed". Comparison-side fix only:
`build.hash_for_format_variants` adds the as-written reading to legacy-format
comparison (exposed as `keys.hashes_in_format`), consumed by
`migrate_hash_format`, `seal._matches_sealed_hash`, `plan_surrogate_storage`
and `key_restore`. Also: `docs/design/inline-calc.md` section 3 restated as
landed facts; the format-6 history in `build.py`/`docs/lifecycle.md`/
`docs/change-tracking.md` corrected (a resolvable span's `source()` fed the
source-inputs hash since format 4). Suite 4314.

## Round 7 (chunks 1-3 APPROVE, chunk 4 CHANGES REQUESTED)

MEDIUM: round 6 accepted the stripped reading unconditionally, so a
KEY-HALF-only edit of an expansion-written composite strips right back to
the bare text a pre-expansion record made -- silently carried as
"unchanged". Fix: the stripped reading is offered only for composites
faithful to what the expansion writes -- key half == the key of the item
the display half names (`build._span_composites_are_faithful`); a composite
failing it keeps only the as-written reading -- fail-closed. LOW: set
membership raised TypeError on an unhashable stored hash; new
`keys.stored_hash_matches` string-guards all comparison sites. Stale
`hash_in_format` docstrings corrected. Suite green.

## Round 8 (chunks 1-3 APPROVE, chunk 4 CHANGES REQUESTED)

MEDIUM: `keys.plan_surrogate_storage` inferred a legacy scalar seal's
format from only (HASH_FORMAT, 2, 1) and gated migration on a (1, 2,
HASH_FORMAT) allowlist, so after the bump a genuine format-5 seal whose
format-4/5 payload differs from its format-2/1 one matched nothing:
`refdes keys adopt` reported it uncomparable, rewrote the entry to format
1, and the adopted build then failed "modified since it was sealed".
`seal._matches_sealed_hash` tries the full range newest-first, so the
inference now tries 1..HASH_FORMAT newest-first and a matched format
migrates. Red repro: main's own code stamped real format-5 seal hashes over
a span+fence fixture. LOW: "currently 5" -> 6; the `hash_in_format`
"exactly as hash-format would compute" claim rewritten (it is the canonical
single reconstruction vs the hashes_in_format comparison set). Suite 4318.

## Round 9 (docs accuracy pass, chunks 2/3/4 APPROVE)

`docs/design/keys.md` section 5(c) now describes the full-range scalar-seal
inference as landed; three LOW docstring fixes: `lifecycle._stale_arithmetic`
(no calc block *and no inline span*; the probe is fence block and/or inline
span), `keys.plan_surrogate_storage` (recorded-format / inferred-carry
shapes), `keys.stored_hash_matches` (the migration-sweep sites; key_restore
has its own inline equivalent). Log "this commit" references removed.

## Round 10 (rebase + MEDIUM: upstream rename invalidates a REFERRER's fmt-5 seal)

Rebased onto current `origin/main` (CHK-ATTR releases merged; clean, no
conflicts). Baseline suite 4451.

MEDIUM (reviewer's repro): fmt-5 seal of LOG-001 with span
`Vb := DEC-001.V_in = 12 V`; the load expands it to `DEC-001@key`; an
ordinary upstream rename (`id: DEC-002`, `former_ids: [DEC-001]`, key
kept) refreshes the span label to `DEC-002@key` -- an author-side text
move no edit produced -- and formats <= 5 hashed that text, so the sealed
referrer builds "modified since it was sealed" at head although its
authored text and format-6 hash never moved. Fix:
`_span_composites_are_faithful` resolves the owner by KEY and accepts a
display half that is the owner's live id OR one of its declared former ids
(`project.former_ids`); `hash_for_format_variants` adds the stripped
readings over the historical display halves (product over composites, cap
16, fail-closed above, as-written skipped) via a `strip_display` map
threaded through `_hash_payload`/`hash_payload_builder`/
`links._calc_ref_rewrites`. Six tests in section 7: scalar and
keyed fmt-5 seals and a fmt-5 baseline entry of the referrer survive
single + double renames; the referrer's OWN rename stays clean (seal
resolves via former_ids); a display half that is a foreign LIVE id fails
the gate (stripped reading withdrawn, round-7 posture) and the fmt-5
record reports modified; deleting the target fails loudly. Three core
tests red at the pre-fix head. Real main-stamped constants
(`e44d58abd0c521ca`/`641abfaf38e45eae`).

LOWs: `lifecycle.py` -- `calc_hash` described as fence-block-only twice
(baseline docstring, stamp docstring); both now say fence block and/or
inline span (an inline-only item is stamped). `serve/sources.py` --
`_item_names`/`_item_units` read only `item.calcs`; they now include
inline-span names and units (span `| unit` + stored-result unit), so the
picker refuses a name a span assigns and suggests the span's unit (test
added). Evidence (a)-(e) re-run green against the final tree; full suite
4458 passed, 2 skipped. Task finished.
