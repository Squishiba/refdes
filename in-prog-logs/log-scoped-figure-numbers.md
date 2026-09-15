# Per-board / per-workspace log page figure numbering — test gap closure

Test-only task (no `src/` changes). Closes a blind spot noted on the two
existing per-board / per-workspace log figure tests: each project had only ONE
log entry, so a `figured` closure accidentally built over *all* log entries
(say) would still have passed. Figure numbering is per page, so a wrong closure
shows up as a wrong figure NUMBER.

## What was added (tests/test_render_assets.py)

- `test_per_board_log_page_numbers_figures_against_its_own_entries`:
  two boards (`power`, `control`). `power/log-001.md` (2026-01-05) defines
  `fig-a`; `control/log-002.md` (2026-01-06) defines `fig-b` and references
  `[[fig:fig-b]]`. Because of the date order, the unscoped `log.html` numbers
  fig-a "Figure 1" and fig-b "Figure 2" (asserted, to lock the premise). The
  test asserts `log-control.html` numbers fig-b "Figure 1" (its own first
  figure), its reference link reads "Figure 1", and `fig-a` never appears on
  that page.
- `test_per_workspace_log_page_numbers_figures_against_its_own_entries`:
  the same shape with workspaces `product-a` / `product-b`, asserting on
  `log-product-b.html`.

## Sabotage checks (temporary src edits, both restored)

1. Per-board: changed render.py's per-board `log-<board>.html` write to build
   its `figured` closure over `_log_entries(project)` (all entries). The test
   FAILED exactly where expected: `log-control.html` rendered fig-b's caption
   as "Figure 2" instead of "Figure 1" — assertion
   `"<figcaption>Figure 1 — Control curve</figcaption>" in html` failed (the
   reference link would also have read "Figure 2").
2. Per-workspace: same change for the per-workspace write. The workspace test
   FAILED the same way on `log-product-b.html`.

`git diff -- src/` was empty after restoring — the only change is the test file
(plus this log). Full suite: `python -m pytest -q` green (count in final report).

## Notes

- FIG_PNG is the 8-byte PNG signature stub already used by the sibling tests;
  the images are only present so the `![...](figures/*.png)` figures parse —
  `_process_images` needs the file to exist.
- ruff: the file's bare `open(...).read()` pattern (SIM115) is pre-existing
  throughout (13 findings at HEAD); the added tests follow the same style, so
  they add instances of the same pre-existing class, not a new violation.