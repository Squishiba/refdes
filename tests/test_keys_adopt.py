"""Explicit surrogate-key adoption."""

from __future__ import annotations

import yaml
from conftest import write_project_config

from refdes import adopt as adopt_mod
from refdes import boards as boards_mod
from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import lifecycle, parse, seal
from refdes.schema import load_project

ADOPT_SCHEMA = """\
site: { title: Adoption test, out: _site }
link_types:
  refines: { inverse: refined_by, label: Refines }
  amends: { inverse: amended_by, label: Amends }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      title: { type: text, required: true }
    links:
      refines: [requirement]
  log:
    prefix: LOG
    label: Log
    append_only: true
    fields:
      summary: { type: text, required: true }
    links:
      amends: [log]
"""


def _project(root, *, seal_write=False):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=seal_write, reseal=False)
    return project


def _snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "_site" not in path.parts and "schema.json" not in path.name
    }


def _write_shape_project(root):
    write_project_config(root, ADOPT_SCHEMA)
    items = root / "items"
    items.mkdir()
    (items / "target.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - {id: REQ-001, title: Target}\n",
        encoding="utf-8",
    )
    (items / "flow.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-002\n"
        "    title: Flow list\n"
        "    refines: [\"REQ-001\"]\n",
        encoding="utf-8",
    )
    (items / "block.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-003\n"
        "    title: Block sequence\n"
        "    refines:\n"
        "      - 'REQ-001'\n",
        encoding="utf-8",
    )
    (items / "mapping.yaml").write_bytes(
        b"defaults: { type: requirement }\r\n"
        b"items:\r\n"
        b"  - {id: REQ-004, title: Flow mapping, refines: [REQ-001]}\r\n"
    )
    (items / "defaults.yaml").write_text(
        "defaults:\n"
        "  type: requirement\n"
        "  refines: [REQ-001]\n"
        "items:\n"
        "  - id: REQ-005\n"
        "    title: Defaults block\n",
        encoding="utf-8",
    )
    (items / "front-matter.md").write_text(
        "---\n"
        "id: REQ-006\n"
        "type: requirement\n"
        "title: Front matter\n"
        "refines: [REQ-001]\n"
        "---\n"
        "Prose REQ-001 stays bare.\n",
        encoding="utf-8",
    )


def test_adopt_preserves_supported_source_shapes_and_crlf(tmp_path, capsys):
    _write_shape_project(tmp_path)
    empty_seal = tmp_path / ".refdes" / "log-seal.yaml"
    empty_seal.parent.mkdir()
    empty_seal.write_text(seal.format_seals({}), encoding="utf-8")
    empty_seal_before = empty_seal.read_bytes()
    config = str(tmp_path / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    output = capsys.readouterr().out
    assert "minted 6 key(s)" in output
    assert "expanded 5 link reference(s) to composite form" in output
    assert "Review the diff before committing." in output
    assert ".refdes/log-seal.yaml" not in output

    project = _project(tmp_path)
    target_key = project.item_by_id("REQ-001").key
    assert target_key
    for item in project.local_items:
        assert item.key
    assert f'refines: ["REQ-001@{target_key}"]' in (
        tmp_path / "items" / "flow.yaml"
    ).read_text(encoding="utf-8")
    assert f"- 'REQ-001@{target_key}'" in (
        tmp_path / "items" / "block.yaml"
    ).read_text(encoding="utf-8")
    assert f"refines: [REQ-001@{target_key}]" in (
        tmp_path / "items" / "mapping.yaml"
    ).read_text(encoding="utf-8")
    assert f"refines: [REQ-001@{target_key}]" in (
        tmp_path / "items" / "defaults.yaml"
    ).read_text(encoding="utf-8")
    markdown = (tmp_path / "items" / "front-matter.md").read_text(encoding="utf-8")
    assert f"refines: [REQ-001@{target_key}]" in markdown.split("---")[1]
    assert "Prose REQ-001 stays bare." in markdown
    crlf = (tmp_path / "items" / "mapping.yaml").read_bytes()
    assert b"\r\n" in crlf
    assert b"\n" not in crlf.replace(b"\r\n", b"")
    marker_text = (tmp_path / keys_mod.ADOPTION_MARKER).read_text(encoding="utf-8")
    assert "Commit this file" in marker_text
    assert "Written by `refdes keys adopt`" in marker_text
    assert yaml.safe_load(marker_text) == {"adopted": True, "format": 1}
    assert empty_seal.read_bytes() == empty_seal_before
    assert cli_mod.main(["-c", config, "--no-write", "check"]) == 0


def test_adopt_rekeys_every_baseline_and_seal_and_reports_uncomparable(
    tmp_path, capsys
):
    write_project_config(
        tmp_path,
        ADOPT_SCHEMA
        + "boards:\n"
        "  board-a: { label: Board A, token: A }\n",
    )
    (tmp_path / "items" / "board-a").mkdir(parents=True)
    (tmp_path / "items" / "requirements.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    title: Unchanged\n"
        "  - id: REQ-002\n    title: Changed later\n",
        encoding="utf-8",
    )
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: Base log\n",
        encoding="utf-8",
    )
    (tmp_path / "items" / "board-a" / "log.yaml").write_text(
        "defaults: { type: log }\nitems:\n  - id: LOG-A-001\n    summary: Board log\n",
        encoding="utf-8",
    )
    before = _project(tmp_path, seal_write=True)
    assert lifecycle.stamp(before, kind="revision", name="rev-a").status == "stamped"
    path = tmp_path / "items" / "requirements.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Changed later", "Actually changed"),
        encoding="utf-8",
    )

    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    output = capsys.readouterr().out
    assert "rev-a (3/4 entries carried)" in output
    assert "uncomparable baseline entry rev-a: REQ-002" in output
    assert ".refdes/log-seal.yaml (1/1 entries carried)" in output
    assert ".refdes/log-seal-board-a.yaml (1/1 entries carried)" in output

    project = _project(tmp_path)
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.items["REQ-002"]["hash_format"] == 1
    assert all("id" in entry for key, entry in baseline.items.items() if key != "REQ-002")
    for board in ("", "board-a"):
        stored = seal.load_seals(project, board)
        assert all("id" in value for value in stored.values())


def test_adopt_drops_stale_memberships_reports_ambiguity_and_is_idempotent(
    tmp_path, capsys
):
    write_project_config(
        tmp_path,
        ADOPT_SCHEMA
        + "boards:\n"
        "  board-a: { label: Board A }\n"
        "  board-b: { label: Board B }\n"
        "workspaces:\n"
        "  product-a: { label: Product A }\n",
    )
    item_dir = tmp_path / "items" / "board-a"
    item_dir.mkdir(parents=True)
    (item_dir / "r.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n"
        "    former_ids: [REQ-OLD-001]\n"
        "    type: requirement\n"
        "    title: Current item\n"
        "    workspace: product-a\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / boards_mod.MANIFEST_FILE
    manifest_path.parent.mkdir(exist_ok=True)
    manifest_path.write_text(
        "boards:\n"
        "  REQ-001: board-a\n"
        "  REQ-OLD-001: board-b\n"
        "  LOST-001: board-b\n"
        "workspaces:\n"
        "  REQ-001: product-a\n"
        "  LOST-001: product-z\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    output = capsys.readouterr().out
    assert "membership manifests rebased:" in output
    assert ".refdes/boards.yaml (2/5 entries carried)" in output
    assert "unidentified membership entry boards: REQ-OLD-001" in output
    assert (
        "dropped 2 stale membership entries: "
        "boards: LOST-001, workspaces: LOST-001"
    ) in output

    project = _project(tmp_path)
    live_key = project.item_by_id("REQ-001").key
    manifest = boards_mod.load_manifest(project)
    assert manifest["boards"] == {
        live_key: {"id": "REQ-001", "board": "board-a"},
        "REQ-OLD-001": "board-b",
    }
    assert manifest["workspaces"] == {
        live_key: {"id": "REQ-001", "workspace": "product-a"},
    }
    adopted_bytes = _snapshot(tmp_path)

    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    second_output = capsys.readouterr().out
    assert "nothing to do -- project already adopted" in second_output
    assert "unidentified membership entry boards: REQ-OLD-001" in second_output
    assert _snapshot(tmp_path) == adopted_bytes


def test_adopt_dry_run_writes_nothing(tmp_path, capsys):
    _write_shape_project(tmp_path)
    before = _snapshot(tmp_path)
    config = str(tmp_path / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "keys", "adopt", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "would mint 6 key(s)" in output
    assert "files that would change:" in output
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / keys_mod.ADOPTION_MARKER).exists()


def test_adopt_mid_write_failure_restores_every_file_byte_for_byte(
    tmp_path, monkeypatch
):
    _write_shape_project(tmp_path)
    manifest_path = tmp_path / boards_mod.MANIFEST_FILE
    manifest_path.parent.mkdir(exist_ok=True)
    manifest_path.write_text("boards:\n  REQ-001: board-a\n", encoding="utf-8")
    before = _snapshot(tmp_path)
    real_write = adopt_mod.revise.write_rewrites

    def sabotage(rewrites):
        real_write(rewrites)
        assert yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["boards"] != {
            "REQ-001": "board-a"
        }
        raise OSError("sabotaged after every staged write")

    monkeypatch.setattr(adopt_mod.revise, "write_rewrites", sabotage)
    result = adopt_mod.apply(str(tmp_path))

    assert not result.ok
    assert "rolled back" in result.errors[0]
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / keys_mod.ADOPTION_MARKER).exists()


def test_adopt_is_idempotent_and_new_history_is_keyed_and_rename_safe(
    tmp_path, capsys
):
    write_project_config(tmp_path, ADOPT_SCHEMA)
    (tmp_path / "items").mkdir()
    item_path = tmp_path / "items" / "items.yaml"
    item_path.write_text(
        "items:\n"
        "  - id: LOG-001\n    type: log\n    summary: First log\n"
        "  - id: REQ-001\n    type: requirement\n    title: Target\n"
        "  - id: REQ-002\n    type: requirement\n    title: Source\n"
        "    refines: [REQ-001]\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    capsys.readouterr()
    adopted_bytes = _snapshot(tmp_path)

    assert cli_mod.main(["-c", config, "keys", "adopt"]) == 0
    assert "nothing to do -- project already adopted" in capsys.readouterr().out
    assert _snapshot(tmp_path) == adopted_bytes

    project = _project(tmp_path, seal_write=True)
    assert lifecycle.stamp(project, kind="revision", name="rev-b").status == "stamped"
    baseline = lifecycle.load_baseline(project, "rev-b")
    assert set(baseline.items) == {item.key for item in project.local_items}
    assert all("id" in entry and "key" not in entry for entry in baseline.items.values())
    sealed = seal.load_seals(project)
    log_key = project.item_by_id("LOG-001").key
    assert sealed[log_key]["id"] == "LOG-001"

    item_path.write_text(
        item_path.read_text(encoding="utf-8").replace("id: LOG-001", "id: LOG-009"),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", config, "check"]) == 0
    capsys.readouterr()
    renamed = _project(tmp_path)
    assert renamed.seal_violations == []
    diff = lifecycle.diff_against(renamed, lifecycle.load_baseline(renamed, "rev-b"))
    assert diff.relabelled == [("LOG-001", "LOG-009", log_key)]
    assert diff.added == []
    assert diff.removed == []
