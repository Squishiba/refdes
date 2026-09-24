# named-calc-blocks implementation (Phases 1 + 4)

Worker: refdes-158. Spec: docs/design/named-calc-blocks.md (merged,
architecture decided 2026-09-24). Scope: Phase 1 (Names) + Phase 4 (Hash
pins). Phases 2/3/5 deliberately not implemented.

## What landed

- `calc.py`: `parse_fence_attrs()` owns the §3.3 grammar (`id="..."` only,
  lowercase-initial `[a-z][a-z0-9_-]*`, 1-40 chars, quoted value); raises
  `CalcFenceError` (new `CalcError` subclass) with the §7 messages verbatim.
  `fence_errors(body)` reports (body-line, message) per invalid fence.
  `extract_blocks_with_lines` grows a third tuple element (the id or None);
  it stays lenient (bad fence -> None) so hashing/rendering/citation walks
  never crash on a project already failing at `run_calcs`. `CALC_BLOCK_RE`
  unchanged. `BLOCK_QUALIFIED_REF_RE` + an `evaluate_block` branch reject
  `ITEM.block.NAME` with the §7 error naming the plain form.
- `model.py`: `CalcLine.block: str = ""`.
- `build.py`: `_run_item_calcs` reports fence errors at the fence line's
  file:line, enforces per-item block-name uniqueness (§7 duplicate message),
  passes the id into every `CalcLine`. `render_bodies` threads the id to
  `_calc_table_html(chunk, block=...)`, which adds
  `<table class="calc" id="calc-losses">` + `<caption class="calc-caption">`
  only when named; unnamed output byte-identical (pinned).
- `citations.py`: unpack updated to the 3-tuple.
- `calc_rewrite.py`: no change needed — its fence handling (`FENCE_OPEN_RE`
  toggles state, never rewrites the fence line) already preserves a named
  fence; pinned by `test_calc_rewrite_preserves_fence`.

## Tests

- `tests/test_calc_block_names.py` — 14 tests, every §10 Phase-1 row,
  message-for-message where §7 specifies. Sabotage notes inline.
- `tests/test_calc_block_hash.py` — 4 Phase-4 pins, all green with zero
  implementation change (as §6.1 predicted): HASH_FORMAT stays 4, naming
  moves owner content_hash only, dependents + calc_reference_snapshot
  unmoved by a rename, `calc_hash_for` unmoved by fence add/rename.

## Findings / decisions logged

- §7's qualified-reference example shows the prefix `ERROR calc P:`; the
  house prefix in `_run_item_calcs` is `calc {name!r}:` (quoted), which is
  what every existing calc error emits. Kept the existing shape ("Wording
  follows the existing shapes", §7 preamble); the §7 message body itself is
  verbatim.
- Fence error line numbers: expected values must be computed from the file
  AFTER key minting (minting rewrites front matter and shifts body lines).
  The implementation's arithmetic (`body_line + fence_offset`) is correct;
  the test harness reads post-build text.
- Unspecified edge: `id=` given twice on one fence (`id="a" id="b"`) gets
  `calc fence: id is given twice -- a calc fence accepts one id="...";
  keep one.` (§7 has no message for it; it is an error per "One attribute
  today").
- No docs/math.md sentence added — no §10 Phase-1 test requires it; left to
  Phase 5.

## Verification

- `python -m pytest -q` — 2071 passed (incl. 18 new).
- `ruff check --select E9,F` on all touched .py files — clean.
- No fixture regenerated; unnamed-render byte-identity pinned by comparing
  rendered strings, never raw file bytes (CRLF/LF caution).

Status: Phase 1 + Phase 4 complete.
