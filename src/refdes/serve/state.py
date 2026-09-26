"""Loaded-project state for `refdes serve`: inputs, revision, polling, git.

One process owns one project. The in-memory model is a `Snapshot` built through
the side-effect-free path (`loader.load_readonly`), and its *revision* is a hash
of the content of every semantic project input -- never git identity, never
mtimes (docs/design/browser-editor.md, "Revision and conflict detection"). Git
branch/HEAD/dirty state is reported separately and only as advisory metadata.

External edits are noticed by polling: a cheap (mtime, size) signature first,
then a content-hash confirmation, so a touch that changes no bytes is not a
change. A confirmed change rebuilds the model and the temp-dir preview through
the same read-only path. A failed rebuild (say, a half-typed config) keeps the
last good model, records the error, and leaves the snapshot marked stale.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .. import loader
from ..model import Project
from ..parse import source_files
from .preview import PreviewManager

CONFIG_NAMES = ("refdes-project.yaml", "refdes-schema.yaml")
# `.refdes/` files that feed a build. schema.json is regenerated on every
# writable load (disposable), so it is not an input; copies/ holds fetched PDFs.
_STATE_SUFFIXES = (".yaml", ".yml", ".json")
_DISPOSABLE_STATE = {"schema.json"}


def asset_files(project: Project) -> set[str]:
    """Every file under a declared `site.assets:` directory, walked.

    Images are build inputs (Jared's 2026-09-25 decision, docs/design/
    editor-image-upload.md 15.1), and image resolution is a *query*:
    `_search_image_src` matches a bare `src` against any file in any declared
    directory, and `collect_static_assets` registers every file there without a
    reference. So the watched set is every file resolution could pick up, not
    the subset some body currently names -- adding an image can retire an
    absent/ambiguous error, and deleting one can create it.

    The walk mirrors those two functions exactly (same directories, same
    no-reference-needed breadth, missing directory skipped) so the watcher can
    never watch a file the build cannot resolve, or miss one it can. The image
    picker's list reads the same walk (`serve.api._images`), so the editor
    cannot offer an image the build would not resolve either.
    """
    found: set[str] = set()
    for rel_dir in project.asset_dirs:
        full_dir = os.path.join(project.root, rel_dir)
        if not os.path.isdir(full_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(full_dir):
            for name in filenames:
                found.add(os.path.join(dirpath, name))
    return found


def project_inputs(project: Project) -> list[str]:
    """Absolute paths of every file whose content is a semantic project input:
    the two config files, item sources, page sources, `.refdes/` state,
    imported artifacts, and every file under a `site.assets:` directory.
    Sorted; may name files that no longer exist."""
    root = project.root
    found: set[str] = set()
    for name in CONFIG_NAMES:
        found.add(os.path.join(root, name))
    found.update(source_files(project))
    pages_dir = os.path.join(root, project.pages_dir)
    if os.path.isdir(pages_dir):
        for dirpath, dirnames, filenames in os.walk(pages_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.endswith(".md") and not name.startswith("."):
                    found.add(os.path.join(dirpath, name))
    state_dir = os.path.join(root, ".refdes")
    if os.path.isdir(state_dir):
        for name in os.listdir(state_dir):
            path = os.path.join(state_dir, name)
            if (
                name.endswith(_STATE_SUFFIXES)
                and name not in _DISPOSABLE_STATE
                and os.path.isfile(path)
            ):
                found.add(path)
    for spec in project.imports:
        found.add(os.path.join(root, spec.items_path))
    found.update(asset_files(project))
    return sorted(found)


def signature(paths: list[str]) -> tuple:
    """(path, mtime_ns, size) per input; None for a missing file."""
    out = []
    for path in paths:
        try:
            st = os.stat(path)
            out.append((path, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((path, None, None))
    return tuple(out)


def content_hashes(paths: list[str], root: str) -> dict[str, str]:
    """relpath -> sha256 of the file's bytes ("" for a missing file)."""
    out: dict[str, str] = {}
    for path in paths:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with open(path, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            out[rel] = ""
    return out


def revision_of(hashes: dict[str, str]) -> str:
    blob = json.dumps(sorted(hashes.items()), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


@dataclass
class Snapshot:
    project: Project
    revision: str
    hashes: dict[str, str]
    signature: tuple
    serial: int
    built_at: float = field(default_factory=time.time)


def git_status(root: str) -> dict:
    """Advisory git context; `{"available": False}` outside a repo or without
    git. Never stages, commits, or refreshes the index (`--no-optional-locks`)."""

    def run(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "--no-optional-locks", "-C", root, *args],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    head = run("rev-parse", "HEAD")
    if head is None:
        return {"available": False}
    branch = (run("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    porcelain = run("status", "--porcelain=v1") or ""
    lines = [ln for ln in porcelain.splitlines() if ln]
    return {
        "available": True,
        "branch": branch,
        "head": head.strip()[:12],
        # Working tree: any unstaged change or untracked file. Index: anything staged.
        "worktree_dirty": any(ln[1] != " " for ln in lines),
        "index_dirty": any(ln[0] not in " ?" for ln in lines),
    }


class ProjectState:
    def __init__(self, config_path: str | None, preview: PreviewManager | None = None):
        self.config_path = config_path
        self.preview = preview
        self._lock = threading.RLock()
        self._serial = 0
        self._snapshot: Snapshot | None = None
        self._disk_revision: str | None = None
        self.load_error: str | None = None
        self._git_cache: tuple[float, dict] | None = None
        # The last on-disk signature acted on (rebuilt, confirmed unchanged, or
        # failed), so a broken-but-unchanged file is not rebuilt every poll.
        self._handled_signature: tuple = ()

    # ------------------------------------------------------------ building

    def _build(self) -> Snapshot:
        # Hash the inputs before and after the load: a file that changed while
        # the model was being built would otherwise carry a revision newer than
        # the model it labels, and a later save would pass its conflict check
        # against content the form never saw.
        for _attempt in range(3):
            before = (
                content_hashes(project_inputs(self._snapshot.project), self._snapshot.project.root)
                if self._snapshot is not None
                else None
            )
            project = loader.load_readonly(self.config_path)
            paths = project_inputs(project)
            hashes = content_hashes(paths, project.root)
            if before is None or all(hashes.get(rel, "") == h for rel, h in before.items()):
                break
        else:
            raise RuntimeError("project files kept changing while the model was being built")
        self._serial += 1
        if self.preview is not None:
            self.preview.render(project)
        return Snapshot(
            project=project,
            revision=revision_of(hashes),
            hashes=hashes,
            signature=signature(paths),
            serial=self._serial,
        )

    def load(self) -> Snapshot:
        """First load. A configuration error propagates to the caller."""
        with self._lock:
            self._snapshot = self._build()
            self._disk_revision = self._snapshot.revision
            self._handled_signature = self._snapshot.signature
            self.load_error = None
            return self._snapshot

    @property
    def snapshot(self) -> Snapshot:
        assert self._snapshot is not None, "load() has not run"
        return self._snapshot

    @property
    def stale(self) -> bool:
        return self._disk_revision != self.snapshot.revision

    # ------------------------------------------------------------- polling

    def pending_signature(self) -> tuple | None:
        """The current on-disk signature if it differs from the loaded model's,
        else None -- the cheap first stage of change detection."""
        with self._lock:
            snap = self.snapshot
            paths = project_inputs(snap.project)
            sig = signature(paths)
            return None if sig == self._handled_signature else sig

    def refresh(self) -> bool:
        """Confirm a change by content hash and rebuild on it. Returns True
        when the model was replaced. Idempotent and safe to call at any time."""
        with self._lock:
            snap = self.snapshot
            paths = project_inputs(snap.project)
            sig = signature(paths)
            if sig == self._handled_signature:
                return False
            self._handled_signature = sig
            hashes = content_hashes(paths, snap.project.root)
            disk_revision = revision_of(hashes)
            self._disk_revision = disk_revision
            if disk_revision == snap.revision:
                # Touched, not changed: remember the new stat so we stop re-hashing.
                self.load_error = None
                return False
            try:
                self._snapshot = self._build()
            except Exception as exc:  # noqa: BLE001 - keep serving the last good model
                self.load_error = f"{type(exc).__name__}: {exc}"
                return False
            self._disk_revision = self._snapshot.revision
            self._handled_signature = self._snapshot.signature
            self.load_error = None
            return True

    def git(self, max_age: float = 1.0) -> dict:
        with self._lock:
            now = time.monotonic()
            if self._git_cache and now - self._git_cache[0] < max_age:
                return self._git_cache[1]
            info = git_status(self.snapshot.project.root)
            self._git_cache = (now, info)
            return info

    def revision_info(self) -> dict:
        with self._lock:
            snap = self.snapshot
            return {
                "revision": snap.revision,
                "serial": snap.serial,
                "stale": self.stale,
                "load_error": self.load_error,
                "git": self.git(),
            }


class Poller(threading.Thread):
    """Background change detector. Debounced: a change is acted on only once
    the on-disk signature has been identical across two consecutive polls, so
    an editor saving in several steps triggers one rebuild."""

    def __init__(self, state: ProjectState, interval: float = 1.0):
        super().__init__(name="refdes-serve-poller", daemon=True)
        self.state = state
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        last_pending = None
        ticks = 0
        while not self._stop_event.wait(self.interval):
            try:
                pending = self.state.pending_signature()
                if pending is not None and pending == last_pending:
                    self.state.refresh()
                    pending = None
                last_pending = pending
                ticks += 1
                if self.state.preview is not None and ticks % 30 == 0:
                    self.state.preview.touch()
            except Exception:  # noqa: BLE001 - a poll must never kill the thread
                last_pending = None

    def stop(self) -> None:
        self._stop_event.set()
