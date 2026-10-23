"""Transaction journal for browser-editor saves.

An editor save replaces several files. Today a crash between two of those
replacements leaves a half-applied save with no trace on disk (see
docs/design/browser-editor.md, "Transaction model"). This module is the
trace: a journal directory under the project root, written in full BEFORE
any live file is touched, removed on success, and replayed by ``recover``
to put the originals back when a save died halfway.

The posture is: a journal directory on disk means "the project may be
half-applied", and every consumer refuses to proceed until ``recover`` has
run. ``begin`` is crash-safe by construction -- it builds the journal in a
temporary sibling directory, writes originals first and ``manifest.json``
last, then ``os.replace``\\ s the whole directory into place, so
``.refdes/editor-transaction/`` is only ever visible complete. A journal
whose manifest is missing is by that construction a crash *inside*
``begin``: no live file can have been replaced, so ``recover`` simply
removes it.

The journal stores the original bytes (the recovery data) and only the
sha256 of each replacement (the live file *is* the replacement once the
save lands). Originals live under ``orig/`` named by manifest position, so
nothing on disk depends on a user's path characters being filesystem-safe.

Standalone by design: stdlib only, no refdes imports, so the future
wiring in ``serve/edit.py`` and ``cli.py`` is the only integration point.
"""

from __future__ import annotations

import errno
import hashlib
import json
import ntpath
import os
import posixpath
import secrets
import shutil
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass

JOURNAL_DIR = ".refdes/editor-transaction"

_MANIFEST_NAME = "manifest.json"
_ORIG_DIR_NAME = "orig"


class JournalPending(Exception):
    """A journal already exists: the project may be half-applied.

    The message names the transaction and points at ``refdes recover``,
    which is the only thing that clears the condition.
    """

    def __init__(self, transaction_id: str) -> None:
        self.transaction_id = transaction_id
        super().__init__(
            f"editor transaction {transaction_id} is pending; the project "
            f"may be half-applied. Run 'refdes recover' to restore it."
        )


class JournalCorrupt(Exception):
    """The journal cannot be trusted; recovery refused and changed nothing."""


@dataclass(frozen=True)
class Entry:
    """One file a save touches.

    ``path`` is project-root-relative with forward slashes. ``original`` is
    the file's bytes before the save, or ``None`` when the file did not
    exist. ``replacement`` is what the save writes -- recorded only as a
    hash, because the live file becomes the replacement.
    """

    path: str
    original: bytes | None
    replacement: bytes


# ---------------------------------------------------------------------------
# paths and ids
# ---------------------------------------------------------------------------


def _journal_path(project_root: str) -> str:
    return os.path.join(project_root, *JOURNAL_DIR.split("/"))


def _journal_parent(project_root: str) -> str:
    return os.path.dirname(_journal_path(project_root))


def _live_path(project_root: str, rel: str) -> str:
    # Safe only for paths that passed `_is_safe_relpath`: no `..`, no
    # absolute, no backslash/colon, so the join cannot leave the root.
    return os.path.join(project_root, *rel.split("/"))


def _escapes_root(project_root: str, rel: str) -> bool:
    """True when a path's containing directory resolves outside the root.

    `_is_safe_relpath` is lexical, and lexical cannot see symlinks: with
    ``project/jump -> /outside``, the manifest path ``jump/file.txt`` is
    lexically safe, yet writing it lands a file outside the project.
    Resolving the PARENT directory (the file itself may not exist) and
    requiring it to stay under the resolved root closes that. A symlink
    as the final component is fine: ``os.replace``/``os.remove`` act on
    the link itself, never on its target.
    """
    parent = os.path.dirname(_live_path(project_root, rel))
    root_real = os.path.realpath(project_root)
    parent_real = os.path.realpath(parent)
    try:
        return os.path.commonpath([root_real, parent_real]) != root_real
    except ValueError:
        # commonpath raises for paths on different drives (Windows).
        return True


def _journal_escapes_root(project_root: str) -> bool:
    """True when the journal location itself escapes the root via a symlink.

    ``_escapes_root`` guards the *entry* paths; the journal lives under
    ``<root>/.refdes``, and nothing else resolves that directory. If it
    is a symlink to outside the project, ``begin`` would stage the
    originals and the manifest outside the root (defeating confinement
    and exposing file contents), and ``recover``/``complete`` would
    remove a directory outside the root. Require the parent directory
    and the journal path to resolve inside the resolved root, and the
    journal path to be no symlink of its own.
    """
    root_real = os.path.realpath(project_root)
    journal = _journal_path(root_real)
    for path in (os.path.dirname(journal), journal):
        real = os.path.realpath(path)
        try:
            if os.path.commonpath([root_real, real]) != root_real:
                return True
        except ValueError:
            return True
    return os.path.islink(journal)


def _is_safe_relpath(path: str) -> bool:
    """Project-relative and free of anything that makes two spellings name
    one file: no ``..``, ``.``, empty segments (which covers trailing
    slashes and ``a//b``), absolute form, backslash, colon.
    """
    if not path:
        return False
    if "\\" in path or ":" in path:
        return False
    if posixpath.isabs(path) or ntpath.isabs(path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def _new_transaction_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{secrets.token_hex(8)}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# low-level write helpers (deliberately local: the module imports no refdes)
# ---------------------------------------------------------------------------


def _create_temp(directory: str, name: str) -> tuple[int, str]:
    for _ in range(100):
        tmp = os.path.join(directory, f".{name}.refdes-tmp-{secrets.token_hex(8)}")
        try:
            return (
                os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666),
                tmp,
            )
        except FileExistsError:
            continue
    raise FileExistsError(f"could not create a temporary file in {directory}")


def _atomic_write_bytes(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = _create_temp(directory, os.path.basename(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# `os.open` of a directory is the POSIX-only half of a directory fsync;
# Windows refuses with PermissionError (occasionally IsADirectoryError),
# and some filesystems refuse the fsync itself (e.g. network mounts).
# Those are the "platform does not support it" cases the contract allows
# to pass quietly; everything else is a real I/O error and must surface.
_FSYNC_DIR_OPEN_UNSUPPORTED = (PermissionError, IsADirectoryError)
_FSYNC_UNSUPPORTED = (errno.ENOTSUP, errno.ENOSYS, errno.EBADF, errno.EOPNOTSUPP)


def _fsync_dir(path: str) -> None:
    """Directory fsync, where the platform supports it.

    Callers depend on this for the durability of renames and unlinks:
    without it, a power loss can resurrect a removed journal (undoing a
    completed save on the next recover) or lose a created one (hiding a
    live transaction). Only the unsupported-platform cases are swallowed;
    a real I/O error propagates, because a silently non-durable journal
    defeats the module's purpose.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except _FSYNC_DIR_OPEN_UNSUPPORTED:
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in _FSYNC_UNSUPPORTED:
            raise
    finally:
        os.close(fd)


def _read_if_file(path: str) -> bytes | None:
    """The file's bytes, or None if it plainly does not exist."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _read_orig(journal: str, index: int) -> bytes | None:
    return _read_if_file(os.path.join(journal, _ORIG_DIR_NAME, f"{index}.bin"))


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def _read_manifest_raw(journal: str) -> object | None:
    """The parsed manifest; None when it is missing or unparseable.

    Missing/unparseable is the inert state: begin() writes manifest.json
    last, so a journal without one is a crash before any live file was
    touched, and recover removes it. An UNREADABLE manifest is the
    opposite -- it says nothing about whether begin() completed -- so it
    raises JournalCorrupt naming the path: deleting the journal there
    would discard the only rollback copy while replacement bytes are
    live. (UnicodeDecodeError is a ValueError; JSONDecodeError too.)
    """
    manifest_path = os.path.join(journal, _MANIFEST_NAME)
    try:
        with open(manifest_path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise JournalCorrupt(
            f"journal manifest at {manifest_path} cannot be read ({exc}); "
            f"refusing to judge the journal without it"
        ) from exc
    try:
        return json.loads(data)
    except ValueError:
        return None


def _manifest_entries(manifest: object) -> tuple[str, list[dict]]:
    """Validate the parsed manifest's shape; JournalCorrupt on garbage.

    A parseable manifest means ``begin`` completed (it is the last thing
    written), so structural garbage here is corruption, not a mid-begin
    crash -- and an entry we cannot read is an entry we cannot verify.
    """
    if not isinstance(manifest, dict):
        raise JournalCorrupt("journal manifest is not a JSON object")
    transaction_id = manifest.get("transaction")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise JournalCorrupt("journal manifest has no transaction id")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise JournalCorrupt("journal manifest has no entries list")
    normalized: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise JournalCorrupt("journal manifest entry is not an object")
        path = raw.get("path")
        existed = raw.get("existed")
        original_sha = raw.get("original_sha256")
        replacement_sha = raw.get("replacement_sha256")
        if not isinstance(path, str) or not isinstance(existed, bool):
            raise JournalCorrupt("journal manifest entry is missing path/existed")
        if not _is_safe_relpath(path):
            raise JournalCorrupt(f"journal names an unsafe path: {path!r}")
        key = tuple(path.split("/"))
        if key in seen:
            raise JournalCorrupt(f"journal manifest lists the path {path!r} twice")
        seen.add(key)
        if not (original_sha is None or isinstance(original_sha, str)):
            raise JournalCorrupt(f"journal manifest entry for {path!r} has a bad hash")
        if existed and original_sha is None:
            raise JournalCorrupt(f"journal entry for {path!r} has no recorded original hash")
        if not isinstance(replacement_sha, str):
            raise JournalCorrupt(f"journal entry for {path!r} has no recorded replacement hash")
        normalized.append(
            {
                "path": path,
                "existed": existed,
                "original_sha256": original_sha,
                "replacement_sha256": replacement_sha,
            }
        )
    return transaction_id, normalized


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def begin(project_root: str, entries: Sequence[Entry]) -> str:
    """Record a save's originals in a fresh journal; return the transaction id.

    Raises ``JournalPending`` if a journal already exists (nothing is
    created), ``ValueError`` for unusable entry paths (absolute, ``..``,
    backslash, colon, empty, duplicated, resolving outside the root via
    a symlink) -- also with nothing created.
    """
    _validate_entries(project_root, entries)
    if _journal_escapes_root(project_root):
        raise ValueError(
            "the journal location (.refdes) resolves outside the project root"
        )
    journal = _journal_path(project_root)
    if os.path.exists(journal):
        raise JournalPending(pending(project_root) or "unknown")

    transaction_id = _new_transaction_id()
    os.makedirs(_journal_parent(project_root), exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".editor-transaction-", dir=_journal_parent(project_root))
    try:
        orig_dir = os.path.join(staging, _ORIG_DIR_NAME)
        os.mkdir(orig_dir)
        manifest_entries: list[dict] = []
        for index, entry in enumerate(entries):
            existed = entry.original is not None
            if existed:
                _atomic_write_bytes(os.path.join(orig_dir, f"{index}.bin"), entry.original)
            manifest_entries.append(
                {
                    "path": entry.path,
                    "existed": existed,
                    "original_sha256": _sha256(entry.original) if existed else None,
                    "replacement_sha256": _sha256(entry.replacement),
                }
            )
        manifest = json.dumps(
            {"transaction": transaction_id, "entries": manifest_entries},
            indent=2,
        ).encode("utf-8")
        # The backups live in a directory of their own: fsyncing staging
        # persists its entry for `orig/`, never the files inside it, so
        # orig/ is synced here -- a power loss must not leave a visible
        # manifest beside backup entries that never reached the disk.
        _fsync_dir(orig_dir)
        # manifest.json last: a visible journal without it means "crash
        # inside begin, no live file touched", and recover relies on that.
        _atomic_write_bytes(os.path.join(staging, _MANIFEST_NAME), manifest)
        _fsync_dir(staging)
        try:
            os.replace(staging, journal)
        except OSError:
            # A journal appeared between the check and the rename (a racing
            # save): os.replace never clobbers a non-empty directory.
            if os.path.exists(journal):
                raise JournalPending(pending(project_root) or "unknown") from None
            raise
        # Durable before the caller touches any live file: fsync the
        # parent so the rename that made the journal visible survives.
        _fsync_dir(_journal_parent(project_root))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return transaction_id


def pending(project_root: str) -> str | None:
    """The transaction id of a live journal, ``"unknown"`` if unreadable
    (including a plain file squatting on the journal path), None if there
    is no journal.

    Existence is judged the way ``begin`` judges it -- any path at the
    journal location -- so the guard refuses exactly the projects where a
    save would be refused.
    """
    journal = _journal_path(project_root)
    if not os.path.exists(journal):
        return None
    if _journal_escapes_root(project_root):
        # A journal location that symlinks out of the root is not a
        # journal we can read (and must not be followed); it is still
        # the condition begin refuses, so report it, unreadable.
        return "unknown"
    try:
        manifest = _read_manifest_raw(journal)
    except JournalCorrupt:
        # Unreadable: it is still a live journal, and pending() is the
        # refusal gate -- it must report, not raise.
        return "unknown"
    if isinstance(manifest, dict):
        transaction_id = manifest.get("transaction")
        if isinstance(transaction_id, str) and transaction_id:
            return transaction_id
    return "unknown"


def refuse_if_pending(project_root: str) -> None:
    """Raise ``JournalPending`` if a journal exists at all."""
    transaction_id = pending(project_root)
    if transaction_id is not None:
        raise JournalPending(transaction_id)


def complete(project_root: str) -> None:
    """Remove the journal after a successful save. Idempotent.

    The manifest is deleted first, and that is the step whose failure this
    must not swallow: a journal directory without a readable manifest is
    inert (``recover`` removes it as a crashed begin), so once the
    manifest is gone a completed save can never be undone by leftover
    directory debris. A failed *manifest* delete therefore raises -- the
    journal is still armed, and the caller has to know. The directory is
    then always cleared, inert debris (no manifest) included: a leftover
    journal directory would keep ``refuse_if_pending`` blocking projects
    whose saves succeeded, and a directory that outlives complete()
    raises too, pointing at ``recover``, which clears it.
    """
    journal = _journal_path(project_root)
    manifest = os.path.join(journal, _MANIFEST_NAME)
    if _journal_escapes_root(project_root):
        raise OSError(
            f"the journal location {_journal_path(os.path.realpath(project_root))} "
            "resolves outside the project root; refusing to delete through it. "
            "Remove the symlink, then run 'refdes recover'."
        )
    try:
        os.remove(manifest)
        _fsync_dir(journal)
    except FileNotFoundError:
        if not os.path.isdir(journal):
            return  # no journal at all: the idempotent no-op
    except OSError as exc:
        raise OSError(
            f"journal manifest in {journal} could not be removed: {exc}"
        ) from exc
    try:
        shutil.rmtree(journal)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise OSError(
            f"journal leftovers in {journal} could not be deleted: {exc}. "
            "Run 'refdes recover'."
        ) from exc
    _fsync_dir(_journal_parent(project_root))


def recover(project_root: str) -> list[str]:
    """Restore every journaled original; return the paths whose live state
    actually changed, in manifest order.

    Refuses (``JournalCorrupt``, changing nothing, journal kept) when a
    stored original is missing or does not match its recorded hash, when
    the manifest names an unsafe path, lists one path twice, resolves
    outside the root, or names a path that is a directory on disk.
    Restored files' parent directories are fsynced before the journal is
    removed. Leaves the journal in place on any failure, so running it
    again is safe.
    """
    journal = _journal_path(project_root)
    if _journal_escapes_root(project_root):
        raise JournalCorrupt(
            "the journal location (.refdes) resolves outside the project "
            "root; refusing to restore through the symlink"
        )
    if not os.path.isdir(journal):
        return []
    manifest = _read_manifest_raw(journal)
    if manifest is None:
        # begin() writes manifest.json last, from a staging directory it
        # renames in as one unit: a journal without a readable manifest is
        # a crash before any live file was touched. Nothing to restore.
        shutil.rmtree(journal)
        _fsync_dir(_journal_parent(project_root))
        return []
    _transaction_id, entries = _manifest_entries(manifest)

    for entry in entries:
        if _escapes_root(project_root, entry["path"]):
            raise JournalCorrupt(
                f"journal path {entry['path']!r} resolves outside the project root"
            )
        if os.path.isdir(_live_path(project_root, entry["path"])):
            raise JournalCorrupt(
                f"journal path {entry['path']!r} is a directory on disk, not a file"
            )

    originals: dict[int, bytes] = {}
    for index, entry in enumerate(entries):
        if not entry["existed"]:
            continue
        data = _read_orig(journal, index)
        if data is None:
            raise JournalCorrupt(
                f"journal is missing the stored original for {entry['path']!r}"
            )
        if _sha256(data) != entry["original_sha256"]:
            raise JournalCorrupt(
                f"stored original for {entry['path']!r} does not match its recorded hash"
            )
        originals[index] = data

    restored: list[str] = []
    synced: set[str] = set()
    for index, entry in enumerate(entries):
        live = _live_path(project_root, entry["path"])
        if entry["existed"]:
            if _read_if_file(live) == originals[index]:
                continue
            _atomic_write_bytes(live, originals[index])
        else:
            if not os.path.lexists(live):
                # lexists, not exists: a dangling symlink at a path that
                # did not exist before the save IS live state (it follows
                # to nothing, so exists() calls it absent), and it must
                # not survive to start resolving when its target appears.
                continue
            os.remove(live)
        restored.append(entry["path"])
        # Durable before the safety net goes: the journal is removed at the
        # end of this run, so every directory a restore landed in is fsynced
        # first (each one once) -- a restore that reverted on power loss
        # with the journal gone is the exact half-applied save again.
        parent = os.path.dirname(live)
        if parent not in synced:
            _fsync_dir(parent)
            synced.add(parent)

    shutil.rmtree(journal)
    _fsync_dir(_journal_parent(project_root))
    return restored


def _validate_entries(project_root: str, entries: Sequence[Entry]) -> None:
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        if not _is_safe_relpath(entry.path):
            raise ValueError(f"unusable entry path: {entry.path!r}")
        if _escapes_root(project_root, entry.path):
            raise ValueError(
                f"entry path {entry.path!r} resolves outside the project root"
            )
        key = tuple(entry.path.split("/"))
        if key in seen:
            raise ValueError(f"duplicate entry path: {entry.path!r}")
        seen.add(key)
