"""One response leaves as one write, and the accepted socket has TCP_NODELAY.

The windows-latest flake (run 42606063274): `tests/test_serve_early_refusal.py`
read the response head fine, then its body recv aborted (WinError 10053).
`_Handler._send` writes the head in `end_headers()`'s flush and the body in a
second `wfile.write` -- two `sendall`s: the stdlib buffers the status line and
headers into `_headers_buffer` and `flush_headers` writes it once
(http.server.BaseHTTPRequestHandler), and with `wbufsize = 0` each write is
one straight socket send (socketserver.StreamRequestHandler.setup, whose
`_SocketWriter.write` calls `sendall`). Nagle is on: `setup()` sets
TCP_NODELAY only when `disable_nagle_algorithm` is True, and `_Handler`
never sets it. On Windows the small second segment can then sit behind the
client's delayed ACK (~200 ms), outlasting the 0.25 s linger in
`_Server.shutdown_request`; the close becomes an RST, and Winsock discards
the queued body with the abort.

These tests pin the two product changes with a recording fake socket driven
through the real `_Handler` (segment boundaries are not observable from a
real client's `recv`, so they are pinned at the `sendall` call itself):
a refused response leaves as ONE write carrying head and body together, and
`setup` sets TCP_NODELAY on the accepted socket. No real port, no threads:
deterministic on both CI platforms.
"""

from __future__ import annotations

import io
import socket

from refdes.serve.server import _Handler

PUT_RESTORE = (
    "PUT /api/navis/restore HTTP/1.1\r\n"
    "Host: 127.0.0.1:8765\r\n"
    "Content-Length: 10\r\n"
    "\r\n"
    "0123456789"
)


class _RawReader(io.RawIOBase):
    def __init__(self, source: io.BytesIO) -> None:
        self._source = source

    def readable(self) -> bool:
        return True

    def readinto(self, buf) -> int:
        return self._source.readinto(buf)


class _FakeSocket:
    """The accepted connection as the handler sees it: records every
    `sendall` and `setsockopt`, and serves the request bytes on rfile."""

    def __init__(self, request: bytes) -> None:
        self._request = io.BytesIO(request)
        self.sends: list[bytes] = []
        self.options: list[tuple] = []

    def makefile(self, mode: str, buffering: int = -1):
        assert mode == "rb"
        return io.BufferedReader(_RawReader(self._request))

    def sendall(self, data) -> None:
        self.sends.append(bytes(data))

    def settimeout(self, timeout) -> None:
        pass

    def setsockopt(self, level: int, option: int, value) -> None:
        self.options.append((level, option, value))


class _FakeServer:
    app = None


def _refuse(request: str) -> _FakeSocket:
    """Run the real handler over the recording socket for one refused
    request (PUT is answered on the method line, body never read), and
    return the socket with its recordings."""
    sock = _FakeSocket(request.encode("ascii"))
    _Handler(sock, ("127.0.0.1", 12345), _FakeServer())
    return sock


def test_a_refusal_response_leaves_as_one_write_of_head_and_body():
    sock = _refuse(PUT_RESTORE)
    assert len(sock.sends) == 1, f"writes: {sock.sends!r}"
    head, _, body = sock.sends[0].partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 405")
    assert b"Content-Length: 18" in head
    assert body == b"method not allowed"


def test_the_accepted_socket_gets_tcp_nodelay():
    sock = _refuse(PUT_RESTORE)
    options = [(level, option, int(value)) for level, option, value in sock.options]
    assert (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) in options, (
        f"setsockopt calls: {options!r}"
    )
