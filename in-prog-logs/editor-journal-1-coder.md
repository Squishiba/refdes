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

`ruff check src/refdes/editor_journal.py --select E501,I` clean, and the
scratch check `.scratch/editor-journal-1-check/check.py` covers every
contract bullet: begin contents, JournalPending text, invalid-path
ValueError with nothing left, lifecycle + idempotent complete, recover
restore/delete/report-changed/idempotence, tampered and missing
originals, manifest states, simulated mid-save crash, parent-directory
recreation. All pass on the project venv (py3.13).

## Review round 1 (PR #367)

Cross-model review: complete()'s `ignore_errors=True` was a real safety
bug (a swallowed removal leaves an armed journal; a later recover undoes
the completed save), the journal's visible rename was not directory-fsync
durable, and the designer log claimed an undelivered cases.json. Fixed
all three, RED-first (5 new tests, all failing on the old code):
complete() deletes manifest.json first (FileNotFoundError = idempotent
no-op; any other failure raises, journal stays armed) and raises on
debris-removal failure pointing at recover; _fsync_dir runs after the
visible rename in begin, the removals in complete, and the removals in
recover, swallowing only unsupported-platform cases. Designer log
corrected. tests/test_editor_journal.py: 53 pass (47 frozen unchanged,
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

## Round 3 (addendum of review session 72b1902) — findings A-F

All six fixed test-first, RED checked first (10 RED; the duplicate-paths
test initially passed accidentally via the hash check on a tampered
entry, rewritten to use not-existed entries so the duplicate itself is
the operative cause):

- A. `recover` fsyncs each restored file's parent directory (once each)
  before removing the journal — durable before the safety net goes.
- B. `complete()` clears inert debris (manifest-missing journal
  directories), so a completed save never keeps `refuse_if_pending`
  blocking; no-journal stays the silent no-op, both removal failures
  raise.
- C. `_is_safe_relpath` rejects `.`, empty segments, trailing slashes;
  enforced at begin (ValueError) and in `_manifest_entries`
  (JournalCorrupt).
- D. `pending()` judges existence as `begin` does: a plain file on the
  journal path reports "unknown", not "clear".
- E. A journaled live path that is a directory raises `JournalCorrupt`
  naming it, as a pre-restore check; journal kept.
- F. Duplicate/equivalent manifest paths raise `JournalCorrupt`.

One existing test changed, as the addendum allows: the round-1
`test_complete_on_disarmed_journal_is_a_noop` pinned the debris-leaving
behavior; rewritten. The 47 frozen designer tests are unchanged. Tests:
69; full suite 4479 passed / 2 skipped; ruff clean.

## Round 4 (review 5aea024) — findings 1-2

- P1 journal-location confinement: `_journal_escapes_root()` resolves
  `<root>/.refdes` and the journal path and requires both inside
  realpath(root), with the journal path not a symlink. begin() raises
  ValueError before creating anything; pending() reports "unknown" (the
  gate refuses exactly what begin refuses); recover() raises
  JournalCorrupt; complete() raises OSError -- none of them follow the
  link, nothing is written or deleted outside the root.
- P2 dangling symlink at a not-existed path: recover's absence test is
  now `os.path.lexists` (exists() follows links, so a dangling link
  read as absent and survived recovery, ready to resolve later). The
  link is removed as a link and counted as restored.

Both RED first (the P1 test needed its symlink target genuinely outside
the root -- pytest's tmp_path IS the root here, so the first version's
target was inside it and the RED run caught that, not the code). No
existing tests changed; 47 frozen designer tests untouched.
Tests: 71 in tests/test_editor_journal.py; full suite 4481 passed,
2 skipped; ruff clean on the two files. The reviewer's "533 lines"
remark is explicitly out of scope for this round.

## Round 5 (manual review of 853e519) — findings 1-3

- MEDIUM wedged state: a non-directory squatter on the journal path
  (plain file, symlink, dangling symlink) is now removed by recover as
  the squatter it is -- os.remove of the path inside realpath(root),
  never following a link -- and reported as [JOURNAL_DIR], so the
  documented remediation (refuse -> recover -> begin) works. pending()
  and begin() moved from os.path.exists to os.path.lexists so a dangling
  journal symlink is refused as pending too (exists() follows it and
  called the project clear). Directories keep the existing rules
  (journal / inert debris / JournalCorrupt), and round 4's confinement
  of a symlinked .refdes is untouched.
- LOW fsync swallowing: _FSYNC_DIR_OPEN_UNSUPPORTED now swallows
  PermissionError only on Windows (os.name == "nt"); on POSIX EACCES
  from opening a directory is a real durability failure and propagates.
  Test monkeypatches os.open.
- The file-mode NIT is documented, not fixed: recover's docstring now
  states restored files get the process's default permissions -- the
  journal stores bytes and hashes, bytes are the contract.
- The PR body's stale/fabricated SHAs are corrected (its "5aea024" is
  the review session id, not a commit; head cited 98cb7ae, now 853e519).

RED first (3 tests). No existing tests changed; 47 frozen untouched.
Tests: 74; full suite 4484 passed / 2 skipped; ruff clean.
