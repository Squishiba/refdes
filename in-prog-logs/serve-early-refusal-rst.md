# fix(serve): drain an early-refused request before closing (Windows connection reset)

Slice: windows-socket-flakes-fix, worker. Branch `fix/serve-early-refusal-rst`
off `origin/main` (base `95c2f737`). Red-first, two commits, per the accepted
diagnosis on `origin/fix/windows-socket-flakes-diagnosis`
(`in-prog-logs/winflake-diagnosis.md`).

## Commit 1 (red): tests/test_serve_early_refusal.py

Raw-socket client against a real `EditorApp` (ephemeral port, watcher parked,
socket/thread timeouts, no fixed ports, no text-mode fixtures): sends the
headers of a request the server refuses on the headers alone, then drips the
body (4 KB per ~1 ms) so bytes are in flight when the refusal lands. Four
cases, 20 iterations each: 405 (PUT /api/navis/restore), 415 (POST,
text/plain), 403 (POST, wrong token), 413 (POST declaring 1.5 MiB, header-only
gate). Asserts per iteration: (a) the status line read is the expected
refusal, (b) every body `sendall` succeeded, (c) the read after the full
response returns b"" (FIN, not RST).

Red against the unfixed server (`git checkout` of the two touched files,
test file final, 0.65 s): 4 failed — (a) passes on Linux (Linux delivers
bytes received before an RST), (b) fails **20/20 sends died (RST mid-write)**
in every case, matching the diagnosis's 200/200.

## Commit 2 (green): _Server.shutdown_request + Client timeout

`src/refdes/serve/server.py`: `_Server.shutdown_request` override —
`shutdown(SHUT_WR)` (response already flushed by `finish()`), then
read-and-discard at most `LINGER_BYTES` (2 * MAX_BODY_BYTES = 2 MiB) for at
most `LINGER_SECONDS` (0.25 s) with a socket timeout, swallowing `OSError`,
then the normal `close_request`. One place, after the flush, so it covers
405/403/411/413/415 and future refusals. Not drained in `_deny` (rejected in
the diagnosis: cannot cover the 413, declared over cap). The 413 header-only
size gate is untouched — the drain is bounded, so a client still cannot make
a refused request buffer an oversized body.

`tests/serve_support.py`: `Client.request` timeout 10 → 30 (diagnosis case 2:
a synchronous rebuild+render on a loaded Windows runner beats 10 s on a ~0.5 s
request here). The REAL fix for case 2 — not rendering the whole site inside
the request — is out of scope for this slice and stays its own slice. Case 3
(node timeout) untouched, per task.

Green: new file 4 passed in ~5.1 s (well under the 10 s budget);
`test_serve_navis_write.py` + `test_serve_security.py` +
`test_editor_empty_link_target_types.py` + `test_serve_api.py` +
`test_serve_edit_http.py` + new file = 208 passed, 16 s.

Latency (`GET /api/revision`, 200 reqs after warmup, fixture project, same
box, patched vs unpatched imported from two trees): median 0.460 ms vs
0.460 ms, p95 0.549 ms vs 0.549 ms — no regression (the diagnosis's 0.3/0.4
ms box reads lower in absolute terms; the relative result is what matters).

`pr_size.py` scope: 51 added lines under `src/` (server.py only) — under the
350 gate. `ruff check` on the touched files: only the pre-existing UP012 at
the untouched `write_launch_file` line.

## Not verified here (report it plainly)

The Windows behaviour itself — that an RST discards the buffered response on
Winsock and 10053/10054 replace the 4xx — cannot be reproduced on this Linux
box (the diagnosis documents the same: all its Linux clients got their 405
even in the RST rows). Evidence is the CI traceback location, the two prior
repo records, and this mechanism test; final word is CI on windows-latest,
and a single green run proves little for a ~1-in-6000 flake.
