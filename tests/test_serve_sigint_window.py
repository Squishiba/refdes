"""The Ctrl+C window between the launch file appearing and serve serving.

`--token-file` is documented as "removed when serve stops cleanly -- Ctrl+C or
SIGTERM", and the scripted client's readiness signal is the file's existence
(docs/cli-reference.md: `until [ -s /tmp/refdes-launch.txt ]`). Those two
statements compose into a promise: the moment the file exists, a Ctrl+C must
stop the launch cleanly. It did not -- CI run 42651482508 (commit 80f7fcc, a
test-only change) saw `test_token_file_is_removed_when_serve_stops` fail with
`assert -2 == 0`.

A negative returncode is a process killed by that signal's *default action*
(SIGINT, i.e. signal 2), not a Python exit. `serve` writes the launch file
first and only later enters the `try/except KeyboardInterrupt` that turns a
Ctrl+C into a clean exit; a SIGINT landing in that gap is an *uncaught*
KeyboardInterrupt, and CPython's top-level behaviour for one is to re-raise
SIGINT with SIG_DFL -- the process dies by signal 2 and leaves the bearer
credential on disk. The window is real: a stress loop (`.scratch/sigint/`)
reproduced it at ~3% under CPU contention, leaving the token behind every time.

The fix writes the launch file inside the KeyboardInterrupt guard, so the
file's existence always means a clean stop is armed.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time

import pytest
from serve_support import make_project

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def _reset_sigint_to_default():
    # A suite run as a background job has SIGINT set to SIG_IGN, and an ignored
    # signal survives exec(); reset it so the child sees the SIGINT we send, as
    # it does from a terminal. Mirrors tests/test_serve_cli.py.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


# The child's entry point when the window must be widened: set the app's
# test-only delay, then run the real CLI. The knob lives in the test, not in
# src -- `refdes.serve.server.launch_file_window_delay` defaults to 0.0 and no
# production code reads an environment variable to reach it.
_BOOTSTRAP = (
    b"import sys\n"
    b"import refdes.serve.server as server\n"
    b"server.launch_file_window_delay = float(sys.argv[1])\n"
    b"from refdes.cli import main\n"
    b"raise SystemExit(main(sys.argv[2:]))\n"
)


def _start(config, token_file, tmp_path, window_delay: float | None = None):
    env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC), PYTHONIOENCODING="utf-8")
    if window_delay is None:
        argv = ["-m", "refdes.cli", "-c", config, "serve", "--no-open",
                "--token-file", token_file]
    else:
        child = tmp_path / "window-child.py"
        child.write_bytes(_BOOTSTRAP)
        argv = [str(child), str(window_delay), "-c", config, "serve", "--no-open",
                "--token-file", token_file]
    return subprocess.Popen(
        [sys.executable, *argv],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        preexec_fn=None if os.name == "nt" else _reset_sigint_to_default,  # noqa: PLW1509
    )


def _wait_for_complete_line(path, proc, timeout=180.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if text.endswith("\n"):
                return text
        if proc.poll() is not None:
            raise AssertionError(f"serve exited ({proc.returncode}) before writing {path}")
        time.sleep(0.001)  # 1 ms, the smallest gap the OS will show us
    raise AssertionError(f"{path} never held a complete line")


def _kill(proc):
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=30)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Popen.send_signal(SIGINT) raises 'Unsupported signal: 2' on Windows; "
    "the Ctrl+C path is POSIX-only, exactly like the sibling test in test_serve_cli.py",
)
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_ctrl_c_in_the_window_right_after_the_launch_file_stops_cleanly(tmp_path, sig):
    """Ctrl+C (and `kill $pid`) landing the instant the launch file exists must
    stop cleanly -- exit 0, credential removed.

    ``launch_file_window_delay`` widens the gap between the launch file
    reaching disk and the accept loop, so the signal is delivered inside the
    stop-handling window deterministically (the real window is microseconds and
    the flake reproduced at ~3%); with the fix that whole span is guarded, so
    the signal is caught. Before the fix the file was written outside the
    KeyboardInterrupt guard, the signal was uncaught, and the launch died by
    signal (returncode -2 / -15) leaving the credential on disk. The child sets
    the delay from the test's bootstrap, not from an environment variable in src.
    """
    token_file = str(tmp_path / "launch-url.txt")
    proc = _start(make_project(tmp_path), token_file, tmp_path, window_delay=2.0)
    try:
        text = _wait_for_complete_line(token_file, proc)
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+/\?token=\S+\n", text), text
        proc.send_signal(sig)
        proc.wait(timeout=60)
        assert proc.returncode == 0, (
            f"the {sig!s} stop was not clean: returncode {proc.returncode} "
            "(negative == killed by signal's default action, i.e. uncaught)"
        )
        assert not os.path.exists(token_file), "a dead launch's credential outlived it"
    finally:
        _kill(proc)


def test_the_launch_file_is_not_written_until_stop_handling_is_armed(tmp_path):
    """The invariant, locked in-process: `EditorApp.__init__` must not create the
    launch file; it is created by `arm_launch_file`, which runs inside the guard.

    This is the property that closes the window: a reader that sees the file can
    trust that a clean stop is armed. It is deterministic and cross-platform --
    no signal timing, so it runs on Windows too, where the Ctrl+C path above
    cannot.
    """
    from refdes.serve.server import EditorApp

    token_file = str(tmp_path / "launch-url.txt")
    app = EditorApp(str(make_project(tmp_path)), poll_interval=60, token_file=token_file)
    try:
        assert not os.path.exists(token_file), (
            "__init__ wrote the launch file before the stop signal is armed -- the "
            "readiness signal must not exist before a clean Ctrl+C is possible"
        )
        app.arm_launch_file()
        assert os.path.exists(token_file), "arm_launch_file did not create the launch file"
    finally:
        app.stop()
    assert not os.path.exists(token_file)
