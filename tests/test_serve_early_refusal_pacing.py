"""The early-refusal drip's pacing is a contract with the server's linger.

`tests/test_serve_early_refusal.py` drips a refused request's body in
pieces spaced by `time.sleep(DRIP_SECONDS)`. A sleep is a floor, not a
duration: Windows' default timer resolution makes `sleep(0.001)` return
after ~15.6 ms, so a piece count of N costs up to N * 15.6 ms there and
only N * DRIP_SECONDS here. `_Server.shutdown_request` drains a refused
request for at most `LINGER_SECONDS` and then closes; a drip still writing
at that point gets an RST mid-write -- the windows-latest flakes of runs
42606063274 (413, WinError 10053) and 42645047704 (405, "1/20 sends
died"). The bounded linger is intended product behavior, so the pacing is
what has to move.

This file pins that, with arithmetic only: for every body the pacing
module drips, the WORST-CASE drip wall time -- one Windows tick per piece,
`max(DRIP_SECONDS, 0.0156) * n_chunks` -- must fit half the linger, and
the body must fit `LINGER_BYTES` so assertion (b) of the pacing module
("no send dies") is a justified expectation and not a luck of the buffer.
No sockets, no server, no timing: it says the same thing on both
platforms, which is exactly the property the CI flakes violated.
"""

from __future__ import annotations

import math

import pytest
from test_serve_early_refusal import (
    BODY_BYTES,
    DRIP_SECONDS,
    MAX_CHUNKS,
    _drip_chunk,
)

from refdes.serve.server import LINGER_BYTES, LINGER_SECONDS, MAX_BODY_BYTES

# Windows' default timer resolution: sleep() cannot return sooner than one
# tick, so a paced drip costs at least this per piece on windows-latest.
WINDOWS_TICK_SECONDS = 0.0156

# Every body the pacing module drips, keyed by the refusal that drives it.
# Mirrors the _assert_drains call sites; the 413 body is the one that
# breaks the byte bound first if the pacing is widened, so it is here.
BODIES = {
    "405/415/403": BODY_BYTES,
    "413": MAX_BODY_BYTES + BODY_BYTES // 2,
}


def worst_case_drip_seconds(body_len: int) -> float:
    """Upper bound on the drip's wall time: one Windows tick per piece."""
    n_chunks = math.ceil(body_len / _drip_chunk(body_len))
    return n_chunks * max(DRIP_SECONDS, WINDOWS_TICK_SECONDS)


@pytest.mark.parametrize("name", sorted(BODIES))
def test_the_worst_case_drip_fits_half_the_linger(name):
    body_len = BODIES[name]
    budget = LINGER_SECONDS / 2
    worst = worst_case_drip_seconds(body_len)
    n_chunks = math.ceil(body_len / _drip_chunk(body_len))
    assert worst < budget, (
        f"{name}: a dripped {body_len}-byte body takes "
        f"{n_chunks} pieces x {max(DRIP_SECONDS, WINDOWS_TICK_SECONDS)}s = "
        f"{worst:.3f}s at the Windows tick, over half the "
        f"{LINGER_SECONDS}s linger -- a drip that outlives the drain gets "
        f"an RST mid-write on Windows"
    )


def test_the_piece_count_stays_bounded_by_construction():
    # The chunk derives from the body length, so the drip's cost is capped
    # by MAX_CHUNKS and does not grow with the body: the property the
    # fixed-size 4 KB chunk violated (256 KiB -> 64 pieces, 1.5 MiB -> 18).
    for name, body_len in BODIES.items():
        n_chunks = math.ceil(body_len / _drip_chunk(body_len))
        assert n_chunks <= MAX_CHUNKS, f"{name}: {n_chunks} > {MAX_CHUNKS}"
    assert DRIP_SECONDS > 0, "pieces must be spaced, not fired back to back"


@pytest.mark.parametrize("name", sorted(BODIES))
def test_every_dripped_body_fits_the_linger_byte_bound(name):
    body_len = BODIES[name]
    assert body_len <= LINGER_BYTES, (
        f"{name}: {body_len} bytes over the {LINGER_BYTES}-byte drain bound "
        f"-- the drain stops on bytes, not on time, and a late RST on the "
        f"writer is then legitimate, not a flake to pace around"
    )
