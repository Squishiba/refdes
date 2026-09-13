"""The two-file config contract: refdes-project.yaml + refdes-schema.yaml.

These two tests are the safeguard for the split, so the first one deliberately
does NOT go through `conftest.write_project_config`. It writes both files by
hand, exactly as an author would, because a helper that no test bypasses proves
only that the helper works -- which is how this repo's citation tests once
passed against a hand-rolled schema field the shipped standard no longer had.
"""

from __future__ import annotations

import pytest

from refdes.schema import (
    LEGACY_CONFIG_ERROR,
    PROJECT_SETTINGS_NAME,
    SCHEMA_NAME,
    SchemaError,
    load_project,
)

# Written as literal file text, not built by a helper.
PROJECT_SETTINGS = """\
# The project marker: every setting lives here.
site:
  title: "Split Test"
  out: _split_site

id:
  width: 4

history:
  default: invalidate

units:
  preferred: [W, V]

standard:
  base: hardware
  version: 3
  presets: []

boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
    token: B

sigfigs: 5
"""

SCHEMA_OVERLAY = """\
# The optional overlay: the project's own schema, and nothing else.
types:
  audit_note:
    prefix: AN
    label: Audit Note
    fields:
      body_text: { type: text, required: true }
"""


def test_two_file_layout_loads_as_authored(tmp_path):
    """Both files written literally: every setting applies, and the overlay's
    own type joins the standard's vocabulary."""
    (tmp_path / PROJECT_SETTINGS_NAME).write_text(PROJECT_SETTINGS, encoding="utf-8")
    (tmp_path / SCHEMA_NAME).write_text(SCHEMA_OVERLAY, encoding="utf-8")

    project = load_project(start=str(tmp_path))

    # Settings, from refdes-project.yaml.
    assert project.title == "Split Test"
    assert project.out_dir == "_split_site"
    assert project.id_width == 4
    assert project.default_on_change == "invalidate"
    assert "W" in project.preferred_units
    assert project.sigfigs == 5
    assert project.standard_base == "hardware"
    assert project.standard_version == 3
    assert project.boards["board-b"].token == "B"

    # Types, from the standard the settings point at plus the overlay beside it.
    assert "requirement" in project.types
    assert "audit_note" in project.types
    assert project.types["audit_note"].prefix == "AN"
    assert project.types["audit_note"].fields["body_text"].required is True


def test_two_file_layout_without_an_overlay_file(tmp_path):
    """refdes-schema.yaml is optional: a standard-pinned project with no
    overlay of its own loads, and takes its whole vocabulary from the bundle."""
    (tmp_path / PROJECT_SETTINGS_NAME).write_text(PROJECT_SETTINGS, encoding="utf-8")

    project = load_project(start=str(tmp_path))

    assert "requirement" in project.types
    assert "audit_note" not in project.types


def test_a_legacy_refdes_yaml_is_rejected_naming_both_replacements(tmp_path):
    """The error is the feature: it is how a user discovers the split, so it
    has to name both files and say what goes in each."""
    (tmp_path / "refdes.yaml").write_text(
        PROJECT_SETTINGS + "\ntypes:\n  note: { prefix: NOTE, fields: {} }\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaError) as excinfo:
        load_project(start=str(tmp_path))

    message = str(excinfo.value)
    assert "refdes.yaml is retired" in message
    assert PROJECT_SETTINGS_NAME in message
    assert SCHEMA_NAME in message
    assert "types:" in message
    assert message == LEGACY_CONFIG_ERROR


def test_a_legacy_refdes_yaml_beside_a_marker_is_also_rejected(tmp_path):
    """Half-migrated is worse than not migrated: reading only the new file
    would leave the settings still sitting in the old one unsaid."""
    (tmp_path / PROJECT_SETTINGS_NAME).write_text(PROJECT_SETTINGS, encoding="utf-8")
    (tmp_path / "refdes.yaml").write_text("site: { title: Left behind }\n", encoding="utf-8")

    with pytest.raises(SchemaError, match="refdes.yaml is retired"):
        load_project(start=str(tmp_path))

    with pytest.raises(SchemaError, match="refdes.yaml is retired"):
        load_project(config_path=str(tmp_path / PROJECT_SETTINGS_NAME))


def test_types_left_in_the_settings_file_names_the_overlay(tmp_path):
    """A `types:` still in refdes-project.yaml is a setting that would silently
    stop applying, so it is an error naming where it belongs."""
    (tmp_path / PROJECT_SETTINGS_NAME).write_text(
        PROJECT_SETTINGS + "\ntypes:\n  note: { prefix: NOTE, fields: {} }\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaError, match=r"types does not belong here.*refdes-schema\.yaml"):
        load_project(start=str(tmp_path))


def test_a_setting_left_in_the_overlay_names_the_settings_file(tmp_path):
    (tmp_path / PROJECT_SETTINGS_NAME).write_text(PROJECT_SETTINGS, encoding="utf-8")
    (tmp_path / SCHEMA_NAME).write_text("sigfigs: 6\n", encoding="utf-8")

    with pytest.raises(
        SchemaError, match=r"refdes-schema\.yaml: 'sigfigs' is a project setting"
    ):
        load_project(start=str(tmp_path))
