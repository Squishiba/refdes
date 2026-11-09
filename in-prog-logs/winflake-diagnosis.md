# Windows serve flake — diagnosis (no fix applied)

Task: root-cause the recurring windows-latest flake in the serve tests; diagnosis
only. Added: this log and `.scratch/winflake/{repro,fix_probe,case2_timing,
probe_raw}.py`. No `src/` or `tests/` change, no PR.

## Evidence read

- `gh run view 42558316788 --attempt 1 --log-failed` (windows-latest,
  `feat/n62b1-navis-actions`): `FAILED tests/test_serve_navis_write.py::
  test_the_write_routes_reject_other_methods[PUT-/api/navis/restore] -
  ConnectionAbortedError: [WinError 10053]`, raised at `http/client.py:286
  _read_status` → `socket.py:706 recv_into` — **inside reading the status
  line** — from `serve_support.py:345 conn.getresponse()` after
  `client.request("PUT", path, token=True, body=b"{}")`
  (tests/test_serve_navis_write.py:612). 1 failed, 6109 passed.
- Same shape in the repo twice already:
  `in-prog-logs/release-readiness-audit.md:477-487` (WinError 10053 on
  `test_serve_edit_http.py::test_edit_requires_a_matching_origin`, a POST with
  a body refused 403 **before** the body read, recorded as "a flake, not a
  regression") and `add-github-actions-test-workflow.txt:64-73` (the 413 route,
  mechanism spelled out: "the server answers and closes while the client is
  still writing, and a socket closed with unread data sends RST rather than FIN
  ... the RST can discard the 413 as well, which no amount of client-side retry
  logic recovers"). Worked around in the tests (`serve_support.py:355-369`,
  `test_serve_edit_http.py:184-187`), not in the server.

## Root cause (high confidence for case 1)

`_Handler` (`src/refdes/serve/server.py:691-694`) sets no `protocol_version`;
measured on the wire it answers `HTTP/1.0 405 ...` with no `Connection:` header,
so the connection closes after every response. Every refusal is decided on the
request line/headers and never reads the body: `do_PUT/do_DELETE/do_PATCH →
_deny(405)` (755-758), 403 host (762-763), 403 origin (768-769), 403 token
(889-890), 403 origin for POST (893-894), 415 (904, 908), 411 (913), 413
(914-915); the only body read is `self.rfile.read(length)` at 916, after all of
them. `_Server` (361-373) has no `shutdown_request` override, so the stdlib runs
`finish()` (flush) then `shutdown(SHUT_WR)` + `close()` (local stdlib,
socketserver.py:513-521). Closing with the client's body bytes unread sends RST
instead of FIN; on Windows the abort also discards what the client already
buffered, so `getresponse()` raises 10053/10054 instead of returning the 405.
The client is not at fault: `Client.request` (tests/serve_support.py:309-353)
opens a fresh `HTTPConnection` per call (320), writes the body eagerly (341),
closes it (353) — no keep-alive reuse, no late body write — and it swallows a
*send*-side abort (342-348) while re-raising the *read*-side one (349), which is
the CI traceback. Server at fault; the test client only exposes it.

## Linux repro (`.scratch/winflake/repro.py`, real `EditorApp`, raw sockets)

200 iterations per row; `close=` is what the client's next `recv` sees
(`fin` = FIN/clean EOF, `rst` = ConnectionResetError):

    PUT restore 2B / 64KB / 64KB under 8-way concurrency   200 each: resp=405 | close=fin
    POST /api/navis/archive 64KB   200  resp=400 | close=fin   (body read first: not an early refusal)
    PUT restore 64KB dripped 4KB/ms 200  resp=send-BrokenPipeError | close=extra:1
    synthetic 405 fast-close, no drain  141 resp=405|close=fin   59 resp=405|close=rst
    synthetic 405 fast-close, drain     200 resp=405|close=fin

What this proves (Linux): (a) closing mid-write is real — the drip client's
`sendall` dies 200/200 while the response sits in its buffer; (b) the RST is
produced by closing while body bytes are in flight, and draining first removes
it (59/200 → 0/200); (c) **the client-side loss cannot be reproduced on this
box**: all 200 Linux clients got their 405 in every row, including all 59 RST
rows, because Linux delivers bytes received before an RST and Windows discards
them. That last step is documented Winsock behaviour, verified here only by the
CI traceback location (the raise is *inside* `_read_status`) and the two repo
records above.

## Proposed patch (not applied)

`src/refdes/serve/server.py`, class `_Server` (361-373): add a lingering close,
~20 added lines, 0 removed (well inside the 350-line gate):

    add imports: `socket`, `time`
    add consts near MAX_BODY_BYTES (45): LINGER_SECONDS = 0.25, LINGER_BYTES = 2 * MAX_BODY_BYTES
    def shutdown_request(self, request):
        try: request.shutdown(socket.SHUT_WR)   # FIN; finish() flushed the response
        except OSError: pass
        deadline, drained = time.monotonic() + LINGER_SECONDS, 0
        try:                                    # bounded drain: never buffer, never linger
            while drained < LINGER_BYTES:
                if time.monotonic() >= deadline: break
                request.settimeout(deadline - time.monotonic())
                chunk = request.recv(65536)
                if not chunk: break
                drained += len(chunk)
        except OSError: pass
        self.close_request(request)

`shutdown_request` runs after `finish()` flushed the response and covers every
route at once (405/403/411/415/413 and future ones). The bounds preserve the
documented gate at 914-915: at most 2 MiB read-and-discarded for at most 0.25 s
per connection, so a client still cannot make `refdes serve` buffer an oversized
request. Rejected alternative: draining in `_deny` (729) — it cannot cover 413
(declared over cap), so the RST family survives there. Measured with the patch
as an in-process monkeypatch (`.scratch/winflake/fix_probe.py`, 200 iters/row):
drip case 200/200 `send-BrokenPipeError` → 200/200 `405 | fin`; PUT 2B/64KB stay
`405 | fin`; `GET /api/revision` 0.3 ms/req vs 0.4 unpatched — no cost on
normal traffic.

Test that is red on Linux today, green after: a raw-socket client (bytes via
`.encode("ascii")`, no text fixtures, no path asserts) sends
`PUT /api/navis/restore HTTP/1.1` + `X-Refdes-Token` + `Content-Length: 262144`,
then drips the body in 4 KB pieces with `time.sleep(0.001)`; it asserts the
status line is 405, that **every `sendall` succeeds** (today: BrokenPipeError,
200/200 measured), and that `sock.recv(1) == b""` — a FIN, not an RST. That
asserts the mechanism, not just a status code, and is deterministic on Linux;
the Windows symptom disappears as a consequence.

## Case (2) — the editor empty-link POST timeout: different cause

`test_the_server_applies_an_add_of_any_type_under_an_empty_list`
(tests/test_editor_empty_link_target_types.py:143) is a normal `api_post` →
`POST /api/item/LOG-001/edit`. The 200 path reads the whole body (server.py:916)
and closes clean — every read-the-body row in my repro shows `close=fin` — so
the RST shape does not apply. The timeout is the client's fixed 10 s
(`serve_support.py:320`) against a handler that rebuilds synchronously inside
the request: `_apply_edit` → `app.state.refresh()` (api.py:1184) → `_build()` +
`preview.render(project)` (state.py:225-226, 235), on a 601-item fixture.
Measured here (`.scratch/winflake/case2_timing.py`): fixture load+render 0.51 s,
POST (write+rebuild+render) 0.51 s — so the flake needs ~20x, which 4-way xdist
plus Defender scanning ~601 rewritten preview files on a shared Windows runner
can plausibly cost (the load class of #167's node timeouts). Ruled out: an
un-timeouted blocking recv (the 10 s covers connect+read), a thread-start race
(the listener binds and listens in `EditorApp.__init__`, server.py:567, before
`start()`), port reuse (tests use port=0). Fix: `timeout=10 → 30` at
serve_support.py:320 (one line); the real fix is to stop rendering the whole
site inside the request (separate slice).

## Case (3) — the node timeout, one paragraph

`test_id_completion_range_covers_the_whole_typed_id`
(tests/test_vscode_extension.py:337) spawns `node -e <extracted JS>` with
`timeout=NODE_TIMEOUT_S` (120 s, already raised by #167) and
`capture_output=True`, so it is `communicate()`-based and cannot pipe-deadlock.
A few KB of `-e` script needing >120 s on Windows is not compute but spawn
pathology (AV scanning `node.exe`, cold page-in) on a loaded runner — the same
load class as (2), unrelated to sockets; raising the cap again is the wrong
lever, and a `skipif os.name == "nt"` on the node-execute tests trades one leg's
coverage for a flake that has eaten two timeout increases. Latent bug nearby: the
node call at 439 has `text=True` with `timeout=10` and no `encoding="utf-8"`.

## Not verified

The Windows-side discard (WSA drops buffered data on abort) — no Windows runner;
supported only by the traceback location and the two prior repo records. Why
~1 in 6109 requests (loopback timing, Defender, runner load), and which recv
timed out in case (2) — no Windows trace. The patch ran only as an in-process
monkeypatch; nothing under `src/` or `tests/` was changed.
