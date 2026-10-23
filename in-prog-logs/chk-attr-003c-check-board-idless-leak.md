# chk-attr-003c — check --board leaks id-less items' diagnostics

Task: `refdes check --board NAME` showed warnings from id-less items in
other boards' reports, because parse reports those diagnostics with the
display id `?`, which resolves to no item, so the `--board` filter in
`_visible()` skipped them and every board showed them.

Reproduced first in `.scratch/chk-attr-003c/proj/` (two-board fixture,
`items/board-a/log.md` with id + unknown-field warning,
`items/board-a/noid.md` id-less + same warning, clean `items/board-b/
log2.md`): `check --board board-b` listed `noid.md`'s warnings on main.

Fix (src/refdes/cli.py only): added `_scope_of_items_path()`, which maps
a file path under `items/` to its (board, workspace) by the same layout
rules `boards.resolve()` uses (board segment per `item_layout`, matched
against each spec's `path:` alias). In `_visible()`, an item diagnostic
whose `item_id` resolves to no item (the `?` case) now attributes by its
own file path instead of falling through the filter. Diagnostics with no
`item_id` at all — e.g. "item has no id — run 'refdes id' to allocate
one" — keep their project-level posture: visible under every board
selection, per docs/cli-reference.md. Items with ids take the identical
item-based path as before.

Verified against the fixture: `text` warning present for `--board
board-a`, absent for `--board board-b`; the no-id error present for
both; no-filter output unchanged. Ran tests/test_check*.py,
test_build.py, test_workspaces.py, test_blocks.py, test_exit_codes.py
(186 passed), then the full suite.

## PR #357 review round (5 items)

1. Narrowed the path fallback to `d.item_id == "?"` only — parse.py
   reports id-less items as `item.id or "?"`, so other emitters
   (blocked.py, build.py where_id, seal.py display_id, former_ids.py
   new_id) keep their prior every-scope visibility. Added a test
   (synthetic `LOG-A-999` diagnostic, visible for every board).
2. Added `item_layout: workspace` tests: the board axis (second path
   segment) and the `--workspace` filter (first segment), plus the
   no-id error visible under all five scope selections.
3. Chose "keep visible": a `?`-id diagnostic under an UNREGISTERED
   items/ segment is unattributable, so `--board` must not hide it —
   `_scope_of_items_path` now returns None per axis on no registry
   match (documented as a deliberate divergence from
   `boards._derive`'s `""`). Test added.
4. `_scope_of_items_path` now reuses `boards.path_segments` +
   `boards._path_index`/`workspaces._path_index` (no import cycle:
   neither imports cli); the remaining 3-line segment pick carries a
   comment pointing at `boards._board_segment`/`_derive`.
5. Restored `tests/chk-attr-003c.cases.json` from 17e00f1 and added
   the 5 new test cases to it.

Ran `pytest -q tests/test_check_board_scope.py` (12 passed) and the
check/board suites above (198 passed). Confirmed the 2 new-behavior
workspace tests fail on the pre-fix source (base cdf85c0~1) and pass
after.

Finished. Touched src/refdes/cli.py, tests/test_check_board_scope.py,
tests/chk-attr-003c.cases.json, this log.

