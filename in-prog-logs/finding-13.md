# Finding 13 — `{{index tag=}}`: mirror the existing `board=` filter

Backlog finding 13: `{{index}}` gains a `tag=` filter parameter, mirroring the
`board=` parameter it already has. `tags:` is the field this project uses for
cross-cutting grouping that does not follow board or type lines, and
`{{index}}` was the one place that could not select on it. One fixed, named,
single-valued parameter — deliberately not a query language.

## What I did

1. **Synced first** (`git merge --ff-only main`): fast-forwarded the stale
   worktree tip to `8e33c08` before touching anything (STEP 0 of the task).
2. **Grounded on the schema**: `tags` is declared in the `provenance` field
   set as `{ type: list, on_change: ignore }` (verified in
   `src/refdes/standards/hardware/v3/base.yaml` line 81 and the test schema's
   own decision type). Read how it is actually stored on an item by checking
   `cli.py`'s `_item_tags` (line 340): `item.fields.get("tags")`, lenient
   about list-vs-scalar, values stringified. `item.fields` is the storage
   (model.py Item).
3. **`src/refdes/blocks.py`**:
   - Added `"tag"` to the index `BlockSpec`'s `optional=` tuple.
   - Added `_item_tags(item)` — the same lenient list/scalar read `cli.py`
     uses, duplicated rather than imported (blocks.py already duplicates
     `_ATTR_RE` for the same circular-import reason; build.py imports blocks,
     cli.py imports build).
   - `_render_index` now reads `tag = params.get("tag")`, builds the known
     tags set from every local item's tags, validates `tag` against it the
     way `board` is validated (`_BlockError` + `_suggest`, so a typo names
     the nearest real tag), and adds `(tag is None or tag in _item_tags(item))`
     to the comprehension — so `board=` and `tag=` AND, never OR.
   - Known tags come from `project.local_items`, the same population the
     index filters over; an imported item's tag is not "known", so a tag
     that only exists there fails loudly instead of silently rendering an
     empty table.
4. **`tests/test_blocks.py`** (no new file): three tests placed next to the
   existing board-scoping tests —
   - `test_index_tag_scoping`: `tag="review"` selects exactly DEC-001 and
     DEC-002 (both carry `review`), not DEC-003 (no tags).
   - `test_index_tag_and_board_scope_together`: `tag="review" board="power"`
     plus a new DEC-004 (tagged `review`, on the thermal board) written by
     the test itself — if the two filters OR'd, DEC-004 would sneak in under
     its tag alone; AND correctly keeps it out (as does DEC-003, matching
     neither). An earlier draft of this test used only the stock fixture,
     where both filters happen to select the same two items — it could not
     distinguish AND from OR, so I added the one-filter-only item.
   - `test_index_unknown_tag_suggests_a_correction`: `tag="reviw"` raises
     the block error naming `unknown tag 'reviw'` and suggesting `'review'`
     (the loud-failure case that must not silently render an empty table).
5. **`docs/blocks.md`**: added the `tag` row to `{{index}}`'s parameter
   table, matching the `board` row's register; also refreshed the stale
   `index accepts: by, type, board.` string in the failure-modes example to
   `by, type, board, tag.` (that message literally changed with this patch).

## Difficulties

- None blocking. The only fiddly bit was deciding where the known-tags set
  comes from: `project.items` vs `project.local_items`. Chose local items —
  the index only ever lists local items (`test_index_only_local_items_not_imports`),
  so a tag that only exists on an import should fail loudly rather than
  validate to an always-empty table.
- The existing `test_index_unknown_parameter_names_accepted_ones` asserts
  `"by, type, board" in msg` as a substring; adding `tag` makes the message
  `by, type, board, tag` — the substring still matches, so no test edit was
  needed there, and I did not touch its expected values.

## Verification

- `python -m pytest tests/ -q` → 650 pre-existing + 3 new = **653 passed,
  0 failed**.
- `git status --short` → only `src/refdes/blocks.py`, `tests/test_blocks.py`,
  `docs/blocks.md`, `in-prog-logs/finding-13.md`.

## Status

Finished. Committed locally per the task's spec (message + trailers); not
pushed, no PR.