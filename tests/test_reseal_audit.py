"""Accepted seal overrides must leave durable evidence, including after reload."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from refdes import build as build_mod
from refdes import cli, parse, seal
from refdes import keys as keys_mod
from refdes.schema import load_project


def _load(root, **kwargs):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, **kwargs)
    return project


def _edit(root, board="board-a", old="first entry", new="edited entry"):
    path = root / "items" / board / "log.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


@pytest.mark.parametrize("adopted", [False, True])
def test_reseal_is_durable_and_audit_visible(sealed_board_project, capsys, adopted):
    root = sealed_board_project
    config = str(root / "refdes-project.yaml")
    original = _load(root, seal_write=True)
    if adopted:
        assert cli.main(["-c", config, "keys", "adopt"]) == 0
    item = original.item_by_id("LOG-A-001")
    old_hash = item.content_hash
    _edit(root)
    assert cli.main(["-c", config, "build", "--reseal", "board-a"]) == 0
    capsys.readouterr()

    fresh = _load(root)
    new_hash = fresh.item_by_id("LOG-A-001").content_hash
    assert old_hash != new_hash
    assert seal.resealed_ids(fresh) == []  # accepted, no outstanding drift
    events = seal.load_reseals(fresh, "board-a")
    assert len(events) == 1
    event = events[0]
    assert event["id"] == "LOG-A-001"
    assert event["key"] == fresh.item_by_id("LOG-A-001").key
    assert event["action"] == "edit"
    assert event["old_hash"] == old_hash
    assert event["new_hash"] == new_hash
    assert event["new_hash_format"] == build_mod.HASH_FORMAT
    assert datetime.fromisoformat(event["occurred_at"]).tzinfo == timezone.utc
    stored = yaml.safe_load(Path(seal.seal_path(fresh, "board-a")).read_text())
    assert stored["reseals"] == events
    assert seal.load_reseals(fresh, "board-b") == []

    before = Path(seal.seal_path(fresh, "board-a")).read_bytes()
    assert cli.main(["-c", config, "audit"]) == 0
    output = capsys.readouterr().out
    accepted = output.split("Accepted append-only reseals (durable history):", 1)[1]
    assert "LOG-A-001 [board-a]" in accepted
    assert old_hash in accepted and new_hash in accepted
    assert event["occurred_at"] in accepted
    assert Path(seal.seal_path(fresh, "board-a")).read_bytes() == before


def test_repeated_edits_and_reverts_append_without_erasing_events(sealed_board_project):
    root = sealed_board_project
    first = _load(root, seal_write=True)
    a = first.item_by_id("LOG-A-001").content_hash
    _edit(root)
    second = _load(root, seal_write=True, reseal="board-a")
    b = second.item_by_id("LOG-A-001").content_hash
    event = seal.load_reseals(second, "board-a")[0]
    _edit(root, old="edited entry", new="first entry")
    _load(root, seal_write=True, reseal="board-a")
    _edit(root)
    third = _load(root, seal_write=True, reseal="board-a")
    events = seal.load_reseals(third, "board-a")
    assert events[0] == event
    assert [(e["old_hash"], e["new_hash"]) for e in events] == [(a, b), (b, a), (a, b)]
    path = Path(seal.seal_path(third, "board-a"))
    before = path.read_bytes()
    _load(root, seal_write=True, reseal=seal.RESEAL_ALL)
    _load(root, seal_write=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize("flags", [["--dry-run"], ["--no-write"]])
def test_preview_reseal_records_nothing_and_does_not_claim_acceptance(
    sealed_board_project,
    flags,
    capsys,
):
    root = sealed_board_project
    project = _load(root, seal_write=True)
    path = Path(seal.seal_path(project, "board-a"))
    before = path.read_bytes()
    _edit(root)
    command = ["-c", str(root / "refdes-project.yaml")]
    command += [flag for flag in flags if flag == "--no-write"]
    command += ["build", "--reseal", "board-a"]
    command += [flag for flag in flags if flag == "--dry-run"]
    assert cli.main(command) == 0
    output = capsys.readouterr().out
    assert "would reseal" in output
    assert "No seal or audit record was written" in output
    assert "This is recorded in the audit output" not in output
    assert path.read_bytes() == before
    fresh = _load(root)
    assert seal.load_reseals(fresh, "board-a") == []
    assert seal.resealed_ids(fresh) == ["LOG-A-001"]


def test_board_scoping_does_not_record_another_boards_drift(sealed_board_project):
    root = sealed_board_project
    _load(root, seal_write=True)
    _edit(root)
    _edit(root, board="board-b")
    project = _load(root, seal_write=True, reseal="board-a")
    assert project.seal_violations == ["LOG-B-001"]
    assert len(seal.load_reseals(project, "board-a")) == 1
    assert seal.load_reseals(project, "board-b") == []


def test_accepted_removal_preserves_previous_edits_and_removed_hash(sealed_board_project, capsys):
    root = sealed_board_project
    _load(root, seal_write=True)
    _edit(root)
    edited = _load(root, seal_write=True, reseal="board-a")
    edit = seal.load_reseals(edited, "board-a")[0]
    (root / "items" / "board-a" / "log.yaml").write_text("items: []\n", encoding="utf-8")
    removed = _load(root, seal_write=True, reseal="board-a")
    assert seal.load_seals(removed, "board-a") == {}
    events = seal.load_reseals(removed, "board-a")
    assert events[0] == edit
    assert events[1]["action"] == "remove"
    assert events[1]["old_hash"] == edit["new_hash"]
    assert events[1]["new_hash"] is None
    assert cli.main(["-c", str(root / "refdes-project.yaml"), "audit"]) == 0
    output = capsys.readouterr().out
    assert edit["old_hash"] in output and edit["new_hash"] in output
    assert "now (removed)" in output


def test_adoption_and_seal_rewrites_preserve_history(sealed_board_project):
    root = sealed_board_project
    _load(root, seal_write=True)
    _edit(root)
    project = _load(root, seal_write=True, reseal="board-a")
    events = seal.load_reseals(project, "board-a")
    assert cli.main(["-c", str(root / "refdes-project.yaml"), "keys", "adopt"]) == 0
    adopted = _load(root)
    assert seal.load_reseals(adopted, "board-a") == events
    seal.save_seals(adopted, seal.load_seals(adopted, "board-a"), "board-a")
    assert seal.load_reseals(_load(root), "board-a") == events


def test_keyed_rename_preserves_the_event_time_label_and_identity(sealed_board_project, capsys):
    root = sealed_board_project
    _load(root, seal_write=True)
    config = str(root / "refdes-project.yaml")
    assert cli.main(["-c", config, "keys", "adopt"]) == 0
    _edit(root)
    edited = _load(root, seal_write=True, reseal="board-a")
    events = seal.load_reseals(edited, "board-a")
    _edit(root, old="LOG-A-001", new="LOG-A-002")
    renamed = _load(root, seal_write=True)
    assert renamed.seal_violations == []
    assert seal.load_reseals(renamed, "board-a") == events
    assert events[0]["id"] == "LOG-A-001"
    assert events[0]["key"] == renamed.item_by_id("LOG-A-002").key
    capsys.readouterr()
    assert cli.main(["-c", config, "audit"]) == 0
    assert "LOG-A-001 [board-a]" in capsys.readouterr().out


def test_base_history_survives_lazy_migration_and_undeclared_board(sealed_board_project):
    root = sealed_board_project
    project = _load(root)
    item = project.item_by_id("LOG-A-001")
    seal.save_seals(project, {item.id: item.content_hash})
    _edit(root)
    # Accept in the base file, then let a normal build migrate the active seal.
    project = _load(root)
    item = project.item_by_id("LOG-A-001")
    item.board = ""
    seal.verify(project, write=True, reseal=seal.RESEAL_ALL)
    events = seal.load_reseals(project)
    assert len(events) == 1
    migrated = _load(root, seal_write=True)
    assert item.id not in seal.load_seals(migrated)
    assert item.id in seal.load_seals(migrated, "board-a")
    assert seal.load_reseals(migrated) == events
    # Historical board files are still reported when a board is retired.
    seal.save_seals(migrated, {}, "retired", events=events)
    assert ("retired", events[0]) in seal.reseal_history(migrated)


def test_failed_seal_replacement_keeps_old_hash_and_history(sealed_board_project, monkeypatch):
    root = sealed_board_project
    project = _load(root, seal_write=True)
    path = Path(seal.seal_path(project, "board-a"))
    before = path.read_bytes()
    _edit(root)

    def fail_replace(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(seal.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        _load(root, seal_write=True, reseal="board-a")
    assert path.read_bytes() == before
    assert seal.load_reseals(project, "board-a") == []


def test_hash_format_upgrade_preserves_history_without_recording_an_edit(sealed_board_project):
    root = sealed_board_project
    _load(root, seal_write=True)
    _edit(root)
    project = _load(root, seal_write=True, reseal="board-a")
    events = seal.load_reseals(project, "board-a")
    item = project.item_by_id("LOG-A-001")
    older_hash = keys_mod.hash_in_format(item, project, build_mod.HASH_FORMAT - 1)
    seal.save_seals(
        project,
        {
            item.id: {
                "hash": older_hash,
                "hash_format": build_mod.HASH_FORMAT - 1,
            }
        },
        "board-a",
    )
    upgraded = _load(root, seal_write=True, reseal=seal.RESEAL_ALL)
    assert upgraded.seal_violations == []
    assert seal.load_reseals(upgraded, "board-a") == events
    assert seal.load_seals(upgraded, "board-a")[item.id]["hash"] == item.content_hash


def test_reseal_cannot_record_acceptance_of_key_corruption(sealed_board_project):
    root = sealed_board_project
    _load(root, seal_write=True)
    config = str(root / "refdes-project.yaml")
    assert cli.main(["-c", config, "keys", "adopt"]) == 0
    original = _load(root)
    old_key = original.item_by_id("LOG-A-001").key
    path = Path(seal.seal_path(original, "board-a"))
    before = path.read_bytes()
    _edit(root, old=old_key, new=keys_mod.mint())
    _edit(root)
    corrupt = _load(root, seal_write=True, reseal=seal.RESEAL_ALL)
    assert "LOG-A-001" in corrupt.seal_violations
    assert seal.load_reseals(corrupt, "board-a") == []
    assert path.read_bytes() == before


def test_malformed_history_is_never_silently_discarded(sealed_board_project):
    root = sealed_board_project
    project = _load(root, seal_write=True)
    path = Path(seal.seal_path(project, "board-a"))
    path.write_text(path.read_text() + "reseals: corrupted\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="malformed reseal history"):
        seal.save_seals(project, {}, "board-a")
    assert path.read_bytes() == before
