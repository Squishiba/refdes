# chk-attr-003c — blind test designer

Task: write tests (no product code) for CHK-ATTR-003, where `refdes check
--board NAME` leaks an id-less item's `[?]`-display-id diagnostics from other
boards.

## What I wrote

- `tests/test_check_board_scope.py` — fixture `noid_board_project`: two
  boards (board-a, board-b); board-a has `log.md` (id `LOG-A-001` + stray
  `text:` field) and `noid.md` (no id + same stray `text:` field); board-b has
  a clean `log2.md`. Both board-a items emit the identical warning
  "unknown field 'text' on log entry", so only the file path tells their
  diagnostics apart. Invoked via the real in-process CLI `cli_mod.main(...)`
  with `--no-write check --board ...`, matching tests/test_build.py.
- `tests/chk-attr-003c.cases.json` — maps each node id to expected_on_base.

## Reproduction / run

`PYTHONPATH=src <venv>/bin/python -m pytest -q tests/test_check_board_scope.py`
on the current (unfixed) source: **2 failed, 5 passed**. The two failures are
the new-behavior tests:
- `test_id_less_item_warning_absent_for_other_board`
- `test_other_board_summary_excludes_id_less_item_warning`
The other five are controls that must already pass on the base code.

Verified the leak live: `check --board board-b` prints
`WARNING items/board-a/noid.md:2 [?] — unknown field 'text' on log entry.`
and counts it (summary "1 warnings"). The project-level
"item has no id — run 'refdes id' to allocate one" error stays visible for
every board (emitted to stderr), and keeps exit 1.

## Notes

- Repro fixture lives in `.scratch/chk-attr-003c-repro/` (gitignored).
- `python -m refdes` has no `__main__`; used the in-process CLI helper as the
  other check tests do.
- Task finished: tests + cases.json + this log committed on the designer branch.
