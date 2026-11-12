# fix(serve): Ctrl+C right after the launch file appears exits cleanly

## Symptom

`tests/test_serve_cli.py::test_token_file_is_removed_when_serve_stops` failed on
main's push CI (run 42651482508, ubuntu-latest, commit 80f7fcc, a test-only
change) with `AssertionError: assert -2 == 0` at the line after
`proc.send_signal(signal.SIGINT)`. A negative returncode is a process killed by
that signal's default action (SIGINT = signal 2), not a Python exit. 6432 tests
passed; the failure is a rare Linux-only flake.

## Frequency check

`gh run list --branch main --limit 30`: 5 conclusions=failure; 2 on
ubuntu-latest (42651482508 = the named 80f7fcc; 42632897923 whose test name is
unverifiable — GH log archives expired, `gh run view --log-failed` returns 0
lines). The other 3 failures are windows-latest. So a rare, Linux-only flake.

## Diagnosis (hypothesis (a) confirmed by code + stress)

`cmd_serve` (src/refdes/cli.py) constructs `EditorApp(...)`, which wrote the
launch file in `__init__` (src/refdes/serve/server.py), printed the URL, then
only entered `with sigterm_stops_cleanly(): try: app.serve_forever()
except KeyboardInterrupt: pass`. The test's `_wait_for_file` returns the instant
the file exists — which is during `__init__`, long before the KeyboardInterrupt
guard. A SIGINT in that window is an *uncaught* KeyboardInterrupt; CPython's
top-level behaviour re-raises SIGINT with SIG_DFL, so the process dies by
signal 2 (returncode -2) and the credential file is left on disk.

Confirmed the CPython mechanic with a 5-line probe (top-level KeyboardInterrupt
during `time.sleep` → shell 130 = 128+2). Confirmed the product window with a
stress loop (`.scratch/sigint/stress.py`): start serve with `--token-file`, poll
the file at 1 ms, send SIGINT, record returncode + whether the file survived.

- BEFORE (under 20-way busy-loop CPU contention, ~CI parallel load):
  `{0: 290, -2: 10}`, **10 token files left behind** (3.3% signal-kills, every
  one leaking the credential).
- On an idle box (no contention) the window is microseconds wide: 30/30 clean.

## Fix (product ordering — the docs promise a clean stop whenever the file exists)

`docs/cli-reference.md` states two clean stops (Ctrl+C, SIGTERM), that a scripted
stop exits 0 and leaves no credential, and gives the readiness idiom
`until [ -s file ]` — so "the file exists" must imply "Ctrl+C is safe". Fixed by
writing the launch file only after the stop handling is armed:

- Split the refusal checks out of `write_launch_file` into
  `check_launch_file_target`; `__init__` calls the check (early refusal → exit 2,
  no URL printed) and records `self._token_file_target`, but writes nothing.
- New `EditorApp.arm_launch_file()` writes the file (setting `self.token_file`
  first so a mid-write signal still finds it to remove) and is called from
  `serve_forever` / `cmd_serve`, inside the `except KeyboardInterrupt` /
  `finally: stop()` guard, after the SIGTERM handler is installed.
- `cmd_serve` restructured: the SIGTERM `with` is entered first, `app` is bound
  and construction + arm + prints + serve all run inside one guarded try
  (`ServeStartupError`→2, `KeyboardInterrupt`→0, `finally: app.stop()`). The
  `--token-file` refusal tests still exit 2 before any URL (the check stays in
  `__init__`).

## Deterministic test (red-first, new file `tests/test_serve_sigint_window.py`)

- `test_the_launch_file_is_not_written_until_stop_handling_is_armed`: in-process,
  cross-platform — `__init__` must not create the file; `arm_launch_file` does.
- `test_ctrl_c_in_the_window_...stops_cleanly` (SIGINT and SIGTERM, POSIX): widens
  the window with the env knob `REFDES_SERVE_TEST_WINDOW_DELAY` (seconds, read in
  `arm_launch_file`, unset by default), sends the signal the instant the file
  appears, asserts returncode 0 and file removed.

Red (old code, knob injected into the pre-guard `__init__` window):
`-2` for SIGINT (the exact CI failure `assert -2 == 0`) and `-15` for SIGTERM,
plus the in-process ordering test — 3 failed. Green after the fix: 3 passed.

## AFTER stress (same 20-way contention, fixed code)

- `.scratch/sigint/stress.py` 300 runs: `{0: 299, 1: 1}`, **0 signal-kills,
  0 credentials left behind**.
- `.scratch/sigint/stress2.py` 250 runs (capturing output on rc≠0): `{0: 250}`.
- Startup-timeline probe (SIGINT at 0.05–0.8 s after launch, 40 each): all rc 0.

The single `rc 1` (1/300) left **no** credential and is not the CI's `-2` (a
generic Python exit-1, not a signal death). It did not reproduce at 0/250,
0/~570, or 0/200, and is not produced by the token-file window (that window is
fully guarded after the fix). Noted as an unreproduced non-leak anomaly.

## Verification

- `tests/test_serve_cli.py` + `test_serve_sigint_window.py` +
  `test_serve_security.py`: 67 passed.
- `tests/test_crossplatform_lint.py`: 26 passed.
- `ruff check` on touched files: only two pre-existing findings (the
  `.encode("utf-8")` payload line at HEAD, and `cli.py:3` import-sort) — not
  introduced by these edits; left per the repo's not-ruff-clean note.

Full suite run separately (see final report).

## Fix round (whole-PR review, 3 findings)

(1) `arm_launch_file` set `self.token_file = target` *before*
`write_launch_file`, so a write that refuses/fails after `__init__`'s check (a
foreign file planted in the check→arm window, ENOSPC on the temp) left a
`token_file` pointing at a path serve never created — and `cmd_serve`'s
`finally: app.stop()` then unlinked it, contradicting the `__init__` comment
and docs/cli-reference.md's "exit 2, no launch, and the path left exactly as it
was". Fix: write first, claim (`self.token_file = target`) after. The ordering
that closes the SIGINT window is kept: the handler is still armed before the
write (cmd_serve's guard), ownership now follows the write. The window the new
ordering opens — rename landed, flag not set — is handled in the raising frame:
`except BaseException` calls `_remove_launch_file_if_ours(target, payload)`,
which unlinks only a regular file (lstat) whose bytes equal *this* launch's URL.
Token is per-launch and the rename atomic, so matching bytes prove the file is
ours; a refused target, a stale file (older token → different bytes), a symlink
or a huge file are never touched. Signal-handler consistency: a SIGINT landing
anywhere in the write+claim region raises at a bytecode boundary in this frame,
the cleanup runs here before the re-raise, and `stop()` sees `token_file` None
and no-ops — one owner, one removal, in either interleaving. Mid-write signals
leave the target absent (rename never ran) and only a `.refdes-launch-*.tmp`
(partial URL, 0600) — the documented pre-existing behaviour of
`write_launch_file`'s kill-window, unchanged.
RED first (new `tests/test_serve_launch_ownership.py`, in-process, cross-platform):
foreign file planted after construction + arm refuses → stop() had unlinked it
(`FileNotFoundError` reading it back); ENOSPC-on-temp over a stale launch file →
stale file unlinked; signal in the write→claim gap → credential still on disk;
control (successful arm → stop removes) passed. 3 failed / 1 passed on the head,
4 passed after the fix.

(2) `REFDES_SERVE_TEST_WINDOW_DELAY` was the only `os.environ` read in
src/refdes and `float(raw)` raised uncaught on garbage. Replaced with a
default-off module seam `launch_file_window_delay = 0.0` read at call time.
The subprocess test reaches the child through a bootstrap the test writes
(`window-child.py`: set the attribute, then call `refdes.cli.main`) — no env
var in src. (3) removed the literal `(#task)` from the changelog fragment.

- Stress loop re-run after the fix-round change (`.scratch/sigint/
  contention.sh` = 20 busy-loops + `stress.py`, same recipe as before): see the
  PR report for the distribution.
- `test_serve_cli.py` + `test_serve_sigint_window.py` +
  `test_serve_launch_ownership.py` + `test_crossplatform_lint.py` green.
- Informational (PR body): `EditorApp(..., token_file=...).start()` (background
  thread) no longer writes a launch file — only `serve_forever`/`cmd_serve` arm
  it; `grep -rn "token_file=" src/ tests/ editors/` finds no caller of
  `EditorApp(token_file=...)` outside `cli.cmd_serve`, so nothing depended on it.
