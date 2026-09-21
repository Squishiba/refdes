"""The rendered preview, in an OS temp directory (never `_site/`).

Each rebuild renders into a fresh generation directory under one per-launch
temp root, then swaps it in as `current`, so a request never sees a
half-written site. The root is removed on normal exit; a later launch prunes
same-user roots a crash left behind (identified by a marker file whose mtime
this launch keeps fresh).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time

from .. import render as render_mod
from ..model import Project

ROOT_PREFIX = "refdes-preview-"
MARKER = ".refdes-preview"
STALE_AFTER_SECONDS = 3600  # the live server touches its marker far more often


def prune_stale(temp_dir: str | None = None, now: float | None = None) -> list[str]:
    """Remove same-user preview roots whose marker has not been touched for
    `STALE_AFTER_SECONDS` -- what a crashed launch leaves behind. Returns the
    removed paths. Never touches anything without both the prefix and the
    marker file, so it cannot delete an unrelated directory."""
    temp_dir = temp_dir or tempfile.gettempdir()
    now = time.time() if now is None else now
    removed: list[str] = []
    try:
        names = os.listdir(temp_dir)
    except OSError:
        return removed
    for name in names:
        if not name.startswith(ROOT_PREFIX):
            continue
        path = os.path.join(temp_dir, name)
        marker = os.path.join(path, MARKER)
        try:
            if not os.path.isfile(marker) or os.path.islink(path):
                continue
            if hasattr(os, "getuid") and os.stat(path).st_uid != os.getuid():
                continue
            if now - os.path.getmtime(marker) < STALE_AFTER_SECONDS:
                continue
            shutil.rmtree(path)
            removed.append(path)
        except OSError:
            continue
    return removed


class PreviewManager:
    def __init__(self, temp_dir: str | None = None):
        self._temp_dir = temp_dir
        prune_stale(temp_dir)
        self.root = tempfile.mkdtemp(prefix=ROOT_PREFIX, dir=temp_dir)
        self._marker = os.path.join(self.root, MARKER)
        self.touch()
        self._lock = threading.RLock()
        self._current: str | None = None
        self._leftovers: list[str] = []
        self._generation = 0

    def touch(self) -> None:
        with open(self._marker, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))

    @property
    def current(self) -> str | None:
        return self._current

    def render(self, project: Project) -> str:
        """Render `project` into a new generation and make it current. The
        project's out_dir is redirected to the temp generation for the render;
        the site is real and browsable ("draft": nothing was sealed)."""
        with self._lock:
            self._generation += 1
            gen = os.path.join(self.root, f"gen-{self._generation}")
        os.makedirs(gen)
        project.out_dir = gen  # absolute: render_site joins it onto root
        render_mod.render_site(project, draft=True)
        with self._lock:
            previous, self._current = self._current, gen
            if previous:
                self._leftovers.append(previous)
            self._sweep()
        return gen

    def _sweep(self) -> None:
        # A generation may still be open on Windows (a request streaming an
        # image); leave it for the next sweep rather than fail the rebuild.
        remaining = []
        for path in self._leftovers:
            shutil.rmtree(path, ignore_errors=True)
            if os.path.exists(path):
                remaining.append(path)
        self._leftovers = remaining

    def open_file(self, parts: list[str]):
        """Open a file below the current generation for reading, or None.
        Containment is re-checked on the resolved path, so a symlink or
        junction inside the preview cannot lead out of it."""
        with self._lock:
            if self._current is None:
                return None
            base = os.path.realpath(self._current)
            path = os.path.realpath(os.path.join(base, *parts))
            if os.path.commonpath([base, path]) != base or not os.path.isfile(path):
                return None
            try:
                return open(path, "rb")
            except OSError:
                return None

    def close(self) -> None:
        with self._lock:
            self._current = None
        shutil.rmtree(self.root, ignore_errors=True)
