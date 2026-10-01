"""A fetched citation over `FETCH_SIZE_WARN_BYTES` gets a warning, not a cap.

Finding F3 of `in-prog-logs/remote-fetch-exercise.md`: `fetch_bytes` was one
`urlopen` and one `resp.read()` with no `Content-Length` inspection and no
bound of any kind, so a 26 MiB octet-stream was pinned in 0.49 s and reported
like any other pin. The report's fix shape proposed a cap and a streamed
abort; the maintainer's decision was the opposite of a cap -- a datasheet is
allowed to be enormous -- so what landed is the one warning, and these tests
hold the three properties that make it honest:

1. it fires, and it names the citation, the size and where the copy went;
2. it does *not* change the outcome -- the pin lands and the exit code is the
   one a small fetch would have produced, which is the whole difference
    between a warning and a cap;
3. it is measured on the bytes actually received, never on a `Content-Length`
   header -- so it still fires for the chunked transfer a large datasheet
   usually is, and `test_a_chunked_response_with_no_content_length_still_warns`
   holds that half against a real socket rather than a story about one;
4. it stays off the local-citation path, where nothing was downloaded.


The threshold is patched down in the tests that need a big file -- 100 MB of
bytes per test run is not a price worth paying for a warning -- and
`test_the_threshold_is_100_mb` is what keeps the patched number honest about
the real one.
"""

from __future__ import annotations

import hashlib
import socket
import threading

import pytest
from conftest import write_project_config

from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes.schema import load_project

SCHEMA = """\
site: {title: "Size Warning", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
types:
  component:
    prefix: CMP
    fields:
      title:      { type: text, required: true }
      datasheets: { type: citations }
"""

REMOTE = "https://example.com/big.pdf"
BODY = b"%PDF-1.4 " + b"x" * 24


def _project(tmp_path, item_extra: str = "", path: str = REMOTE):
    write_project_config(tmp_path, SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(
        "defaults:\n  type: component\nitems:\n"
        f"  - id: CMP-001\n    title: Regulator\n    datasheets:\n"
        f"      - path: {path}{item_extra}\n",
        encoding="utf-8",
    )
    return str(tmp_path / "refdes-project.yaml")


@pytest.fixture
def net(monkeypatch):
    """The network, replaced by a body of a known size. `fetch_bytes` is
    monkeypatched rather than passed as `fetcher` so this goes through
    `refdes fetch` itself, which is where the warning has to appear."""
    def _serve(body: bytes):
        monkeypatch.setattr(
            citations_mod, "fetch_bytes", lambda url, timeout=30.0: body
        )
    return _serve


def _threshold(monkeypatch, size: int) -> None:
    monkeypatch.setattr(citations_mod, "FETCH_SIZE_WARN_BYTES", size)


def _lockfile(config: str) -> dict:
    return citations_mod.load_lockfile(load_project(config_path=config))


def _no_root(text: str, root, what: str) -> None:
    assert str(root) not in text, (what, text)


# ------------------------------------------------------------- the threshold


def test_the_threshold_is_100_mb():
    """The number the docs quote. Everything below patches this one, so it is
    pinned here rather than left to the doc and the code agreeing by accident."""
    assert citations_mod.FETCH_SIZE_WARN_BYTES == 100 << 20


def test_the_message_quotes_the_size_in_the_unit_the_threshold_is_in():
    """Exercised at real magnitudes through the helper, because every
    end-to-end test below patches the threshold down to bytes and would
    otherwise only ever see "0.0 MB" in the sentence."""
    message = citations_mod.large_fetch_message(
        "https://example.com/ds.pdf", 268435457, None
    )
    assert "268435457 bytes (256.0 MB)" in message, message
    assert "over the 100.0 MB a fetch is warned at" in message, message
    assert message.startswith("https://example.com/ds.pdf: "), message


# ------------------------------------------------------------------- it fires


def test_a_fetch_over_the_threshold_warns_and_names_the_citation(
    tmp_path, monkeypatch, capsys, net
):
    _threshold(monkeypatch, 8)
    net(BODY)
    config = _project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    err = capsys.readouterr().err
    assert f"{REMOTE}: fetched {len(BODY)} bytes" in err, err
    _no_root(err, tmp_path, "size warning")


def test_the_warning_says_where_the_copy_went_and_there_is_none(
    tmp_path, monkeypatch, capsys, net
):
    """The hash-only half: no `keep_copy:`, so no second copy on disk, and a
    message claiming otherwise would send an author looking for a file that
    was never written."""
    _threshold(monkeypatch, 8)
    net(BODY)
    config = _project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    err = capsys.readouterr().err
    assert "pinned anyway, no local copy kept (hash-only)" in err, err
    assert not (tmp_path / ".refdes" / "copies").exists()


def test_the_warning_names_the_kept_copy_when_one_was_kept(
    tmp_path, monkeypatch, capsys, net
):
    """The other half, and the reason the warning is built after the kept copy
    is written rather than at the read: the path is not knowable before then,
    and it is half of what makes the line actionable."""
    _threshold(monkeypatch, 8)
    net(BODY)
    config = _project(tmp_path, item_extra="\n        keep_copy: true")
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    err = capsys.readouterr().err
    digest = hashlib.sha256(BODY).hexdigest()
    assert f"pinned anyway, kept at .refdes/copies/{digest}.pdf" in err, err
    # and it is the file that is really there, not a spelling of it
    assert (tmp_path / ".refdes" / "copies" / f"{digest}.pdf").is_file()
    _no_root(err, tmp_path, "size warning naming the kept copy")


# ---------------------------------------------------------- a warning only


def test_the_pin_lands_and_the_exit_code_is_unchanged(
    tmp_path, monkeypatch, capsys, net
):
    """The difference between a warning and a cap, asserted on both halves: the
    lockfile carries the sha256 and the byte count, and `fetch` exits 0. A cap
    would have failed one of these and the maintainer ruled it out precisely
    because a datasheet is allowed to be big."""
    _threshold(monkeypatch, 8)
    net(BODY)
    config = _project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    out = capsys.readouterr().out
    assert "1 citation(s) processed, 0 failed" in out, out
    record = _lockfile(config)[REMOTE]
    assert record["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert record["bytes"] == len(BODY)
    assert record["kept_copy"] is False


def test_a_fetch_under_the_threshold_says_nothing(tmp_path, monkeypatch, capsys, net):
    """The absence half, and it is deliberately anchored to the firing half
    rather than standing alone: silence proves nothing about a warning unless
    the same project, the same fake network and the same threshold are shown to
    speak one byte later. Both runs are here so the pair cannot be broken by
    someone lowering the threshold far enough to make everything quiet.
    """
    _threshold(monkeypatch, len(BODY))
    net(BODY)
    config = _project(tmp_path)
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    quiet = capsys.readouterr()
    assert "bytes (" not in quiet.err, quiet.err
    assert "WARNING" not in quiet.err, quiet.err

    # One byte of a bigger body, `--update` so the pin is re-fetched rather
    # than skipped, and the same line appears.
    net(BODY + b"x")
    assert cli_mod.main(["-c", config, "fetch", "--update"]) == 0
    assert f"fetched {len(BODY) + 1} bytes" in capsys.readouterr().err


def test_a_local_citation_is_not_warned_about(
    tmp_path, monkeypatch, capsys, net
):
    """The size is measured on a download, so a local citation is out of scope
    however big it is: the bytes were already on the author's own disk, and
    pinning one neither downloads nor duplicates anything. Asserted because
    that is a decision, not an accident -- a future reader has no other way to
    tell it from an oversight."""
    _threshold(monkeypatch, 8)
    net(b"")  # a local citation must not reach the network at all
    (tmp_path / "datasheets").mkdir()
    body = b"%PDF-1.4 " + b"y" * 24
    (tmp_path / "datasheets" / "big.pdf").write_bytes(body)
    config = _project(tmp_path, path="datasheets/big.pdf")
    assert cli_mod.main(["-c", config, "fetch"]) == 0
    captured = capsys.readouterr()
    assert "bytes (" not in captured.err, captured.err
    assert _lockfile(config)["datasheets/big.pdf"]["bytes"] == len(body)


# ------------------------------------------------- over a real socket, no header


def _chunked_origin(body: bytes):
    """A loopback origin that answers with `Transfer-Encoding: chunked` and no
    `Content-Length` at all, and stops when closed.

    Hand-rolled rather than `http.server`, which always sets the header. Bound
    to port 0 and handed back, so there is no free-port race to lose.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    # A timeout on the listening socket, not just a close in the finally: a
    # thread blocked in `accept()` is not reliably woken by another thread
    # closing the socket, so without this the join below costs its full timeout
    # on every run.
    sock.settimeout(0.2)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except TimeoutError:  # the listening socket's own timeout
                continue
            except OSError:
                return  # the socket was closed by the test
            with conn:
                try:
                    conn.settimeout(5)
                    conn.recv(4096)  # the request line; the path is fixed
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                        + b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n"
                    )
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return sock, thread, stop, port


def test_a_chunked_response_with_no_content_length_still_warns(
    tmp_path, monkeypatch, capsys
):
    """The half of the "received bytes, not the header" decision that has to be
    measured rather than argued. A chunked response carries no `Content-Length`,
    and a server picks that framing freely -- so a warning keyed on the header
    would be silent for exactly the streaming transfer a large datasheet tends
    to be, and the 100 MB it was supposed to announce would pass unnoticed.

    No `net` fixture here: this one goes through the real `fetch_bytes`, over a
    real socket, because the thing under test is what urllib hands back when
    there is no header to read.
    """
    sock, thread, stop, port = _chunked_origin(BODY)
    try:
        _threshold(monkeypatch, 8)
        config = _project(tmp_path, path=f"http://127.0.0.1:{port}/big.pdf")
        assert cli_mod.main(["-c", config, "fetch"]) == 0
        err = capsys.readouterr().err
        assert f"fetched {len(BODY)} bytes" in err, err
        record = _lockfile(config)[f"http://127.0.0.1:{port}/big.pdf"]
        assert record["bytes"] == len(BODY)
    finally:
        stop.set()
        sock.close()
        thread.join(timeout=5)
