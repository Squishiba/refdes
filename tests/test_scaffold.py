"""init, new, schema, presets -- and: refdes new, preset add/remove, preset-provided diagnostics.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os

import pytest
from helpers import _build_at_repo_schema

from refdes import cli as cli_mod
from refdes import parse, standards
from refdes import scaffold as scaffold_mod
from refdes.schema import SchemaError, load_project

# ------------------------------------------------ init, new, schema, presets

def test_latest_version_resolves_the_concrete_bundled_max():
    """Deliberately not a literal: this is the highest vN directory that
    actually ships, so hard-coding the number of the day just breaks on the
    next version bump without telling anyone anything."""
    bundled = [
        int(name[1:])
        for name in os.listdir(
            os.path.join(os.path.dirname(standards.__file__), "standards", "hardware")
        )
        if name.startswith("v")
    ]
    assert standards.latest_version("hardware") == max(bundled)
    assert standards.latest_version("hardware") >= 2


def test_available_presets_includes_design_debate():
    assert "design-debate" in standards.available_presets("hardware", 1)
    assert "design-debate" in standards.available_presets("hardware", 2)


def test_preset_providers_maps_names_to_the_preset():
    types, link_types = standards.preset_providers("hardware", 1)
    assert types["debate"] == "design-debate"
    assert types["option"] == "design-debate"
    assert link_types["raises"] == "design-debate"
    assert link_types["resolved_by"] == "design-debate"


def test_init_writes_the_exact_documented_file(tmp_path):
    path = scaffold_mod.init(str(tmp_path))
    assert path == str(tmp_path / "refdes.yaml")
    text = open(path, encoding="utf-8").read()
    assert "types:" not in text
    assert "link_types:" not in text
    assert "field_sets:" not in text
    assert "standard:" in text
    assert "base: hardware" in text
    # The concrete integer, never the word "latest" -- and read from the
    # bundle rather than hard-coded, so a version bump doesn't fail here.
    assert f"version: {standards.latest_version('hardware')}" in text
    assert "latest" not in text
    assert "presets: []" in text

    # The file must actually load and resolve to a real, usable schema.
    project = load_project(config_path=path)
    assert "requirement" in project.types
    assert "decision" in project.types


def test_init_standard_none_writes_the_escape_hatch(tmp_path):
    path = scaffold_mod.init(str(tmp_path), standard=None)
    text = open(path, encoding="utf-8").read()
    assert "standard: none" in text
    assert "base:" not in text


def test_init_with_preset_writes_it_into_the_list(tmp_path):
    path = scaffold_mod.init(str(tmp_path), standard="hardware", presets=["design-debate"])
    text = open(path, encoding="utf-8").read()
    assert "presets: [design-debate]" in text
    project = load_project(config_path=path)
    assert "debate" in project.types


def test_init_preset_with_standard_none_is_a_load_time_error(tmp_path):
    with pytest.raises(SchemaError, match="presets require a base standard"):
        scaffold_mod.init(str(tmp_path), standard=None, presets=["design-debate"])


def test_init_refuses_to_overwrite_an_existing_config(tmp_path):
    (tmp_path / "refdes.yaml").write_text("site: {title: t, out: _site}\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="already exists"):
        scaffold_mod.init(str(tmp_path))


def test_init_writes_vscode_yaml_schema_association(tmp_path):
    scaffold_mod.init(str(tmp_path))
    settings = (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8")
    data = json.loads(settings)
    schema_keys = list(data["yaml.schemas"])
    assert len(schema_keys) == 1
    schema_key = schema_keys[0]
    assert data["yaml.schemas"][schema_key] == ["items/**/*.yaml"]
    # An absolute, this-project-only path -- not a bare relative one that two
    # different refdes projects would produce byte-identically (finding 9).
    assert os.path.isabs(schema_key)
    assert os.path.normpath(schema_key) == os.path.normpath(
        str(tmp_path / ".refdes" / "schema.json")
    )


def test_init_two_projects_get_disambiguated_schema_paths(tmp_path):
    """Finding 9: every generated .vscode/settings.json pointed at the same
    relative './.refdes/schema.json', so redhat.vscode-yaml -- which doesn't
    reliably scope a relative schema path to the workspace folder that
    declared it -- could apply one project's schema to another's files when
    both happened to be open in the same VS Code session (a multi-root
    workspace, or just switching folders without a full reload)."""
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    scaffold_mod.init(str(proj_a))
    scaffold_mod.init(str(proj_b))

    settings_a = json.loads((proj_a / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    settings_b = json.loads((proj_b / ".vscode" / "settings.json").read_text(encoding="utf-8"))

    key_a = next(iter(settings_a["yaml.schemas"]))
    key_b = next(iter(settings_b["yaml.schemas"]))
    assert key_a != key_b, "two projects produced the identical, collision-prone schema key"


def test_cli_init_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    status = cli_mod.main(["init"])
    assert status == 0
    assert (tmp_path / "refdes.yaml").is_file()
    assert (tmp_path / ".vscode" / "settings.json").is_file()
    out = capsys.readouterr().out
    assert f"standard: hardware@{standards.latest_version('hardware')}" in out


# --------------------------------------------------------------- refdes new


def test_new_item_text_required_field_no_default_is_a_placeholder():
    project = _build_at_repo_schema()
    spec = project.types["bound"]
    text = scaffold_mod.new_item_text("bound", spec)
    assert "type: bound" in text
    assert "limit:  # required -- limit" in text


def test_new_item_text_hints_a_required_body_when_the_type_has_no_other_content():
    """requirement's only content field is body:, reserved rather than a
    normal schema field, so it never appears in the fields: loop above --
    this is the hint that fills the gap."""
    project = _build_at_repo_schema()
    spec = project.types["requirement"]
    text = scaffold_mod.new_item_text("requirement", spec)
    assert "required: the content itself goes here." in text


def test_new_item_text_hints_an_optional_body_otherwise():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "optional body." in text


def test_new_item_text_field_with_default_is_uncommented_with_the_default():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "status: proposed  # choices:" in text


def test_new_item_text_optional_field_is_commented_out():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# date:  # date" in text


def test_new_item_text_required_when_field_notes_the_condition():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# rationale:" in text
    assert "required when status is 'rejected'" in text


def test_new_item_text_links_are_commented_out_with_target_hint():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# satisfies: []  # target: requirement" in text


def test_cli_new_unknown_type_reports_a_hint(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "new", "decisoin"])
    assert status == 1
    err = capsys.readouterr().err
    assert "unknown type 'decisoin'" in err
    assert "Did you mean 'decision'?" in err


def test_cli_new_known_type_prints_scaffold(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "new", "requirement"])
    assert status == 0
    out = capsys.readouterr().out
    assert "type: requirement" in out


# ------------------------------------------------------- preset add/remove


def test_add_preset_appends_to_the_list(tmp_path):
    scaffold_mod.init(str(tmp_path))
    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: [design-debate]" in text


def test_add_preset_unknown_name_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path))
    with pytest.raises(SchemaError, match="does not exist"):
        scaffold_mod.add_preset(str(tmp_path), "nope-preset")


def test_add_preset_already_selected_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    with pytest.raises(SchemaError, match="already selected"):
        scaffold_mod.add_preset(str(tmp_path), "design-debate")


def test_add_preset_preserves_hand_written_comments(tmp_path):
    scaffold_mod.init(str(tmp_path))
    config_path = tmp_path / "refdes.yaml"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("site:", "# A hand-written comment nobody wants lost.\nsite:")
    config_path.write_text(text, encoding="utf-8")

    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    after = config_path.read_text(encoding="utf-8")
    assert "# A hand-written comment nobody wants lost." in after


def test_remove_preset_removes_from_the_list(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text


def test_remove_preset_not_selected_is_an_error(tmp_path):
    scaffold_mod.init(str(tmp_path))
    with pytest.raises(SchemaError, match="not currently selected"):
        scaffold_mod.remove_preset(str(tmp_path), "design-debate")


def test_remove_preset_reports_orphaned_items_before_writing(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    diagnostics = scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    assert any(
        "unknown type 'debate'" in d.message and "design-debate" in d.message
        for d in diagnostics
    )
    # The report ran, but the config change still applied -- this command's
    # job is to surface the consequence, not block an author who already
    # decided to accept it.
    text = (tmp_path / "refdes.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text
    # No leftover scratch file.
    assert not (tmp_path / "refdes.yaml.scratch").exists()


def test_cli_standard_add_and_remove_preset(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    config = str(tmp_path / "refdes.yaml")
    status = cli_mod.main(["-c", config, "standard", "add-preset", "design-debate"])
    assert status == 0
    assert "design-debate" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 0
    assert "presets: []" in (tmp_path / "refdes.yaml").read_text(encoding="utf-8")


def test_cli_standard_remove_preset_exit_code_reflects_errors(tmp_path):
    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes.yaml")
    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 1


# ---------------------------------------------- preset-provided diagnostics


def test_unknown_type_matching_a_preset_names_it(tmp_path):
    scaffold_mod.init(str(tmp_path))  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "unknown type 'debate'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )


def test_unknown_type_with_no_preset_match_is_the_ordinary_message(tmp_path):
    scaffold_mod.init(str(tmp_path))
    items = tmp_path / "items"
    items.mkdir()
    (items / "x.md").write_text(
        "---\nid: X-001\ntype: totallymadeup\ntitle: t.\n---\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    msg = next(d.message for d in project.errors if "unknown type" in d.message)
    assert "provided by" not in msg


def test_unknown_link_matching_a_preset_names_it(tmp_path):
    scaffold_mod.init(str(tmp_path))  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: t.\nstatus: accepted\n"
        "resolved_by: []\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "unknown field 'resolved_by'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )
