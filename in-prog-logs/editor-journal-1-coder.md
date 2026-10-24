# editor-journal-1 — editor_journal module

Task: standalone transaction-journal module for browser-editor saves
(docs/design/browser-editor.md "Transaction model"). Library only —
serve/edit.py and cli.py deliberately untouched, wiring is a later task.

## State

- `src/refdes/editor_journal.py`, stdlib only, no refdes imports:
  `JOURNAL_DIR`, `JournalPending`, `JournalCorrupt`, frozen `Entry`,
  `begin`/`pending`/`refuse_if_pending`/`complete`/`recover`. Phase
  model in the module docstring: STAGING -> ARMED -> DISARMED -> GC;
  `complete` and `recover` tear a journal down through one
  `_disarm_and_gc` helper (manifest removed, journal dir fsynced, then
  backups deleted), and every live/backup/manifest read goes through
  one lstat classifier (`_classify`). begin stages in a temp sibling,
  writes originals (`orig/<index>.bin`, position-named) first and
  `manifest.json` last, renames the directory in as one unit; recover
  verifies EVERY stored original before touching any live file and is
  idempotent. `changelog.d/editor-journal-module.added.md` added.
- Every round: RED tests first, targeted + full suite + ruff
  (default and `--select E501,I`) clean. Round-0 scratch checks live in
  `.scratch/editor-journal-1-check/`.

## Mutation sites x checks-before-first-mutation

| mutation site | checks that run before it |
| --- | --- |
| begin: makedirs/mkdtemp in `.refdes`, staging writes | entry safety (incl. NUL, Windows-mangled names) + escapes_root + duplicates + journal-internal + namespace (alias/ancestor/.refdes-alias, shared `_namespace_problems`) (ValueError); `.refdes`/journal confinement (ValueError); pending → JournalPending |
| begin: `os.replace` staging→journal; root/parent fsyncs | all of the above; late-fsync failure WITHDRAWS the journal; root fsynced when `.refdes` is new |
| recover: squatter `os.remove` | `_journal_parent_escapes_root` first; acts on the journal path, never follows |
| recover: journal teardown (`_disarm_and_gc`, inert + recovery tail) | confinement; inert only for missing/not-JSON manifest; DISARM barrier (fsync journal dir) always precedes the backup GC, re-run on every pass |
| recover: live-file writes/unlinks | full parser validation (path, dup, alias, ancestor, control namespace, hash schema) + escapes_root + lstat dir/special refusal, ALL pre-restore; final components lstat'ed, never followed; parent fsync chains run after the last write, on every pass |
| recover: backup/manifest reads | lstat: regular file only — symlink/special → JournalCorrupt naming the entry; unreadable → JournalCorrupt naming the entry |
| complete: teardown | `_journal_escapes_root` → OSError; same disarm→barrier→GC helper |
| pending / `_fsync_dir` | read-only (fsync opens the dir); pending: lexists + confinement → "unknown" |

Round-7 rows have pinned tests: namespace rows →
`..._paths_that_alias_one_file`,
`..._ancestor_(entry_paths|paths_in_the_manifest)`,
`..._control_(directory_alias|namespace)`; lstat rows →
`test_recover_replaces_a_symlink_whose_target_already_matches`,
`test_recover_refuses_a_special_file_at_a_live_path`,
`test_recover_refuses_a_(backup|manifest)_that_is_a_symlink`,
`test_recover_names_the_entry_when_a_backup_cannot_be_read`; teardown
rows → `test_recover_disarms_the_journal_before_the_gc_replays`,
`test_complete_retries_the_disarm_barrier`,
`test_recover_unchanged_files_not_reported_and_journal_removed`;
barrier rows → `test_recover_syncs_the_live_directories_after_the_last_write`,
`test_recover_re_runs_the_durability_barrier_on_retries`; begin fsync →
`test_begin_fsyncs_the_root_when_it_creates_the_refdes_dir` (+ skip case);
path rules → `test_begin_rejects_paths_containing_nul_bytes`,
`test_begin_rejects_windows_mangled_names` (8 ids); hash schema →
`test_recover_refuses_malformed_entry_hashes` (3 ids),
`test_recover_refuses_a_hash_for_a_file_that_never_existed`.

## Rounds (round number -> what landed)

- Round 1: complete() manifest-first + raises, journal-parent
  fsyncs everywhere, real fsync errors propagate. 53 tests.
- Round 2: unreadable manifest → JournalCorrupt; `_escapes_root`
  for entry paths; begin fsyncs orig/. 58 / full 4468+2s.
- Round 3: recover fsyncs restored parents before the journal
  rmtree; complete clears inert debris; strict paths at begin + parser;
  pending "unknown" for journal-path squatters; live-is-directory
  refusal; duplicate manifest paths refused. One round-1 test rewritten
  (allowed). 69 / 4479+2s.
- Round 4: `_journal_escapes_root` confinement (begin ValueError,
  recover JournalCorrupt, complete OSError, pending "unknown"); lexists
  for dangling-symlink restores. 71 / 4481+2s.
- Round 5: recover clears non-directory squatters (reports
  [JOURNAL_DIR]); pending/begin lexists; PermissionError swallowed by
  `_fsync_dir` on Windows only; mode contract documented. 74 / 4484+2s.
- Round 6: confinement BEFORE recover's squatter delete
  (`_journal_parent_escapes_root`); `_NO_MANIFEST` sentinel (parsed
  non-object = corruption, journal kept); begin late-fsync withdrawal;
  journal-internal path refusal; leaf→root fsync chain. 85 / 4495+2s.

## Round 7 (on round 6's head) — phase model + 14 probe findings

Deep analysis `.scratch/analysis/deep-analysis-pr367.md` + 23 probes
(baseline on round 6's head: 8 PASS / 15 FAIL). Structure written into the
module first (docstring phase model, shared `_disarm_and_gc`, shared
`_classify`, shared `_namespace_problems`), then one RED test per
finding (30 new, all confirmed RED first):

- P04 alias duplicates: identity = (realpath parent, leaf; leaf
  casefolded on nt/darwin) — begin ValueError / parser JournalCorrupt.
- P05/P11 begin refuses Windows device stems (extension included),
  trailing dot/space, and NUL — on every platform, conservatively.
- P07 begin fsyncs the project root when it creates `.refdes` (root
  first, then the journal parent; the withdrawal path covers both).
- P08/P23 live-parent fsync chains run AFTER the restore loop over
  EVERY entry (leaf→root, each dir once, non-directories skipped): the
  barrier lands after each directory's last write, and re-runs on a
  retry that restores nothing.
- P09/P19 recover's recovery tail, recover's inert path and complete
  share `_disarm_and_gc`: manifest removed → fsync journal dir → GC →
  fsync `.refdes`; the barrier re-runs when the manifest is already
  gone, so an interrupted teardown can never leave a retry restoring
  live bytes from backups it is about to delete.
- P10/P15/P21/P22 every live path, backup and manifest is lstat'ed:
  symlinks are replaced as links, never read through (an
  equal-content symlink is replaced, not "already restored"); special
  files are refused and kept; an unreadable backup is JournalCorrupt
  naming the entry, never a bare OSError.
- P12 the parser validates the full hash schema (64 lowercase hex;
  original_sha256 iff existed) before any mutation.
- P13 ancestor/descendant entry paths refused at begin and by the
  parser, as are `.refdes`-alias (control-namespace) paths.

Out of scope, documented as limits in the docstring: P14 (a *different*
process swapping a path component between check and write — the caller
serializes writers) and the P18 nuance (begin publishes before its
final fsync; withdrawal covers it). Windows name rules are enforced on
every platform but nothing here is Windows-native tested — the Windows
behavior is a reading of the rules, not a verified one.

## Round 8 — designer log wording

The designer log claimed 45 functional tests; the frozen set is 44
functional + stdlib control (collect-only verified); one line fixed.

## Round 9 — durability through symlinked parents; journal-symlink un-wedge

- Chain fsync (RED first): chain nodes classified "symlink" get fsynced
  through the link (`os.open` follows to the real directory the
  restored bytes live in; the link's parent is already in the chain);
  an "error:" classification propagates as OSError.
- `_read_orig` classifies `orig/` itself: a symlinked/missing backup
  directory is JournalCorrupt naming it (the leaf lstat never sees the
  directory behind the link).
- A journal-path symlink to a directory no longer wedges: recover's
  squatter branch covers it (the LINK is removed, never followed,
  target untouched); begin reports a confined journal-path symlink
  (dangling included) as JournalPending, not as a location escape.
- Tests: the vacuous manifest-bytes comparison captures the bytes
  before and compares to them; hard-coded `orig/0.bin` replaced by
  the structural helper.
- Docs: hard-kill staging debris (`.editor-transaction-*` siblings)
  documented as a limit; changelog fragment starts with `- `; no
  commit SHAs cited in logs.

## Verification

Probes on this head: PASS P01-P13 and P15-P28 (P24-P28 new this round);
FAIL P14 only (the documented limit). Targeted 120; full suite 4530 / 2
skipped; ruff clean (default + `--select E501,I`). Frozen tests (47)
unchanged all rounds; one round-1 test rewritten in round 3 (allowed).
