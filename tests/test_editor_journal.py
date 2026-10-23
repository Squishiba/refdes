"""EDITOR-JOURNAL-1: blind tests for the standalone editor-save journal module.

The module under test is ``refdes/editor_journal.py`` (new; not present on the
base tree), so every functional test imports it lazily through ``_ej()`` and
fails on base with ImportError. The three ``test_control_*`` tests import
nothing from it and must already pass on base -- they lock the contract's
scope rule that this task wires NOTHING into ``serve/edit.py`` or ``cli.py``,
and that the new module (if present) stays stdlib-only.

Tests encode the contract: journal at ``.refdes/editor-transaction``,
manifest.json last via temp+replace, originals under ``orig/``, begin is
all-or-nothing, recover verifies every stored original against its recorded
sha256 BEFORE touching any live file, reports only changed paths, removes the
journal only after a complete restore, and treats a missing/garbled manifest as
a crashed begin (journal removed, ``[]``).

The manifest's *entry field names* (path/existed/original_sha256/
replacement_sha256) and the ``orig/`` subdirectory are contract-mandated, so
tests read them directly. The transaction-id key name, the entry-list key name,
and the per-file names inside ``orig/`` are implementation choices, so tests
find the entry list by structure and search the raw manifest bytes for the id.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Contract-mandated layout: JOURNAL_DIR and its manifest filename.
JOURNAL_REL = Path(".refdes") / "editor-transaction"
MANIFEST_NAME = "manifest.json"


def _ej():
    from refdes import editor_journal

    return editor_journal


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _journal(root: Path) -> Path:
    return root / JOURNAL_REL


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _read(root: Path, rel: str) -> bytes:
    return (root / rel).read_bytes()


def _read_manifest(root: Path) -> dict:
    return json.loads((_journal(root) / MANIFEST_NAME).read_bytes())


def _find_entry_list(node):
    """Locate the manifest's entry list without assuming its key name."""
    if (
        isinstance(node, list)
        and node
        and all(isinstance(item, dict) for item in node)
        and all("path" in item for item in node)
    ):
        return node
    if isinstance(node, list):
        for item in node:
            found = _find_entry_list(item)
            if found is not None:
                return found
    if isinstance(node, dict):
        for value in node.values():
            found = _find_entry_list(value)
            if found is not None:
                return found
    return None


def _backup_files(root: Path) -> list[Path]:
    """Files under the contract-mandated ``orig/`` directory."""
    orig = _journal(root) / "orig"
    assert orig.is_dir(), "contract: originals live under <journal>/orig/"
    return sorted(p for p in orig.iterdir() if p.is_file())


def _all_journal_files(root: Path) -> list[Path]:
    return sorted(p for p in _journal(root).rglob("*") if p.is_file())


# ------------------------------------------------------------- shared fixtures

# A three-file save: two pre-existing files (replaced by the save) and one
# file the save creates (no original). Entry order == manifest order.
P1 = "src/main.c"
P2 = "notes/readme.txt"
P3 = "items/new.yaml"
OLD1, NEW1 = b"OLD MAIN\n", b"NEW MAIN\n"
OLD2, NEW2 = b"OLD NOTES\n", b"NEW NOTES\n"
NEW3 = b"NEW ITEM\n"


def _entries(ej):
    return [
        ej.Entry(P1, OLD1, NEW1),
        ej.Entry(P2, OLD2, NEW2),
        ej.Entry(P3, None, NEW3),
    ]


def _project(tmp_path: Path) -> str:
    """Project with the pre-existing files at their original bytes."""
    _write(tmp_path, P1, OLD1)
    _write(tmp_path, P2, OLD2)
    return str(tmp_path)


def _apply_save(root: Path, entries) -> None:
    """Simulate the editor replacing every destination with its replacement."""
    for entry in entries:
        _write(root, entry.path, entry.replacement)


# ------------------------------------------------------------------- controls


def test_control_serve_edit_has_no_journal_wiring():
    """Scope rule: this task must not touch the editor's save path (serve/edit.py)."""
    source = (REPO / "src" / "refdes" / "serve" / "edit.py").read_text(encoding="utf-8")
    assert "editor_journal" not in source
    assert "editor-transaction" not in source


def test_control_cli_has_no_journal_wiring():
    """Scope rule: this task must not touch cli.py (no `refdes recover` yet)."""
    source = (REPO / "src" / "refdes" / "cli.py").read_text(encoding="utf-8")
    assert "editor_journal" not in source


def test_control_module_is_stdlib_only():
    """The module, once it exists, imports only stdlib (plus refdes helpers).

    Vacuous pass on base (no module); a third-party import is a contract
    violation ("pure stdlib ... no new dependencies").
    """
    module = REPO / "src" / "refdes" / "editor_journal.py"
    if not module.exists():
        return
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: inside the refdes package
                continue
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names or top == "refdes", (
                f"editor_journal.py imports {name!r}, which is neither stdlib "
                "nor a refdes helper"
            )


# --------------------------------------------------------------- constants API


def test_journal_dir_constant():
    ej = _ej()
    assert ej.JOURNAL_DIR == ".refdes/editor-transaction"
    assert "\\" not in ej.JOURNAL_DIR
    assert not ej.JOURNAL_DIR.startswith("/")


def test_entry_is_frozen_dataclass_with_contract_fields():
    ej = _ej()
    entry = ej.Entry(path="a.txt", original=b"old", replacement=b"new")
    assert dataclasses.is_dataclass(entry)
    assert entry.path == "a.txt"
    assert entry.original == b"old"
    assert entry.replacement == b"new"
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.path = "b.txt"
    none_entry = ej.Entry(path="a.txt", original=None, replacement=b"new")
    assert none_entry.original is None


# ----------------------------------------------------------------------- begin


def test_begin_writes_manifest_and_originals_and_returns_id(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    tx = ej.begin(root, _entries(ej))
    assert isinstance(tx, str) and tx
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    assert manifest_path.is_file()
    assert tx.encode() in manifest_path.read_bytes(), (
        "manifest must record the transaction id (the one begin() returned)"
    )
    # the originals of the two pre-existing files are recoverable from the
    # journal (stored under orig/, per the contract)
    stored = b" ".join(p.read_bytes() for p in _backup_files(tmp_path))
    assert OLD1 in stored
    assert OLD2 in stored
    assert ej.pending(root) == tx


def test_begin_records_contract_manifest_fields(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    entries = _find_entry_list(_read_manifest(tmp_path))
    assert entries is not None, "manifest.json must hold a list of entry objects"
    assert [e["path"] for e in entries] == [P1, P2, P3]
    by_path = {e["path"]: e for e in entries}
    for path, existed, old, new in (
        (P1, True, OLD1, NEW1),
        (P2, True, OLD2, NEW2),
        (P3, False, None, NEW3),
    ):
        e = by_path[path]
        assert e["existed"] is existed
        expected_old = _sha(old) if old is not None else None
        assert e["original_sha256"] == expected_old, (
            f"original_sha256 for {path}: hex sha256 of the original bytes, "
            "null when the file did not exist"
        )
        assert e["replacement_sha256"] == _sha(new)


def test_begin_stores_no_replacement_bytes(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    blob = b"".join(p.read_bytes() for p in _all_journal_files(tmp_path))
    for replacement in (NEW1, NEW2, NEW3):
        assert replacement not in blob, (
            "replacements are recorded as a hash only; the live file is the "
            "replacement -- the journal must not copy it"
        )


def test_begin_returns_unique_ids_across_transactions(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    first = ej.begin(root, _entries(ej))
    ej.complete(root)
    second = ej.begin(root, _entries(ej))
    assert first != second


def test_second_begin_raises_journal_pending_naming_id(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    tx = ej.begin(root, _entries(ej))
    with pytest.raises(ej.JournalPending) as excinfo:
        ej.begin(root, _entries(ej))
    message = str(excinfo.value)
    assert tx in message
    assert "refdes recover" in message


def test_pending_begin_changes_nothing(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    before = manifest_path.read_bytes()
    with pytest.raises(ej.JournalPending):
        ej.begin(root, _entries(ej))
    assert manifest_path.read_bytes() == before


UNSAFE_PATHS = [
    ("absolute", "/etc/passwd"),
    ("drive", "C:/evil.txt"),
    ("backslash", "dir\\evil.txt"),
    ("colon", "a:b.txt"),
    ("dotdot-leading", "../evil.txt"),
    ("dotdot-inner", "a/../evil.txt"),
    ("dotdot-trailing", "a/.."),
    ("empty", ""),
]


@pytest.mark.parametrize(
    "path",
    [p for _, p in UNSAFE_PATHS],
    ids=[name for name, _ in UNSAFE_PATHS],
)
def test_begin_rejects_unsafe_paths(tmp_path, path):
    ej = _ej()
    root = _project(tmp_path)
    entries = [ej.Entry(P1, OLD1, NEW1), ej.Entry(path, None, b"X")]
    with pytest.raises(ValueError):
        ej.begin(root, entries)
    assert not _journal(tmp_path).exists()
    assert ej.pending(root) is None
    # no half-built journal directory (or temp sibling of it) is left behind
    leftovers = [
        p for p in tmp_path.rglob("*")
        if "editor-transaction" in p.name
    ]
    assert leftovers == []


def test_begin_rejects_duplicate_paths(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    entries = [
        ej.Entry("dup.txt", None, b"A"),
        ej.Entry("dup.txt", None, b"B"),
    ]
    with pytest.raises(ValueError):
        ej.begin(root, entries)
    assert not _journal(tmp_path).exists()


def test_begin_leaves_no_temporary_siblings(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    refdes_dir = tmp_path / ".refdes"
    assert sorted(p.name for p in refdes_dir.iterdir()) == ["editor-transaction"]
    ej.complete(root)
    if refdes_dir.exists():
        assert [p for p in refdes_dir.iterdir() if "editor-transaction" in p.name] == []


# ------------------------------------------------------- pending / refuse / complete


def test_pending_none_without_journal(tmp_path):
    ej = _ej()
    assert ej.pending(str(tmp_path)) is None


def test_pending_returns_transaction_id(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    tx = ej.begin(root, _entries(ej))
    assert ej.pending(root) == tx


def test_pending_unknown_when_manifest_missing(tmp_path):
    ej = _ej()
    _journal(tmp_path).mkdir(parents=True)
    assert ej.pending(str(tmp_path)) == "unknown"


def test_pending_unknown_when_manifest_unparseable(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    (_journal(tmp_path) / MANIFEST_NAME).write_bytes(b"{{{ not json")
    assert ej.pending(root) == "unknown"


def test_refuse_if_pending_raises_journal_pending(tmp_path):
    ej = _ej()
    ej.refuse_if_pending(str(tmp_path))  # no journal: no-op
    root = _project(tmp_path)
    tx = ej.begin(root, _entries(ej))
    with pytest.raises(ej.JournalPending) as excinfo:
        ej.refuse_if_pending(root)
    assert tx in str(excinfo.value)
    assert "refdes recover" in str(excinfo.value)


def test_refuse_if_pending_raises_even_over_garbled_manifest(tmp_path):
    ej = _ej()
    _journal(tmp_path).mkdir(parents=True)
    with pytest.raises(ej.JournalPending):
        ej.refuse_if_pending(str(tmp_path))


def test_complete_removes_journal(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    ej.complete(root)
    assert not _journal(tmp_path).exists()
    assert ej.pending(root) is None


def test_complete_is_idempotent(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.complete(root)  # missing journal: no-op
    ej.begin(root, _entries(ej))
    ej.complete(root)
    ej.complete(root)  # second removal is still a no-op
    assert not _journal(tmp_path).exists()


# --------------------------------------------------------------------- recover


def test_recover_without_journal_returns_empty(tmp_path):
    ej = _ej()
    assert ej.recover(str(tmp_path)) == []


def test_recover_full_crash_state_restores_everything(tmp_path):
    """Crash after every replacement: all originals come back, the new file
    is removed, the journal is removed, and the return is all paths in
    manifest order."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    restored = ej.recover(root)
    assert restored == [P1, P2, P3]
    assert _read(tmp_path, P1) == OLD1
    assert _read(tmp_path, P2) == OLD2
    assert not (tmp_path / P3).exists()
    assert not _journal(tmp_path).exists()


def test_recover_partial_crash_state_reports_only_changed(tmp_path):
    """Crash after replacing only the first file: it is restored, the
    untouched file is not reported, the never-created file stays absent."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _write(tmp_path, P1, NEW1)  # the save died after the first replacement
    restored = ej.recover(root)
    assert restored == [P1]
    assert _read(tmp_path, P1) == OLD1
    assert _read(tmp_path, P2) == OLD2
    assert not (tmp_path / P3).exists()
    assert not _journal(tmp_path).exists()


def test_recover_deletes_file_that_did_not_exist(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry(P3, None, NEW3)])
    _write(tmp_path, P3, NEW3)
    restored = ej.recover(root)
    assert restored == [P3]
    assert not (tmp_path / P3).exists()


def test_recover_tolerates_absent_new_file(tmp_path):
    """A not-existed entry whose live file is already absent: fine, and not
    reported as changed."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry(P3, None, NEW3)])
    assert ej.recover(root) == []
    assert not _journal(tmp_path).exists()


def test_recover_returns_paths_in_manifest_order(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "z.txt", b"Z-OLD")
    _write(tmp_path, "m.txt", b"M-OLD")
    _write(tmp_path, "a.txt", b"A-OLD")
    entries = [
        ej.Entry("z.txt", b"Z-OLD", b"Z-NEW"),
        ej.Entry("m.txt", b"M-OLD", b"M-NEW"),
        ej.Entry("a.txt", b"A-OLD", b"A-NEW"),
    ]
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    assert ej.recover(root) == ["z.txt", "m.txt", "a.txt"]


def test_recover_is_idempotent(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    ej.recover(root)
    assert ej.recover(root) == []
    assert _read(tmp_path, P1) == OLD1
    assert _read(tmp_path, P2) == OLD2
    assert not (tmp_path / P3).exists()


def test_recover_creates_missing_parent_directories(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "deep/a/b/f.txt", b"DEEP-OLD")
    ej.begin(root, [ej.Entry("deep/a/b/f.txt", b"DEEP-OLD", b"DEEP-NEW")])
    shutil.rmtree(tmp_path / "deep")  # directory vanished in the crash
    restored = ej.recover(root)
    assert restored == ["deep/a/b/f.txt"]
    assert _read(tmp_path, "deep/a/b/f.txt") == b"DEEP-OLD"


def test_recover_unchanged_files_not_reported_and_journal_removed(tmp_path):
    """Nothing was ever replaced: recover reports nothing and clears the
    journal (recovery completed -- the before-state is intact)."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    assert ej.recover(root) == []
    assert not _journal(tmp_path).exists()
    assert _read(tmp_path, P1) == OLD1
    assert _read(tmp_path, P2) == OLD2


def test_recover_leaves_non_journaled_files_untouched(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    _write(tmp_path, "other.txt", b"OTHER-MODIFIED")  # not in the journal
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    _write(tmp_path, "other.txt", b"OTHER-MODIFIED")
    ej.recover(root)
    assert _read(tmp_path, "other.txt") == b"OTHER-MODIFIED"


def test_recover_tampered_backup_raises_journalcorrupt(tmp_path):
    """Backup bytes no longer match the recorded sha256: refuse to touch
    anything, keep the journal, name the offending path."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    backups = _backup_files(tmp_path)
    assert len(backups) == 2, "two pre-existing entries -> two stored originals"
    for backup in backups:
        backup.write_bytes(b"CORRUPTED")
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    message = str(excinfo.value)
    assert P1 in message or P2 in message, "JournalCorrupt must name the path"
    assert _read(tmp_path, P1) == NEW1, "a corrupt backup means NOTHING is restored"
    assert _read(tmp_path, P2) == NEW2
    assert _read(tmp_path, P3) == NEW3, "the save's new file stays as-is"
    assert _journal(tmp_path).is_dir()


def test_recover_missing_backup_raises_journalcorrupt(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    for backup in _backup_files(tmp_path):
        backup.unlink()
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert P1 in str(excinfo.value) or P2 in str(excinfo.value)
    assert _read(tmp_path, P1) == NEW1
    assert _journal(tmp_path).is_dir()


def test_recover_corrupt_backup_checked_before_any_restore(tmp_path):
    """Entry order: file0 (backup intact, live replaced) then file1 (backup
    tampered). Recovering file0 first would violate change-nothing: nothing
    may move, including file0."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "a.txt", b"A-OLD")
    _write(tmp_path, "b.txt", b"B-OLD")
    entries = [
        ej.Entry("a.txt", b"A-OLD", b"A-NEW"),
        ej.Entry("b.txt", b"B-OLD", b"B-NEW"),
    ]
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    for backup in _backup_files(tmp_path):
        if backup.read_bytes() == b"B-OLD":
            backup.write_bytes(b"TAMPERED")
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a.txt") == b"A-NEW", (
        "the intact entry must NOT be restored while a later entry is corrupt"
    )
    assert _read(tmp_path, "b.txt") == b"B-NEW"
    assert _journal(tmp_path).is_dir()


def test_recover_missing_manifest_removes_journal_returns_empty(tmp_path):
    """Crash during begin, before manifest.json landed: no live file can have
    been touched, so the journal is simply cleared."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, P1, OLD1)
    _write(tmp_path, "other.txt", b"OTHER")
    journal = _journal(tmp_path)
    (journal / "orig").mkdir(parents=True)
    (journal / "orig" / "0").write_bytes(OLD1)
    assert ej.recover(root) == []
    assert not journal.exists()
    assert _read(tmp_path, P1) == OLD1
    assert _read(tmp_path, "other.txt") == b"OTHER"


def test_recover_unparseable_manifest_removes_journal_returns_empty(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    (_journal(tmp_path) / MANIFEST_NAME).write_bytes(b"\x00\x01garbage{{")
    assert ej.recover(root) == []
    assert not _journal(tmp_path).exists()
    # live files untouched: a crashed begin can never have replaced them
    assert _read(tmp_path, P1) == NEW1
    assert _read(tmp_path, P2) == NEW2


def test_recover_unsafe_manifest_path_journalcorrupt(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["path"] = "../escape.txt"
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "escape" in str(excinfo.value)
    assert _read(tmp_path, P1) == NEW1
    assert not (tmp_path.parent / "escape.txt").exists()
    assert _journal(tmp_path).is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_recover_midway_failure_keeps_journal_and_completes(tmp_path):
    """A restore that fails partway (unreadable target directory) keeps the
    journal; after fixing the cause, a second recover finishes the job
    (recovery is resumable/idempotent)."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "one.txt", b"O1")
    _write(tmp_path, "sub/two.txt", b"O2")
    entries = [
        ej.Entry("one.txt", b"O1", b"R1"),
        ej.Entry("sub/two.txt", b"O2", b"R2"),
    ]
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    sub = tmp_path / "sub"
    os.chmod(sub, 0o500)
    if os.access(sub, os.W_OK):
        os.chmod(sub, 0o700)
        pytest.skip("running as root: chmod does not block writes")
    try:
        with pytest.raises(OSError):
            ej.recover(root)
    finally:
        os.chmod(sub, 0o700)
    assert _read(tmp_path, "one.txt") == b"O1", "the first entry completed"
    assert _read(tmp_path, "sub/two.txt") == b"R2", "the second did not"
    assert ej.pending(root) is not None, "journal kept for a second run"
    assert ej.recover(root) == ["sub/two.txt"]
    assert _read(tmp_path, "sub/two.txt") == b"O2"
    assert ej.pending(root) is None


# --------------------------------------------------------- awkward path names


def test_begin_and_recover_survive_awkward_path_names(tmp_path):
    """orig/ names must not depend on the user's path characters being
    filesystem-safe: spaces, unicode, parentheses and dots in paths must
    round-trip through begin + recover."""
    ej = _ej()
    root = str(tmp_path)
    weird = [
        ("my dir/file (1).txt", b"W1-OLD", b"W1-NEW"),
        ("deep/sub.dirs/ünïcodé-ü.txt", b"W2-OLD", b"W2-NEW"),
        ("trailing.dots.tar.gz", b"W3-OLD", b"W3-NEW"),
    ]
    entries = []
    for rel, old, new in weird:
        _write(tmp_path, rel, old)
        entries.append(ej.Entry(rel, old, new))
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    assert sorted(ej.recover(root)) == sorted(rel for rel, _, _ in weird)
    for rel, old, _ in weird:
        assert _read(tmp_path, rel) == old
