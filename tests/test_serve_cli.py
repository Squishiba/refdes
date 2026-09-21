"""`refdes serve` as a real process: prints a launch URL on 127.0.0.1, serves
through it, and exits cleanly with its temp preview removed."""

from __future__ import annotations

import http.client
import os
import re
import shutil
import subprocess
import sys
import threading

from serve_support import make_project, path_of

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def _start(config, *extra, tmpdir=None):
    env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC), PYTHONIOENCODING="utf-8")
    if tmpdir is not None:
        # Isolate the child's preview temp dir so a concurrent run in the same
        # shared system temp dir cannot change what this launch created.
        env.update(TMP=str(tmpdir), TEMP=str(tmpdir), TMPDIR=str(tmpdir))
    return subprocess.Popen(
        [sys.executable, "-m", "refdes.cli", "-c", config, "serve", "--no-open", *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
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
