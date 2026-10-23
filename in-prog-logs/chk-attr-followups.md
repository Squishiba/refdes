# CHK-ATTR follow-ups (branch fix-chk-attr-followups)

Task (from .scratch/qwen-followup2.txt): two follow-ups to merged CHK-ATTR
PRs, one PR titled "chore(check): CHK-ATTR-003 changelog fragment and
declared Page.front_matter_lines".

## Item 1 — changelog fragment for PR #357

`changelog.d/check-board-id-less-item-diagnostics.fixed.md` added, in the
neighbouring `*.fixed.md` style (single bullet, user-facing). Claims
verified by running `refdes check` from `./.scratch/r18repro` (copy of
`/home/jorb/work/refdes/.scratch/agentcoder-pilot-repro-20261021/` plus a
stray `items/board-c/` dir with an id-less item, board-c not in `boards:`):

- `--board board-b`: board A's `[?]` "unknown field" warning no longer
  appears (this is the leak #357 fixed; "before" is the merged commit
  message + tests/test_check_board_scope.py names like
  `test_id_less_item_warning_absent_for_other_board`).
- `--board board-a`: shows board A's `[?]` warning.
- `items/board-c/` (unregistered path): its `[?]` diagnostic stays visible
  under *both* `--board board-a` and `--board board-b` — unattributable,
  per the fragment.
- "item has no id" ERRORs (no item_id) visible under every `--board`; plain
  `check` (no flag) shows everything — unchanged.

## Item 2 — declared Page.front_matter_lines

`Page` (model.py:746) now declares `front_matter_lines: int = 0`; pages.py
passes it in the constructor instead of setting it after construction;
build.py:3662 reads `page.front_matter_lines` directly (getattr gone).
Behavior unchanged: grep shows no other readers; dataclass field appended
last with a default, so positional construction elsewhere is unaffected.
tests/test_page_block_lines.py: added
`test_invalid_front_matter_page_reports_true_line` (invalid YAML front
matter -> not stripped, front_matter_lines stays 0, directive's
body-relative line is already the file line; 7 passed).

## Numbers

Full suite foreground: 4395 passed / 2 skipped. ruff E9,F on the four
touched files clean. Not merged (left to a human).
