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


def test_control_serve_edit_is_wired_to_the_journal():
    """The module task's scope rule (do not touch the save path) was flipped
    by the wiring task (backlog finding 15a): the save path now calls the
    module. This pins the wired side of the flip; the behavior itself is
    pinned by tests/test_editor_journal_wiring.py."""
    source = (REPO / "src" / "refdes" / "serve" / "edit.py").read_text(encoding="utf-8")
    assert "editor_journal.begin" in source
    assert "editor_journal.complete" in source
    assert "editor-transaction" in source


def test_control_cli_has_the_journal_gate_and_recover():
    """The cli side of the same flip: `refdes recover` exists and every
    project-loading command is gated on a pending journal (behavior pinned
    by tests/test_editor_journal_wiring.py)."""
    source = (REPO / "src" / "refdes" / "cli.py").read_text(encoding="utf-8")
    assert "editor_journal" in source
    assert '"recover"' in source


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


def test_recover_refuses_a_live_file_missing_where_the_replacement_belongs(tmp_path):
    """A journaled file that is simply gone is not the replacement: its
    absence is a state the transaction does not describe, and restoring
    the original into it writes over an unexplained deletion. Recover
    refuses, creates nothing, and keeps the journal."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "deep/a/b/f.txt", b"DEEP-OLD")
    ej.begin(root, [ej.Entry("deep/a/b/f.txt", b"DEEP-OLD", b"DEEP-NEW")])
    (tmp_path / "deep/a/b/f.txt").unlink()  # replacement landed, file vanished after
    with pytest.raises(ej.JournalCorrupt) as exc:
        ej.recover(root)
    assert "deep/a/b/f.txt" in str(exc.value)
    assert not (tmp_path / "deep/a/b/f.txt").exists(), "refusal must not restore the file"
    assert _journal(tmp_path).is_dir()


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


def test_recover_unparseable_manifest_is_journal_corrupt(tmp_path):
    """begin publishes manifest.json atomically, LAST, from a staging
    directory it renames in as one unit: a visible journal whose manifest
    does not parse is damage, not a crash inside begin (that shape leaves
    the manifest ABSENT, and that stays inert). Recover refuses, touches
    nothing, keeps the journal -- deleting it here would discard the only
    rollback copy while replacement bytes are live."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    manifest = _journal(tmp_path) / MANIFEST_NAME
    manifest.write_bytes(b"\x00\x01garbage{{")
    with pytest.raises(ej.JournalCorrupt) as exc:
        ej.recover(root)
    assert MANIFEST_NAME in str(exc.value)
    assert manifest.read_bytes() == b"\x00\x01garbage{{", "the evidence is kept"
    assert _journal(tmp_path).is_dir(), "the journal (and its backups) survive"
    # live files untouched
    assert _read(tmp_path, P1) == NEW1
    assert _read(tmp_path, P2) == NEW2
    assert ej.pending(root) == "unknown", "the gate keeps refusing"


def test_recover_refuses_a_live_file_that_matches_neither_hash(tmp_path):
    """The documented replacement check, enforced: live bytes matching
    neither the recorded replacement nor the recorded original mean
    something wrote outside the transaction. Recover refuses naming the
    path, changes NOTHING (not even the entries that would have
    restored), and keeps the journal."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    _write(tmp_path, P1, b"written by a writer outside the transaction\n")
    with pytest.raises(ej.JournalCorrupt) as exc:
        ej.recover(root)
    assert P1 in str(exc.value)
    assert _read(tmp_path, P1) == b"written by a writer outside the transaction\n"
    assert _read(tmp_path, P2) == NEW2, "refusal touches nothing: P2 stays as the save left it"
    assert (tmp_path / P3).exists(), "and restores nothing: the created file stands"
    assert _journal(tmp_path).is_dir()


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


# ----------------------------------------- review round 1: disarm-first complete, dir fsync


def _raise_oserror(*args, **kwargs):
    raise OSError("simulated removal failure")


def test_complete_disarms_the_manifest_before_a_removal_failure(tmp_path, monkeypatch):
    """If deleting the journal directory fails, the manifest must already be
    gone: a journal directory without a manifest is inert, so a later
    recover() removes it as a crashed begin -- it can never restore the
    originals over a save that completed."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    monkeypatch.setattr(shutil, "rmtree", _raise_oserror)
    with pytest.raises(OSError):
        ej.complete(root)
    monkeypatch.undo()
    journal = _journal(tmp_path)
    assert journal.is_dir(), "the simulated failure left the directory behind"
    assert not (journal / MANIFEST_NAME).exists(), "the manifest must be deleted first"
    assert ej.recover(root) == []
    assert not journal.exists()
    assert _read(tmp_path, P1) == NEW1, "the completed save must not be undone"
    assert _read(tmp_path, P2) == NEW2
    assert _read(tmp_path, P3) == NEW3


def test_complete_raises_when_the_manifest_removal_fails(tmp_path, monkeypatch):
    """A save is not complete while its manifest is still on disk: complete()
    must not report success over a failed disarm, and the journal stays
    armed and visible so recover can still restore."""
    ej = _ej()
    root = _project(tmp_path)
    tx = ej.begin(root, _entries(ej))
    monkeypatch.setattr(os, "remove", _raise_oserror)
    with pytest.raises(OSError):
        ej.complete(root)
    monkeypatch.undo()
    assert ej.pending(root) == tx


def test_complete_removes_a_disarmed_journal_directory(tmp_path):
    """Debris of a failed complete (directory, no manifest) must not keep
    refuse_if_pending blocking a project whose save succeeded: a journal
    directory without a manifest is inert, so complete() finishes the job
    and clears it. A wholly absent journal stays the silent no-op the
    contract demands."""
    ej = _ej()
    _journal(tmp_path).mkdir(parents=True)
    ej.complete(str(tmp_path))
    assert not _journal(tmp_path).exists()
    assert ej.pending(str(tmp_path)) is None
    ej.complete(str(tmp_path))  # still an idempotent no-op


def test_begin_fsyncs_staging_then_parent_around_the_visible_rename(tmp_path, monkeypatch):
    """The rename that makes the journal visible must be durable before
    begin() returns: fsync the staging content first, then the parent
    directory after the rename."""
    ej = _ej()
    root = _project(tmp_path)
    events: list[tuple] = []
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: events.append(("fsync", path)))
    real_replace = os.replace

    def spy_replace(src, dst):
        events.append(("replace", src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    ej.begin(root, _entries(ej))
    journal = str(_journal(tmp_path))
    parent = str(tmp_path / ".refdes")
    visible = next(
        i
        for i, event in enumerate(events)
        if event[0] == "replace" and event[2] == journal
    )
    staging = events[visible][1]
    assert ("fsync", staging) in events[:visible], (
        "journal content must be fsynced before the rename that exposes it"
    )
    assert ("fsync", parent) in events[visible + 1:], (
        "the parent directory must be fsynced after the rename, before begin returns"
    )
    assert events[-1] == ("fsync", parent)


def test_complete_fsyncs_the_journal_parent_after_removal(tmp_path, monkeypatch):
    """A removal that is not durable can resurrect the journal on reboot and
    arm a later recover against a save that succeeded."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    fsyncs: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", fsyncs.append)
    ej.complete(root)
    assert fsyncs[-1] == str(tmp_path / ".refdes")


def test_recover_fsyncs_the_journal_parent_after_removal(tmp_path, monkeypatch):
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    fsyncs: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", fsyncs.append)
    ej.recover(root)
    assert fsyncs[-1] == str(tmp_path / ".refdes")


# ------------------------------------------ review round 2: unreadable manifest, symlinks, fsync


def _symlink(target: str, link: str) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this platform")


def test_recover_keeps_journal_when_the_manifest_is_unreadable(tmp_path, monkeypatch):
    """An unreadable manifest (permissions, a sharing violation) says nothing
    about whether begin() crashed: recover must NOT remove the journal --
    that would discard the only rollback copy while the replacement bytes
    are live. It refuses, changes nothing, keeps the journal, and pending()
    still reports it."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    manifest = str(_journal(tmp_path) / MANIFEST_NAME)
    real_open = open

    def blocked_open(file, *args, **kwargs):
        if str(file) == manifest:
            raise PermissionError(13, "simulated sharing violation", str(file))
        return real_open(file, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr("builtins.open", blocked_open)
        assert ej.pending(root) == "unknown", "unreadable manifest is still pending"
        with pytest.raises((ej.JournalCorrupt, OSError)):
            ej.recover(root)
    assert _journal(tmp_path).is_dir(), "the journal (and its rollback data) is kept"
    assert _read(tmp_path, P1) == NEW1, "an unreadable manifest restores NOTHING"
    assert _read(tmp_path, P2) == NEW2
    assert _read(tmp_path, P3) == NEW3
    assert ej.pending(root) is not None


def test_recover_refuses_paths_through_escaping_symlinks(tmp_path):
    """A manifest path can be lexically safe and still escape the project
    through a symlinked directory: `jump/file.txt` with `jump -> /outside`
    must be refused as JournalCorrupt, touching nothing, journal kept."""
    ej = _ej()
    root = _project(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_bytes(b"VICTIM")
    _symlink(str(outside), str(tmp_path / "jump"))
    _write(tmp_path, "jump/victim.txt", b"VICTIM")
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["path"] = "jump/victim.txt"
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "jump/victim.txt" in str(excinfo.value)
    assert victim.read_bytes() == b"VICTIM", "nothing may be written outside the root"
    assert _read(tmp_path, P1) == NEW1, "the refusal changes nothing"
    assert _journal(tmp_path).is_dir()


def test_begin_refuses_entries_through_escaping_symlinks(tmp_path):
    """begin() must not journal a save that runs through an escaping
    symlink: ValueError, no journal directory left behind."""
    ej = _ej()
    root = _project(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_bytes(b"VICTIM")
    _symlink(str(outside), str(tmp_path / "jump"))
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry("jump/victim.txt", b"VICTIM", b"ESCAPE")])
    assert not _journal(tmp_path).exists()
    assert victim.read_bytes() == b"VICTIM"


def test_recover_allows_symlinked_directories_inside_the_project(tmp_path):
    """Guard against over-refusing: containment means the resolved parent
    stays inside the root; a symlink to a directory inside the project is
    the project's own business and must keep working."""
    ej = _ej()
    root = str(tmp_path)
    (tmp_path / "realdir").mkdir()
    _symlink(str(tmp_path / "realdir"), str(tmp_path / "linkdir"))
    _write(tmp_path, "linkdir/f.txt", b"F-OLD")
    ej.begin(root, [ej.Entry("linkdir/f.txt", b"F-OLD", b"F-NEW")])
    _write(tmp_path, "linkdir/f.txt", b"F-NEW")
    assert ej.recover(root) == ["linkdir/f.txt"]
    assert (tmp_path / "realdir" / "f.txt").read_bytes() == b"F-OLD"


def test_begin_fsyncs_the_orig_directory_before_exposing_the_journal(tmp_path, monkeypatch):
    """fsyncing the staging directory does not persist the entries written
    into orig/: after a power loss a visible manifest must not sit beside
    backup files whose directory entries never landed (JournalCorrupt on
    recovery of a journal that was journaled correctly)."""
    ej = _ej()
    root = _project(tmp_path)
    events: list[tuple] = []
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: events.append(("fsync", path)))
    real_replace = os.replace

    def spy_replace(src, dst):
        events.append(("replace", src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    ej.begin(root, _entries(ej))
    journal = str(_journal(tmp_path))
    parent = str(tmp_path / ".refdes")
    visible = next(
        i
        for i, event in enumerate(events)
        if event[0] == "replace" and event[2] == journal
    )
    staging = events[visible][1]
    assert ("fsync", os.path.join(staging, "orig")) in events[:visible], (
        "the backup files' directory must be fsynced before the journal appears"
    )
    assert ("fsync", staging) in events[:visible]
    assert events[-1] == ("fsync", parent)


# ------------------------------- review round 2 addendum: restore fsync, inert debris, dot paths
def test_recover_fsyncs_restored_parents_before_the_journal_goes(tmp_path, monkeypatch):
    """The restored live files must be durable before the journal that is
    their only safety net is removed: fsync each restored file's parent
    directory before the journal directory goes away."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    events: list[tuple] = []
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: events.append(("fsync", path)))
    real_rmtree = shutil.rmtree

    def spy_rmtree(path, *args, **kwargs):
        events.append(("rmtree", path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", spy_rmtree)
    assert ej.recover(root) == [P1, P2, P3]
    removed = next(i for i, event in enumerate(events) if event[0] == "rmtree")
    for parent in ("src", "notes", "items"):
        assert ("fsync", str(tmp_path / parent)) in events[:removed], (
            f"{parent}/ must be fsynced before the journal is removed"
        )


def test_recover_refuses_a_live_path_that_is_a_directory(tmp_path):
    """A live path that is a directory surfaces as JournalCorrupt naming the
    path -- nothing restored, journal kept -- not a bare IsADirectoryError."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "keep.txt", b"K-OLD")
    _write(tmp_path, "conflict", b"C-OLD")
    entries = [
        ej.Entry("keep.txt", b"K-OLD", b"K-NEW"),
        ej.Entry("conflict", b"C-OLD", b"C-NEW"),
    ]
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    (tmp_path / "conflict").unlink()
    (tmp_path / "conflict").mkdir()
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "conflict" in str(excinfo.value)
    assert _read(tmp_path, "keep.txt") == b"K-NEW", "the refusal touches nothing"
    assert ej.pending(root) is not None


def test_recover_refuses_duplicate_paths_in_the_manifest(tmp_path):
    """begin refuses duplicates; a tampered manifest that lists one path
    twice is equally untrustworthy: JournalCorrupt, nothing touched. The
    entries use not-existed originals so the hash check cannot be what
    trips -- the refusal must be the duplicate itself."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry(P3, None, NEW3)])
    _write(tmp_path, P3, NEW3)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    entry_list = _find_entry_list(manifest)
    entry_list.append(dict(entry_list[0]))
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert P3 in str(excinfo.value)
    assert _read(tmp_path, P3) == NEW3
    assert _journal(tmp_path).is_dir()


DOT_PATHS = [".", "./", "./a.txt", "a/", "a//b", "a/./b"]


@pytest.mark.parametrize("path", DOT_PATHS)
def test_begin_rejects_dot_and_empty_path_segments(tmp_path, path):
    """`"."`, trailing slashes and empty segments name the same files as
    other paths (or the root itself) and must be refused at begin, with no
    journal left behind."""
    ej = _ej()
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry(path, b"O", b"N")])
    assert not _journal(tmp_path).exists()


def test_recover_refuses_empty_segments_in_the_manifest(tmp_path):
    """The recover-side validation refuses the same path shapes begin
    refuses: JournalCorrupt, nothing touched, journal kept."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["path"] = "src//main.c"
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, P1) == NEW1
    assert _journal(tmp_path).is_dir()


def test_a_regular_file_at_the_journal_path_blocks_everything(tmp_path):
    """begin treats any existing path at the journal location as pending;
    pending/refuse_if_pending must agree, or the guard says clear while
    every save is refused."""
    ej = _ej()
    root = _project(tmp_path)
    journal = _journal(tmp_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_bytes(b"not a directory")
    assert ej.pending(root) == "unknown"
    with pytest.raises(ej.JournalPending):
        ej.refuse_if_pending(root)
    with pytest.raises(ej.JournalPending):
        ej.begin(root, _entries(ej))


# ------------------------- review round 4: journal-location confinement, dangling-symlink restore
def test_a_symlinked_journal_location_is_refused_everywhere(tmp_path):
    """<root>/.refdes symlinking outside the project must not let begin
    stage the originals outside the root, nor let recover/complete act
    through the link: every entry point refuses, touching nothing. begin
    raises ValueError with nothing created; recover raises JournalCorrupt
    and restores nothing; complete raises and deletes nothing; the refusal
    gate reports the project as pending, exactly as begin refuses it."""
    ej = _ej()
    root = _project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    shutil.move(str(tmp_path / ".refdes"), str(outside / "moved"))
    _symlink(str(outside / "moved"), str(tmp_path / ".refdes"))
    with pytest.raises(ValueError):
        ej.begin(root, entries)
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, P1) == NEW1, "recover touched nothing"
    with pytest.raises(OSError):
        ej.complete(root)
    assert (outside / "moved" / "editor-transaction").is_dir()
    assert ej.pending(root) == "unknown"
    with pytest.raises(ej.JournalPending):
        ej.refuse_if_pending(root)


def test_recover_unlinks_a_dangling_symlink_at_a_new_file_path(tmp_path):
    """os.path.exists() follows symlinks: a dangling symlink at a path
    that did not exist before the save reads as absent and would survive
    recovery, ready to start resolving when its target appears. The link
    IS the live state: recover removes it as a link (never following) and
    reports the path as restored."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry(P3, None, NEW3)])
    (tmp_path / "items").mkdir()
    _symlink("never-exists", str(tmp_path / P3))
    assert not (tmp_path / P3).exists(), "the symlink is dangling"
    assert ej.recover(root) == [P3]
    assert not os.path.lexists(tmp_path / P3)


# ---------------------- review round 5: un-wedge non-directory squatters; strict fsync errors
def test_recover_clears_a_plain_file_squatting_on_the_journal_path(tmp_path):
    """A plain file at the journal path wedges the project: pending
    reports "unknown" and begin refuses, telling the user to run
    recover -- so recover must clear it. Refuse -> recover -> begin, in
    one sequence, is the documented remediation."""
    ej = _ej()
    root = _project(tmp_path)
    journal = _journal(tmp_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_bytes(b"not a journal")
    with pytest.raises(ej.JournalPending):
        ej.refuse_if_pending(root)
    assert ej.recover(root) == [ej.JOURNAL_DIR]
    assert not journal.exists()
    ej.begin(root, _entries(ej))  # begin works again


def test_recover_clears_a_dangling_symlink_at_the_journal_path(tmp_path):
    """Same wedge via a dangling symlink: recover removes the LINK
    itself -- never following it -- and reports it. The gate reports the
    project as pending and begin refuses it the same way: the link
    exists at the journal location even though its target does not, so
    begin points at recover (JournalPending), not at a location
    escape."""
    ej = _ej()
    root = _project(tmp_path)
    journal = _journal(tmp_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    _symlink("nowhere", str(journal))
    with pytest.raises(ej.JournalPending):
        ej.refuse_if_pending(root)
    with pytest.raises(ej.JournalPending):
        ej.begin(root, _entries(ej))
    assert ej.recover(root) == [ej.JOURNAL_DIR]
    assert not os.path.lexists(journal)
    assert not (tmp_path / "nowhere").exists(), "the link was never followed"
    ej.begin(root, _entries(ej))


def test_fsync_dir_propagates_posix_permission_errors(tmp_path, monkeypatch):
    """PermissionError from opening a directory is Windows'
    not-supported signal, not a universal one: on POSIX EACCES is a real
    durability failure and must propagate, not be swallowed."""
    ej = _ej()
    if os.name == "nt":
        pytest.skip("opening directories as fds is the unsupported case on Windows")

    def deny_open(*args, **kwargs):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(ej.os, "open", deny_open)
    with pytest.raises(PermissionError):
        ej._fsync_dir(str(tmp_path))


# ----------------- review round 6: confinement first, parsed manifests, late fsync,
# journal-internal paths, intermediate-directory fsync
def test_recover_refuses_to_delete_through_a_symlinked_journal_parent(tmp_path):
    """<root>/.refdes -> outside with a plain-file squatter in the
    outside directory: the squatter branch must not run before the
    confinement check -- realpath(root) does not resolve the .refdes
    component -- or recover deletes a file OUTSIDE the root."""
    ej = _ej()
    root = _project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-out6"
    outside.mkdir()
    squatter = outside / "editor-transaction"
    squatter.write_bytes(b"squatter")
    _symlink(str(outside), str(tmp_path / ".refdes"))
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert squatter.read_bytes() == b"squatter"
    assert ej.pending(root) == "unknown"
    with pytest.raises(ValueError):
        ej.begin(root, _entries(ej))
    with pytest.raises(OSError):
        ej.complete(root)


NOT_OBJECTS = ["null", "[]", '"x"', "3"]


@pytest.mark.parametrize("literal", NOT_OBJECTS)
def test_recover_refuses_a_manifest_that_is_not_an_object(tmp_path, literal):
    """A manifest that PARSES to null/list/str/int is a readable,
    trustworthy document saying something impossible -- not the inert
    crashed-begin state, which is a MISSING manifest. recover must keep
    the journal (it may hold the only rollback copy) and refuse."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    (_journal(tmp_path) / MANIFEST_NAME).write_text(literal)
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert (_journal(tmp_path) / MANIFEST_NAME).read_text() == literal
    assert _read(tmp_path, P1) == NEW1, "nothing restored"


def test_begin_withdraws_the_journal_when_the_final_fsync_fails(tmp_path, monkeypatch):
    """After the rename the journal is ours and no live file is touched;
    a failure of the final durability fsync must not leave the caller
    with a failure AND an armed journal whose id was never returned.
    begin removes the just-created journal and re-raises."""
    ej = _ej()
    root = _project(tmp_path)
    parent = tmp_path / ".refdes"

    def spy(path):
        if os.path.realpath(path) == os.path.realpath(str(parent)):
            raise OSError("disk full")

    monkeypatch.setattr(ej, "_fsync_dir", spy)
    with pytest.raises(OSError):
        ej.begin(root, _entries(ej))
    assert not _journal(tmp_path).exists()
    assert ej.pending(root) is None


JOURNAL_INTERNAL = [
    ".refdes/editor-transaction",
    ".refdes/editor-transaction/manifest.json",
    ".refdes/editor-transaction/orig/0.bin",
]


@pytest.mark.parametrize("path", JOURNAL_INTERNAL)
def test_begin_refuses_paths_inside_the_journal(tmp_path, path):
    """An entry writing inside the journal directory would overwrite
    journal state the moment the save lands: refused at begin (ValueError,
    nothing created) and by the manifest parser on the recover side."""
    ej = _ej()
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry(path, b"O", b"N")])
    assert not _journal(tmp_path).exists()


def test_recover_refuses_a_manifest_path_inside_the_journal(tmp_path):
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["path"] = ".refdes/editor-transaction/manifest.json"
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert (_journal(tmp_path) / MANIFEST_NAME).is_file()


# ---------------- review round 7: alias identity, windows names, phase model
def test_begin_refuses_paths_that_alias_one_file(tmp_path):
    """`real/a` and `alias/a` (alias -> real) are two spellings of ONE
    file: the save would apply both entries to it. Identity is the
    resolved (parent, leaf), not the spelled path: ValueError, nothing
    created."""
    ej = _ej()
    root = str(tmp_path)
    (tmp_path / "real").mkdir()
    _symlink(str(tmp_path / "real"), str(tmp_path / "alias"))
    with pytest.raises(ValueError):
        ej.begin(
            root,
            [ej.Entry("real/a", b"ONE", b"X"), ej.Entry("alias/a", b"TWO", b"Y")],
        )
    assert not _journal(tmp_path).exists()


def test_recover_refuses_manifest_paths_that_alias_one_file(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, P1, OLD1)
    _symlink(str(tmp_path / "src"), str(tmp_path / "src2"))
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    entries = _find_entry_list(manifest)
    twin = dict(entries[0])
    twin["path"] = "src2/main.c"
    entries.append(twin)
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, P1) == NEW1
    assert _journal(tmp_path).is_dir()


WINDOWS_NAMES = ["NUL", "nul.txt", "CON", "COM1", "LPT9.log", "a.", "a ", "dir/CON.txt"]


@pytest.mark.parametrize("path", WINDOWS_NAMES)
def test_begin_rejects_windows_mangled_names(tmp_path, path):
    """Windows reserves device-name stems (with extension included) and
    drops trailing dots/spaces: names valid as POSIX filenames become
    unwriteable or mangled when the project moves to Windows. Refused
    on every platform (conservative, documented in the module)."""
    ej = _ej()
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry(path, None, b"X")])
    assert not _journal(tmp_path).exists()


def test_begin_fsyncs_the_root_when_it_creates_the_refdes_dir(tmp_path, monkeypatch):
    """A freshly created `.refdes` is durable in the project root only
    once the root is fsynced; a power loss can make the whole journal
    directory vanish. begin fsyncs the root (after the visible rename,
    before the journal parent's own fsync)."""
    ej = _ej()
    root = _project(tmp_path)
    events: list[tuple] = []
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: events.append(("fsync", path)))
    real_replace = os.replace

    def spy_replace(src, dst):
        events.append(("replace", src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    ej.begin(root, _entries(ej))
    visible = next(i for i, event in enumerate(events) if event[0] == "replace")
    assert ("fsync", str(tmp_path)) in events[visible + 1:]
    assert events[-1] == ("fsync", str(tmp_path / ".refdes"))


def test_begin_skips_the_root_fsync_when_refdes_already_exists(tmp_path, monkeypatch):
    ej = _ej()
    root = _project(tmp_path)
    (tmp_path / ".refdes").mkdir()
    fsynced: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", fsynced.append)
    ej.begin(root, _entries(ej))
    assert str(tmp_path) not in fsynced


def test_recover_re_runs_the_durability_barrier_on_retries(tmp_path, monkeypatch):
    """A retried recover must make the live files durable even when every
    byte is already on disk: the first run restored the bytes, then its
    barrier failed, and a retry that skips the fsyncs (nothing left to
    write) reports recovery complete over data power loss can still
    lose. The live parents are fsynced on a pass that restores nothing."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a.txt", b"old", b"new")])
    _write(tmp_path, "a.txt", b"new")
    real = ej._fsync_dir

    def deny_root(path):
        if os.path.realpath(path) == os.path.realpath(root):
            raise OSError("injected live parent fsync failure")
        return real(path)

    with monkeypatch.context() as m:
        m.setattr(ej, "_fsync_dir", deny_root)
        with pytest.raises(OSError):
            ej.recover(root)
    assert _journal(tmp_path).exists(), "the journal is kept for the retry"
    assert _read(tmp_path, "a.txt") == b"old"
    fsynced: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", fsynced.append)
    assert ej.recover(root) == []
    assert os.path.realpath(root) in [os.path.realpath(path) for path in fsynced]


def test_complete_retries_the_disarm_barrier(tmp_path, monkeypatch):
    """complete() whose manifest delete landed but whose journal-directory
    fsync failed leaves disarmed debris; the retry must re-run the disarm
    barrier -- fsync the journal dir BEFORE the GC deletes the backups --
    not skip the fsync because the manifest is already gone."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    journal = _journal(tmp_path)
    real = ej._fsync_dir

    def deny_journal(path):
        if os.path.realpath(path) == os.path.realpath(str(journal)):
            raise OSError("injected disarm fsync failure")
        return real(path)

    with monkeypatch.context() as m:
        m.setattr(ej, "_fsync_dir", deny_journal)
        with pytest.raises(OSError):
            ej.complete(root)
    assert not (journal / MANIFEST_NAME).exists(), "the disarm landed before the failure"
    assert journal.is_dir()
    fsynced: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", fsynced.append)
    ej.complete(root)
    assert os.path.realpath(str(journal)) in [os.path.realpath(path) for path in fsynced]


def test_recover_disarms_the_journal_before_the_gc_replays(tmp_path, monkeypatch):
    """Recovery restores, then DISARMS (manifest removed + barrier) and
    then GCs the backups. An interrupted GC -- half the backups deleted,
    the directory left -- must not leave a retry rereading a manifest
    whose backups are gone (the old ordering: permanent JournalCorrupt);
    the durable disarm makes the journal inert, so the retry finishes
    with [] and the journal gone."""
    ej = _ej()
    root = _project(tmp_path)
    entries = _entries(ej)
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    journal = _journal(tmp_path)
    real_rmtree = shutil.rmtree
    failed: list[bool] = []

    def interrupt(path, *args, **kwargs):
        if os.path.realpath(path) == os.path.realpath(str(journal)) and not failed:
            failed.append(True)
            _backup_files(tmp_path)[0].unlink()
            raise OSError("injected cleanup interruption")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", interrupt)
    with pytest.raises(OSError):
        ej.recover(root)
    assert not (journal / MANIFEST_NAME).exists(), "disarmed before the GC"
    assert journal.is_dir()
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert ej.recover(root) == []
    assert not journal.exists()


def test_recover_replaces_a_symlink_whose_target_already_matches(tmp_path):
    """An equality check that follows the final symlink reads the TARGET's
    bytes: an `a -> target` link carrying the original content reads as
    "already restored" and survives recovery, silently redirecting the
    project's file. The last component is lstat'ed: a symlink is not the
    journaled file and is replaced by the regular file."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "target", b"old")
    _symlink(str(tmp_path / "target"), str(tmp_path / "a"))
    assert _read(tmp_path, "a") == b"old", "the link resolves to the original"
    assert ej.recover(root) == ["a"]
    assert not (tmp_path / "a").is_symlink()
    assert _read(tmp_path, "a") == b"old"
    assert _read(tmp_path, "target") == b"old", "the link's target is untouched"


def test_begin_rejects_paths_containing_nul_bytes(tmp_path):
    """A NUL is a legal POSIX filename character and an ENAMETOOLONG-at-
    byte-0 for every syscall: an entry that can never be named on disk
    is not a safe path."""
    ej = _ej()
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry("bad\x00name", None, b"X")])
    assert not _journal(tmp_path).exists()


HASH_CASES = {
    "replacement-not-hex": lambda e: e.update({"replacement_sha256": "not-a-hash"}),
    "original-not-hex": lambda e: e.update({"original_sha256": "not-null"}),
    "original-short-hex": lambda e: e.update({"original_sha256": "abc123"}),
}


@pytest.mark.parametrize(
    "tweak", list(HASH_CASES.values()), ids=list(HASH_CASES.keys())
)
def test_recover_refuses_malformed_entry_hashes(tmp_path, tweak):
    """The parser validates the whole schema -- hashes are 64 hex digits,
    original_sha256 present exactly when existed -- BEFORE recover
    touches a live file: the bytes it is about to restore are verified
    against those very hashes, so a malformed one is an unverifiable
    entry, not a cosmetic field."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    tweak(_find_entry_list(manifest)[0])
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a") == b"new", "the refusal restores nothing"
    assert _journal(tmp_path).is_dir()


def test_recover_refuses_a_hash_for_a_file_that_never_existed(tmp_path):
    """existed=False with an original_sha256 set is a manifest that
    contradicts itself (a hash of nothing): refused, nothing touched."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a", None, b"new")])
    _write(tmp_path, "a", b"new")
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["original_sha256"] = hashlib.sha256(b"ghost").hexdigest()
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a") == b"new"
    assert _journal(tmp_path).is_dir()


def test_begin_refuses_ancestor_entry_paths(tmp_path):
    """`a` and `a/b` cannot both land: writing one destroys the other's
    parent, and the crash state is unrecoverable (recover hits the
    directory conflict). A save that cannot be applied is refused at
    begin, nothing created."""
    ej = _ej()
    root = str(tmp_path)
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry("a", b"old", b"new"), ej.Entry("a/b", None, b"new")])
    assert not _journal(tmp_path).exists()


def test_recover_refuses_ancestor_paths_in_the_manifest(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    entries = _find_entry_list(manifest)
    twin = dict(entries[0])
    twin.update({"path": "a/b", "existed": False, "original_sha256": None})
    entries.append(twin)
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a") == b"new"
    assert _journal(tmp_path).is_dir()


def test_recover_refuses_a_backup_that_is_a_symlink(tmp_path):
    """The backups are read as the journal's own recovery data, so they
    are read only as regular files: an orig/0.bin symlink points at
    bytes the journal never wrote (here: OUTSIDE the project), and
    reading through it restores attacker-chosen content. The last
    component is lstat'ed; the journal is kept."""
    ej = _ej()
    root = str(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-backup"
    outside.write_bytes(b"old")
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    backup = _backup_files(tmp_path)[0]
    backup.unlink()
    _symlink(str(outside), str(backup))
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "a" in str(excinfo.value)
    assert _read(tmp_path, "a") == b"new", "nothing is restored"
    assert _journal(tmp_path).is_dir()
    assert outside.read_bytes() == b"old"


def test_recover_refuses_a_manifest_that_is_a_symlink(tmp_path):
    """Same rule for the manifest: read as a regular file inside the
    journal, never through a link."""
    ej = _ej()
    root = str(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-manifest"
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    manifest = _journal(tmp_path) / MANIFEST_NAME
    manifest_bytes = manifest.read_bytes()
    outside.write_bytes(manifest_bytes)
    manifest.unlink()
    _symlink(str(outside), str(manifest))
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a") == b"new"
    assert outside.read_bytes() == manifest_bytes, (
        "the link's target keeps the manifest's bytes: untouched, not written through"
    )
    assert _journal(tmp_path).is_dir()


def test_recover_names_the_entry_when_a_backup_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable backup is neither absent (the journal is not inert)
    nor verified: refuse naming the ENTRY whose recovery data is in
    question, keep the journal, touch nothing."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, [ej.Entry(P1, OLD1, NEW1)])
    _write(tmp_path, P1, NEW1)
    backup = str(_backup_files(tmp_path)[0])
    real_open = open

    def deny(file, *args, **kwargs):
        if str(file) == backup:
            raise PermissionError(13, "injected backup read failure", str(file))
        return real_open(file, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr("builtins.open", deny)
        with pytest.raises(ej.JournalCorrupt) as excinfo:
            ej.recover(root)
    assert P1 in str(excinfo.value)
    assert _read(tmp_path, P1) == NEW1
    assert _journal(tmp_path).is_dir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX fifos")
def test_recover_refuses_a_special_file_at_a_live_path(tmp_path):
    """A fifo/socket/device at a journaled path is not a file the save
    wrote: opening a fifo blocks, and nothing proves a plain file can
    replace the object. Refused naming the path, the object left in
    place, the journal kept."""
    ej = _ej()
    root = str(tmp_path)
    ej.begin(root, [ej.Entry("a", None, b"new")])
    os.mkfifo(tmp_path / "a")
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "a" in str(excinfo.value)
    assert (tmp_path / "a").exists(), "the object is left in place"
    assert _journal(tmp_path).is_dir()


def test_recover_syncs_the_live_directories_after_the_last_write(tmp_path, monkeypatch):
    """A directory fsync makes durable the changes that landed BEFORE it:
    fsyncing inline with the restore loop (deduplicated) leaves the last
    write's directory unsynced when its chain ran earlier. The barriers
    run AFTER the restore loop, over every entry's parent chain: each
    directory is fsynced once, after the last change inside it."""
    ej = _ej()
    root = str(tmp_path)
    _write(tmp_path, "a", b"A-OLD")
    _write(tmp_path, "b", b"B-OLD")
    entries = [
        ej.Entry("a", b"A-OLD", b"A-NEW"),
        ej.Entry("b", b"B-OLD", b"B-NEW"),
    ]
    ej.begin(root, entries)
    _apply_save(tmp_path, entries)
    events: list[tuple] = []
    real_write = ej._atomic_write_bytes

    def spy_write(path, data):
        events.append(("write", path))
        return real_write(path, data)

    monkeypatch.setattr(ej, "_atomic_write_bytes", spy_write)
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: events.append(("sync", path)))
    assert ej.recover(root) == ["a", "b"]
    last_write = max(i for i, event in enumerate(events) if event[0] == "write")
    assert ("sync", root) in events[last_write + 1:], (
        "the last write in a directory must precede that directory's fsync"
    )


def test_begin_refuses_paths_through_a_control_directory_alias(tmp_path):
    """An alias to `.refdes` (or to the journal inside it) is a save
    writing the journal's own state: the journal-internal rule covers
    the spelled path, realpath covers the alias. Refused at begin with
    nothing created."""
    ej = _ej()
    root = str(tmp_path)
    (tmp_path / ".refdes").mkdir()
    _symlink(str(tmp_path / ".refdes"), str(tmp_path / "ctrl"))
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry("ctrl/x", None, b"X")])
    assert not _journal(tmp_path).exists()


def test_recover_refuses_a_manifest_path_in_the_control_namespace(tmp_path):
    ej = _ej()
    root = str(tmp_path)
    (tmp_path / ".refdes").mkdir()
    _symlink(str(tmp_path / ".refdes"), str(tmp_path / "ctrl"))
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    manifest_path = _journal(tmp_path) / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    _find_entry_list(manifest)[0]["path"] = "ctrl/x"
    manifest_path.write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ej.JournalCorrupt):
        ej.recover(root)
    assert _read(tmp_path, "a") == b"new"
    assert (_journal(tmp_path) / MANIFEST_NAME).is_file()


def test_recover_fsyncs_the_parent_chain_of_every_restored_file(tmp_path, monkeypatch):
    """The durability barrier after a restore: every directory from the
    restored file's leaf parent up to the root gets a guarded fsync, leaf
    first -- fsyncing only the leaf leaves the leaf directory undurable in
    its parent."""
    ej = _ej()
    root = str(tmp_path)
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.txt").write_bytes(b"NEW")
    ej.begin(root, [ej.Entry("a/b/c.txt", b"OLD", b"NEW")])
    fsynced: list[str] = []
    monkeypatch.setattr(ej, "_fsync_dir", lambda path: fsynced.append(path))
    assert ej.recover(root) == ["a/b/c.txt"]
    leaf = str(tmp_path / "a" / "b")
    assert leaf in fsynced
    assert str(tmp_path / "a") in fsynced
    assert fsynced.index(leaf) < fsynced.index(str(tmp_path / "a"))


# --------------------------- review round 9: symlinked-directory fsync,
# the orig/ directory's identity, a journal symlink to a directory


def test_recover_fsyncs_the_real_directory_behind_a_symlinked_parent(
    tmp_path, monkeypatch
):
    """A journaled path restored THROUGH an in-project symlinked
    directory (linkdir -> realdir): the restored bytes land in realdir,
    so the durability barrier must fsync realdir. A chain node
    classified "symlink" and skipped as "not a directory" leaves the
    entry's real directory unsynced: fsyncing the link's parent
    persists the link, not the file inside the real directory."""
    ej = _ej()
    root = str(tmp_path)
    realdir = tmp_path / "realdir"
    realdir.mkdir()
    (realdir / "a").write_bytes(b"old")
    _symlink("realdir", str(tmp_path / "linkdir"))
    ej.begin(root, [ej.Entry("linkdir/a", b"old", b"new")])
    _write(tmp_path, "linkdir/a", b"new")
    fsynced: list[str] = []
    real_fsync = ej._fsync_dir

    def record(path):
        fsynced.append(os.path.realpath(path))
        return real_fsync(path)

    monkeypatch.setattr(ej, "_fsync_dir", record)
    assert ej.recover(root) == ["linkdir/a"]
    assert (realdir / "a").read_bytes() == b"old"
    assert str(realdir) in fsynced, (
        "the directory the restored bytes live in must be fsynced, even "
        "when the journaled path reaches it through a symlink"
    )


def test_recover_propagates_a_chain_fsync_inspection_error(tmp_path, monkeypatch):
    """An I/O error inspecting a chain node is not "not a directory":
    a barrier that cannot see the directory it must fsync cannot
    promise durability. The error propagates -- and the journal, not
    yet taken down, stays for the retry."""
    ej = _ej()
    root = _project(tmp_path)
    ej.begin(root, _entries(ej))
    _apply_save(tmp_path, _entries(ej))
    blocked = str(tmp_path / "src")
    real_classify = ej._classify

    def flaky(path):
        if str(path) == blocked:
            return "error:injected inspection failure"
        return real_classify(path)

    monkeypatch.setattr(ej, "_classify", flaky)
    with pytest.raises(OSError):
        ej.recover(root)
    assert _journal(tmp_path).is_dir(), "the journal survives for a retry"
    assert _read(tmp_path, P1) == OLD1, "the restored bytes are on disk"


def test_recover_refuses_a_symlinked_orig_directory(tmp_path):
    """The leaf backup is lstat'ed, its containing directory is not:
    orig/ -> a directory OUTSIDE the root makes recovery read backup
    data the journal never wrote, from a directory the journal does not
    own. The orig/ directory itself must be a real directory; the
    refusal names it and nothing is restored."""
    ej = _ej()
    root = str(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-origdir"
    outside.mkdir()
    ej.begin(root, [ej.Entry("a", b"old", b"new")])
    _write(tmp_path, "a", b"new")
    journal = _journal(tmp_path)
    orig = journal / "orig"
    real = journal / "orig-real"
    orig.rename(real)
    real.rename(outside / "orig")
    _symlink(str(outside / "orig"), str(orig))
    with pytest.raises(ej.JournalCorrupt) as excinfo:
        ej.recover(root)
    assert "orig" in str(excinfo.value)
    assert _read(tmp_path, "a") == b"new", "nothing is restored"
    assert _journal(tmp_path).is_dir()
    assert sorted(p.read_bytes() for p in _backup_files(tmp_path)) == [b"old"]


def test_recover_clears_a_journal_symlink_to_a_directory(tmp_path):
    """A symlink AT the journal path whose target is a DIRECTORY wedges
    the project under a refusal regime: pending says "unknown", begin
    refuses, recover refuses to follow -- forever. The link ITSELF is
    the squatter (the parent is confined, checked first): recover
    removes the LINK, never following it, exactly as it removes
    file/dangling-link squatters, and the target directory and its
    contents are untouched."""
    ej = _ej()
    root = str(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").write_bytes(b"keep")
    journal = _journal(tmp_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    _symlink("target", str(journal))
    assert ej.pending(root) == "unknown"
    with pytest.raises(ej.JournalPending):
        ej.begin(root, _entries(ej))
    assert ej.recover(root) == [ej.JOURNAL_DIR]
    assert not os.path.lexists(journal)
    assert target.is_dir()
    assert (target / "keep").read_bytes() == b"keep"
    ej.begin(root, _entries(ej))  # the project works again


def test_begin_refuses_a_journal_symlink_under_an_escaping_refdes(tmp_path):
    """Confinement keeps its shape next to the pending refusal: a
    symlink at the journal path UNDER a `.refdes` that resolves outside
    the root is refused as a location escape (ValueError), not reported
    as a pending journal."""
    ej = _ej()
    root = str(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-esc9"
    outside.mkdir()
    (tmp_path / "realdir").mkdir()
    _symlink(str(outside), str(tmp_path / ".refdes"))
    (outside / "editor-transaction").symlink_to(
        str(tmp_path / "realdir"), target_is_directory=True
    )
    with pytest.raises(ValueError):
        ej.begin(root, [ej.Entry("a", b"old", b"new")])
    assert (tmp_path / "realdir").is_dir()
