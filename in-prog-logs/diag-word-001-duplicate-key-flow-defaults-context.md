# DIAG-WORD-001 — duplicate-key context under an inline-flow `defaults:`

Date: 2026-10-15. Branch: `fix/duplicate-key-inline-defaults-context-20261015`.

## The finding (verified PRESENT on current main before the fix)

Baseline (`in-prog-logs/current-main-resweep-yaml-diagnostics.txt`, row 001,
reproduced at 8b6a52e): a list file whose first line is
`defaults: { type: requirement, prefix: REQ-A }` and whose top-level `items:`
is repeated printed the false clause `(in this file's defaults:, so every
item here inherited it)`.

Re-verified at this branch's HEAD (7e49a20) with the real CLI in
`.scratch/diag-word-001/p1` (`PYTHONPATH` pinned to this worktree's `src`,
`refdes.parse.__file__` asserted to the worktree path):

- `a_dup_inline.yaml` (inline-flow defaults, `items:` twice) — printed the
  clause. Present.
- `b_dup_direct.yaml` (block defaults, `items:` twice) — no clause. The
  control isolating the cause.

Root cause: `parse.py::_duplicate_entry_id` decided the attribution by
comparing `record.mapping_line` to `defaults_line`. A flow mapping on line 1
and the document's own top-level mapping both start on line 1, so the
comparison fires for both.

## The fix

Structural mapping identity, read off the node graph while it is being
constructed, carried on the record:

- `DuplicateKey` gains `is_top` / `is_defaults` (defaults False).
- `_note_document_root` (new): a loader's first constructed mapping is its
  document's root (construction is depth-first); the root's `defaults:` key's
  value node is kept by identity (`loader.defaults_node`) — node identity is
  exact during construction where line numbers are not.
- `_collect_duplicates` tags every record it collects; wired in
  `_construct_mapping` (item files) and `_construct_mapping_dupes` (config
  files; the config path ignores the tags).
- `_duplicate_entry_id`: entry-line check first (unchanged), then
  `is_defaults` → clause, then `is_top` → no id/no clause, then the existing
  enclosing-entry walk. The `defaults_line` parameter is gone.
- The two per-mapping groupings (`parse_list_file`,
  `_report_duplicate_keys`) key on `(mapping_line, is_defaults, is_top)`, so
  a line-1 flow-defaults repeat and a line-1 top-level repeat cannot merge
  into one survivor-chaining group.

The line comparison cannot be replaced by "check top line first" — a repeat
*inside* an inline-flow `defaults:` on line 1 shares that line too, and
checking top first would silently drop the clause the existing
`test_a_repeat_in_a_defaults_block_is_reported_as_such` pins. The new
`..._inside_flow_defaults_shares_line_one_and_keeps_the_clause` pins the
other side of the same shared line.

## Tests

`tests/test_parse.py`, after the block-defaults clause test:

- red on HEAD (proved by restoring HEAD's `parse.py` over the tree, file
  backed up in `.scratch/diag-word-001/parse_fixed.py.bak`; no stash):
  `test_a_top_level_repeat_under_flow_defaults_is_not_blamed_on_the_defaults`,
  `test_a_top_level_repeat_and_a_flow_defaults_repeat_are_told_apart`.
- control passing on HEAD and after:
  `test_a_top_level_repeat_under_block_defaults_is_not_blamed_on_the_defaults`,
  `test_a_repeat_inside_flow_defaults_shares_line_one_and_keeps_the_clause`.
- sibling boundary (DIAG-WORD-005, nested one level inside block defaults —
  unchanged behavior, pinned):
  `test_a_repeat_nested_inside_a_defaults_block_is_not_blamed_on_the_defaults`.
  Not fixed: it is not in the defaults mapping nor the top-level one, and
  giving it a clause is a scope broadening this seam does not naturally make
  (the structural fix says "neither mapping", which is today's answer).

Green after fix: targeted (`test_parse.py`, `test_config_duplicate_keys.py`),
full suite (`3869 passed, 2 skipped`), `ruff check` on both touched files
(project default set + `I`) clean. CLI re-probe after the fix: false clause
gone from `a_dup_inline.yaml`, block control unchanged,
`c_dup_flowdefaults.yaml` (repeat inside inline-flow defaults, shared line 1)
keeps the clause.

## Finish state

Finished. Changelog fragment:
`changelog.d/duplicate-key-flow-defaults-context.fixed.md`.
