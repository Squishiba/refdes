# History redact rollback: atomic restore, disclosed failure

Ticket: PR #244 reviewer 3389f9ee — `src/refdes/history.py` redact's
rollback loop restored removed files with `open(path, "wb").write(blob)`
inside `except Exception:`. Two defects in one shape: the open truncates at
open, so a write faulting (injected ENOSPC) left the removed event 0 bytes;
and the restore's `OSError` escaped the handler and *replaced* the original
exception. PROGRESS row: "History redact rollback may truncate a removed
event" (Sol's lane, resumed by Claude on usage).

## Reproduced (red) on current main (de9d664)

`.scratch/repro-history-redact-rollback/test_probe_redact_rollback.py`:
capture LOG-001, force `append_event` to raise (the original failure), fault
every rollback write with ENOSPC. On main: victim event file 453 -> 0 bytes,
escaping exception `OSError: [Errno 28] No space left on device` (the
original `RuntimeError` masked). Matches the reviewer's probe (390 -> 0).

## Fix

`src/refdes/history.py`:
- New `_restore_atomically(files)`: bytes -> house-shaped same-directory
  temp (`.{name}.refdes-tmp-{random}`, `secrets` naming, `O_CREAT|O_EXCL`
  at 0666 so the mode lands at umask like the store's own writes — the
  `textio._create_temp`/`seal._create_temp` idiom, PERM-OWNER-001/002) ->
  write/flush/fsync -> one `os.replace` per file. The target is created
  whole or not at all; a faulted restore leaves the path exactly where the
  removal left it (absent). Faulted temps are unlinked (best-effort);
  returns `(path, reason)` for files that did not land.
- New `_create_temp` (same module, mirroring seal/textio).
- `redact`'s `except Exception as exc:`: restores via the helper; on any
  restore failure raises `HistoryError` naming the original failure, the
  restored/total count, and each unrestored file (project-relative, "/"-
  spelled) with its reason — `from exc`, so the original is `__cause__`.
  With no restore failures the original re-raises unchanged (as before).
- Docstring's "Transactional" paragraph updated to say what is now true.
- No touch to `serve/edit.py` (#244/#253 active lanes).

## Tests

`tests/test_history_redact_rollback.py` (4):
1. rolled-back redaction leaves store byte-identical + original raises
   unchanged (working-rollback regression guard);
2. faulted restore NEVER leaves a file at the event's path (the truncation
   defect) and the store still loads;
3. faulted restore reports both failures (count, both names, `__cause__`);
4. partly-faulted restore (events dir refuses renames, objects dir
   accepts): message counts 1-of-2 truthfully, names only the event.

Red-before/green-after verified: with `src/refdes/history.py` swapped for
the origin/main copy, tests 2-4 FAIL (truncation/masking/claims), test 1
passes (success path never broken). With the fix: 4/4 pass.

## Gates

- `python -m pytest tests/test_history.py tests/test_history_commands.py
  tests/test_history_capture.py tests/test_history_seal.py
  tests/test_exit_codes.py` -> 106 passed.
- Full suite once, foreground: 3907 passed, 2 skipped (exit 0).
- Scoped ruff (CI gate is `--select E9,F`, see .github/workflows/tests.yml):
  `ruff check --select E9,F src tests` -> clean; touched files clean.
  Note: first draft used a backslash escape in an f-string — invalid on the
  py311 target ruff enforces; restructured to a precomputed `rel`.

## Limits / notes

- The atomic restore changes the restored file's inode (like every atomic
  swap in this repo); a file created fresh by the restore gets the umask
  default, same as a store file written normally.
- A restore that faults leaves that file absent (state as the removal left
  it) — disclosed in the message, never silent; recovery bytes are the
  in-memory blobs, which die with the process. No journal by design.
- Concurrent writers mid-redact are out of scope (pre-existing; the store
  has no cross-process lock on the history dir today).
- PROGRESS.md row left as-is per the resume instruction not to touch the
  main checkout's `.scratch/`.

Status: finished. PR opened from `fix/history-redact-atomic-rollback-20261015`.
