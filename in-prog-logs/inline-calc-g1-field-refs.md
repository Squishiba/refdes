# Live inline-calc G1: `ITEM.$field` field references (2026-10-29)

Implemented slice G1 of the live inline-calc design
(in-prog-logs/inline-calc-live-editor-design-20261020.md §6.5a/§6.5b): a calc
reference whose name half starts with `$` reads one of the target's declared
FIELDS (saved front-matter value, parsed as a quantity) instead of a calc
value. Fence lines and inline spans; batch build/check path only (no
serve/JS, no live preview pass — those are later slices).

## What landed

- `calc.py`: `FIELD_REF_RE` (target half identical to `CROSS_REF_RE`, `$`
  on the name half); `BLOCK_QUALIFIED_REF_RE` extended so `A.$b.$c` is the
  same "names a block" error; `CALC_WARNINGS_KEY` env slot; in
  `evaluate_block` the shared reference branch tries the field pattern after
  the cross-ref one, and a `$` spliced into larger arithmetic gets a clear
  error naming the two-step form (placed before the arithmetic fallback so
  the message is about the `$`, not pint).
- `inline_calc.py`: `span_field_ref` (mirrors `span_cross_ref`).
- `build.py`: `_make_calc_resolver(..., warnings=)` — the `$` branch reads
  `target.fields` straight (no `_calc_failed` gate, no edge, no ordering):
  undeclared / list-valued / empty / non-quantity are loud errors naming
  the field, the undeclared/empty messages listing the item's declared
  fields. Bare-name collision (target has BOTH calc value and field of that
  name) resolves to the calc value and appends a warning naming both and
  the `ITEM.$name` spelling; the sink is wired through
  `CALC_WARNINGS_KEY` in `_run_item_calcs` and drained into
  `project.warnings`. `_calc_field_reference_targets` scans fence+span
  `$` refs for the rewrite/expansion machinery only — deliberately NOT
  fed to the scheduler (no dependency edges).
- Hash rule 7: `_calc_refs_hash_value` gives field refs NO `resolved`
  entry (field values never in `calc_refs`/`calc_hash`), but their target
  half IS reduced to the same link token in the hashed body text, so the
  bare -> composite on-disk expansion stays hash-invisible. `HASH_FORMAT`
  stays 6 — checked.
- `links.py`: `_calc_ref_rewrites` matches field refs in fences and spans,
  and `plan_calc_ref_expansion` walks them, so key minting, composite
  expansion, rename display-half refresh, and `calc-rewrite` all treat the
  target half exactly like every other reference; the `.$field` text itself
  is never touched.
- `tests/test_calc_field_refs.py`: 23 tests — evaluation, span form,
  arithmetic-after-field, `$`-in-arithmetic error, block-qualified
  rejection, all four field-failure shapes, collision warning + explicit
  `$` silence, own-item `X.$field` not a cycle / bare self-ref still
  cycle, no-edge proof (mutual field reads build fine), `HASH_FORMAT == 6`,
  field values never in the snapshot, field edit moves the value not the
  hashes + stale-span warning, bare/composite hash-identity, composite
  expansion + rename survival, `--no-write` writes nothing, calc-rewrite
  preserves `$` lines.
- Docs: `docs/math.md` new "Reading a field: `ITEM.$field`" subsection +
  an Inline calc paragraph note; `changelog.d/calc-field-refs.added.md`.

## Verification

- Full suite: 5087 passed, 2 skipped (baseline origin/main f460e46 runs
  5067/2 in a clean archive; the delta is exactly the 22+1 new tests).
  Note: an earlier worktree run looked 26 tests short — the worktree was
  created one commit before origin/main advanced (f460e46 added
  test_history_baseline.py); rebased, counts reconcile.
- Differential build (mandatory rule 7): seeded 4-item project (fences,
  spans, cross refs, tolerances, named blocks, keys minted) with new code,
  copied, rebuilt once with baseline-main code and once with worktree code
  — `diff -rq` byte-identical. No-`$` projects are untouched by the slice.
- Mutation checks: (a) disabling the collision warning fails
  test_collision_warns_and_resolves_to_calc; (b) dropping field targets
  from the hash tokens fails the bare/composite hash-identity test — that
  test was added after the first mutation round survived it (gap found and
  closed; `calc_hash_for` hashes raw block text by design, the invariant
  lives in `content_hash`).
- `ruff check` on all touched files: identical findings to baseline (20
  pre-existing, on untouched lines; nothing added).

## Review round (PR #387, CHANGES REQUESTED, batched)

No correctness bugs; fixed in one batch: (1) docs claimed a field value may
carry `± tolerance` — false, the read is bare `parse_quantity`; docs now say
plain quantity, tolerance goes on a following calc line (`v = ITEM.$V_in`
then `w = v ± 5%`, verified in a probe), plus a test pinning the
not-a-quantity error for a tolerance field value. (2) Renamed the
mis-named happy-path test (it asserted the `5 V` resolve; now asserts both
computed values). (3) The `docs/design/... inline-calc field refs, G1` cite
in calc.py (and this log) was dangling — design lives at
in-prog-logs/inline-calc-live-editor-design-20261020.md §6.5a, cites fixed.
(4) Warning-sink protocol comment now states the append-before-return
constraint, and the drain rides the error outcomes too, so no message can
be lost on any path. (5) Block-qualified `$` shapes get their own message
naming `ITEM.$field` and the working `DEC-001.$rds_on` spelling. (6)
`_calc_ref_rewrites` docstring now covers the `$` field refs it rewrites.
(7) Bare-key item half (`KEY.$field`) resolve test added. Suite 5090
passed/2 skipped; touched-file ruff unchanged vs baseline.

## Review round 2 (PR #387, final round, batched)

(1) Non-identifier field names (`$rds-on`, `$2stage`) got their own error
(field name + identifier rule + the qualifying declared fields, via a new
FIELD_FIELDS_KEY callable); grammar NOT widened; hyphen and leading-digit
tests pin it. (2) The `drained` closure took loop vars (5 new B023);
it now takes them as parameters — per-file ruff counts re-measured and
stated in the PR body: build 0/0, calc 15/15, inline_calc 4/4, links 1/1
(worktree/baseline). (3) Collision warning now fires whenever the target
has both a calc value and a set field of that name — empty string, null,
list-valued included (list gets its own hint: no reference reads it);
tests pin each. (4) Hash wording in docs/math.md and the changelog
narrowed: the field's value is not part of the REFERRING item's hash;
the target's own hash moves with the edit as for any field. (5) The
calc-rewrite test spells its retired-form line directly. Suite 5094
passed / 2 skipped.

## Notes / leftovers
- Unit display quirk (pre-existing): `mohm` normalizes to `mΩ` in computed
  output, so tests assert `18 m\u03a9` for results while stored spans may
  use `mohm`.
- Probe project kept at `.scratch/g1-probe`; differential trees at
  `.scratch/diff-{proj,old-1,new-1}`; baseline archive at
  `.scratch/baseline-main` (all gitignored).
- Not in slice (per spec): serve/JS, live preview pass, list-valued fields
  (loud out-of-scope), design-doc G1 status left as-is.

Done — pushed as a PR, not merged.
