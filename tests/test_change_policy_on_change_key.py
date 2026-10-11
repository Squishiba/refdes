from __future__ import annotations

from conftest import write_project_config
from helpers import _build_at

from refdes.parse import load_items
from refdes.schema import SchemaError, load_project


CONFIG = (
    "site: {title: T, out: _site}\n"
    "on_change: {default: ignore}\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      status: {type: enum, choices: [draft, live], default: draft}\n"
)


def _write_project(tmp_path, config: str, item: str):
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "note.yaml").write_text(item, encoding="utf-8")


def test_project_on_change_key_sets_the_schema_default(tmp_path):
    write_project_config(tmp_path, CONFIG)
    project = load_project(start=str(tmp_path))

    assert project.types["note"].fields["status"].on_change == "ignore"


def test_item_on_change_scalar_override(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change: invalidate\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")

    assert item.on_change_override == {"mode": "invalidate"}
    assert item.on_change_for("status", project.types["note"], "ignore") == "invalidate"


def test_item_on_change_field_override(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change:\n"
        "      fields:\n"
        "        status: log\n"
        "      reason: Rotates during bring-up.\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")

    assert item.on_change_override == {
        "fields": {"status": "log"},
        "reason": "Rotates during bring-up.",
    }
    assert item.on_change_for("status", project.types["note"], "ignore") == "log"


def test_old_item_history_override_errors_and_renames(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    history: ignore\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")
    messages = [d.message for d in project.errors]

    assert any("item-level history: was renamed to on_change:" in m for m in messages)
    assert item.on_change_override == {"mode": "ignore"}


def test_item_history_key_with_a_null_value_still_errors(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    history:\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")
    messages = [d.message for d in project.errors]

    assert any("item-level history: was renamed to on_change:" in m for m in messages)
    assert item.on_change_override == {}


def test_item_on_change_empty_value_errors_like_a_bad_mode(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change: \"\"\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")
    errors = [d for d in project.errors if "must be one of invalidate" in d.message]

    assert len(errors) == 1
    assert "on_change: ''" in errors[0].message
    assert item.on_change_override == {}


def test_on_change_override_inherited_from_defaults_is_reported_at_the_defaults_line(
    tmp_path,
):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults:\n"
        "  type: note\n"
        "  on_change: {fields: {status: log}}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "  - id: NOTE-002\n",
    )
    project = _build_at(tmp_path)
    warnings = [d for d in project.warnings if "has no 'reason'" in d.message]

    assert len(warnings) == 2
    # The defaults: block's own first key ("type: note") is line 2 -- not each
    # inheriting entry's line, which never wrote on_change: at all.
    assert {d.line for d in warnings} == {2}


def test_inherited_history_rename_error_is_reported_at_the_defaults_line(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults:\n"
        "  type: note\n"
        "  history: ignore\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "  - id: NOTE-002\n",
    )
    project = _build_at(tmp_path)
    errors = [d for d in project.errors if "was renamed to on_change:" in d.message]

    assert len(errors) == 2
    assert {d.line for d in errors} == {2}


def test_declared_history_field_keeps_owning_the_item_key(tmp_path):
    _write_project(
        tmp_path,
        CONFIG.replace(
            "      status: {type: enum, choices: [draft, live], default: draft}\n",
            "      status: {type: enum, choices: [draft, live], default: draft}\n"
            "      history: {type: text}\n",
        ),
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    history: a note kept as the field, not an override\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")

    assert item.fields["history"] == "a note kept as the field, not an override"
    assert item.on_change_override == {}
    assert not [d for d in project.errors if "renamed to on_change" in d.message]
    assert not [d for d in project.warnings if "unknown field" in d.message]


def test_old_project_history_key_errors_and_renames(tmp_path):
    write_project_config(
        tmp_path,
        CONFIG.replace("on_change: {default: ignore}\n", "history: {default: ignore}\n"),
    )

    try:
        load_project(start=str(tmp_path))
    except SchemaError as exc:
        assert "history: was renamed to on_change:" in str(exc)
    else:
        raise AssertionError("old project history: loaded")


def test_declared_on_change_field_takes_over_the_item_key(tmp_path):
    _write_project(
        tmp_path,
        CONFIG.replace(
            "      status: {type: enum, choices: [draft, live], default: draft}\n",
            "      status: {type: enum, choices: [draft, live], default: draft}\n"
            "      on_change: {type: text}\n",
        ),
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change: not-a-change-mode\n",
    )
    project = _build_at(tmp_path)
    item = project.item_by_id("NOTE-001")

    assert item.fields["on_change"] == "not-a-change-mode"
    assert item.on_change_override == {}
    assert not [d for d in project.errors if "must be one of invalidate" in d.message]


def test_item_override_is_parsed_without_building_the_site(tmp_path):
    _write_project(
        tmp_path,
        CONFIG,
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change: log\n",
    )
    project = load_project(start=str(tmp_path))
    load_items(project)

    assert project.item_by_id("NOTE-001").on_change_override == {"mode": "log"}
