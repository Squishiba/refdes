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

Finished. Only src/refdes/cli.py touched (plus this log).
