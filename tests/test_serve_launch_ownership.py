"""`--token-file` ownership: a failed arm never unlinks a path serve did not create.

`arm_launch_file` writes the launch file and `stop()` removes it, but the claim
that lets `stop()` remove it is `self.token_file` -- and the docs promise a
refused `--token-file` leaves "the path left exactly as it was"
(docs/cli-reference.md), and `__init__` promises "a failed launch never unlinks
a path it did not create". A write can fail *after* the check in `__init__` ran:
a foreign file planted at the target in the window between that check and the
arm, or ENOSPC when the temp file is created. If `arm_launch_file` claims the
target before the write succeeds, the failed launch's `stop()` unlinks the very
file it refused to touch.

The fix sets `self.token_file` only once the write has succeeded. That leaves a
signal window between the rename landing the file and the flag being set, and
the fix handles it where it lands: a KeyboardInterrupt in the gap is caught in
`arm_launch_file` itself, which removes the file this launch demonstrably wrote
(the bytes are exactly its launch URL) before re-raising -- so the credential
never outlives a clean stop, and ownership is never claimed over bytes the
launch did not write.
"""

from __future__ import annotations

import errno

import pytest
from serve_support import make_project

# The exact shape of a launch file: one URL, newline-terminated. A file like
# this at the target is "a file of ours" and the check allows overwriting it --
# which is what makes it the interesting victim of a write that then fails.
_STALE_LAUNCH = b"http://127.0.0.1:8123/?token=" + b"a" * 43 + b"\n"


def _make_app(tmp_path, token_file):
    from refdes.serve.server import EditorApp

    return EditorApp(str(make_project(tmp_path)), poll_interval=60, token_file=token_file)


def test_a_refused_arm_leaves_a_file_that_appeared_after_the_check_untouched(tmp_path):
    """A foreign file planted at the target between `__init__`'s check and the
    arm must survive the refused launch, byte for byte.

    `__init__` checked an absent path, so the refusal surfaces from the arm
    (the write re-checks). The launch must not remove what it refused to
    overwrite -- the docs' "the path left exactly as it was".
    """
    from refdes.serve.server import ServeStartupError

    target = tmp_path / "launch-url.txt"
    app = _make_app(tmp_path, str(target))  # target absent: the check passes
    foreign = b"# project notes, not a launch file\n"
    try:
        target.write_bytes(foreign)  # appeared between the check and the arm
        with pytest.raises(ServeStartupError):
            app.arm_launch_file()
    finally:
        app.stop()
    assert target.read_bytes() == foreign, (
        "the refused launch's stop() unlinked the foreign file it promised "
        "to leave exactly as it was"
    )


def test_a_write_failure_leaves_the_target_exactly_as_it_was(tmp_path, monkeypatch):
    """The write itself failing (here: ENOSPC creating the temp) is also a
    refusal -- exit 2, path untouched. A stale launch file at the target is
    *this tool's own*, so the check allows the overwrite; a failed overwrite
    must still leave the old bytes in place, not delete them.
    """
    from refdes.serve import server

    target = tmp_path / "launch-url.txt"
    target.write_bytes(_STALE_LAUNCH)  # a relaunch onto our own stale file
    app = _make_app(tmp_path, str(target))
    try:
        def boom(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(server.tempfile, "mkstemp", boom)
        with pytest.raises(server.ServeStartupError):
            app.arm_launch_file()
        assert target.read_bytes() == _STALE_LAUNCH
    finally:
        app.stop()
    assert target.read_bytes() == _STALE_LAUNCH, (
        "stop() unlinked a launch file this launch never wrote"
    )


def test_a_signal_in_the_gap_between_the_write_and_the_ownership_flag_removes_the_file(
    tmp_path, monkeypatch
):
    """The window the new ordering opens: the bytes are on disk, the ownership
    flag is not set yet. A KeyboardInterrupt landing there must still not
    leave the credential behind -- and the cleanup is provably of *our* file:
    the bytes on disk are exactly this launch's URL.

    The fake write lands the real payload then raises, standing in for a
    signal that hits after the rename returns and before the flag is set. The
    fix removes the file inside `arm_launch_file`, in the raising frame, so
    the promise holds before `stop()` ever runs.
    """
    from refdes.serve import server

    target = tmp_path / "launch-url.txt"
    app = _make_app(tmp_path, str(target))
    try:
        def write_then_signal(path, url):
            with open(path, "wb") as fh:
                fh.write(f"{url}\n".encode())
            raise KeyboardInterrupt

        monkeypatch.setattr(server, "write_launch_file", write_then_signal)
        with pytest.raises(KeyboardInterrupt):
            app.arm_launch_file()
        assert not target.exists(), (
            "a launch killed after writing its credential must take it with "
            "it -- the clean-stop promise holds from the moment the file lands"
        )
    finally:
        app.stop()
    assert not target.exists()


def test_a_successful_launchs_file_is_removed_on_stop(tmp_path):
    """Control: ownership taken by a *successful* write is honoured -- the
    file lands on arm and dies with the launch.
    """
    target = tmp_path / "launch-url.txt"
    app = _make_app(tmp_path, str(target))
    app.arm_launch_file()
    assert target.exists(), "arm_launch_file did not create the launch file"
    app.stop()
    assert not target.exists(), "a dead launch's credential outlived it"
