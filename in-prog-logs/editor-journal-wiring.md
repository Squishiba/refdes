# editor-journal-wiring (backlog finding 15a)

Wire `src/refdes/editor_journal.py` (#367, landed unwired) into the editor
save path, add `refdes recover`, and gate project-loading commands.

Acceptance boundary quoted from docs/design/browser-editor.md: "If the
process is killed between two replacements, a visible
`.refdes/editor-transaction/` is left behind, and all project-loading
commands are refused until `refdes recover` restores it."

## Tests FIRST — RED on current main

Wrote tests/test_editor_journal_wiring.py before any source change. Run:
`PYTHONPATH=src .../python -m pytest -q tests/test_editor_journal_wiring.py`
→ **23 failed, 5 passed** on main (tip 703f0bd). Representative failing
lines:

- :107 `assert seen and all(tx is not None for tx in seen)` —
  `assert ([None] and False)`: no journal armed while `_atomic_replace`
  runs (save path never calls the module).
- :270 `assert rc == 2` — `assert 0 == 2`: `check`/`build`/`index`/`ls`/
  `id`/`audit`/`schema`/`rename` all load happily over a pending journal.
- recover tests die in argparse (`invalid choice: 'recover'`); crash tests
  find `pending(...) is None` (nothing journals).

The 5 that passed on main are guards, not new behavior: read-only commands /
read-only save never create a journal, no-project commands unaffected,
create-crash guard (asserts recovery only IF a journal exists), concurrent
saves (passes pre-wiring too; pins journal serialization post-wiring).

## Scope decisions

- Journal covers item files only. `editor_journal.begin` raises ValueError
  for entries inside `.refdes` (its control namespace), so
  `.refdes/citations.yaml` (lockfile) and `.refdes/ids.yaml` (ledger) are
  NOT journaled. A kill between the accept pair's lockfile write and item
  write leaves an inert pin + journaled item; recover restores the item
  half to the complete old state (test_crash_between_the_pair...).
- Kill after `complete()` would have run (post-save journal survival):
  the save IS reported applied, with the survival named in the message;
  recover then rolls it back to the complete old state (documented,
  tested).
- Unwritable journal dir (chmod 0o500 on `.refdes`): save is refused,
  nothing written, no journal dir left behind (tested).
- CLI gate lives in `main()` before the write lock, so `serve` is gated
  too (test runs it in a thread with a join timeout — main() dispatches
  to a blocking serve loop).

## Result

All 28 wiring tests green. Full suite: 4916 passed, 2 skipped. Two control
tests in tests/test_editor_journal.py pinned the module task's scope rule
("landed unwired") — flipped to pin the wired state. Ruff on the touched
files shows only the two findings already on main (cli.py module docstring,
edit.py DTZ005 `date.today()`); no new findings.

Journal messages route through serve's `_write_outcome` scrubber, pinned by
the no-absolute-root tests (journal-pending refusal + unwritable-dir
refusal, whose OSError text names the control directory before scrubbing).

Finished: wired, gated, recoverable, documented (cli-reference recover
section, design-doc status, changelog fragment).

## Review round (PR #381, reviews cd1478d + a828d8e)

CI: windows-latest failed on ONE real test,
test_crlf_bytes_survive_the_journal_and_recover: the fixture's
`replace(b"\n", b"\r\n")` doubles the fixture's Windows-written CRLF
(write_text translates on write), and `---\r\r\n` does not parse as
front-matter. Fixture now normalizes before converting. The 19F+5E in the
review transcript are the reviewer's local symlink-permission artifacts,
not CI (ubuntu 2/2 green, windows log: 1 failed, 4703 passed).

RED lines recorded for the review fixes (each failed on 42a92ec before
the implementation pass):
- tests/test_editor_journal.py::test_recover_refuses_a_live_file_missing_where_the_replacement_belongs -- DID NOT RAISE JournalCorrupt
- tests/test_editor_journal.py::test_recover_unparseable_manifest_is_journal_corrupt -- DID NOT RAISE
- tests/test_editor_journal.py::test_recover_refuses_a_live_file_that_matches_neither_hash -- DID NOT RAISE
- test_editor_journal_wiring.py::test_recover_refuses_an_unreadable_manifest_and_keeps_the_journal -- rc 0, journal cleared, half-apply left live
- test_editor_journal_wiring.py::test_recover_refuses_a_live_file_the_transaction_does_not_describe -- rc 0, silently overwrote the outside writer
- test_editor_journal_wiring.py::test_recover_clears_a_journal_directory_that_recorded_nothing -- printed "recovered editor transaction unknown"
New pins that were already green on 42a92ec (reviewer's coverage gaps,
verified as real coverage, not behavior changes): hard-kill shape
(BaseException), real replace-failure-string journal clearing, create
rollback-failure journal survival (the old conditional create test is
gone), new-file (original=None) journal entry + recover-removes-created,
Created.journal_warning, fetch in the gate parametrization.
