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

The phase model: a transaction moves STAGING (a temp sibling of the
journal; nothing of it is visible) -> ARMED (one rename makes the journal
visible; the parent is fsynced, and the project root too when ``.refdes``
was created there) -> DISARMED (the manifest is durably removed; from
this point the journal is inert) -> GC (the backups are deleted and the
parent fsynced). ``complete`` and ``recover`` take a journal down through
the same ``_disarm_and_gc`` helper, and the disarm barrier (fsync the
journal dir after the manifest is gone) re-runs on every pass, so an
interrupted teardown can never leave a pass restoring live bytes from
backups it is about to delete.

Every live path, backup and manifest is classified with ``lstat`` before
it is read: the last component is never followed (a symlink is replaced
as a link, never read through; a fifo/socket/device is refused), and an
I/O error is never treated as "absent".

Documented limits: checks run before writes, so a *different* process
swapping a path component between a check and the write it guards is
outside the threat model (the caller serializes writers); ``begin``
publishes the journal before its final fsync and withdraws it when that
fsync fails, and a hard kill in the staging phase can leave a
``.editor-transaction-*`` sibling of the journal behind -- inert (not a
journal, invisible to pending/recover), and nothing cleans it. Windows
device-name and trailing-dot/space rules are enforced on every
platform, but nothing here is Windows-native tested: the Windows
behavior is a reading of the rules, not a verified one.

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
import stat
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass

JOURNAL_DIR = ".refdes/editor-transaction"

_MANIFEST_NAME = "manifest.json"
_ORIG_DIR_NAME = "orig"

# Returned by _read_manifest_raw for the inert state (manifest missing,
# or bytes that are not JSON at all). Distinct from every JSON value:
# a manifest that parses -- to null, a list, a number -- is a readable
# document saying something impossible, i.e. corruption, not a crash.
_NO_MANIFEST = object()

# Leaf comparison in path identity is case-folded on the platforms whose
# filesystems are (NTFS default, APFS default): there, "A" and "a" are
# one file, and a save listing both is a save that writes one file twice.
_CASE_INSENSITIVE = os.name == "nt" or sys.platform == "darwin"

# Windows reserves these stems -- with an extension included, and as a
# directory name -- and silently drops trailing dots/spaces. These names
# are valid POSIX filenames that become unwriteable or mangled when a
# project moves to Windows, so they are refused on every platform
# (conservative; the module is not Windows-native tested).
_WINDOWS_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(10)]
    + [f"LPT{i}" for i in range(10)]
)

_HEX_DIGITS = frozenset("0123456789abcdef")


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


def _journal_parent_escapes_root(project_root: str) -> bool:
    """True when ``<root>/.refdes`` resolves outside the resolved root.

    The confinement test recover runs BEFORE it mutates anything: the
    journal path itself may be the symlink (a dangling one is the
    squatter recover removes), and realpath of the root does not
    resolve a symlinked ``.refdes`` component -- only resolving the
    parent does. Removing the journal path itself is then safe:
    ``os.remove`` acts on the final component, never its target chain.
    """
    root_real = os.path.realpath(project_root)
    parent = os.path.dirname(_journal_path(root_real))
    real = os.path.realpath(parent)
    try:
        return os.path.commonpath([root_real, real]) != root_real
    except ValueError:
        return True


def _points_into_journal(path: str) -> bool:
    """True when a project-relative path is the journal directory or
    anything under it -- an entry writing journal state as part of a
    save. Segments are compared after the strict-path check, which has
    already removed every lexical spelling trick (``.``, empty, ``..``).
    """
    parts = JOURNAL_DIR.split("/")
    segments = path.split("/")
    return segments[: len(parts)] == parts


def _is_safe_relpath(path: str) -> bool:
    """Project-relative and free of anything that makes two spellings name
    one file: no ``..``, ``.``, empty segments (which covers trailing
    slashes and ``a//b``), absolute form, backslash, colon, NUL (legal on
    POSIX, fatal at byte 0 of every syscall), and no Windows-mangled
    segment: trailing dot/space (silently dropped there), or a stem on
    the reserved-device list (unwriteable there, extension included).
    """
    if not path:
        return False
    if "\0" in path or "\\" in path or ":" in path:
        return False
    if posixpath.isabs(path) or ntpath.isabs(path):
        return False
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return False
        if segment.endswith((".", " ")):
            return False
        if segment.split(".")[0].upper() in _WINDOWS_RESERVED_STEMS:
            return False
    return True


def _is_sha256(value: object) -> bool:
    """A 64-lowercase-hex string: the parser's job is to guarantee every
    recorded hash is a hash, because the bytes recover restores are
    verified against exactly these strings."""
    return isinstance(value, str) and len(value) == 64 and _HEX_DIGITS.issuperset(value)


def _namespace_problems(project_root: str, paths: Sequence[str]) -> list[str]:
    """Reasons this set of project-relative paths cannot be one save.

    Spellings collapse onto filesystem reality in three ways the
    lexical checks cannot see:

    - alias: ``real/a`` and ``alias/a`` (``alias -> real``), or ``A``/``a``
      on a case-insensitive filesystem -- identity is (resolved parent,
      leaf), not the spelled string;
    - ancestor: ``a`` and ``a/b`` -- writing one destroys the other, and
      the crash state is unrecoverable;
    - control namespace: a path whose resolved location is ``.refdes``
      or under it, by alias included -- a save writing journal state.
    """
    root_real = os.path.realpath(project_root)
    refdes_real = os.path.realpath(os.path.join(root_real, ".refdes"))
    problems: list[str] = []
    identities: dict[tuple[str, str], str] = {}
    seen: list[tuple[str, str]] = []
    for path in paths:
        live = _live_path(root_real, path)
        leaf = os.path.basename(live)
        if _CASE_INSENSITIVE:
            leaf = leaf.casefold()
        key = (os.path.realpath(os.path.dirname(live)), leaf)
        first = identities.get(key)
        if first is not None:
            problems.append(f"paths {first!r} and {path!r} name the same file")
        identities[key] = path
        live_real = os.path.realpath(live)
        for other_real, other_path in seen:
            if live_real.startswith(other_real + os.sep):
                problems.append(f"path {path!r} is inside path {other_path!r}")
            elif other_real.startswith(live_real + os.sep):
                problems.append(f"path {other_path!r} is inside path {path!r}")
        seen.append((live_real, path))
        if live_real == refdes_real or live_real.startswith(refdes_real + os.sep):
            problems.append(f"path {path!r} lands inside the .refdes control directory")
    return problems


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
# and that is the platform-unsupported signal. On POSIX an EACCES here is
# a real durability failure, so PermissionError is swallowed on Windows
# only.
_FSYNC_DIR_OPEN_UNSUPPORTED: tuple[type[OSError], ...] = (IsADirectoryError,)
if os.name == "nt":
    _FSYNC_DIR_OPEN_UNSUPPORTED += (PermissionError,)
# Some filesystems refuse the fsync itself (e.g. network mounts). Those
# are the "platform does not support it" cases the contract allows to
# pass quietly; everything else is a real I/O error and must surface.
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


def _classify(path: str) -> str:
    """What IS at this path, judged with lstat -- the last component is
    never followed: ``"missing" | "file" | "symlink" | "directory" |
    "special" | "error:<os error>"``. An I/O error is its own answer,
    never "absent": acting on a path this function could not see is
    acting blind.
    """
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError as exc:
        return f"error:{exc}"
    kind = stat.S_IFMT(st.st_mode)
    if kind == stat.S_IFREG:
        return "file"
    if kind == stat.S_IFLNK:
        return "symlink"
    if kind == stat.S_IFDIR:
        return "directory"
    return "special"


def _read_bytes_strict(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _read_orig(journal: str, index: int, path: str) -> bytes:
    """The stored original for one entry: a REGULAR file inside a REAL
    directory of the journal (never a symlink to be read through, never
    a special file, and ``orig/`` itself judged too -- a symlinked
    ``orig/`` reads recovery data out of a directory the journal does
    not own), read, or a ``JournalCorrupt`` naming what it refuses.
    The journal's bytes are the recovery data; anything the journal did
    not write as a regular file is not recovery data."""
    orig_dir = os.path.join(journal, _ORIG_DIR_NAME)
    dir_kind = _classify(orig_dir)
    if dir_kind != "directory":
        raise JournalCorrupt(
            f"the journal's backup directory {orig_dir} is not a real "
            f"directory ({dir_kind}); refusing to read recovery data through it"
        )
    backup = os.path.join(orig_dir, f"{index}.bin")
    kind = _classify(backup)
    if kind == "missing":
        raise JournalCorrupt(f"journal is missing the stored original for {path!r}")
    if kind != "file":
        raise JournalCorrupt(
            f"stored original for {path!r} is not a regular file ({kind}); "
            "refusing to read through it"
        )
    try:
        return _read_bytes_strict(backup)
    except OSError as exc:
        raise JournalCorrupt(
            f"stored original for {path!r} cannot be read ({exc}); "
            "refusing to restore bytes that cannot be verified"
        ) from exc


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def _read_manifest_raw(journal: str) -> object:
    """The parsed manifest (any JSON value); ``_NO_MANIFEST`` when it is
    MISSING.

    Missing is the inert state: begin() writes manifest.json last, from
    a staging directory it renames in as one unit, so a visible journal
    without one is a crash before any live file was touched, and recover
    removes it. An UNPARSEABLE manifest is the opposite: a complete file
    published atomically cannot truncate, so bytes that do not parse are
    damage -- like an UNREADABLE manifest it says nothing about whether
    begin() completed, and deleting the journal there would discard the
    only rollback copy while replacement bytes are live. Both raise
    JournalCorrupt naming the path. (UnicodeDecodeError is a ValueError;
    JSONDecodeError too.)
    """
    manifest_path = os.path.join(journal, _MANIFEST_NAME)
    kind = _classify(manifest_path)
    if kind == "missing":
        return _NO_MANIFEST
    if kind != "file":
        raise JournalCorrupt(
            f"journal manifest at {manifest_path} is not a regular file "
            f"({kind}); refusing to read through it"
        )
    try:
        data = _read_bytes_strict(manifest_path)
    except OSError as exc:
        raise JournalCorrupt(
            f"journal manifest at {manifest_path} cannot be read ({exc}); "
            f"refusing to judge the journal without it"
        ) from exc
    try:
        return json.loads(data)
    except ValueError as exc:
        raise JournalCorrupt(
            f"journal manifest at {manifest_path} is not valid JSON ({exc}); "
            "begin() publishes it atomically and complete() deletes it "
            "first, so a visible journal whose manifest does not parse is "
            "damage, not a crash inside begin: refusing to clear it"
        ) from exc


def _manifest_entries(manifest: object, project_root: str) -> tuple[str, list[dict]]:
    """Validate the parsed manifest's shape; JournalCorrupt on garbage.

    A parseable manifest means ``begin`` completed (it is the last thing
    written), so structural garbage here is corruption, not a mid-begin
    crash -- and an entry we cannot read, cannot verify (a malformed
    hash), cannot name (unsafe path), cannot place (alias of another
    entry, ancestor of one, inside ``.refdes``), cannot order (a path
    twice) is an entry recovery must refuse before touching anything.
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
        if _points_into_journal(path):
            raise JournalCorrupt(
                f"journal entry path {path!r} writes inside the journal directory"
            )
        key = tuple(path.split("/"))
        if key in seen:
            raise JournalCorrupt(f"journal manifest lists the path {path!r} twice")
        seen.add(key)
        if not _is_sha256(replacement_sha):
            raise JournalCorrupt(
                f"journal entry for {path!r} has a malformed replacement hash"
            )
        if existed:
            if not _is_sha256(original_sha):
                raise JournalCorrupt(
                    f"journal entry for {path!r} has no valid recorded original hash"
                )
        elif original_sha is not None:
            raise JournalCorrupt(
                f"journal entry for {path!r} records an original hash for a "
                "file that did not exist"
            )
        normalized.append(
            {
                "path": path,
                "existed": existed,
                "original_sha256": original_sha,
                "replacement_sha256": replacement_sha,
            }
        )
    problems = _namespace_problems(project_root, [entry["path"] for entry in normalized])
    if problems:
        raise JournalCorrupt(f"journal manifest is untrustworthy: {problems[0]}")
    return transaction_id, normalized


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def begin(project_root: str, entries: Sequence[Entry]) -> str:
    """Record a save's originals in a fresh journal; return the transaction id.

    Raises ``JournalPending`` if a journal already exists (nothing is
    created), ``ValueError`` for unusable entry paths (absolute, ``..``,
    NUL, a Windows device name or trailing dot/space, backslash, colon,
    empty, duplicated, aliased onto another entry, an ancestor of
    another entry, landing inside ``.refdes``, resolving outside the
    root via a symlink, pointing inside the journal directory) -- also
    with nothing created. If the final durability fsync fails after the
    journal's visible rename, the just-created journal (no live file
    touched, no id returned) is removed before the failure propagates:
    a failed begin leaves nothing behind.
    """
    _validate_entries(project_root, entries)
    journal = _journal_path(project_root)
    if os.path.islink(journal):
        # A symlink AT the journal path: begin never follows it. When
        # its parent resolves inside the root it is a squatter recover
        # removes -- report it as the pending journal it blocks saves
        # as, not as a location escape. Under a `.refdes` that resolves
        # outside the root it is exactly that: refused.
        if _journal_parent_escapes_root(project_root):
            raise ValueError(
                "the journal location (.refdes) resolves outside the project root"
            )
        raise JournalPending(pending(project_root) or "unknown")
    if _journal_escapes_root(project_root):
        raise ValueError(
            "the journal location (.refdes) resolves outside the project root"
        )
    if os.path.lexists(journal):
        raise JournalPending(pending(project_root) or "unknown")

    transaction_id = _new_transaction_id()
    journal_parent = _journal_parent(project_root)
    parent_existed = os.path.isdir(journal_parent)
    os.makedirs(journal_parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".editor-transaction-", dir=journal_parent)
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
        # parent so the rename that made the journal visible survives --
        # and when begin created `.refdes` itself, fsync the project
        # root first, so the new directory's own existence survives.
        try:
            if not parent_existed:
                _fsync_dir(os.path.dirname(journal_parent))
            _fsync_dir(journal_parent)
        except BaseException:
            # The journal is ours, live files are untouched, and no
            # transaction id has been returned: withdraw it, so a failed
            # begin leaves the state it promises -- nothing created.
            shutil.rmtree(journal, ignore_errors=True)
            raise
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
    if not os.path.lexists(journal):
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


def _disarm_and_gc(project_root: str) -> None:
    """Take a journal down: DISARM (manifest removed, then the journal
    directory fsynced -- from here the journal is inert, so a crash
    cannot arm a later recover against a save that completed), then GC
    (the backups and directory deleted), then fsync ``.refdes`` so the
    removal survives.

    The disarm barrier is NOT skipped on a pass that finds the manifest
    already gone (the previous pass died right there): fsyncing the
    journal directory after the disarm, before the GC deletes the
    backups, is the point of the ordering -- re-running it is always
    safe, skipping it is not.
    """
    journal = _journal_path(project_root)
    manifest = os.path.join(journal, _MANIFEST_NAME)
    try:
        os.remove(manifest)
    except FileNotFoundError:
        if not os.path.isdir(journal):
            return  # no journal at all: the idempotent no-op
    except OSError as exc:
        raise OSError(
            f"journal manifest in {journal} could not be removed: {exc}"
        ) from exc
    _fsync_dir(journal)
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


def _fsync_directory_chain(path: str, root_real: str, synced: set[str]) -> None:
    """fsync ``path`` and every parent directory up to the resolved root,
    leaf first, each directory at most once per run (one ``synced`` set
    for the whole run). The walk stops at the first directory already
    synced: its own chain walk synced its ancestors. A chain node that
    is a symlink is fsynced through the link (``os.open`` follows it to
    the real directory -- the directory a restored file's bytes
    actually live in; the link's own parent is in the chain, so the
    link's existence is durable too) and counted as processed. A node
    that is neither a directory nor a symlink (never created: no live
    state, nothing to make durable; a special file: not openable as a
    directory) is counted as processed and not fsynced. An I/O error
    classifying a node PROPAGATES: a barrier that cannot see the
    directory it must fsync cannot promise durability.
    """
    chain: list[str] = []
    current = path
    while True:
        if current in synced:
            break
        chain.append(current)
        if os.path.realpath(current) == root_real:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    for directory in chain:
        synced.add(directory)
        kind = _classify(directory)
        if kind.startswith("error:"):
            raise OSError(f"cannot inspect directory {directory} for fsync: {kind[6:]}")
        if kind in ("directory", "symlink"):
            _fsync_dir(directory)


def complete(project_root: str) -> None:
    """Remove the journal after a successful save: DISARM then GC.

    The manifest is deleted first, and that is the step whose failure
    this must not swallow: a journal directory without a readable
    manifest is inert (``recover`` removes it as a crashed begin), so
    once the manifest is gone a completed save can never be undone by
    leftover directory debris. A failed *manifest* delete therefore
    raises -- the journal is still armed, and the caller has to know.
    The directory is then always cleared, inert debris (no manifest)
    included: a leftover journal directory would keep
    ``refuse_if_pending`` blocking projects whose saves succeeded, and
    a directory that outlives ``complete`` raises too, pointing at
    ``recover``, which clears it.
    """
    if _journal_escapes_root(project_root):
        raise OSError(
            f"the journal location {_journal_path(os.path.realpath(project_root))} "
            "resolves outside the project root; refusing to delete through it. "
            "Remove the symlink, then run 'refdes recover'."
        )
    _disarm_and_gc(project_root)


def recover(project_root: str) -> list[str]:
    """Restore every journaled original; return the paths whose live state
    actually changed, in manifest order.

    Refuses (``JournalCorrupt``, changing nothing, journal kept) when the
    manifest names an unsafe path, lists one path twice, names one file
    twice through a symlink alias, names an ancestor of another
    journaled path, lands inside ``.refdes``, names the journal
    directory itself, resolves outside the root, stores a manifest that
    is a symlink/special file, cannot be read, does not parse (begin
    publishes it atomically, last: that shape is damage, not a crash
    inside begin), parses to a non-object value, records a malformed
    hash, or contradicts itself (a hash for a file that never
    existed); and, before touching anything, when a stored original is
    missing, unreadable, not a regular file, does not match its recorded
    hash, when a journaled path is a directory or a special file on
    disk, when a journaled file's live bytes match neither the recorded
    replacement hash nor (for a file that existed) the recorded original
    hash, or when a journaled file is missing on disk while the manifest
    records that it existed. Confinement runs before anything is
    mutated. The live parents
    of every journaled path are fsynced leaf-up to the root -- after the
    last write, and on every pass, a retry that restores nothing
    included -- before the journal is taken down (DISARM, barrier, GC).
    Restored files get the process's default permissions: the journal
    stores bytes and their hashes, not modes -- bytes are the contract.
    A squatter on the journal path (file, symlink -- to a directory
    included, dangling link included) is removed as the squatter it is,
    THE LINK ITSELF and never its target, when its parent resolves
    inside the root, and reported. Leaves the journal in place on any
    failure, so running it again is safe.
    """
    journal = _journal_path(project_root)
    # Confinement BEFORE anything that mutates, and it resolves the
    # PARENT: realpath(root) does not resolve a symlinked .refdes, and
    # removing through one deletes outside the root. A squatter is
    # removable only when its parent resolves inside the real root.
    if _journal_parent_escapes_root(project_root):
        raise JournalCorrupt(
            "the journal location (.refdes) resolves outside the project "
            "root; refusing to restore through the symlink"
        )
    if os.path.lexists(journal) and (os.path.islink(journal) or not os.path.isdir(journal)):
        # A squatter on the journal path (plain file, dangling symlink,
        # symlink to a directory) wedges the project: pending() reports
        # "unknown", begin refuses, and a refusal regime here is
        # permanent -- so recover must clear it. The link/file ITSELF is
        # removed, never followed, and the parent is confined (checked
        # above), so nothing outside the root is touched even when the
        # squatter is a symlink pointing out: os.remove acts on the
        # final component, never its target chain.
        journal_real = _journal_path(os.path.realpath(project_root))
        os.remove(journal_real)
        _fsync_dir(os.path.dirname(journal_real))
        return [JOURNAL_DIR]
    if not os.path.isdir(journal):
        return []
    manifest = _read_manifest_raw(journal)
    if manifest is _NO_MANIFEST:
        # begin() writes manifest.json last, from a staging directory it
        # renames in as one unit: a journal without a manifest (or whose
        # bytes are not JSON at all) is a crash before any live file was
        # touched. A manifest that PARSES -- to null, a list, anything
        # non-object -- is a readable document saying something
        # impossible, i.e. corruption: JournalCorrupt, journal kept.
        _disarm_and_gc(project_root)
        return []
    _transaction_id, entries = _manifest_entries(manifest, project_root)

    for entry in entries:
        if _escapes_root(project_root, entry["path"]):
            raise JournalCorrupt(
                f"journal path {entry['path']!r} resolves outside the project root"
            )
        kind = _classify(_live_path(project_root, entry["path"]))
        if kind == "directory":
            raise JournalCorrupt(
                f"journal path {entry['path']!r} is a directory on disk, not a file"
            )
        if kind == "special":
            raise JournalCorrupt(
                f"journal path {entry['path']!r} is a special file on disk "
                "(fifo, socket, device): not a file the save wrote, and not "
                "a file a plain-file restore can safely replace"
            )
        if kind.startswith("error:"):
            raise OSError(f"cannot inspect journal path {entry['path']!r}: {kind[6:]}")

    # Verify the live state against the recorded hashes BEFORE restoring
    # anything: a live file matching neither hash (or missing where the
    # journal records a replacement) changed outside the transaction, and
    # restoring the original over it is the overwrite the docs promise to
    # refuse. A symlink is not hashed (reading follows it; the restore
    # swaps the link itself, never the target) and stays the shape the
    # restore pass below already governs.
    for entry in entries:
        live = _live_path(project_root, entry["path"])
        kind = _classify(live)
        if kind == "missing":
            if entry["existed"]:
                raise JournalCorrupt(
                    f"the live file {entry['path']!r} is missing: the journal "
                    "records a replacement that is not on disk, and "
                    "restoring the original into unexplained absence is the "
                    "overwrite recover must refuse"
                )
            continue
        if kind != "file":
            continue
        try:
            live_sha = _sha256(_read_bytes_strict(live))
        except OSError as exc:
            raise JournalCorrupt(
                f"the live file {entry['path']!r} cannot be read ({exc}): "
                "recover cannot verify it against the journal"
            ) from exc
        if live_sha == entry["replacement_sha256"]:
            continue
        if entry["existed"] and live_sha == entry["original_sha256"]:
            continue  # the replacement never landed: restore is a no-op
        raise JournalCorrupt(
            f"the live file {entry['path']!r} matches neither the recorded "
            "replacement nor the recorded original: it changed outside the "
            "transaction, so recover refuses to overwrite it (journal kept)"
        )

    originals: dict[int, bytes] = {}
    for index, entry in enumerate(entries):
        if not entry["existed"]:
            continue
        data = _read_orig(journal, index, entry["path"])
        if _sha256(data) != entry["original_sha256"]:
            raise JournalCorrupt(
                f"stored original for {entry['path']!r} does not match its recorded hash"
            )
        originals[index] = data

    restored: list[str] = []
    for index, entry in enumerate(entries):
        live = _live_path(project_root, entry["path"])
        if entry["existed"]:
            kind = _classify(live)
            if kind.startswith("error:"):
                raise OSError(f"cannot inspect {entry['path']!r}: {kind[6:]}")
            # lstat, not open: an equality check that follows the final
            # symlink reads the TARGET's bytes and pronounces a link
            # "already restored", leaving the project's file silently
            # redirected. Only a regular file AT the path is the file.
            if kind == "file" and _read_bytes_strict(live) == originals[index]:
                continue
            _atomic_write_bytes(live, originals[index])
        else:
            kind = _classify(live)
            if kind == "missing":
                continue
            if kind.startswith("error:"):
                raise OSError(f"cannot inspect {entry['path']!r}: {kind[6:]}")
            # "missing", not "not exists": a dangling symlink at a path
            # that did not exist before the save IS live state (it
            # follows to nothing, so exists() calls it absent), and it
            # must not survive to start resolving when its target
            # appears.
            os.remove(live)
        restored.append(entry["path"])

    # Durable before the safety net goes: fsync every directory a
    # journaled path lives in, leaf up to the root, AFTER the last
    # write -- a directory fsync makes durable the changes made before
    # it, so the barrier belongs after the loop, over every entry
    # (entries whose bytes already matched, or whose file is absent,
    # included: a previous pass restored those bytes and its barrier
    # may be the one that failed). A directory the restore's makedirs
    # created is itself durable only once its own parent is fsynced, so
    # the chain runs to the root; the journal is removed at the end of
    # this run, and a chain that reverted on power loss is the exact
    # half-applied save again.
    root_real = os.path.realpath(project_root)
    synced: set[str] = set()
    for entry in entries:
        _fsync_directory_chain(
            os.path.dirname(_live_path(project_root, entry["path"])), root_real, synced
        )
    _disarm_and_gc(project_root)
    return restored


def _validate_entries(project_root: str, entries: Sequence[Entry]) -> None:
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        if not _is_safe_relpath(entry.path):
            raise ValueError(f"unusable entry path: {entry.path!r}")
        if _points_into_journal(entry.path):
            raise ValueError(
                f"entry path {entry.path!r} writes inside the journal directory"
            )
        if _escapes_root(project_root, entry.path):
            raise ValueError(
                f"entry path {entry.path!r} resolves outside the project root"
            )
        key = tuple(entry.path.split("/"))
        if key in seen:
            raise ValueError(f"duplicate entry path: {entry.path!r}")
        seen.add(key)
    problems = _namespace_problems(project_root, [entry.path for entry in entries])
    if problems:
        raise ValueError(f"unusable entry paths: {problems[0]}")
