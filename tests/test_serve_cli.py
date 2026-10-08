"""`refdes serve` as a real process: prints a launch URL on 127.0.0.1, serves
through it, and exits cleanly with its temp preview removed."""

from __future__ import annotations

import http.client
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

import pytest
from serve_support import free_port, make_project, path_of

from refdes.serve.server import sigterm_is_deliverable, sigterm_stops_cleanly

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def _reset_sigint_to_default():
    """Run in the forked child before exec (``preexec_fn``).

    A suite started as a background job has SIGINT set to SIG_IGN (POSIX
    does that for SIGINT and SIGQUIT for a job of a shell without job
    control), and an *ignored* signal survives ``exec()``, unlike a caught one. The
    child would then discard the SIGINT a test sends, serve would never see
    the Ctrl+C, and the launch would outlive the test as an orphan. Reset it
    here so serve starts with SIGINT at its default disposition, exactly as
    it does when a person starts it from a terminal.
    """
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _start(config, *extra, tmpdir=None):
    env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC), PYTHONIOENCODING="utf-8")
    if tmpdir is not None:
        # Isolate the child's preview temp dir so a concurrent run in the same
        # shared system temp dir cannot change what this launch created.
        env.update(TMP=str(tmpdir), TEMP=str(tmpdir), TMPDIR=str(tmpdir))
    return subprocess.Popen(
        [sys.executable, "-m", "refdes.cli", "-c", config, "serve", "--no-open", *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        # None is accepted on Windows and raises nothing; only a non-None
        # preexec_fn is refused there, and it has no Windows equivalent.
        # The fork is safe here in practice: the callback is one signal.signal
        # call before exec, and this harness's only threads block on readline
        # of a pipe -- they hold no lock the callback could need.
        preexec_fn=None if os.name == "nt" else _reset_sigint_to_default,  # noqa: PLW1509
    )


def _launch_url(proc):
    result = {}

    def read():
        result["line"] = proc.stdout.readline()

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(60)
    match = re.search(r"http://127\.0\.0\.1:\d+/\?token=\S+", result.get("line", ""))
    assert match, f"no launch URL printed: {result!r}"
    return match.group(0)


def test_serve_prints_a_loopback_url_serves_it_and_cleans_up(tmp_path):
    config = make_project(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    before = set(os.listdir(tmp))
    proc = _start(config, tmpdir=tmp)
    mine = []
    try:
        url = _launch_url(proc)
        port = int(re.search(r":(\d+)/", url).group(1))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path_of(url), headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 302 and "SameSite=Strict" in resp.getheader("Set-Cookie")
        conn.close()
        assert not (tmp_path / "_site").exists()
        # this launch's preview is in the isolated temp dir, marked
        mine = [n for n in set(os.listdir(tmp)) - before if n.startswith("refdes-preview-")]
        assert len(mine) == 1
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        proc.stdout.close()
        proc.stderr.close()
        # terminate() is a hard kill on Windows, so the launch could not clean
        # up after itself (the crash case prune_stale exists for); do it here.
        for name in mine:
            shutil.rmtree(os.path.join(str(tmp), name), ignore_errors=True)


def test_serve_on_a_directory_without_a_project_exits_with_an_error(tmp_path):
    proc = _start(str(tmp_path / "refdes-project.yaml"))
    try:
        out, _err = proc.communicate(timeout=60)
    finally:
        proc.kill()
    assert proc.returncode != 0
    assert "http://" not in out


# --------------------------------------------------------- --port and --token-file
#
# Finding F8 (in-prog-logs/user-sim-release-gate-run2.md): a script driving
# `serve` had two traps -- the port was always ephemeral, and the only way to the
# launch token was scraping the stdout line. These tests drive the real process
# and, for the token file, deliberately read *only* the file: a test that fell
# back to stdout would not catch the feature breaking.


def _wait_for_file(path, timeout: float = 60.0, differs_from: str | None = None) -> str:
    """The token file appears once the listener is up; poll for it, then return
    its text. Never touches stdout -- that is the point of the flag.

    A *complete* line is what it waits for. `serve` writes the file atomically,
    so a reader should never see half a URL, and a helper that accepted a
    partial read would be papering over exactly that bug instead of catching it.

    `differs_from` is for the relaunch-over-a-stale-file case: the path already
    exists holding the dead launch's text, so existing is not yet news.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if text.endswith("\n") and text != differs_from:
                return text
        time.sleep(0.05)
    if differs_from is None:
        raise AssertionError(f"--token-file {path} never held a complete line")
    raise AssertionError(f"--token-file {path} still holds the stale {differs_from!r}")


def test_port_flag_binds_exactly_the_port_asked_for(tmp_path):
    port = free_port()
    proc = _start(make_project(tmp_path), "--port", str(port))
    try:
        url = _launch_url(proc)
        assert f":{port}/" in url, url
        assert int(re.search(r":(\d+)/", url).group(1)) == port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path_of(url), headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 302 and "SameSite=Strict" in resp.getheader("Set-Cookie")
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def test_a_port_that_is_already_held_is_a_one_line_error_not_a_traceback(tmp_path):
    port = free_port()
    first = _start(make_project(tmp_path), "--port", str(port))
    try:
        _launch_url(first)  # the listener holds the port from this line on
        second = _start(make_project(tmp_path), "--port", str(port))
        out, err = second.communicate(timeout=60)
        assert second.returncode == 2
        assert out == "", "a refused launch must not print a URL it is not serving"
        assert err.startswith("error: ")
        assert f"cannot listen on 127.0.0.1:{port}" in err
        assert "--port" in err  # says what to do, not just what went wrong
        assert "Traceback" not in err and "socket.py" not in err
    finally:
        first.terminate()
        first.wait(timeout=30)


def test_a_port_outside_1_to_65535_is_a_usage_error(tmp_path):
    # Python raises OverflowError, not OSError, for a port over 65535, so the
    # range is checked at parse time -- this is the test that it is.
    for bad in ("0", "70000", "not-a-port"):
        proc = _start(make_project(tmp_path), "--port", bad)
        _out, err = proc.communicate(timeout=60)
        assert proc.returncode == 2, f"--port {bad}: {err}"
        assert "not a port" in err
        assert "Traceback" not in err


def test_token_file_holds_a_working_credential(tmp_path):
    token_file = str(tmp_path / "launch-url.txt")
    proc = _start(make_project(tmp_path), "--token-file", token_file)
    try:
        text = _wait_for_file(token_file)
        match = re.fullmatch(r"http://127\.0\.0\.1:(\d+)/\?token=(\S+)", text.strip())
        assert match, f"token file holds {text!r}, not a launch URL"
        port, token = int(match.group(1)), match.group(2)
        # The token is urlsafe base64: `_` and `-` are in its alphabet, which is
        # the exact thing F8 says a hand-rolled [0-9a-zA-Z-]+ scraper truncates.
        assert re.fullmatch(r"[A-Za-z0-9_-]{43,}", token), token
        if os.name != "nt":
            assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600

        def api(with_token: bool) -> int:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Host": f"127.0.0.1:{port}"}
            if with_token:
                headers["X-Refdes-Token"] = token
            conn.request("GET", "/api/revision", headers=headers)
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        assert api(with_token=False) == 403
        assert api(with_token=True) == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)


@pytest.mark.skipif(
    os.name == "nt",
    reason="this is the Ctrl+C path, and Popen.send_signal(SIGINT) raises "
    "'Unsupported signal: 2' on Windows (CI run 36686276948). Nothing in this "
    "harness has a Windows equivalent -- every other test here stops serve with "
    "terminate(), which is a hard kill and is the crash case the next test "
    "covers -- so the clean-stop promise goes unverified on Windows rather than "
    "faked",
)
def test_token_file_is_removed_when_serve_stops(tmp_path):
    token_file = str(tmp_path / "launch-url.txt")
    proc = _start(make_project(tmp_path), "--token-file", token_file)
    try:
        _wait_for_file(token_file)
        proc.send_signal(signal.SIGINT)  # Ctrl+C, the documented stop
        proc.wait(timeout=60)
        assert proc.returncode == 0
        assert not os.path.exists(token_file), "a dead launch's credential outlived it"
    finally:
        # Same shape as the SIGTERM test below: whatever this test does on the
        # way out -- a failed assert, a timeout, an error in the wait -- the
        # launch it started dies with it. Without this the test orphaned a
        # serve per failure, and 16 of them had accumulated on one machine.
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)


@pytest.mark.skipif(
    os.name == "nt",
    reason="there is no catchable SIGTERM to send on Windows: terminate(), "
    "taskkill and os.kill(pid, SIGTERM) all end in TerminateProcess, which no "
    "handler intercepts, so this would assert the hard-kill case (the one below) "
    "rather than the clean stop. Windows gets no SIGTERM path to test",
)
def test_token_file_is_removed_when_serve_stops_on_sigterm(tmp_path):
    """N4 (in-prog-logs/user-sim-release-gate-run3.md): `--token-file` is written
    for scripted use, and the ordinary scripted stop is `kill $pid` -- SIGTERM --
    which used to leave the credential on disk while --help said the file was
    "removed when serve stops cleanly". Ctrl+C already removed it; this is that
    promise for the signal a script actually sends."""
    token_file = str(tmp_path / "launch-url.txt")
    proc = _start(make_project(tmp_path), "--token-file", token_file)
    try:
        _wait_for_file(token_file)
        proc.send_signal(signal.SIGTERM)  # `kill $pid`, the scripted stop
        proc.wait(timeout=60)
        assert proc.returncode == 0, f"a SIGTERM stop was not clean: {proc.returncode}"
        assert not os.path.exists(token_file), (
            "kill $pid left a dead launch's credential on disk"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)


def test_the_sigterm_handler_lives_only_as_long_as_the_launch():
    """Not installed at import -- nothing else in the process inherits it -- and
    handed back on the way out, so a second `serve` in the same process (and any
    library use of this module) sees the disposition it had."""
    before = signal.getsignal(signal.SIGTERM)
    with sigterm_stops_cleanly():
        inside = signal.getsignal(signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) is before, "the handler outlived the launch"
    if sigterm_is_deliverable():
        assert inside is not before, "no handler was installed while serve was running"


def test_a_stale_token_file_from_a_crash_is_rewritten_not_refused(tmp_path):
    port = free_port()
    token_file = str(tmp_path / "launch-url.txt")
    first = _start(make_project(tmp_path), "--port", str(port), "--token-file", token_file)
    stale = _wait_for_file(token_file)
    first.kill()  # no cleanup runs: this is the crash that leaves the file behind
    first.wait(timeout=30)
    assert os.path.exists(token_file)
    second = _start(make_project(tmp_path), "--port", str(port), "--token-file", token_file)
    try:
        fresh = _wait_for_file(token_file, differs_from=stale)
        assert f":{port}/" in fresh
    finally:
        second.terminate()
        second.wait(timeout=30)


def test_token_file_refuses_to_overwrite_a_file_it_did_not_write(tmp_path):
    """A mistyped or tab-completed `--token-file` must cost a refusal, not the
    file: `serve` does not start, and the file is left byte for byte."""
    config = make_project(tmp_path)
    with open(config, encoding="utf-8") as fh:
        original = fh.read()
    proc = _start(config, "--token-file", config)
    _out, err = proc.communicate(timeout=60)
    assert proc.returncode == 2
    assert "already exists and is not a refdes serve launch file" in err
    assert "Traceback" not in err
    with open(config, encoding="utf-8") as fh:
        assert fh.read() == original


@pytest.mark.skipif(os.name == "nt", reason="a symlink at that path is a POSIX case here")
def test_token_file_refuses_to_write_through_a_symlink(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("do not overwrite me\n", encoding="utf-8")
    link = tmp_path / "launch-url.txt"
    os.symlink(str(victim), str(link))
    proc = _start(make_project(tmp_path), "--token-file", str(link))
    _out, err = proc.communicate(timeout=60)
    assert proc.returncode == 2
    assert "symlink" in err
    assert victim.read_text(encoding="utf-8") == "do not overwrite me\n"
    assert os.readlink(str(link)) == str(victim)  # refused, not followed
