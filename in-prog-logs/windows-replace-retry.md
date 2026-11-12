# windows-replace-retry

Task: on Windows, `os.replace(tmp, path)` raises WinError 5/32/32 when
any other handle (the server's poller, an editor, antivirus) has the
destination open -- Python's `open()` does not pass FILE_SHARE_DELETE.
Evidence: main push CI run 42648833899, job windows-latest
(129269332507), job log line 453/508:
`the write failed ([WinError 5] Access is denied: 'items/.log.yam...
-> 'items/log.yaml')` from
`test_the_continue_route_resolves_the_key_and_the_display_id`.

## What was done

- `textio.replace_with_retry(src, dst, *, attempts=10, delay=0.08)`:
  POSIX = exactly `os.replace`; Windows retries only OSError with
  `winerror in (5, 32, 33)` (module constants `_IS_WINDOWS`,
  `_TRANSIENT_REPLACE_WINERRORS`), no sleep after the final failure
  (worst case 9 x 0.08 s = 0.72 s), re-raises the LAST error unchanged
  so every caller's existing OSError handling sees the same failure.
  `_IS_WINDOWS` is read at call time so tests can force the platform.
- Call sites switched: `serve/edit.py` `_atomic_replace` and `_restore`,
  `textio.atomic_write_text`, `navis_archive.archive_record`,
  `editor_journal._atomic_write_bytes` (file replace only; the
  directory replace in `editor_journal.begin()` left alone -- no
  evidence of that race, and a directory rename's sharing semantics
  differ), `history._restore_atomically`. `history`/`edit` already
  imported textio; added imports to `navis_archive` and
  `editor_journal` (no cycle: textio imports no refdes modules).
- `tests/test_replace_retry.py` (8 tests): transient-denial retry
  (counted calls + recorded sleeps), exhaustion re-raises the last
  error, WinError 2 not retried, winerror-less OSError (the shape the
  existing suites inject) not retried, forced-posix passthrough x2
  (success and denial: exactly one call, no sleep), and two
  `_atomic_replace` integration tests -- the Windows failure shape
  (fail twice, land) returns success with the bytes on disk, and
  persistent denial returns the same "the write failed" refusal with
  the original bytes and no temp residue.

## Red/green

Red first: all 8 new tests failed on `textio` lacking `_IS_WINDOWS`
(`AttributeError`). After the change: 8 pass. No real Windows behaviour
is simulated beyond the monkeypatched exceptions -- the tests force the
platform via `os.name` + `textio._IS_WINDOWS` and run identically on
Linux and Windows CI. No test sleeps in real time (time.sleep
monkeypatched).

Pins checked for conflict: `test_serve_edit.py` (recording_replace,
failed_replace `OSError("injected failure")`, boom, hijack) and
`test_history_redact_rollback.py` (`_faulty_replace` OSError(28)) all
inject winerror-less OSErrors -> not retried; no pin conflicts, task
continued to PR.

## Verification

- New + test_serve_* + test_editor* + test_navis* + test_history* +
  crossplatform lint + preset atomicity: 2285 passed, 1 skipped.
- Full suite once: 6446 passed, 2 skipped.
- `ruff check --select E9,F` on all touched files: clean.
- pr_size: src additions ~90 lines (helper + 6 one-line call sites +
  2 imports), well under 350.

Status: finished. Not verifiable locally: the real Windows effect
(FILE_SHARE_DELETE semantics) -- it will only show in Windows CI over
time; the Linux tests prove the control logic, not the OS behavior.

## Review round 2 (2026-11-12)

- `seal.save_seals` switched to `textio.replace_with_retry` (its
  destination `.refdes/log-seal*.yaml` is a project file a concurrent
  reader can hold, same race class as the save). Its existing
  `except OSError -> _record_seal_write` handling is kept -- the
  exhaustion re-raise lands there unchanged.
- `replace_with_retry` clamps `attempts` to at least 1: on Windows
  `attempts <= 0` skipped the loop and hit `raise last` with
  `last = None` -> TypeError. Test `test_attempts_below_one_is_clamped_
  to_a_single_attempt` (red first: TypeError; green: WinError-5
  PermissionError, one call, no sleep).
- Stale log citation fixed: the excluded directory replace is the
  rename inside `editor_journal.begin()` (no line number cited).

### All `os.replace(` in src/refdes after round 2 (audit)

| Site | Decision |
| --- | --- |
| `textio.replace_with_retry` (both calls) | the helper itself |
| `editor_journal.begin()` journal-dir rename | excluded: destination is a fresh journal directory, never a project file a poller/editor/AV reader holds open; a directory rename's sharing semantics differ (stated in round 1, unchanged) |
| `serve/server.write_launch_file` `--token-file` rename | excluded: the destination is the launch credential written at server startup, before the poller and HTTP threads exist; readers are external scripts that open-read-close, not project files |

Round-2 tests: 3 new in `tests/test_replace_retry.py` (2 seal
integration + 1 clamp), all red-first against the pre-change code, 11
pass after; full-suite re-run recorded below.
