# inline-calc slice 2: spans enter calc_hash, dependency scans, content hash

Branch `feat-inline-calc-slice2-hash`, based on `899ab91` (#358); created
from `main` @ `c9ecc30` and rebased through several releases. Owner
decision 2026-10-19: change the hash format despite
baseline/seal risk. Plan: `docs/design/inline-calc.md` §3, four green steps.

## Steps 1-4 (done)

Step 1: `calc_hash_for` (`src/refdes/build.py`) hashes inline calc spans
alongside fence blocks -- events at source offsets, spans rendered
`name := rhs [| unit]` with the stored result excluded (a result-only edit
leaves the probe fixed), a malformed span contributes its raw text minus
the result portion. Span-free items produce the identical payload.

Step 2: cross-item span refs as dependency edges and hash inputs (gated
`hash_format >= 6`): `_calc_reference_targets` includes span targets, the
ref-scan/hash helpers take `include_inline`, `links._calc_ref_rewrites`
rewrites span target halves so expansion covers spans.

Step 3: `source()` in spans -- `citations.collect_source_uses` discovers
them (fetch pins them), `serve/sources.py` shows them; the "move to the
fence form" advice is retired.

Step 4: `HASH_FORMAT` 5 -> 6. Evidence (green at every head since): (a)
golden byte-identity -- a scratch script (gitignored, recreated as needed)
records a fixture under archived `origin/main` code, the branch rebuilds
the same on-disk state, every hash/baseline/seal byte-identical
(committed mirrors: `test_block_only_calc_hash_is_the_block_only_hash`,
`test_format5_reconstruction_excludes_span_inputs`). (b) Old seal + old
baseline (main-recorded) verify clean under the new code; carry-forward
migration silent (tests). (c) Referenced-value edits move the span item's
hash and fire the stale signal; result-only edits not the probe. (d)
`fetch --update` of a span's `source()` input moves the hash. (e) Cycle
reports the path, missing target is a clean error, three spans on one item
all enter probe and snapshot. Docs: build.py format-history comment,
`docs/lifecycle.md`, `docs/change-tracking.md`,
`changelog.d/inline-calc-spans-hash.changed.md`.

## Review rounds 1-10 (PR #347, cross-model chunks each round)

R1-5 clustered into: scan-grammar parity (RHS comments and a `|` inside a
comment hid span references -- scan helpers reproduce the evaluator's
strip/pipe order), span-scan geometry (`item.body_line` anchoring,
front-matter fences), list files (span-only targets excluded from
expansion), historical-record safety (formats <= 5 reconstruction strips
expanded span targets). R6: an *authored* composite's as-written reading
was missing from legacy comparison -- `hash_for_format_variants` added,
consumed by seal/lifecycle/keys comparison sites. R7: the stripped reading
is gated by `_span_composites_are_faithful` (key-half-only edits keep only
the as-written reading, fail-closed) + `stored_hash_matches` string
guards. R8: `plan_surrogate_storage` format inference widened to
1..HASH_FORMAT newest-first (a genuine fmt-5 seal had rolled back
`keys adopt`). R9: docs/docstrings matched the landed full-range
behavior. R10: an upstream display-id rename broke fmt-5 seals of
referring items -- the gate accepts the owner's live id OR a declared
former id, and `strip_display` stripped readings over historical display
halves joined the comparison set (cap 16); six section-7 tests on
main-stamped fmt-5 constants. LOWs: lifecycle docstrings,
`serve/sources.py` span names/units.

## Round 11 (docs/changelog pass, chunk 1)

Status block resolved against #363; changelog dropped-span-pin claim
corrected to the reproduced hard error (`check` exits 1, "has no locked
value"); YAML list-file bare-span exclusion documented in §3 + math.md
(composite-spelling workaround verified in a throwaway scratch project);
"since format 4" reworded (spans landed in the format-5 era); faithful
gate sentence + lifecycle calc_refs/calc_hash split.

## Round 12 (chunk-2 LOWs)

Restored the dangling `[inline-calc-later.md]` link; `_item_units` strips
a span unit's trailing comment (`split_comment`) so suggestions are clean
values.

## Round 13 (chunk 2: probe/cap LOWs + NITs)

Malformed-span probe hashed `span.raw` (carries the stored result) -- now
`inline_calc.resultless_raw` (raw up to the last top-level `=`);
cap-16 drop documented + pinned both sides (above cap only historical
readings drop; as-written + stripped-current stay: false-positive only).
NITs: `authored_display` rename, `by_key` comprehension, dead
include_inline gate dropped. Cap-test fixture lesson: mapping keys are
targets without `.NAME`; clear the reused tmp items dir between fixture
calls.

## Round 14 (fresh chunk-2: one stale docstring)

`calc_reference_snapshot`'s docstring still described the round-13-removed
gate; rewritten to the code's truth. Swept src/docs/tests for the class:
one site. NITs: itertools to module imports, former_ids build-order
precondition documented.

## Round 15 (chunk 1: docs only)

All findings verified against build.py first (2232: format 6 = 2026-10-19
reference-hashing; `calc_hash_for` takes no format arg -- all six true):
escaped the §3 source()-row pipe (row rendered truncated on GitHub --
verified via GitHub's rendered HTML); reworded format-6 cause in
named-calc-blocks (x2), inline-calc Status, lifecycle "so ... probe"
clause; dropped the unverifiable landed date; era marker now says the
section describes landed behavior; change-tracking source() aside split
out of the change list, fetch-discovery stated as not-a-hash-input; log
`.scratch/` pointers replaced with descriptions. No source changes.
Docs tests 8+27 passed.

## Round 16 (chunk 1: one false sentence from round 15's reword)

lifecycle.md said a result-only span edit "stays invisible to content
hashing" -- inverted; it moves the content hash (body text) and not the
probe. Reworded; nothing in round 15's diff was a code change. Full
verification pass over every round-15 docs claim, claim -> proof:
- "span cross-item references entering the content hash" (Status,
  named-calc x2, change-tracking list) -> build.py:2232-2236.
- "`calc_hash` probe extension ... not a format-gated payload change"
  (Status), "takes no format argument and is not what moved" (named-calc
  x2), "probe covers spans at every format" (lifecycle) ->
  build.py:2390 `def calc_hash_for(item)`;
  test_calc_block_hash.py:61 pins the payload property at 6.
- "result-only edit moves the content hash ... not the probe" (lifecycle,
  fixed) -> test_inline_calc_hash.py:460.
- "source() values input is format 4's own ... fetch discovery is not a
  hash input" (change-tracking, lifecycle, §3 row) -> build.py:2237-2240,
  citations.py:1544 (span discovery, not hashing).
- "landed with slice 2, this PR" (§3 heading) -> gh pr view 347: OPEN.
- era marker / named-calc table re-pins -> #333/#341/#351/#345 merged,
  tests named in the table exist and pass.
NIT: log header base corrected to 899ab91 (#358, merge-base verified).
Docs tests 8+27 passed; full suite green (see PR body note).
