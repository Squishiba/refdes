# named-calc-blocks implementation (Phase 3)

Worker: refdes-160. Spec: docs/design/named-calc-blocks.md (architecture
decided 2026-09-24; all ten §11 questions decided — not relitigated here).
Scope: Phase 3 — the `{{calcblock}}` page block. Phases 2 and 5 deliberately
not implemented.

## What landed

- `blocks.py`:
  - `BlockSpec` grows `missing_names_accepted: bool = False`. §7's
    missing-parameter message for this block is
    `missing required parameter 'block'. calcblock accepts: block, item.` —
    the accepted-set sentence, which the family default does not emit. The
    flag opts into it; every existing block is unchanged (default False), so
    their missing-parameter messages are byte-identical.
  - `_calcblock_target(project, item_id)`: `item=` resolves a display id
    first, then a `DISPLAY-ID@key` composite by its key half (§5.4).
  - `_render_calcblock(project, params, where="")`: reads `item.calcs`
    (§3.6 — `CalcLine.block` is why no second body walk is needed), filters
    `line.block == block`, and formats with `build._calc_table_html(rows,
    block=block)` — the very call the owner's page makes, so the table is
    byte-identical to the owner's, anchor and `<caption>` included. The
    shared renderer comes in by a function-local import, the way `links.py`
    pulls `_calc_reference_targets` (build.py imports blocks.py at module
    level). Preceded by one
    `<p class="calcblock-caption">DEC-PWR-001 / losses</p>` — the item id is
    left bare so the page's own `_linkify` pass links it, exactly as
    `{{index}}`'s ID cells are.
  - Registered as `calcblock`: `required=("item", "block")`, `optional=()`,
    `accepts=("block", "item")`, `missing_names_accepted=True`. The closed
    set is what makes `all=` and `board=` refuse by name (Q7).
  - Check order: exists → `external` → has `item.calcs` → block name matches.
    `external` before the empty-calcs test so an imported item is refused *as
    imported*, never misdiagnosed as an item that computes nothing.
  - Nothing is evaluated: no `item._env`, no `calc.evaluate_block`, no
    verdict of its own. An owner whose calc failed renders its `calc-error`
    row here unchanged; the block adds no diagnostic at the page's line.

## Tests

`tests/test_calcblock.py` — 19 tests, every §10 Phase-3 row, §7 messages
asserted whole (not substring) where §7 specifies them:

- rendering: `renders_owner_rows` (§8.3's table cell for cell),
  `caption_names_owner_and_block`, `two_directives_render_two_blocks` (no
  render-all default), `renders_a_composite_item_ref`.
- never evaluates: `never_evaluates` — code-object pin (no `_env`,
  `evaluate_block`, `evaluate`, `parse_limit`, `resolver`; `calcs` present)
  plus a stored-row rewrite that changes the page (a re-evaluating renderer
  could not do that) — and `renders_the_owner_error_row` (the owner's single
  error stays at the owner's item; zero errors attributed to the page; no
  pass/fail wording on the page).
- §7 errors: `unknown_block_lists_names`, `item_without_calcs`,
  `missing_block_param`, `unknown_param` (`all=`), `imported_item_errors`.
  Plus `missing_item_param`, `no_board_or_tag_param`,
  `item_that_does_not_exist`, `unnamed_blocks_only`.
- plumbing: `local_items_only` (upstream text never rendered),
  `unknown_block_name_untouched`, directive inside a fenced example is not
  executed, `no_write_identical` (full `_site` snapshot compared byte for
  byte).

## Findings / decisions logged

- **Names in "It names: losses, supply." are sorted.** §8.1 authors the
  blocks `supply` then `losses`; §7's error lists them `losses, supply`.
  Alphabetical is the only reading consistent with both, and it makes the
  message deterministic regardless of authoring order.
- **The name set comes from `item.calcs`, not a second body walk** (§3.6's
  explicit reason for `CalcLine.block` existing).
- **§5.4's empty-state paragraph is unreachable here.** Because the name set
  derives from rows, a block name that matches always has ≥1 row; every
  "nothing to render" case is one of §7's named errors instead. No empty
  branch was invented for it.
- **Two edges §7 has no message for**, resolved to the house shapes:
  - unknown `item=` → `{id} does not exist.{_suggest(...)}`, the same shape
    `_compare_bound_targets` raises.
  - item that computes but names nothing → §7's `#calc:` warning wording,
    `DEC-THM-009 has calc blocks but none is named -- add id="..." to its
    fence to make this block work.` ("It names: " with an empty list says
    nothing useful; rendering the unnamed block would ignore the directive.)
- **Two captions on purpose.** §5.4: "the same table `_calc_table_html`
  produces on the owner's page … plus a caption line naming the owning item
  and the block name." The table keeps its own `<caption class="calc-caption">`
  and `id="calc-losses"` anchor because it *is* the owner's table; the added
  line is the block's own. Rendering the same block twice on one page would
  duplicate that anchor — §5.4 does not address it, and no §10 test covers
  it; noted, not fixed.
- No docs/math.md sentence added — no §10 Phase-3 test requires one; that is
  Phase 5's pass.

## Verification

- `python -m pytest -q` — 2102 passed (19 new).
- `ruff check --select E9,F` on `src/refdes/blocks.py` and
  `tests/test_calcblock.py` — clean.
- `--no-write` byte-identity proven in-test against a full `_site` snapshot
  (`test_calcblock_no_write_identical`), not against pinned raw bytes.

Status: Phase 3 complete.
