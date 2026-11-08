"""The docs-context analysis cache must survive concurrent writers (DC-4a review).

The server is a ``ThreadingHTTPServer`` and DC-4a added a second concurrent
writer of ``DocState._cache``: ``POST /api/focus`` resolves its line through
``block_at`` -> ``doc_payload``, the same path ``GET /api/doc`` and
``POST /api/ask`` use. ``doc_payload`` read and mutated the cache with NO
lock: two threads at the 32-key cap can compute the same eviction key, and
the loser's ``dict.pop`` raises KeyError (iterating the dict while another
thread mutates it raises RuntimeError the same way).

RED-FIRST, deterministic: every cache mutation is run through an
instrumented dict whose ``pop`` widens its own window with a short sleep and
raises ``ConcurrentCacheMutation`` the moment a second thread enters a
mutation while one is in progress. On the unlocked code the second thread
overlaps the sleep (the hammer releases every thread at a barrier over
distinct cold paths, so they reach eviction together) and the test is red
for the real reason: two threads evicting at once. Once the fix serialises
the check/evict/store under one lock, the second thread blocks on the lock
OUTSIDE ``pop`` and never observes an overlap: the sleeps serialize (a few
hundred ms total), the test is green.

The fix must not make the hammer pay for the analyze inside the lock; the
payloads returned to every thread must stay well-formed. No existing route
behaviour changes.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from docs_context import server
from test_docs_context_server import make_repo

EVICT_WINDOW = 0.01


class ConcurrentCacheMutation(RuntimeError):
    """Raised by the probe when two threads are inside a cache mutation."""


class ProbedCache(dict):
    """A cache dict that fails loudly on concurrent mutation.

    ``pop`` (the eviction) holds its "active" slot across a short sleep, so
    a second thread entering any mutation during that window is a detected
    overlap -- the exact interleaving of the unlocked eviction. The probe
    only observes; it adds no serialization of its own."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gate = threading.Lock()
        self._active = 0

    def _enter(self, what):
        with self._gate:
            self._active += 1
            return self._active > 1

    def _exit(self):
        with self._gate:
            self._active -= 1

    def _overlap(self, what):
        with self._gate:
            return self._active > 1

    def pop(self, *args):
        overlapped = self._enter("pop")
        if overlapped:
            self._exit()
            raise ConcurrentCacheMutation("two threads in pop at once")
        try:
            time.sleep(EVICT_WINDOW)
            if self._overlap("pop"):
                raise ConcurrentCacheMutation("two threads in pop at once")
            return super().pop(*args)
        finally:
            self._exit()

    def __setitem__(self, key, value):
        if self._enter("setitem"):
            self._exit()
            raise ConcurrentCacheMutation("two threads in setitem at once")
        try:
            if self._overlap("setitem"):
                raise ConcurrentCacheMutation("two threads in setitem at once")
            return super().__setitem__(key, value)
        finally:
            self._exit()


def write_docs(repo, names, text):
    for name in names:
        (repo / "docs" / name).write_text(text, encoding="utf-8", newline="")


def run_workers(threads):
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "a cache writer hung"


def test_eviction_under_concurrent_writers_is_not_corrupted(tmp_path):
    repo = make_repo(tmp_path)
    state = server.DocState(str(repo / "docs" / "a.md"), str(repo))

    pad = [f"pad{i}.md" for i in range(server.CACHE_MAX)]
    write_docs(repo, pad, "# Pad\n\nPlain paragraph, no refs.\n")
    for name in pad:
        state.doc_payload(f"docs/{name}")
    assert len(state._cache) == server.CACHE_MAX  # filled exactly to the cap

    state._cache = ProbedCache(state._cache)

    cold = [f"q{i}.md" for i in range(2 * server.CACHE_MAX)]
    write_docs(repo, cold, "# Q\n\nPlain paragraph, no refs.\n")
    barrier = threading.Barrier(len(cold))
    errors: list[str] = []

    def worker(name):
        try:
            barrier.wait(timeout=30)
            payload = state.doc_payload(f"docs/{name}")
            assert "blocks" in payload, name
        except BaseException as exc:  # noqa: BLE001 - reported via the list
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    run_workers([threading.Thread(target=worker, args=(name,)) for name in cold])
    assert errors == [], errors
    assert len(state._cache) <= server.CACHE_MAX


def test_focus_and_doc_writers_hammer_the_same_key(tmp_path):
    repo = make_repo(tmp_path)
    state = server.DocState(str(repo / "docs" / "a.md"), str(repo))
    state._cache = ProbedCache(state._cache)

    barrier = threading.Barrier(12)
    errors: list[str] = []

    def doc_worker():
        try:
            barrier.wait(timeout=30)
            for _ in range(8):
                assert "blocks" in state.doc_payload(state.rel_doc)
        except BaseException as exc:  # noqa: BLE001 - reported via the list
            errors.append(f"doc: {type(exc).__name__}: {exc}")

    def focus_worker(line):
        try:
            barrier.wait(timeout=30)
            for _ in range(8):
                assert state.block_at(line) in (1, 3, 5, 7), line
        except BaseException as exc:  # noqa: BLE001 - reported via the list
            errors.append(f"focus: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=doc_worker) for _ in range(6)]
    threads += [threading.Thread(target=focus_worker, args=(line,)) for line in (3, 5, 7, 2, 4, 6)]
    run_workers(threads)
    assert errors == [], errors
    assert len(state._cache) == 1  # the served doc is the only key ever stored
