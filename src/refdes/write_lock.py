"""One cross-process project write lock for item and ID transactions."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager

_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_LOCAL = threading.local()


class LockUnavailable(OSError):
    """The project lock could not be acquired."""


@contextmanager
def project_write_lock(root: str):
    """Serialize a project's writers, including threads and nested calls.

    The file is stable: unlinking it could let processes lock different inodes.
    A wholly read-only root cannot host a lock; its ordinary write refusal
    paths remain responsible for reporting the filesystem failure.
    """
    root = os.path.normcase(os.path.abspath(root))
    with _GUARD:
        lock = _THREAD_LOCKS.setdefault(root, threading.RLock())
    with lock:
        depths = getattr(_LOCAL, "depths", None)
        if depths is None:
            depths = _LOCAL.depths = {}
        if depths.get(root, 0):
            depths[root] += 1
            try:
                yield
            finally:
                depths[root] -= 1
            return
        # A read-only checkout must not gain an artifact even when run by a
        # privileged test process that could otherwise create one.
        if not os.stat(root).st_mode & 0o222:
            # A writable child could still hold item sources or the ledger.
            # Refuse that mixed-permission tree instead of writing unlocked.
            for directory, _children, _files in os.walk(root):
                if directory != root and os.stat(directory).st_mode & 0o222:
                    raise LockUnavailable(
                        f"could not lock project {root}: root is read-only "
                        "while a child is writable"
                    )
            yield
            return
        # The root remains writable when .refdes/ alone is read-only. Place
        # the canonical lock here so item writes can still be serialized and
        # the ledger's existing refusal can be reported by its own writer.
        path = os.path.join(root, ".refdes-write.lock")
        try:
            fh = open(path, "a+b")
        except OSError as exc:
            raise LockUnavailable(f"could not open project write lock {path}: {exc}") from exc
        with fh:
            fh.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise LockUnavailable(
                    f"could not acquire project write lock {path}: {exc}"
                ) from exc
            depths[root] = 1
            try:
                yield
            finally:
                del depths[root]
                fh.seek(0)
                if os.name == "nt":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
