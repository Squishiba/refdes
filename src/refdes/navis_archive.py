"""The Navis archive store (in-prog-logs/navis-design-20261025.md §6, §8, §12).

Removal is archival (§2.2): archiving a Navi writes one compressed record
under `.refdes/navis/` named by the Navi's key, and the marker stops
linking -- the record is the archive, the marker in the body is the
pointer. Restore deletes the record (§9); the marker, if it is still there,
is active again with its *current* text.

The §7.3 hard invariant is the module's whole design: archive/restore
write only under `.refdes/navis/` -- no item file byte changes, no hash,
seal, or history content touched. That is why the record is a snapshot of
the text (taken at archive time, never refreshed) and the marker's live
position comes from the scan, not from the record (§9: "the scan is the
live truth; the record's item_key/source are a snapshot for display").

Posture, shared with the project's other store writers:

* **One lock per store write**, the same `project_write_lock` every
  existing writer takes (`write_lock.py`) -- reentrant, so a CLI command
  that already holds it (cli.py's writable-command wrapper) is fine.
* **Atomic writes**: temp file + `os.replace`, so a crash mid-write leaves
  the previous record intact and never a half-written YAML.
* **Journal (§12)**: an armed editor transaction
  (`.refdes/editor-transaction/`) means refuse -- the store writer raises
  `JournalPending`; the CLI gate is the one every command passes
  (`cli._refuse_pending_journal`).
* **Reads never raise**: a corrupt, truncated, foreign-format, or
  key-lying record is a `navis.archive_corrupt` Diagnostic naming its
  file; the rest of the store loads. A build must never die on one bad
  gzip, and a silent skip must never swallow a Navi.
"""

from __future__ import annotations

import gzip
import os
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

import yaml

from . import keys as keys_mod
from .editor_journal import JOURNAL_DIR, pending
from .model import Diagnostic
from .write_lock import project_write_lock

ARCHIVE_FORMAT = 1
STORE_DIRNAME = "navis"
RECORD_SUFFIX = ".yaml.gz"

NAVI_ARCHIVE_CORRUPT_CODE = "navis.archive_corrupt"
NAVI_ARCHIVED_ORPHAN_CODE = "navis.archived_orphan"


class NavisArchiveError(Exception):
    """A store write the caller has to hear about (bad key grammar, an
    unwritable store). The CLI prints it and exits; it never half-writes."""


class JournalPending(NavisArchiveError):
    """§12: `.refdes/editor-transaction/` exists, so the editor's save
    protocol owns the tree right now -- the store refuses to write."""


@dataclass
class NaviRecord:
    """One archive record as loaded from disk. `path` is the record file,
    which is where a diagnostic about it is attached (§9: the orphan
    warning sits "at the record's stored file")."""

    navi_key: str
    item_key: str
    text: str
    archived_at: str
    source: dict
    path: str = field(default="")


def store_dir(root: str) -> str:
    return os.path.join(root, ".refdes", STORE_DIRNAME)


def record_path(root: str, navi_key: str) -> str:
    return os.path.join(store_dir(root), f"{navi_key}{RECORD_SUFFIX}")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_doc(record: NaviRecord) -> dict:
    # Key order is the design's (§6): format, identity, snapshot, stamp.
    return {
        "archive_format": ARCHIVE_FORMAT,
        "navi_key": record.navi_key,
        "item_key": record.item_key,
        "source": dict(record.source),
        "text": record.text,
        "archived_at": record.archived_at,
    }


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------


def _corrupt(path: str, message: str, root: str = "") -> Diagnostic:
    return Diagnostic(
        level="warning",
        message=f"{NAVI_ARCHIVE_CORRUPT_CODE}: navis archive record is "
        f"unreadable ({message}) -- it is "
        "skipped, not deleted; the rest of the store loads",
        file=(
            os.path.relpath(path, root).replace("\\", "/") if root else path
        ),
        code=NAVI_ARCHIVE_CORRUPT_CODE,
    )


def _parse_record(
    path: str, name: str, root: str = ""
) -> tuple[NaviRecord | None, list[Diagnostic]]:
    """One record file, adversarially. Never raises: every failure is a
    diagnostic naming the file, so one bad gzip cannot kill a build or
    hide the good records (§9's posture, the seal-verify precedent)."""
    stem = name.removesuffix(RECORD_SUFFIX)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return None, [
            _corrupt(path, f"it cannot be read: {exc.strerror or exc}", root)
        ]
    try:
        data = gzip.decompress(raw)
    except (OSError, EOFError, zlib.error):
        return None, [
            _corrupt(
                path,
                "the file is not readable as gzip (truncated, corrupt, "
                "or never compressed)",
                root,
            )
        ]
    if not data.strip():
        return None, [_corrupt(path, "the compressed file is empty", root)]
    try:
        doc = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        detail = (
            str(exc).splitlines()[0]
            if isinstance(exc, yaml.YAMLError)
            else "the bytes are not UTF-8"
        )
        return None, [
            _corrupt(path, f"the YAML does not parse: {detail}", root)
        ]
    if not isinstance(doc, dict):
        return None, [_corrupt(path, "the YAML is not a mapping", root)]
    version = doc.get("archive_format")
    if version != ARCHIVE_FORMAT:
        return None, [
            _corrupt(
                path,
                f"archive_format {version!r} is not this version's "
                f"{ARCHIVE_FORMAT} (a future refdes wrote it, or the file "
                "is damaged)",
                root,
            )
        ]
    navi_key = doc.get("navi_key")
    if not isinstance(navi_key, str) or keys_mod.malformed_key_message(navi_key):
        reason = (
            "navi_key is missing or not a string"
            if not isinstance(navi_key, str)
            # the key's own grammar message, not the record-file message
            else keys_mod.malformed_key_message(navi_key).split(". A key")[0]
        )
        return None, [_corrupt(path, str(reason), root)]
    if stem != navi_key:
        # The filename is the key (§6). A record that lies about which
        # Navi it archives cannot be honoured -- archiving by a key that
        # is not its own name would silently archive the wrong Navi.
        return None, [
            _corrupt(
                path,
                f"the file names Navi {stem!r} but records {navi_key!r} "
                "inside -- not its own key",
                root,
            )
        ]
    text = doc.get("text")
    if not isinstance(text, str):
        return None, [
            _corrupt(path, "the `text` snapshot is missing", root)
        ]
    source = doc.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("file"), str)
        or not isinstance(source.get("line"), int)
    ):
        return None, [
            _corrupt(
                path,
                "the `source` snapshot is missing (needs file: and line:)",
                root,
            )
        ]
    item_key = doc.get("item_key")
    archived_at = doc.get("archived_at")
    return (
        NaviRecord(
            navi_key=navi_key,
            item_key=item_key if isinstance(item_key, str) else "",
            text=text,
            archived_at=archived_at if isinstance(archived_at, str) else "",
            source={"file": source["file"], "line": source["line"]},
            path=path,
        ),
        [],
    )


def load_records(root: str) -> tuple[list[NaviRecord], list[Diagnostic]]:
    """Every readable record in `.refdes/navis/`, plus a diagnostic per
    unreadable one. The store's absence is healthy (nothing archived
    yet). Never raises: a store the current build cannot read is a
    warning, not a dead project -- and never a silent loss of what it
    *can* read."""
    directory = store_dir(root)
    try:
        entries = sorted(os.listdir(directory))
    except FileNotFoundError:
        return [], []
    except NotADirectoryError:
        return [], [
            _corrupt(
                directory,
                "not a directory -- the archive store path is occupied "
                "by a file",
            )
        ]
    except OSError as exc:
        return [], [
            _corrupt(directory, f"it cannot be listed: {exc.strerror or exc}")
        ]
    records: list[NaviRecord] = []
    diagnostics: list[Diagnostic] = []
    for name in entries:
        if name.startswith("."):
            # The writer's own temp files (`.<pid>...tmp`); a crash
            # mid-write leaves at most one, and it is not a record.
            continue
        path = os.path.join(directory, name)
        if not name.endswith(RECORD_SUFFIX):
            diagnostics.append(
                _corrupt(
                    path,
                    f"not a {RECORD_SUFFIX} archive record (stray file in "
                    "the store)",
                )
            )
            continue
        record, diags = _parse_record(path, name, root)
        diagnostics.extend(diags)
        if record is not None:
            records.append(record)
    return records, diagnostics


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def _refuse_journal(root: str) -> None:
    journal = pending(root)
    if journal is not None:
        raise JournalPending(
            f"an editor transaction is in flight ({journal}); navis "
            "archive/restore refuse to write while "
            f"{JOURNAL_DIR} exists (design §12)"
        )


def archive_record(
    root: str,
    *,
    navi_key: str,
    item_key: str,
    source: dict,
    text: str,
) -> tuple[bool, NaviRecord]:
    """Write the record for one Navi (design §6). Returns
    ``(created, record)`` -- a second archive of the same key is a no-op
    that reports the existing record (the snapshot is taken once, at
    archive time; §9's edited-while-archived state says the archive is
    never re-stamped)."""
    reason = keys_mod.malformed_key_message(navi_key)
    if reason:
        raise NavisArchiveError(f"navi key {navi_key!r} is not archivable: {reason}")
    _refuse_journal(root)
    with project_write_lock(root):
        path = record_path(root, navi_key)
        existing, _ = _parse_record(path, os.path.basename(path), root)
        if existing is not None:
            return False, existing
        record = NaviRecord(
            navi_key=navi_key,
            item_key=item_key,
            text=text,
            archived_at=_utc_now(),
            source={"file": source["file"], "line": source["line"]},
            path=path,
        )
        # Atomic: write the whole gzip to a temp in the store dir, then
        # os.replace (same filesystem, rename-atomic). A kill anywhere in
        # here leaves the old state (no file, or the old record) intact.
        os.makedirs(store_dir(root), exist_ok=True)
        tmp = os.path.join(
            store_dir(root), f".{os.getpid()}.{navi_key}.yaml.gz.tmp"
        )
        payload = gzip.compress(
            yaml.safe_dump(
                _record_doc(record), allow_unicode=True, sort_keys=False
            ).encode("utf-8"),
            mtime=0,
        )
        try:
            with open(tmp, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        record.path = path
        return True, record


def restore_record(root: str, navi_key: str) -> bool:
    """Delete the record (design §9: restore is the record's removal; the
    marker -- if the scan still finds it -- is active again). Returns
    whether a record was there. Atomic: a single unlink under the lock;
    a crash leaves the record present (restore is a no-op retry)."""
    reason = keys_mod.malformed_key_message(navi_key)
    if reason:
        raise NavisArchiveError(f"navi key {navi_key!r} is not restorable: {reason}")
    _refuse_journal(root)
    with project_write_lock(root):
        path = record_path(root, navi_key)
        try:
            os.unlink(path)
        except FileNotFoundError:
            return False
        return True
