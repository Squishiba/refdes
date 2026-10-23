# editor-journal-1 — editor_journal module

Task: standalone transaction-journal module for browser-editor saves
(docs/design/browser-editor.md "Transaction model"). Library only —
serve/edit.py and cli.py deliberately untouched, wiring is a later task.

## State

- `src/refdes/editor_journal.py`, stdlib only, no refdes imports:
  `JOURNAL_DIR`, `JournalPending`, `JournalCorrupt`, frozen `Entry`,
  `begin`/`pending`/`refuse_if_pending`/`complete`/`recover`. begin
  stages in a temp sibling of the journal, writes originals
  (`orig/<index>.bin`, position-named) first and `manifest.json` last,
  renames the directory in as one unit; recover verifies EVERY stored
  original before touching any live file and is idempotent.
  `changelog.d/editor-journal-module.added.md` added.
- Every round: RED tests first, targeted + full suite + ruff
  (default and `--select E501,I`) clean. Round-0 scratch checks live in
  `.scratch/editor-journal-1-check/`.

## Mutation sites x checks-before-first-mutation (round-6 process)

| mutation site | checks that run before it |
| --- | --- |
| begin: makedirs/mkdtemp in `.refdes`, staging writes | entry safety + escapes_root + duplicates + journal-internal (ValueError); `.refdes`/journal confinement (ValueError); pending → JournalPending |
| begin: `os.replace` staging→journal | all of the above; post-rename fsync failure now WITHDRAWS the journal (round 6) |
| recover: squatter `os.remove` | `_journal_parent_escapes_root` — resolves the `.refdes` component itself (round 6 HIGH: realpath(root) does not resolve it); `os.remove` acts on the journal path, never follows |
| recover: journal rmtree (inert manifest) | journal is a real in-root directory (journal-path symlink → JournalCorrupt); manifest missing/not-JSON only (`_NO_MANIFEST`) |
| recover: live-file writes/unlinks | path safety, duplicates, journal-internal, escapes_root, live-is-directory — ALL pre-restore (JournalCorrupt, nothing touched); final-component symlinks replaced/removed as links |
| complete: manifest remove, journal rmtree | `_journal_escapes_root` → OSError; inert-debris path keeps the manifest-first ordering |
| pending / `_fsync_dir` | read-only (fsync opens the dir); pending: lexists + confinement → "unknown" |

Every row had a round where it lacked a check: the squatter row is this
round's HIGH, begin's post-rename row this round's LOW, journal-internal
paths and the leaf-to-root fsync chain this round's LOWs, symlinked
`.refdes` round 4, entry symlink escapes round 2 — all rows now carry
checks with a pinned test each.

## Rounds (fix commit → what landed)

- R1 `98cb7ae`: complete() manifest-first + raises, journal-parent
  fsyncs everywhere, real fsync errors propagate (designer-log
  cases.json corrected). 53 tests.
- R2 `1ae59d8` (of 98cb7ae): unreadable manifest → JournalCorrupt (only
  missing/unparseable is inert); `_escapes_root` for entry paths; begin
  fsyncs orig/. 58 / full 4468+2s.
- R3 `27a610f` (addendum A-F): recover fsyncs restored parents before
  the journal rmtree; complete() clears inert debris; strict
  `_is_safe_relpath` at begin + parser; pending reports "unknown" for a
  file on the journal path; live-is-directory pre-restore
  JournalCorrupt; duplicate manifest paths JournalCorrupt. One round-1
  test rewritten (allowed). 69 / 4479+2s.
- R4 `853e519` (of 27a610f): `_journal_escapes_root` confines
  `.refdes`/journal (begin ValueError, recover JournalCorrupt, complete
  OSError, pending "unknown"); recover uses lexists for not-existed
  entries (dangling symlinks unlinked). 71 / 4481+2s.
- R5 `9009139` (of 853e519): recover clears non-directory squatters on
  the journal path, reported as [JOURNAL_DIR] — refuse→recover→begin
  works; pending/begin use lexists (dangling journal link refused as
  pending); PermissionError swallowed by `_fsync_dir` on Windows only;
  file-mode contract documented; PR-body SHAs corrected. 74 / 4484+2s.

## Round 6 (of 9009139) — five findings, RED-first (8 RED; 3
parametrized non-object manifests already passed via the parser)

- HIGH: the squatter branch ran BEFORE confinement and
  `realpath(root)` does not resolve a symlinked `.refdes` — with
  `<root>/.refdes -> /outside` and a file at `/outside/editor-transaction`
  recover deleted OUTSIDE the root. `_journal_parent_escapes_root()`
  now runs first in recover (before ANY mutation); a journal-path
  symlink to a directory is JournalCorrupt; the squatter removal only
  runs with a confined parent and acts on the journal path itself.
- MEDIUM: a manifest parsing to `null` became Python None — identical to
  "missing/unparseable", so recover rmtree'd the journal: silent loss
  of rollback data. `_NO_MANIFEST` sentinel separates the inert state
  (missing bytes / not JSON) from parsed non-object values, which
  reach `_manifest_entries` → JournalCorrupt, journal kept.
- LOW: begin's final durability fsync failing left an armed journal
  with no id returned; begin now removes the just-created journal
  (no live file touched) before re-raising — "failed begin leaves
  nothing" is documented in the docstring.
- LOW: entry paths naming the journal directory or anything under it
  are refused — begin ValueError, manifest parser JournalCorrupt
  (segment compare, safe after the strict-path check).
- LOW: recover's restore fsyncs the whole leaf→root directory chain
  (guarded, each dir once), not just the leaf parent — makedirs-created
  intermediates are durable.

11 RED/added tests; 85 targeted. Full suite: see Verification below.

## Verification

Targeted 85 passed; full suite 4495 passed / 2 skipped; ruff clean on
both files (default + `--select E501,I`). Frozen designer tests
(47) unchanged all rounds; one round-1 test rewritten in round 3
(explicitly allowed).
