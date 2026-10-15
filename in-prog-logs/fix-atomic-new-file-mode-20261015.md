# fix/atomic-new-file-mode-20261015 — PERM-OWNER-002 (2026-10-15)

Finding (`in-prog-logs/current-main-resweep-write-permissions.tsv` row
PERM-OWNER-002, read-only): `textio.atomic_write_text` creates its temp with
`tempfile.mkstemp` (always 0600) and copies the target's mode only
`if os.path.exists(path)` — no else-branch, so every file the helper
creates *new* lands 0600. Reproduced on current main's code: `refdes id`
in a fresh hardware@3 project under umask 022 wrote `.refdes/ids.yaml` at
0600 beside a 0644 `.refdes/schema.json`.

## Caller audit (required before touching the shared helper)

All callers of `atomic_write_text` (grep over src/, 2026-10-15):

- `ids.py:152` `save_ledger` → `.refdes/ids.yaml`: the finding's repro.
  Public data (allocated ids), siblings are umask-mode. Wants umask.
- `ids.py:660` id write-back into source files: target always exists
  (items were loaded from it) → mode-preservation branch, unchanged.
- `scaffold.py:719/791` add/remove-pconfig writes: config exists (project
  was loaded from it; `_config_write_target` resolves a symlink) →
  preservation branch, unchanged.
- `scaffold.py:766` remove-preset `.scratch` simulation copy: new file,
  short-lived (deleted in the `finally`), content is the project config —
  no privacy intent; the pre-#219 truncate write created it at umask
  mode. Now 0644/0664 while it lives. Only semantic change for a caller.
- `revise.py:747/812` rewrite + rollback: source files exist →
  preservation branch, unchanged.

No caller intends a private 0600 file. The one private file in the codebase
(`--token-file` launch URL, `serve/server.py:405`) uses `mkstemp` + explicit
`fchmod 0o600` on its own path, not this helper — untouched, intent intact.

## Fix

`src/refdes/textio.py`: new `_create_temp(directory, name)` creates the temp
itself with `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o666)` so the kernel
filters the mode through the umask (0666 & ~umask), with the same 100-roll
collision retry and the same `.{name}.refdes-tmp-{random}` naming as
`mkstemp` gave. Deliberately identical to the merged seal fix
(`seal._create_temp`, PERM-OWNER-001, PR #229) — including *not* reading
`os.umask` (process-wide; set-and-restore has a cross-thread window).
Existing-file mode preservation is unchanged. The `tempfile` import is gone
(no other user in the module), `secrets` added.

`tests/test_preset_write_atomicity.py`: its ENOSPC injector recorded fds
minted by `tempfile.mkstemp`; the helper no longer calls mkstemp, so the
injector now records fds minted by `os.open` whose basename matches. The
test names/prefixes are unchanged (the temp keeps its naming shape).

## Coordination — PR #244 (editor rollback, serve/edit.py)

PR #244 lives in `serve/edit.py`'s own `_atomic_replace`
(mkstemp + `os.chmod(tmp, os.stat(path)...)`, the editor always writes
*existing* files, so its mkstemp path has no new-file gap; its rollback
bytes problem is untouched by this change). No file overlap; this PR changes
only `src/refdes/textio.py` + its test injector. If #244 lands first, no
rebase conflict expected (disjoint files).

## Verification

- Red (real CLI, `PYTHONPATH` pinned to this worktree's `src`,
  `refdes.__file__` verified): pre-fix helper → new `.refdes/ids.yaml`
  0600, schema.json 0644 (probe `.scratch/perm-owner-002/repro.py`).
- Red (tests, pre-fix textio restored in place): 5 failed / 2 passed —
  new-file 0644 & 0664, CLI ledger under both umasks, collision-retry
  (no `_create_temp`); mode-preservation and umask-spy pass pre-fix
  (pinning, as intended).
- Green: new `tests/test_atomic_write_mode.py` 7/7; same CLI probe now
  shows ids.yaml 0644.
- Targeted suites green: test_preset_write_atomicity, test_write_lock,
  test_ids, test_scaffold, test_revise* (5 files),
  test_readonly_explicit_writes, test_eol_fidelity, test_seal — 392 passed.
- Full suite green: 3845 passed, 2 skipped (~5m18s).
- Scoped ruff: `ruff check src/refdes/textio.py tests/test_atomic_write_mode.py
  tests/test_preset_write_atomicity.py` → 1 finding, RUF023 on
  `SourceText.__slots__` (line untouched by this change, present at HEAD —
  pre-existing, left alone per AGENTS.md).
- `os.umask` spy test proves the helper never touches the process umask.

Status: finished. Branch pushed, PR opened (no merge).
