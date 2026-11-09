"""An early refusal must let the request body drain before the socket closes.

The recurring windows-latest flake (WinError 10053/10054 inside
`getresponse()`; diagnosis in `in-prog-logs/winflake-diagnosis.md`): every
refusal in `_Handler` is decided on the request line and headers -- the 405
for PUT/DELETE/PATCH, the 403 host/origin/token, 411, 413, 415 -- and the
body is never read. The response is HTTP/1.0 close-after-response, and the
stdlib closes the socket with the client's body bytes still unread: a socket
closed with unread data sends RST, not FIN, and a Windows client discards
the response bytes it had already buffered on the abort, so the 4xx the
client asked for is replaced by a connection error.

The mechanism, asserted on Linux where it is deterministic: a raw-socket
client sends the headers of a request the server will refuse, then *drips*
the body (4 KB per ~1 ms) so bytes are still in flight when the refusal
lands. It asserts, per iteration:

(a) the status line it reads is the expected refusal --
(b) every `sendall` of the body succeeded (today the RST kills the write:
    200/200 BrokenPipeError on the diagnosis box), and
(c) the next read after the response returns b"" -- a clean FIN, not a reset.

On Windows the unfixed server loses (a) as well (the buffered response is
discarded with the abort) -- that is the CI flake; these assertions stay
red there for the same mechanism. Nothing here is POSIX-only, so no skipif:
all three sockets APIs behave the same on both platforms.

The client is deliberately not `serve_support.Client`: that client writes
the body in one eager `conn.request` and tolerates the write-side abort
(the recorded workaround); this test is the client-side half of the
mechanism, so it drives the socket by hand.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from serve_support import make_project

from refdes.serve.server import MAX_BODY_BYTES, EditorApp

ITERATIONS = 20
BODY_BYTES = 262144  # 256 KiB: dripped over ~64 ms, in flight when refused
CHUNK = 4096
DRIP_SECONDS = 0.001  # ~1 ms per 4 KB chunk
JOIN_TIMEOUT = 10.0
SOCKET_TIMEOUT = 10.0

ARCHIVE = "/api/navis/archive"
RESTORE = "/api/navis/restore"


@pytest.fixture
def served(tmp_path):
    """A real `EditorApp` on the OS's ephemeral port (port 0, the default),
    with the watcher parked: nothing here mutates the project."""
    app = EditorApp(make_project(tmp_path), poll_interval=60)
    app.start()
    try:
        yield app
    finally:
        app.stop()


def _one_refusal(app, method, path, headers, body_len, chunk):
    """One refused request with a dripped body. Returns
    (status, send_errors, close) -- status is the status line's code or None
    (the response never made it to the client), close is "fin" (clean EOF),
    "rst" (connection reset/aborted), "open" (socket still live), "timeout"
    (no answer in time), or "error:<Name>"."""
    sock = socket.create_connection(("127.0.0.1", app.port), timeout=SOCKET_TIMEOUT)
    try:
        lines = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{app.port}"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        lines.append(f"Content-Length: {body_len}")
        sock.sendall("\r\n".join(lines).encode("ascii") + b"\r\n\r\n")

        send_errors: list[Exception] = []

        def drip() -> None:
            try:
                for offset in range(0, body_len, chunk):
                    sock.sendall(b"x" * min(chunk, body_len - offset))
                    time.sleep(DRIP_SECONDS)
            except OSError as exc:  # BrokenPipeError / ConnectionResetError
                send_errors.append(exc)

        writer = threading.Thread(target=drip, daemon=True)
        writer.start()

        head = b""
        status = None
        try:
            while b"\r\n\r\n" not in head:
                piece = sock.recv(65536)
                if not piece:
                    break
                head += piece
        except (ConnectionResetError, ConnectionAbortedError):
            return None, send_errors, "rst"
        except OSError as exc:  # a timed-out read leaves the head unread
            return None, send_errors, "timeout" if isinstance(exc, TimeoutError) else f"error:{type(exc).__name__}"
        if head:
            head_text, _, rest = head.partition(b"\r\n\r\n")
            status = int(head_text.split(b"\r\n", 1)[0].split(b" ")[1])
            # Read the response body too -- and read it NOW, before joining
            # the writer: the reply left the server complete (head and body
            # in one send), and on a loaded runner a `writer.join` that runs
            # first can push this read past the server's linger window, so
            # the abort a late close produces lands here, in a test that is
            # reading a reply that was already sent in full.
            length = 0
            for line in head_text.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value.strip())
            body = rest
            try:
                while len(body) < length:
                    piece = sock.recv(65536)
                    if not piece:
                        break
                    body += piece
            except (ConnectionResetError, ConnectionAbortedError):
                # Same handling as the head loop above: a late abort is a
                # data point ("rst") for the assertions, not a traceback --
                # assertion (c) reports the closes list, naming this entry,
                # and the status the client did read is kept.
                return status, send_errors, "rst"
        writer.join(timeout=JOIN_TIMEOUT)
        if writer.is_alive():
            return None, send_errors, "error:writer-stuck"
        try:
            close = "fin" if sock.recv(1) == b"" else "open"
        except (ConnectionResetError, ConnectionAbortedError):
            close = "rst"
        except OSError as exc:
            close = "timeout" if isinstance(exc, TimeoutError) else f"error:{type(exc).__name__}"
        return status, send_errors, close
    finally:
        sock.close()


def _assert_drains(app, method, path, headers, body_len, expected, chunk=CHUNK):
    statuses, closes = [], []
    send_failures = 0
    for _ in range(ITERATIONS):
        status, send_errors, close = _one_refusal(app, method, path, headers, body_len, chunk)
        statuses.append(status)
        closes.append(close)
        send_failures += bool(send_errors)
    # (a) the refusal the client asked for, every time
    assert statuses == [expected] * ITERATIONS, f"statuses: {statuses}"
    # (b) the body drains: no sendall of it dies to the server's close
    assert send_failures == 0, f"{send_failures}/{ITERATIONS} sends died (RST mid-write)"
    # (c) clean FIN after the response, not a reset
    assert closes.count("fin") == ITERATIONS, f"closes: {closes}"


def test_the_405_refusal_lets_the_dripped_body_drain(served):
    """PUT /api/navis/restore: refused on the method, body never read."""
    _assert_drains(
        served,
        "PUT",
        RESTORE,
        {"X-Refdes-Token": served.token, "Content-Type": "application/json"},
        BODY_BYTES,
        405,
    )


def test_the_415_refusal_lets_the_dripped_body_drain(served):
    """POST with an unaccepted content type: refused before the body read."""
    _assert_drains(
        served,
        "POST",
        ARCHIVE,
        {
            "X-Refdes-Token": served.token,
            "Origin": f"http://127.0.0.1:{served.port}",
            "Content-Type": "text/plain",
        },
        BODY_BYTES,
        415,
    )


def test_the_403_token_refusal_lets_the_dripped_body_drain(served):
    """POST with the wrong launch token: refused before the body read."""
    _assert_drains(
        served,
        "POST",
        ARCHIVE,
        {
            "X-Refdes-Token": "not-the-launch-token",
            "Origin": f"http://127.0.0.1:{served.port}",
            "Content-Type": "application/json",
        },
        BODY_BYTES,
        403,
    )


def test_the_413_size_refusal_lets_the_dripped_body_drain(served):
    """POST declaring more than the JSON cap: the size gate is header-only
    and the declared body is never read -- so it, too, is in flight when the
    refusal lands. (1.5x the cap: over MAX_BODY_BYTES, under the drain's
    bound, so the whole declared body must arrive.)"""
    _assert_drains(
        served,
        "POST",
        ARCHIVE,
        {
            "X-Refdes-Token": served.token,
            "Origin": f"http://127.0.0.1:{served.port}",
            "Content-Type": "application/json",
        },
        MAX_BODY_BYTES + BODY_BYTES // 2,
        413,
        chunk=65536,  # the 1.5 MiB body drips in 24 pieces, not 384
    )
