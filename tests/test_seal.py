"""per-board seals.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import parse, seal
from refdes.schema import load_project


def test_seal_files_are_split_per_board(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    assert seal.load_seals(project, board="board-a") == {
        "LOG-A-001": project.item_by_id("LOG-A-001").content_hash
    }
    assert seal.load_seals(project, board="board-b") == {
        "LOG-B-001": project.item_by_id("LOG-B-001").content_hash
    }
    # No board: items keep using the base file, unchanged from before boards existed.
    assert seal.load_seals(project, board="") == {
        "LOG-X-001": project.item_by_id("LOG-X-001").content_hash
    }
    assert os.path.isfile(seal.seal_path(project, "board-a"))
    assert os.path.isfile(seal.seal_path(project, "board-b"))


def test_reseal_scoped_to_one_board_only_accepts_that_boards_edits(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    project2 = _build_at(sealed_board_project)
    project2.item_by_id("LOG-A-001").fields["summary"] = "edited"
    project2.item_by_id("LOG-B-001").fields["summary"] = "edited"
    build_mod.compute_hashes(project2)
    seal.verify(project2, write=True, reseal="board-a")

    assert "LOG-A-001" not in project2.seal_violations
    assert "LOG-B-001" in project2.seal_violations
    assert (
        seal.load_seals(project2, board="board-a")["LOG-A-001"]
        == project2.item_by_id("LOG-A-001").content_hash
    )
    # board-b's file is untouched: its edit was not accepted.
    assert (
        seal.load_seals(project2, board="board-b")["LOG-B-001"]
        != project2.item_by_id("LOG-B-001").content_hash
    )


def test_reseal_bare_accepts_every_boards_edits(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    project2 = _build_at(sealed_board_project)
    project2.item_by_id("LOG-A-001").fields["summary"] = "edited"
    project2.item_by_id("LOG-B-001").fields["summary"] = "edited"
    build_mod.compute_hashes(project2)
    seal.verify(project2, write=True, reseal=seal.RESEAL_ALL)

    assert not project2.seal_violations
    assert (
        seal.load_seals(project2, board="board-a")["LOG-A-001"]
        == project2.item_by_id("LOG-A-001").content_hash
    )
    assert (
        seal.load_seals(project2, board="board-b")["LOG-B-001"]
        == project2.item_by_id("LOG-B-001").content_hash
    )


def test_check_finds_legacy_seal_history_without_writing(sealed_board_project):
    """A project newly adopting boards: may still have entries sealed in the old,
    pre-split single file. `refdes check` (write=False) must recognize that
    history via lookback -- not treat the entry as new, not error -- and must
    not create or touch any seal file while doing it."""
    project = _build_at(sealed_board_project)
    legacy_hash = project.item_by_id("LOG-A-001").content_hash
    seal.save_seals(project, {"LOG-A-001": legacy_hash}, board="")
    assert not os.path.isfile(seal.seal_path(project, "board-a"))

    project2 = _build_at(sealed_board_project)  # build() defaults to seal_write=False
    assert not project2.seal_violations
    assert not os.path.isfile(seal.seal_path(project2, "board-a"))
    assert seal.load_seals(project2, board="") == {"LOG-A-001": legacy_hash}


def test_check_catches_an_edit_against_legacy_seal_history(sealed_board_project):
    """The lookback must actually compare, not just silence every legacy id."""
    project = _build_at(sealed_board_project)
    seal.save_seals(project, {"LOG-A-001": "0000000000000000"}, board="")

    project2 = _build_at(sealed_board_project)
    assert "LOG-A-001" in project2.seal_violations


def test_build_migrates_legacy_seal_entries_into_the_boards_own_file(sealed_board_project):
    project = _build_at(sealed_board_project)
    legacy_hash = project.item_by_id("LOG-A-001").content_hash
    seal.save_seals(project, {"LOG-A-001": legacy_hash}, board="")

    # A fresh project, built once with seal_write=True -- a real `refdes build`.
    project2 = load_project(config_path=str(sealed_board_project / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=True)

    assert seal.load_seals(project2, board="board-a") == {"LOG-A-001": legacy_hash}
    assert "LOG-A-001" not in seal.load_seals(project2, board="")


def _load_and_build(root, **kwargs):
    """Load and build in one pass with the given seal flags -- unlike
    `_build_at`, which always runs a default (no-reseal) build first, and so
    would record a violation before the caller's own flags ever applied."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, **kwargs)
    return project


def _empty_the_board_log(root, board, prefix):
    (root / "items" / board / "log.yaml").write_text(
        f"defaults: {{ type: log, prefix: {prefix} }}\nitems: []\n", encoding="utf-8"
    )


def test_deleting_a_sealed_entry_is_an_error_not_silent(sealed_board_project):
    """Editing a sealed entry was already a build error; deleting one outright
    was not detected at all -- a clean build, a clean audit, and an orphaned
    hash left behind in the seal file. Deletion is the louder half of the same
    tamper-evidence question, so it is reported the same way now."""
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-a", "LOG-A")

    project2 = _load_and_build(sealed_board_project, seal_write=False, reseal=False)
    assert any(
        "LOG-A-001" in d.message and "no item with that id" in d.message
        for d in project2.errors
    ), [str(d) for d in project2.errors]
    # A read-only check never mutates seal storage while reporting it.
    assert "LOG-A-001" in seal.load_seals(project2, board="board-a")


def test_deleting_a_sealed_entry_is_accepted_with_reseal(sealed_board_project):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-a", "LOG-A")

    project2 = _load_and_build(sealed_board_project, seal_write=True, reseal="board-a")
    assert not project2.errors, [str(d) for d in project2.errors]
    assert any("no longer in the project" in d.message for d in project2.diagnostics)
    assert "LOG-A-001" not in seal.load_seals(project2, board="board-a")
    # Scoping holds: another board's seals are untouched.
    assert "LOG-B-001" in seal.load_seals(project2, board="board-b")


def test_reseal_scoped_to_one_board_does_not_accept_another_boards_deletion(
    sealed_board_project,
):
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    _empty_the_board_log(sealed_board_project, "board-b", "LOG-B")

    project2 = _load_and_build(sealed_board_project, seal_write=True, reseal="board-a")
    assert any(
        "LOG-B-001" in d.message and "no item with that id" in d.message
        for d in project2.errors
    ), [str(d) for d in project2.errors]
    assert "LOG-B-001" in seal.load_seals(project2, board="board-b")


def test_the_violation_hint_names_a_command_the_printing_command_actually_has(
    sealed_board_project,
):
    """The hint used to read `run with --reseal`, and `refdes check` is one of
    the two commands that print it -- under `check`, following the advice
    verbatim is a usage dump and exit 2, because `check` has no `--reseal`.
    The message names `refdes build --reseal` instead, and the boarded case
    keeps its board scope."""
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)

    (sealed_board_project / "items" / "board-a" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-A }\n"
        "items:\n  - id: LOG-A-001\n    summary: edited\n",
        encoding="utf-8",
    )
    (sealed_board_project / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-X }\n"
        "items:\n  - id: LOG-X-001\n    summary: edited\n",
        encoding="utf-8",
    )

    # Read-only verification is what `refdes check` runs, and what raises both.
    project2 = _load_and_build(sealed_board_project, seal_write=False, reseal=False)
    boarded = [d.message for d in project2.errors if "LOG-A-001 is append-only" in d.message]
    unboarded = [
        d.message for d in project2.errors if "LOG-X-001 is append-only" in d.message
    ]
    assert boarded and unboarded, [str(d) for d in project2.errors]
    assert "run with refdes build --reseal board-a if the edit is deliberate" in boarded[0]
    assert "run with refdes build --reseal if the edit is deliberate" in unboarded[0]
    # The bare flag is what was wrong: nothing may suggest it again.
    for message in boarded + unboarded:
        assert "--reseal" not in message.replace("refdes build --reseal", "")

    # The deletion half names the same command, and was wrong in the same way.
    _empty_the_board_log(sealed_board_project, "board-b", "LOG-B")
    project3 = _load_and_build(sealed_board_project, seal_write=False, reseal=False)
    deleted = [d.message for d in project3.errors if "no item with that id" in d.message]
    assert deleted, [str(d) for d in project3.errors]
    assert (
        "restore it, or run with refdes build --reseal board-b if the removal "
        "is deliberate." in deleted[0]
    ), deleted[0]


def test_a_renumbered_entry_claimed_by_former_ids_is_not_a_deletion(tmp_path):
    """`former_ids:` is exactly the mechanism for an id retired in favour of a
    new one, so its old seal entry has not been deleted -- the entry is still
    in the project, under a new name."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "id: { width: 3 }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)

    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-009\n    former_ids: [LOG-001]\n    summary: first entry\n",
        encoding="utf-8",
    )
    project2 = _load_and_build(tmp_path, seal_write=False, reseal=False)
    assert not any("no item with that id" in d.message for d in project2.errors), [
        str(d) for d in project2.errors
    ]


def test_seal_storage_is_a_single_file_with_no_boards_registered(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  log: { prefix: LOG, append_only: true, "
        "fields: { summary: { type: text, required: true } } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)

    names = os.listdir(tmp_path / ".refdes")
    assert "log-seal.yaml" in names
    assert not any(n.startswith("log-seal-") for n in names)
    assert seal.load_seals(project, board="") == {
        "LOG-001": project.item_by_id("LOG-001").content_hash
    }


def test_keyed_seal_survives_display_id_rename_without_violation(tmp_path):
    key = keys_mod.mint()
    legacy_key = keys_mod.mint()
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields: { summary: { type: text, required: true } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    item_path = items / "log.yaml"
    item_path.write_text(
        "defaults: { type: log }\n"
        "items:\n"
        f"  - id: LOG-001\n    key: {key}\n    summary: First.\n"
        f"  - id: LOG-002\n    key: {legacy_key}\n    summary: Legacy-shaped.\n",
        encoding="utf-8",
    )
    project = _load_and_build(tmp_path, seal_write=False, reseal=False)
    seal.save_seals(
        project,
        {
            key: {
                "id": "LOG-001",
                "hash": project.item_by_id("LOG-001").content_hash,
                "hash_format": build_mod.HASH_FORMAT,
            },
            "LOG-002": project.item_by_id("LOG-002").content_hash,
        },
    )
    seal_path = tmp_path / ".refdes" / "log-seal.yaml"
    before = seal_path.read_text(encoding="utf-8")

    item_path.write_text(
        item_path.read_text(encoding="utf-8").replace("id: LOG-001", "id: LOG-009"),
        encoding="utf-8",
    )
    renamed = _load_and_build(tmp_path, seal_write=True, reseal=False)

    assert renamed.seal_violations == []
    assert not renamed.errors
    assert seal_path.read_text(encoding="utf-8") == before
    assert seal.load_seals(renamed) == {
        key: {
            "id": "LOG-001",
            "hash": renamed.item_by_id("LOG-009").content_hash,
            "hash_format": build_mod.HASH_FORMAT,
        },
        "LOG-002": renamed.item_by_id("LOG-002").content_hash,
    }


def test_write_verify_rejects_changed_key_and_content_without_fresh_seal(tmp_path):
    sealed_key = keys_mod.mint()
    changed_key = keys_mod.mint()
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields: { summary: { type: text, required: true } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    item_path = items / "log.yaml"
    item_path.write_text(
        "defaults: { type: log }\n"
        f"items:\n  - id: LOG-001\n    key: {sealed_key}\n    summary: First.\n",
        encoding="utf-8",
    )
    project = _load_and_build(tmp_path, seal_write=False, reseal=False)
    seal.save_seals(
        project,
        {
            sealed_key: {
                "id": "LOG-001",
                "hash": project.item_by_id("LOG-001").content_hash,
                "hash_format": build_mod.HASH_FORMAT,
            }
        },
    )
    seal_path = tmp_path / ".refdes" / "log-seal.yaml"
    before = seal_path.read_text(encoding="utf-8")
    item_path.write_text(
        item_path.read_text(encoding="utf-8")
        .replace(f"key: {sealed_key}", f"key: {changed_key}")
        .replace("summary: First.", "summary: Edited."),
        encoding="utf-8",
    )

    changed = _load_and_build(tmp_path, seal_write=True, reseal=False)

    assert changed.seal_violations == ["LOG-001"]
    assert any(
        f"key changed since it was sealed: was '{sealed_key}', now '{changed_key}'"
        in diagnostic.message
        for diagnostic in changed.errors
    )
    assert not any("no item with that id" in diagnostic.message for diagnostic in changed.errors)
    assert seal_path.read_text(encoding="utf-8") == before
    assert set(seal.load_seals(changed)) == {sealed_key}
    assert changed_key not in seal.load_seals(changed)
    assert "LOG-001" not in seal.load_seals(changed)


def test_renamed_keyed_seal_does_not_claim_a_new_item_reusing_its_old_id(tmp_path):
    original_key = keys_mod.mint()
    reused_id_key = keys_mod.mint()
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields: { summary: { type: text, required: true } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    item_path = items / "log.yaml"
    item_path.write_text(
        "defaults: { type: log }\n"
        f"items:\n  - id: LOG-001\n    key: {original_key}\n"
        "    summary: Original entry.\n",
        encoding="utf-8",
    )
    project = _load_and_build(tmp_path, seal_write=False, reseal=False)
    original_hash = project.item_by_id("LOG-001").content_hash
    seal.save_seals(
        project,
        {
            original_key: {
                "id": "LOG-001",
                "hash": original_hash,
                "hash_format": build_mod.HASH_FORMAT,
            }
        },
    )
    item_path.write_text(
        "defaults: { type: log }\n"
        "items:\n"
        f"  - id: LOG-005\n    key: {original_key}\n"
        "    summary: Original entry.\n"
        f"  - id: LOG-001\n    key: {reused_id_key}\n"
        "    summary: Different new entry.\n",
        encoding="utf-8",
    )

    reused = _load_and_build(tmp_path, seal_write=True, reseal=False)

    assert reused.seal_violations == []
    assert not reused.errors
    stored = seal.load_seals(reused)
    assert stored[original_key] == {
        "id": "LOG-001",
        "hash": original_hash,
        "hash_format": build_mod.HASH_FORMAT,
    }
    assert stored["LOG-001"] == reused.item_by_id("LOG-001").content_hash
    assert reused.item_by_id("LOG-005").content_hash == original_hash
    assert seal.resealed_ids(reused) == []


def test_deleting_a_sealed_items_key_reports_only_the_deleted_key(tmp_path):
    """A keyless item whose key-keyed seal entry still names the old key is a
    deleted key, not a changed one: the seal verifier stays out of the way of
    the §6 deleted-key report and never re-seals over the evidence."""
    sealed_key = keys_mod.mint()
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    fields: { summary: { type: text, required: true } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    item_path = items / "log.yaml"
    item_path.write_text(
        "defaults: { type: log }\n"
        f"items:\n  - id: LOG-001\n    key: {sealed_key}\n    summary: First.\n",
        encoding="utf-8",
    )
    project = _load_and_build(tmp_path, seal_write=False, reseal=False)
    seal.save_seals(
        project,
        {
            sealed_key: {
                "id": "LOG-001",
                "hash": project.item_by_id("LOG-001").content_hash,
                "hash_format": build_mod.HASH_FORMAT,
            }
        },
    )
    seal_path = tmp_path / ".refdes" / "log-seal.yaml"
    before = seal_path.read_text(encoding="utf-8")
    item_path.write_text(
        item_path.read_text(encoding="utf-8").replace(
            f"    key: {sealed_key}\n", ""
        ),
        encoding="utf-8",
    )

    deleted = _load_and_build(tmp_path, seal_write=True, reseal=False)

    mentions = [d.message for d in deleted.errors if "key deleted" in d.message]
    assert len(mentions) == 1
    assert sealed_key in mentions[0]
    assert not [d.message for d in deleted.errors if "key changed" in d.message], [
        d.message for d in deleted.errors
    ]
    assert seal_path.read_text(encoding="utf-8") == before
    assert set(seal.load_seals(deleted)) == {sealed_key}


# ------------------------------------- a new entry with errors never seals (3b)


SEAL_ERROR_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "    body: {}\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    append_only: true\n"
    "    fields:\n"
    "      summary: { type: text, required: true }\n"
    "    body: {}\n"
)

LOG_OK = (
    "defaults:\n  type: log\n  prefix: LOG\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First entry.\n    body: |\n"
    "      Worked on the layout.\n\n"
    "      ```calc\n      P = 12 V * 0.5 A | W\n      ```\n"
)

LOG_BROKEN = LOG_OK.replace("P = 12 V * 0.5 A | W", "P : W = 12 V * 0.5 A")


def _seal_error_project(tmp_path, log_text):
    write_project_config(tmp_path, SEAL_ERROR_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(log_text, encoding="utf-8")
    return tmp_path


def test_a_new_entry_with_an_error_is_not_sealed(tmp_path):
    """The trap: sealing an entry that this very build flagged with an ERROR
    turns the next fix into "modified since it was sealed" -- the author is
    punished for following the error's own instruction. A new entry with an
    error attributed to it stays unsealed."""
    root = _seal_error_project(tmp_path, LOG_BROKEN)
    project = _load_and_build(root, seal_write=True, reseal=False)
    assert [d for d in project.errors if d.item_id == "LOG-001"]
    assert any(
        "LOG-001 was not sealed because it has errors" in d.message
        for d in project.warnings
    ), [d.message for d in project.warnings]
    assert not seal.load_seals(project)


def test_an_unsealed_entry_with_errors_seals_on_the_first_clean_build(tmp_path):
    root = _seal_error_project(tmp_path, LOG_BROKEN)
    broken = _load_and_build(root, seal_write=True, reseal=False)
    assert not seal.load_seals(broken)
    (root / "items" / "log.yaml").write_text(LOG_OK, encoding="utf-8")
    fixed = _load_and_build(root, seal_write=True, reseal=False)
    assert not fixed.errors
    assert "LOG-001" in seal.load_seals(fixed)


def test_an_error_on_another_item_does_not_stop_this_entry_sealing(tmp_path):
    """Per-entry, not per-build: one broken file elsewhere must not freeze
    every healthy log entry out of sealing."""
    root = _seal_error_project(tmp_path, LOG_OK)
    (root / "items" / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Broken\n---\n\n"
        "```calc\nP = 3.3 V / 1.2 A | W\n```\n",
        encoding="utf-8",
    )
    project = _load_and_build(root, seal_write=True, reseal=False)
    assert [d for d in project.errors if d.item_id == "DEC-001"]
    assert "LOG-001" in seal.load_seals(project)
    assert not [d for d in project.warnings if "not sealed" in d.message]


def test_the_repro_rewrite_then_rebuild_needs_no_reseal(tmp_path):
    """The chunk 3 trap end to end: a new entry on the retired spelling
    errors and is NOT sealed; calc-rewrite fixes it (it refuses sealed
    entries); the rebuild is clean and seals -- no reseal, no punishment."""
    from refdes import calc_rewrite

    root = _seal_error_project(tmp_path, LOG_BROKEN)
    broken = _load_and_build(root, seal_write=True, reseal=False)
    assert [d for d in broken.errors if d.code == "retired_unit_spelling"]
    result = calc_rewrite.apply(str(root))
    assert result.ok, result.errors
    assert not result.sealed_entries
    fixed = _load_and_build(root, seal_write=True, reseal=False)
    assert not fixed.errors
    assert "LOG-001" in seal.load_seals(fixed)


def test_a_corrupt_seal_file_is_a_clean_cli_error_not_a_traceback(sealed_board_project, capsys):
    """Review #212 F2: a seal file that does not decode was a bare ValueError
    out of seal._load_seal_data, and main() printed it as a traceback (the
    recorded repro is in .scratch/f2-traceback.txt). It raises the project's
    SchemaError now, the same class boards/ids/lifecycle raise for their own
    corrupt store files, so main()'s SchemaError handler -- the path every
    config error takes -- prints one line and exits 2."""
    project = _build_at(sealed_board_project)
    build_mod.build(project, seal_write=True)
    Path(seal.seal_path(project, "board-a")).write_bytes(b"\xff")

    code = cli_mod.main(["-c", str(sealed_board_project / "refdes-project.yaml"), "check"])

    err = capsys.readouterr().err
    assert code == 2
    assert "configuration error" in err
    assert "log-seal-board-a.yaml" in err
    assert "seal file is not valid UTF-8" in err
    assert "Traceback" not in err


# ---------------------------------------------------------------- file modes
# PERM-OWNER-001: `save_seals` used to write through a NamedTemporaryFile,
# which creates at 0600, and copy the old file's mode before `os.replace`
# only when an old file existed -- so the first seal file in a tree kept the
# temp's 0600 while its siblings (`schema.json`, the write lock), written by
# ordinary `open()` calls, landed at the umask default. Under a 002 umask
# that left the file carrying the append-only guarantee as the one file in
# `.refdes/` the group could not read. The fix creates the temp itself with
# `O_CREAT | O_EXCL` at 0666 so the kernel applies the umask -- the temp
# creation must therefore never go back to a 0600-creating helper, and
# `os.umask` must stay untouched: it is process-wide, so reading it by
# mutation would mis-mode any other thread's concurrent file creations.


@contextmanager
def _umask(mask: int):
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.parametrize(
    ("umask", "expected"),
    [(0o002, 0o664), (0o022, 0o644)],
)
def test_a_new_seal_file_gets_the_umask_default_mode(sealed_flat_project, umask, expected):
    project = load_project(config_path=str(sealed_flat_project / "refdes-project.yaml"))
    path = seal.seal_path(project)
    assert not os.path.exists(path)
    with _umask(umask):
        assert seal.save_seals(project, {"LOG-001": "0" * 16})
    assert os.stat(path).st_mode & 0o777 == expected


def test_a_colliding_temp_name_is_retried_not_fatal(tmp_path, monkeypatch):
    """`O_EXCL` is what makes the temp creation collision-safe rather than
    clobbering, so the collision branch must retry, not die: a foreign file
    that happens to hold one roll of the name must not fail the write."""
    tokens = iter(["c" * 16])
    real_hex = seal.secrets.token_hex

    def once_colliding(_n):
        try:
            return next(tokens)
        except StopIteration:
            return real_hex(_n)

    decoy = tmp_path / f".log-seal-{'c' * 16}.tmp"
    decoy.write_text("", encoding="utf-8")
    monkeypatch.setattr(seal.secrets, "token_hex", once_colliding)
    fd, path = seal._create_temp(str(tmp_path))
    os.close(fd)
    assert path != str(decoy)  # retried onto its own name, not the decoy reused
    assert os.path.basename(path).startswith(".log-seal-") and path.endswith(".tmp")
    assert os.path.exists(path)


def test_saving_seals_never_reads_or_writes_the_process_umask(sealed_flat_project, monkeypatch):
    """The temp file gets its new-file mode from the kernel (`O_CREAT` mode
    filtered through the umask), not from reading the umask itself:
    `os.umask` is process-wide, so a set-and-restore read has a window in
    which another thread's file creation -- serve's ThreadingHTTPServer is
    one process, and `build.py` keeps thread-locals -- would land with the
    wrong mode. Pin that the whole write touches it zero times."""
    calls = []
    real = os.umask

    def spy(mask):
        calls.append(mask)
        return real(mask)

    monkeypatch.setattr(os, "umask", spy)
    project = load_project(config_path=str(sealed_flat_project / "refdes-project.yaml"))
    assert seal.save_seals(project, {"LOG-001": "0" * 16})
    assert calls == []


def test_a_rewritten_seal_file_keeps_the_mode_it_had(sealed_flat_project):
    """The other half: the new-file default must not start overwriting a mode
    someone deliberately set. 0640 is neither umask default, so a rewrite
    that recomputed instead of copied would land 0664 and fail here."""
    project = load_project(config_path=str(sealed_flat_project / "refdes-project.yaml"))
    path = seal.seal_path(project)
    with _umask(0o002):
        assert seal.save_seals(project, {"LOG-001": "0" * 16})
        os.chmod(path, 0o640)
        assert seal.save_seals(project, {"LOG-001": "1" * 16})
    assert os.stat(path).st_mode & 0o777 == 0o640
