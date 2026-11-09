# fix(serve): send a response as one write with TCP_NODELAY

Windows CI flake, second round. Branch `fix/serve-single-send` off current
main (`86c0d043`, merge of origin/main was a no-op fast-forward). Diagnosis
first, then a small product fix, then the test-robustness fix. No fixed
ports, no text fixtures, no POSIX-only tools in the new tests.

## The CI failure (evidence read)

`gh run view --job=129122260662 --log-failed --attempt=1` (run 42606063274,
windows-latest, attempt 1 — attempt 2 of that run was canceled by a
higher-priority queue): `FAILED tests/test_serve_early_refusal.py::
test_the_413_size_refusal_lets_the_dripped_body_drain - ConnectionAbortedError:
[WinError 10053]`, raised at `tests\test_serve_early_refusal.py:122`, which is
`piece = sock.recv(65536)` inside the body-read loop (`while len(body) <
length:`). The client HAD the status line and headers (the head loop,
L96-105, is the only loop with a `(ConnectionResetError,
ConnectionAbortedError)` handler) and the body read aborted. The head loop
runs before `writer.join(...)` (L106); the body read runs after it — on a
loaded runner the join (a 1.5 MiB drip) can outlast the server's 0.25 s
linger, and the close lands before the test asks for the body.

## What the code shows (hypothesis CONFIRMED by reading)

`_Handler._send` (src/refdes/serve/server.py, the `_send`/`_deny` block)
built every response as TWO writes: `end_headers()` and `wfile.write(body)`.
In the venv's stdlib (Python 3.13.5, read from the venv):

- `BaseHTTPRequestHandler.send_response/send_header` only buffer into
  `_headers_buffer`; `end_headers()` appends `b"\r\n"` and `flush_headers()`
  writes the joined head in ONE `wfile.write`.
- `socketserver.StreamRequestHandler.setup` runs with `wbufsize = 0`, so
  `self.wfile = _SocketWriter(self.connection)`, and
  `_SocketWriter.write` is a straight `self._sock.sendall(b)`.

So the head leaves as one `sendall` and the body as a second, separate TCP
send — confirmed empirically by the red test below, which records exactly
`[head..., b"method not allowed"]` as two sends.

Socket options on the accepted socket: `setup()` sets TCP_NODELAY only when
`disable_nagle_algorithm` is True; `_Handler` (server.py) never sets it and
sets no setsockopt anywhere (grep for `setsockopt`/`TCP_NODELAY` in
`src/refdes/serve/server.py` finds only the new line). `_Handler.timeout =
30` only sets the socket timeout. Nagle therefore stayed ON on every
accepted socket.

Mechanism of the flake, on Windows: head segment ACKed, body segment small
and unacked → Nagle holds it up to the delayed ACK (~200 ms). The 413 case
drips its declared body longer than LINGER_SECONDS (server.py:52, 0.25 s),
`_Server.shutdown_request` (server.py:387) hits the deadline and
`close_request` closes with body bytes unread → RST, and Winsock discards
the queued body with the abort → the client's body recv raises 10053. The
test's own `writer.join`-before-body-read ordering widened the window.

## The fix (product, server.py)

- `_Handler.setup`: `super().setup()` then
  `self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)`
  under `try/except OSError`.
- `_Handler._send`: append `b"\r\n"` (what `end_headers` appends) and the
  body to `_headers_buffer` and `flush_headers()` — head+body leave as ONE
  `sendall`. The HTTP/0.9 branch keeps the stdlib's raw-body behavior
  (0.9 has no header buffer, so `_headers_buffer` does not exist there).
  `_Server.shutdown_request`'s drain/linger is untouched, per task.

## The fix (test, test_serve_early_refusal.py)

Body read moved BEFORE `writer.join` (the reply is sent complete now;
reading it as it arrives is the whole point of assertion (a)), and the
body loop is wrapped in the same `(ConnectionResetError,
ConnectionAbortedError)` handler as the head loop — a late abort returns
`close="rst"` with the status the client did read, so the failure is
assertion (c)'s closes-list message, not an uncaught traceback. Nothing
weakened: a dripped body must still get status+full body+FIN, 20
iterations per refusal.

## Red first (tests/test_serve_single_send.py, new)

Drives the real `_Handler` with a recording fake socket (no real port, no
threads — deterministic on both CI platforms). RED on the unfixed server:

    writes: [b"HTTP/1.0 405 ...\r\n\r\n", b"method not allowed"]  -> 2 != 1
    setsockopt calls: []  -> (6, 1, 1) not in []

GREEN after the product change: 2 passed in 0.13 s. The early-refusal suite
(4 tests) passes on Linux before and after — on Linux the RST never ate the
response, which is why the flake was Windows-only.

## Runs

- tests/test_serve_early_refusal.py + tests/test_serve_single_send.py: 6 passed.
- tests/test_serve*.py tests/test_editor*.py tests/test_crossplatform_lint.py
  (-n 4 --dist worksteal): 1434 passed, 1 skipped.
- ruff check on the two touched py files: see below (only pre-existing).
- Full suite once before push: 6421 passed, 2 skipped in 109 s
  (`-n 4 --dist worksteal`, the venv `venv-refdes`, absolute PYTHONPATH).

## Not verified (say it plainly, it is in the PR body too)

The Windows effect itself cannot be reproduced on Linux (the prior diagnosis
in-prog-logs/winflake-diagnosis.md documents the same: all Linux clients
got their 405 even on RST rows; Winsock discards, Linux delivers). The
single-write + NODELAY change removes the queued-second-segment window the
CI traceback names, and the test fix removes the join-before-read window,
but a flake at ~1-in-thousands is only shown over CI time. No claim that
the flake is fixed; the word is windows-latest, over runs.
