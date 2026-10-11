"""No user-facing message may carry a Python repr.

The config/schema-validation family, following #83's fix of the same defect
in the item-level diagnostics family (`build.py`). A message a human reads
has to be prose: the valid values are named in declared order, comma-joined,
never printed as a `['error', 'warning', 'info']` repr.

`build.py`'s two sites are pinned in `test_build.py`; the project-settings
and `standard.base` sites in `test_project_settings.py` and
`test_standards.py`; the `check_severity` pair in
`test_check_severity_status.py`. The rest are here, including two in
`configcheck.py` -- see `test_body_on_change_outside_the_modes_is_named_in_prose`
for why that module, not `schema.py`, is what a user reads for a `body:`
`on_change` mistake.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import configcheck as configcheck_mod
from refdes.schema import SchemaError, load_project

BASE = (
    "site: {title: T, out: _site}\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      status: {type: enum, choices: [draft, live], default: draft}\n"
)


def _load(tmp_path, extra: str):
    write_project_config(tmp_path, BASE + extra)
    with pytest.raises(SchemaError) as exc:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    return str(exc.value)


def test_field_on_change_outside_the_modes_is_named_in_prose(tmp_path):
    message = _load(tmp_path, "      title: {type: text, on_change: maybe}\n")
    assert "types.note.fields.title.on_change must be one of " in message
    assert "invalidate, log, ignore, got 'maybe'" in message
    assert "['" not in message


def test_body_on_change_outside_the_modes_is_named_in_prose(tmp_path):
    """`configcheck.BlockChecker.mode()` validates this key before the type
    spec is ever built, so this is the message a user actually reads for
    `body: {on_change: ...}` -- not `schema.py`'s later same-named check.
    Both are fixed; this one is the one that is reachable."""
    message = _load(tmp_path, "    body: {on_change: maybe}\n")
    assert "types.note.body.on_change must be one of " in message
    assert "invalidate, log, ignore" in message
    assert "['" not in message


def test_field_type_outside_the_declared_types_is_named_in_prose(tmp_path):
    """Named in *declared* order (the map's own order, `enum` last), not
    `sorted()` and not a repr."""
    message = _load(tmp_path, "      title: {type: strng, on_change: invalidate}\n")
    assert "types.note.fields.title.type must be one of the field types " in message
    assert "text, person, limit, quantity, date, list, options, checks, citations, tasks, enum" in message
    assert "got 'strng'" in message
    assert "['" not in message


def test_field_types_remain_a_set_for_membership_checks():
    """The new ordered tuple must not have replaced the frozenset: it is
    declared order *for messages*, while membership tests want O(1) and do
    not care about order."""
    assert configcheck_mod.FIELD_TYPES == frozenset(configcheck_mod.FIELD_TYPE_ORDER)
    assert set(configcheck_mod.FIELD_TYPE_ORDER) == configcheck_mod.FIELD_TYPES
    assert configcheck_mod.FIELD_TYPE_ORDER != tuple(sorted(configcheck_mod.FIELD_TYPES))


def test_item_on_change_mode_outside_the_modes_is_named_in_prose(tmp_path):
    """The item-level half: this one is a `project.error` against an item
    rather than a load-time `SchemaError`, and lives in `parse.py`."""
    write_project_config(tmp_path, BASE)
    items = tmp_path / "items"
    items.mkdir()
    (items / "note.yaml").write_text(
        "defaults: {type: note}\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    on_change: maybe\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    messages = [d.message for d in project.errors]
    assert any(
        "on_change: 'maybe' must be one of invalidate, log, ignore" in m
        for m in messages
    ), messages
    assert not any("['" in m for m in messages), messages
