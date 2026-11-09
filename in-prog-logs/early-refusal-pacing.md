# test(serve): pace the early-refusal drip so Windows timer granularity cannot outlast the linger

Windows CI flake, third symptom. Branch `fix/early-refusal-pacing` off
current main (`19399122`; merge of origin/main was a no-op fast-forward,
clean tree). Test-only: no `src/` change, so no changelog.d fragment.

## The numbers (measured + computed)

Server bound (read from `src/refdes/serve/server.py`): `LINGER_SECONDS =
0.25`, `LINGER_BYTES = 2 * MAX_BODY_BYTES = 2 MiB`, `MAX_BODY_BYTES =
1 MiB`. `shutdown_request` drains a refused request's body for at most
that window, then closes; a writer still dripping at that point is
legitimately RST on its next send.

Measured Linux drip wall time per iteration, pre-change
(`pytest --durations` on the original file): 256 KiB cases
(405/415/403): 1.38 s / 20 iters = ~69 ms (64 chunks x ~1 ms);
413 (1.5 MiB, chunk 65536): 0.41 s / 20 = ~20 ms (18 chunks).

Computed Windows duration at the ~15.6 ms default timer tick
(`time.sleep(0.001)` returns no sooner than one tick):
`n_chunks x max(DRIP_SECONDS, 0.0156)`:
- 405/415/403: 64 x 0.0156 = 0.998 s vs LINGER_SECONDS 0.25 -> the drip
  outlives the drain ~4x: the server closes, the writer's next sendall
  gets an RST. Matches run 42645047704 ("1/20 sends died", 405).
- 413: 18 x 0.0156 = 0.281 s > 0.25 -> marginal, the flake fires
  occasionally. Matches run 42606063274 (WinError 10053 on the 413).

The hypothesis holds arithmetically: the pacing, not the product, is
platform-dependent. Product behavior (bounded linger) is intended and
untouched.

## The fix (test pacing, tests/test_serve_early_refusal.py)

Constants/helper only (no assertion touched): `MAX_CHUNKS = 6`,
`DRIP_SECONDS = 0.005`, `_drip_chunk(body_len) = ceil(body_len /
MAX_CHUNKS)`, and `_assert_drains` derives the chunk from the body length
(the 413's explicit `chunk=65536` call site dropped for the same helper).
Per-body piece counts and worst-case wall time at the tick:
- 256 KiB -> 43691-byte chunks, 6 pieces, 6 x 0.0156 = 0.094 s
- 1.5 MiB -> 196608-byte chunks, 6 pieces, 0.094 s
Both under LINGER_SECONDS/2 = 0.125, a third of the linger on Linux
(~30 ms). First chunk is sent unsleep'd right after the headers, and the
refusal lands before the first body byte is read, so "bytes in flight
when refused" still holds. All three assertions (status / no send dies /
FIN) kept on all four cases; every body fits LINGER_BYTES, so "no send
dies" stays a justified expectation (task step (4): no case exceeds the
drain budget by design, so no assertion restated).

## The guard (tests/test_serve_early_refusal_pacing.py, new)

No sockets, no server, no timing: parametrized over every body the
pacing module drips, asserts `max(DRIP_SECONDS, 0.0156) x n_chunks <
LINGER_SECONDS / 2` (importing the pacing module's constants and
`LINGER_SECONDS` from the server), plus `n_chunks <= MAX_CHUNKS` and
`body_len <= LINGER_BYTES` (the expectation pin).

Red first:
- On the PRE-CHANGE constants imported from the real module (scratch
  harness, `.scratch/pacing-red/`): 256 KiB -> 0.998 s vs 0.125, 413 ->
  0.281 s vs 0.125: 2 failed.
- The new file itself, with the pacing module temporarily set to the old
  shape (`MAX_CHUNKS=64`, i.e. 4 KiB pieces): both parametrized cases
  fail with the same 0.998 s number; restored after.
Green after: 5 passed (2 parametrized + bound + 2 byte-bound).

## Runs

- `tests/test_serve_early_refusal*.py` 5x in a row: 9 passed each
  (3.09-3.19 s; the drip loop also got faster on Linux: 1.38 s -> 0.63 s
  per case).
- `tests/test_serve*.py tests/test_crossplatform_lint.py`
  (-n 4 --dist worksteal): 1229 passed, 1 skipped.
- `ruff check` on the two touched files: clean.
- Full suite once before push: 6435 passed, 2 skipped in 97.56 s
  (`-n 4 --dist worksteal`, the venv `venv-refdes`, absolute PYTHONPATH).

## Not verified (say it plainly)

The Windows effect itself is unverifiable on this Linux box -- no
Windows runner here, and the prior logs record the same
(in-prog-logs/serve-early-refusal-rst.md, serve-single-send.md). The
15.6 ms tick is the documented Windows default, not a measurement. The
guard makes the timing contract explicit so the next person does not
have to re-derive it from a CI log.
