# inline-calc slice 2: spans enter calc_hash, dependency scans, content hash

Branch `feat-inline-calc-slice2-hash`, base `main` @ `c9ecc30`, rebased
through #363. Owner decision 2026-10-19: change the hash format despite
baseline/seal risk. Plan: `docs/design/inline-calc.md` §3, four green steps.

## Steps 1-4 (done)

Step 1: `calc_hash_for` (`src/refdes/build.py`) hashes inline calc spans
alongside fence blocks -- events at source offsets, spans rendered
`name := rhs [| unit]` with the stored result excluded (a result-only edit
leaves the probe fixed), a malformed span contributes its raw text.
Span-free items produce the identical `{"calc_blocks": [...]}` payload.

Step 2: cross-item span refs as dependency edges and hash inputs (gated
`HASH_FORMAT >= 6`): `_calc_reference_targets` includes span targets
(F12-5 is now a passing ordering-edge test), the ref-scan/hash helpers take
`include_inline`, `links._calc_ref_rewrites` rewrites span target halves so
expansion covers spans.

Step 3: `source()` in spans -- `citations.collect_source_uses` discovers
them (fetch pins them), `serve/sources.py` shows them; the "move to the
fence form" advice is retired (F12-6 rewritten).

Step 4: `HASH_FORMAT` 5 -> 6 (steps 2-3 ride in it; full suite green at
each step). Evidence (all green at every head since): (a) golden
byte-identity -- `.scratch/record_golden.py` builds a fixture with archived
`origin/main` code (format 5), the branch rebuilds the same on-disk state;
all five items' content hashes, the baseline, the release baseline and the
seal file byte-identical (committed mirrors
`test_block_only_calc_hash_is_the_block_only_hash`,
`test_format5_reconstruction_excludes_span_inputs`). (b) Old seal + old
baseline (main-recorded) verify clean under the new code; carry-forward
migration silent (tests). (c) Referenced-value edits move the span item's
hash and fire the stale signal; result-only edits not the probe. (d)
`fetch --update` of a span's `source()` input moves the hash. (e) Cycle
reports the path, missing target is a clean error, three spans on one item
all enter probe and snapshot.

Docs: `build.py` format-history comment, `docs/lifecycle.md`,
`docs/change-tracking.md`, `changelog.d/inline-calc-spans-hash.changed.md`.

## Review rounds 1-5 (PR #347, three cross-model chunks each round)

Findings clustered into scan-grammar parity (RHS comments and a comment
containing `|` hid span references -- scan helpers now reproduce the
evaluator's strip/pipe order), span-scan geometry (bounds anchored on
`item.body_line`, front-matter fences, fence/span same-line edits), list
files (span-only targets excluded from expansion; the crossed-reference
refusal runs before the skip), and historical-record safety (formats <= 5
reconstruction strips expanded span targets, so the bump never makes an
unchanged item look edited). Every fix red-green verified; red checks swap
HEAD module copies in place (conftest hard-prepends `src`, so a PYTHONPATH
overlay is inert under pytest).

## Rounds 6-10 (cross-model chunks each round; every fix red-green, main-code-stamped constants)

Round 6 (chunk 1 changes requested): an *authored* composite span target
was stripped by my reconstruction although format-5 code hashed it
verbatim -- `build.hash_for_format_variants` adds the as-written reading to
legacy comparison (`keys.hashes_in_format`), consumed by
`migrate_hash_format`/`seal._matches_sealed_hash`/`plan_surrogate_storage`/
`key_restore`.

Round 7 (chunk 4 changes requested): the stripped reading must not be
accepted unconditionally (a key-half-only edit stripped back to the bare
recorded text) -- `build._span_composites_are_faithful` gates it: key half
== the key of the item the display half names; a composite failing it keeps
only the as-written reading (fail-closed). Plus `keys.stored_hash_matches`
string-guards every comparison site against unhashable stored values.

Round 8 (chunk 4 changes requested): `keys.plan_surrogate_storage`
inferred a legacy scalar seal's format from an allowlist narrower than
`seal._matches_sealed_hash`'s full range, so a genuine format-5 seal rolled
back `refdes keys adopt` -- the inference now tries 1..HASH_FORMAT
newest-first and a matched format migrates.

Round 9 (docs accuracy, approved): `keys.md` §5(c) and three docstrings
(lifecycle `_stale_arithmetic`, `plan_surrogate_storage`,
`stored_hash_matches`) now describe the landed full-range behavior.

Round 10 (chunk 1 changes requested): a format-5 seal/baseline of a
REFERRING span item broke on an ordinary UPSTREAM display-id rename (the
load's label refresh is a text move no edit produced, and formats <= 5
hashed that text). The gate now resolves the composite's owner by key and
accepts a display half that is the owner's live id or a declared former id
(`project.former_ids`); `hash_for_format_variants` adds stripped readings
over historical display halves (`strip_display` through
`_hash_payload`/`_calc_ref_rewrites`, cap 16, fail-closed above; foreign
live halves still fail -- round-7 posture). Six section-7 tests on
main-stamped fmt-5 constants (three red at head). LOWs: lifecycle docstrings
(fence and/or span) and `serve/sources.py` `_item_names`/`_item_units` now
include span names/units (one item-wide scope).

## Round 11 (docs/changelog pass after chunk 1's review)

Status block in `docs/design/inline-calc.md` resolved against #363's
rewrite (slice 2 lands with this PR, #333/#341/#351/#345 citations kept,
numbers verified via `gh pr view`); the changelog's dropped-span-pin
claim corrected to the real behavior (reproduced: `check` exits 1 with
`source(...) has no locked value`, a hard error, not a stale warning);
the YAML list-file bare-span exclusion documented in `inline-calc.md` §3
and `docs/math.md` (workaround: hand-written composite spelling, verified
clean across a rename in `.scratch/r11pin`, bare breaks with "no item");
"since format 4" reworded in three docs + the build.py comment (spans
landed in the format-5 era -- verified `HASH_FORMAT = 5` at #333's merge
commit); faithful-composite sentence now includes the former-id/
historical-display-half acceptance; lifecycle.md `calc_refs` vs
`calc_hash` applicability split (pinned to `_items_map`'s
non-empty-snapshot gate). Log collapsed per AGENTS.md.
