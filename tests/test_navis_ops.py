"""navis_ops (slice N5.0): the archive/restore decisions as a service,
driven directly -- no CLI, no argparse, no stdout capture. One test per
outcome kind; the CLI's *rendering* of each kind stays pinned by
tests/test_navis_archive_cli.py, and this file pins the decisions.

Rows are synthetic projection-shaped dicts (the module only reads the
keys the verbs read), so no project is loaded; the store writes land in
``tmp_path``.
"""

from __future__ import annotations

import dataclasses
import gzip

import pytest
import yaml

from refdes import keys as keys_mod
from refdes import navis_ops

DATA_A = "aaaaaa1111"
DATA_B = "bbbbbb2222"
KEY_A = DATA_A + keys_mod.check_char(DATA_A)
KEY_B = DATA_B + keys_mod.check_char(DATA_B)
# shares KEY_A's 6-character prefix, so `DATA_A[:6]` is ambiguous between
# the two rows (prefix `aaaaaa` matches both)
DATA_A2 = "aaaaaa2222"
KEY_A2 = DATA_A2 + keys_mod.check_char(DATA_A2)


def row(key=KEY_A, text="A flying note", archived=False, marker_found=True,
        item="NOTE-001", file="items/note-a.md", line=3):
    return {
        "key": key,
        "text": text,
        "archived": archived,
        "snapshot": None,
        "text_changed": False,
        "source": {
            "item": item,
            "file": file,
            "line": line,
            "key": "NOTEKEY001",
            "marker_found": marker_found,
        },
    }


def rows(*seeds):
    return list(seeds)


def record_exists(root, key):
    return (root / ".refdes" / "navis" / f"{key}.yaml.gz").exists()


# ---------------------------------------------------------------------------
# select: the selector contract, same answers as every Navis verb
# ---------------------------------------------------------------------------


def test_select_full_key_prefix_and_ordinal():
    pool = [row(key=KEY_A), row(key=KEY_B, line=7)]
    assert navis_ops.select(pool, KEY_A) == (pool[0], [])
    assert navis_ops.select(pool, KEY_B[:6]) == (pool[1], [])
    assert navis_ops.select(pool, "2") == (pool[1], [])
    assert navis_ops.select(pool, KEY_A) == (pool[0], [])
    # an all-digit full key is a key, never the ordinal (slice 2 rule)
    digits = "0123456789" + keys_mod.check_char("0123456789")
    pool2 = [row(key=digits)] + pool
    assert navis_ops.select(pool2, digits) == (pool2[0], [])


def test_select_miss_and_ambiguity():
    pool = [row(key=KEY_A), row(key=KEY_A2)]
    assert navis_ops.select(pool, "9") == (None, [])
    assert navis_ops.select(pool, "zzzzzz") == (None, [])
    row2, ambiguous = navis_ops.select(pool, DATA_A[:6])
    assert row2 is None
    assert [r["key"] for r in ambiguous] == [KEY_A, KEY_A2]


# ---------------------------------------------------------------------------
# apply: one test per outcome kind
# ---------------------------------------------------------------------------


def test_apply_refused_no_write(tmp_path):
    result = navis_ops.apply(
        str(tmp_path), "archive", rows(row()), "1", allow_write=False
    )
    assert result.kind == "refused_no_write"
    assert result.row is None and not result.changed
    assert not record_exists(tmp_path, KEY_A)


def test_apply_not_found(tmp_path):
    result = navis_ops.apply(
        str(tmp_path), "archive", rows(row()), "9", allow_write=True
    )
    assert result.kind == "not_found"
    assert result.row is None and not result.changed
    assert not record_exists(tmp_path, KEY_A)


def test_apply_ambiguous(tmp_path):
    result = navis_ops.apply(
        str(tmp_path),
        "archive",
        rows(row(key=KEY_A), row(key=KEY_A2)),
        DATA_A[:6],
        allow_write=True,
    )
    assert result.kind == "ambiguous"
    assert [r["key"] for r in result.candidates] == [KEY_A, KEY_A2]
    assert not result.changed
    assert not record_exists(tmp_path, KEY_A)


def test_apply_keyless(tmp_path):
    target = row(key="")
    result = navis_ops.apply(
        str(tmp_path), "archive", [target], "1", allow_write=True
    )
    assert result.kind == "keyless"
    assert result.row is target
    assert not result.changed
    assert not record_exists(tmp_path, KEY_A)


def test_apply_ok_archive_writes_the_record(tmp_path):
    target = row()
    result = navis_ops.apply(
        str(tmp_path), "archive", [target], KEY_A, allow_write=True
    )
    assert result.kind == "ok"
    assert result.row is target
    assert result.changed is True
    path = tmp_path / ".refdes" / "navis" / f"{KEY_A}.yaml.gz"
    assert path.exists()
    record = yaml.safe_load(gzip.decompress(path.read_bytes()).decode("utf-8"))
    assert record["text"] == "A flying note"
    assert record["source"] == {"file": "items/note-a.md", "line": 3}
    assert record["item_key"] == "NOTEKEY001"


def test_apply_ok_restore_removes_the_record(tmp_path):
    archived = row(archived=True)
    navis_ops.apply(
        str(tmp_path), "archive", [row()], KEY_A, allow_write=True
    )
    assert record_exists(tmp_path, KEY_A)
    result = navis_ops.apply(
        str(tmp_path), "restore", [archived], KEY_A, allow_write=True
    )
    assert result.kind == "ok"
    assert result.row is archived
    assert result.changed is True
    assert not record_exists(tmp_path, KEY_A)


def test_apply_noop_archive_of_an_archived_navi(tmp_path):
    archived = row(archived=True, text="edited since")
    result = navis_ops.apply(
        str(tmp_path), "archive", [archived], KEY_A, allow_write=True
    )
    assert result.kind == "noop"
    assert result.row is archived
    assert result.changed is False
    assert not record_exists(tmp_path, KEY_A)


def test_apply_not_archived_restore(tmp_path):
    target = row()
    result = navis_ops.apply(
        str(tmp_path), "restore", [target], KEY_A, allow_write=True
    )
    assert result.kind == "not_archived"
    assert result.row is target
    assert not result.changed


def test_apply_orphan_refuses_and_keeps_the_record(tmp_path):
    navis_ops.apply(
        str(tmp_path), "archive", [row()], KEY_A, allow_write=True
    )
    orphan = row(archived=True, marker_found=False)
    result = navis_ops.apply(
        str(tmp_path), "restore", [orphan], KEY_A, allow_write=True
    )
    assert result.kind == "orphan"
    assert result.row is orphan
    assert not result.changed
    assert record_exists(tmp_path, KEY_A)


def test_apply_journal_pending(tmp_path):
    journal = tmp_path / ".refdes" / "editor-transaction"
    journal.mkdir(parents=True)
    (journal / "journal.yaml").write_text("stub", encoding="utf-8")
    result = navis_ops.apply(
        str(tmp_path), "archive", [row()], KEY_A, allow_write=True
    )
    assert result.kind == "journal_pending"
    assert "editor transaction" in result.detail
    assert not result.changed
    assert not record_exists(tmp_path, KEY_A)


def test_apply_error_malformed_key(tmp_path):
    target = row(key="not a key!!")
    result = navis_ops.apply(
        str(tmp_path), "archive", [target], "not a key!!", allow_write=True
    )
    assert result.kind == "error"
    assert result.row is target
    assert "not archivable" in result.detail
    assert not result.changed


def test_apply_error_store_path_is_a_file(tmp_path):
    (tmp_path / ".refdes").mkdir()
    (tmp_path / ".refdes" / "navis").write_text("not a dir", encoding="utf-8")
    result = navis_ops.apply(
        str(tmp_path), "archive", [row()], KEY_A, allow_write=True
    )
    assert result.kind == "error"
    assert "could not write the archive store" in result.detail
    assert not result.changed


def test_outcome_is_frozen_data(tmp_path):
    result = navis_ops.apply(str(tmp_path), "archive", [], "1", allow_write=True)
    assert result.kind == "not_found"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.kind = "ok"
