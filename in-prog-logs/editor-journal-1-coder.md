# editor-journal-1 — editor_journal module

Task: standalone transaction-journal module for browser-editor saves
(docs/design/browser-editor.md "Transaction model"). Library only —
serve/edit.py and cli.py deliberately untouched, wiring is a later task.

## Done

- `src/refdes/editor_journal.py` (~390 lines, stdlib only, no refdes
  imports — the atomic-write helpers are a local byte-mode copy of the
  textio.py/seal.py idiom, as the contract allowed).
- Public API per contract: `JOURNAL_DIR`, `JournalPending` (message carries
  the transaction id and `refdes recover`), `JournalCorrupt`, frozen
  `Entry`, `begin`/`pending`/`refuse_if_pending`/`complete`/`recover`.
- begin: validates all paths (absolute, `..`, backslash, colon, empty,
  duplicates incl. `./`-equivalence) BEFORE creating anything, so a
  ValueError leaves nothing behind. Builds the journal in a
  `mkdtemp` sibling of `.refdes/editor-transaction`, writes originals
  (`orig/<index>.bin`, position-named) first, `manifest.json` LAST
  (temp + fsync + `os.replace`), fsyncs the staging dir, then `os.replace`
  the whole directory into place — never a half-visible journal. A racing
  create makes `os.replace` fail; that is reported as `JournalPending`.
- recover: no journal -> []; unreadable/missing manifest -> journal
  removed, [] (crash inside begin); structural garbage or unsafe manifest
  path -> `JournalCorrupt`, nothing touched; verifies EVERY stored
  original against its recorded sha256 before touching any live file;
  restores atomically (parents created) / deletes created files; reports
  only paths whose live state changed; journal removed only after every
  entry is done, so it is idempotent.
- `changelog.d/editor-journal-module.added.md` added.

## Verification

`ruff check src/refdes/editor_journal.py` (also with `--select E501,I`)
clean, and the scratch check
`.scratch/editor-journal-1-check/check.py` covers every contract bullet:
begin contents, JournalPending text, invalid-path ValueError with no dir
left, lifecycle + idempotent complete, recover restore/delete/report-
changed/idempotence, tampered and missing originals (JournalCorrupt,
journal kept, live files untouched), missing/garbled manifest (journal
removed, []), simulated mid-save crash (only the replaced file reported,
non-journaled file untouched), unsafe manifest path, parent-directory
recreation. All pass on the project venv (py3.13).

One scratch-script bug along the way (stale journal path after a root
re-creation) — module code was correct, the checks were fixed.

Finished.
