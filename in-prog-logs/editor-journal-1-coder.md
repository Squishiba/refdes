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

## Review round 1 (PR #367)

Cross-model review: complete()'s `ignore_errors=True` was a real safety
bug (a swallowed removal leaves an armed journal; a later recover undoes
the completed save), the journal's visible rename was not directory-fsync
durable, and the designer log claimed an undelivered cases.json. Fixed
all three, RED-first (5 new tests, all failing on the old code):
complete() now deletes manifest.json first (FileNotFoundError = idempotent
no-op; any other failure raises, journal stays armed); the inert debris
left by a failed rmtree is removed by recover as a crashed begin, so a
completed save can never be undone — complete raises on debris failure so
pending() can't block silently, and the message points at recover.
_fsync_dir now runs after the visible rename in begin, after the manifest
unlink and after the removals in complete, and after both removals in
recover; it swallows only unsupported-platform cases and propagates real
I/O errors. Designer log corrected re cases.json (not delivered).
tests/test_editor_journal.py: 53 pass (47 frozen designer tests unchanged,
6 added).

## Review round 2 (PR #367, manual review of 98cb7ae)

Three MEDIUMs, all fixed test-first (5 RED tests, 4 failing on the old
code): unreadable manifest -> recover no longer deletes the journal
(_read_manifest_raw raises JournalCorrupt naming the path on any OSError
that is not FileNotFoundError; only missing/genuine parse failures mean
the inert crashed-begin state; pending() maps JournalCorrupt to
"unknown" so the refusal gate keeps reporting it). Symlink escape: new
_escapes_root resolves each entry's live parent and requires
os.path.commonpath containment under realpath(root) -- recover raises
JournalCorrupt changing nothing, begin raises ValueError leaving no
journal; final-component symlinks are replaced/removed as links by
os.replace/os.remove, never followed; a guard test keeps
project-internal symlinked dirs allowed. Durability: begin now fsyncs
orig/ (the backups' own directory) before writing the manifest and the
staging rename, per the recorded fsync order test. Module is 496 lines.
Targeted 58 pass (47 frozen unchanged), full suite 4468 passed / 2
skipped (exit 0), ruff clean.

Finished.

## Round 3 (addendum of review 72b1902) — findings A-F

All six fixed test-first in `src/refdes/editor_journal.py`, RED checked
first (10 RED; the duplicate-paths test initially passed accidentally via
the hash check on a tampered entry, rewritten to use not-existed entries
so the duplicate itself is the operative cause):

- A. `recover` fsyncs each restored file's parent directory (once each)
  before `shutil.rmtree(journal)` — restored state is durable before the
  safety net is removed.
- B. `complete()` now clears inert debris: manifest-missing journals get
  their directory removed too (a leftover directory kept
  `refuse_if_pending` blocking projects whose save succeeded).
  No-journal-at-all stays the silent no-op; manifest-removal and
  directory-removal failures both raise, the latter pointing at recover.
- C. `_is_safe_relpath` now rejects `.`, empty segments and trailing
  slashes (so `a/`, `a//b`, `a/./b`, `.`), matching the "one spelling
  per file" contract. Checked at begin (ValueError) and in
  `_manifest_entries` (JournalCorrupt); the recover-side loop moved into
  the parser so all readers get it.
- D. `pending()` uses `os.path.exists` like `begin` does: a plain file at
  the journal path now reports `"unknown"` instead of "clear", so the
  guard and the save refuse exactly the same projects.
- E. A journaled live path that is a directory on disk raises
  `JournalCorrupt` naming it, as a pre-restore check — nothing is
  touched, journal kept (previously a bare `IsADirectoryError` mid-
  restore).
- F. Duplicate/equivalent paths in a manifest raise `JournalCorrupt`
  in `_manifest_entries` (keyed on the split segments, which the strict
  path check now normalizes).

One existing test changed, as the addendum allows:
`test_complete_on_disarmed_journal_is_a_noop` (a round-1 test, not one
of the 47 frozen designer tests) pinned the old "debris left behind"
behavior; rewritten as `test_complete_removes_a_disarmed_journal_
directory`. The 47 frozen designer tests are unchanged.

Tests: 69 passed in tests/test_editor_journal.py (47 frozen + 22 added
across rounds; 11 this round incl. 6 parametrized dot-path cases). ruff
clean (default + E501,I on the two files). Full suite run recorded
below.
