"""A scalar `default:` on a collection-shaped field is a config error, not a value.

SCHEMA-VALID-004 (`in-prog-logs/current-main-resweep-schema-validation.tsv`,
reproduced at 8b6a52e). The exact repro -- a project overlay giving the
bundled standard's `tags` list field a string default:

    # refdes-schema.yaml
    types:
      decision:
        fields:
          tags: { type: list, default: "power, analog" }

`refdes --no-write check` reported `2 items, 0 errors, 0 warnings`, exit 0,
both items' `fields['tags']` held the *single* tag `'power, analog'` (a str),
and `refdes ls --tag analog` listed both items -- because tag matching is a
substring test, the wrong value looked right everywhere it could be looked
at. parse.py copies `fspec.default` straight into `item.fields` with no
shape test (parse.py:1106-1107/:1116), and the only collection-shape check
(`_reject_scalar_collection`) ran on *authored* values, not on the schema's
own default. The same scalar written on an item was already a build error
(`test_scalar_for_list_field.py`); the schema's `default:` was the one door
left open.

The fix fails at config load -- the place the author has to edit, which is
the schema, not any item -- once per schema rather than once per item, with
the same `types.<type>.fields.<field>.<key>` path convention every other
schema-load error uses, and the same refuse-don't-guess posture: a delimiter
guess would be right for `"power, analog"` and silently wrong for a tag
containing a comma.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import cli as cli_mod
from refdes.model import NON_SCALAR_FIELD_TYPES, SchemaError
from refdes.schema import load_project

# Bundled hardware@3 + an overlay defaulting `decision.tags`, i.e. the TSV
# repro verbatim: the field is the standard's own, only the default is the
# project's mistake.
BUNDLED_BAD_DEFAULT = """\
site: { title: Bad default, out: _site }
standard: { base: hardware, version: 3, presets: [] }
types:
  decision:
    fields:
      tags: { type: list, default: "power, analog" }
"""

BUNDLED_GOOD_DEFAULT = """\
site: { title: Good default, out: _site }
standard: { base: hardware, version: 3, presets: [] }
types:
  decision:
    fields:
      tags: { type: list, default: [power, analog] }
"""

# A hand-rolled schema, like the sibling item-side tests: the `tags` field's
# `type: list` is the fixture's own declaration, so nothing here depends on
# the bundled standard for the shape being checked. No default on `tags`
# here -- this is the schema that loads; each failing fixture edits it.
SCHEMA = """\
site: { title: Schema default shape, out: _site }
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title: { type: text, required: true }
      tags: { type: list, on_change: ignore }
      source: { type: text, default: datasheet }
    links: {}
"""

# The same schema with the TSV's mistake on a hand-rolled `list` field,
# without a comma: `refdes check` must still refuse it, but the substring
# consequence does not apply to it.
SCHEMA_COMMA_FREE_DEFAULT = SCHEMA.replace(
    "tags: { type: list, on_change: ignore }",
    'tags: { type: list, on_change: ignore, default: "power" }',
)

TWO_DECISIONS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-001\n"
    "    body: First decision, tags omitted.\n"
    "  - id: DEC-002\n"
    "    body: Second decision, tags omitted.\n"
)

ONE_COMPONENT = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: A part that omits tags\n"
)


def _project(tmp_path, schema: str, items_yaml: str):
    write_project_config(tmp_path, schema)
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "--no-write", "check"])


# ----------------------------------------------------------- the exact repro


def test_scalar_default_on_a_list_field_is_a_configuration_error(tmp_path, capsys):
    """SCHEMA-VALID-004 verbatim. Before the fix this printed
    `2 items, 0 errors, 0 warnings` and exited 0 while both items silently
    carried the single tag `'power, analog'`."""
    root = _project(tmp_path, BUNDLED_BAD_DEFAULT, TWO_DECISIONS)
    assert _check(root) == 2
    err = capsys.readouterr().err
    assert err.startswith("configuration error: types.decision.fields.tags.default")
    assert "must be a list, got 'power, analog'" in err
    assert "write it as default: [first, second]" in err
    # The comma consequence, same posture as the item-side diagnostic.
    assert "the comma is part of the value" in err


def test_direct_load_raises_schema_error_naming_the_default_path(tmp_path):
    """The check happens at schema load, not per item: `load_project` itself
    raises, with the same dotted-path convention as every other schema error,
    pointing at the line of config the author has to edit."""
    write_project_config(tmp_path, BUNDLED_BAD_DEFAULT)
    with pytest.raises(SchemaError) as excinfo:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert "types.decision.fields.tags.default" in str(excinfo.value)


# ------------------------------------------------------------------ controls


def test_a_list_default_fills_every_item_that_omits_the_field(tmp_path, capsys):
    """The other half of the pair, and the reason the error is a good one:
    the same schema written as a real list builds green, and every item that
    omits the field carries the two tags as a real list -- which is also
    what makes `ls --tag analog` return the right rows."""
    root = _project(tmp_path, BUNDLED_GOOD_DEFAULT, TWO_DECISIONS)
    assert _check(root) == 0
    assert "0 errors" in capsys.readouterr().out
    project = _build_at(root)
    for item in project.local_items:
        assert item.fields["tags"] == ["power", "analog"]


def test_a_scalar_default_on_a_scalar_field_is_untouched(tmp_path):
    """The check reads `FieldSpec.type`, not the mere presence of a default:
    `source: { type: text, default: datasheet }` is ordinary and stays
    ordinary -- this test fails the moment the check widens past
    NON_SCALAR_FIELD_TYPES."""
    root = _project(tmp_path, SCHEMA, ONE_COMPONENT)
    project = _build_at(root)
    assert not project.errors
    item = next(i for i in project.local_items if i.id == "CMP-010")
    assert item.fields["source"] == "datasheet"


# ---------------------------------------------------------------- other shapes


def test_a_mapping_default_is_refused_too(tmp_path):
    """A mapping is the other non-list YAML shape and just as much a
    collection-shaped mistake as a string."""
    schema = BUNDLED_BAD_DEFAULT.replace(
        'default: "power, analog"', "default: {primary: power}"
    )
    write_project_config(tmp_path, schema)
    with pytest.raises(SchemaError) as excinfo:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    message = str(excinfo.value)
    assert "must be a list, got {'primary': 'power'}" in message
    # No comma claim when there is no comma in the value.
    assert "substring" not in message


def test_a_comma_free_scalar_default_does_not_claim_a_substring_problem(tmp_path):
    """Same posture as `parse._reject_scalar_collection`: the substring
    consequence is named only when the value actually contains a comma --
    a search for `power` does find `tags: power`, and a diagnostic claiming
    otherwise would be a second wrong thing in a message whose job is to be
    believed."""
    _project(tmp_path, SCHEMA_COMMA_FREE_DEFAULT, ONE_COMPONENT)
    with pytest.raises(SchemaError) as excinfo:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    message = str(excinfo.value)
    assert "types.component.fields.tags.default" in message
    assert "must be a list, got 'power'" in message
    assert "substring" not in message


@pytest.mark.parametrize("field_type", sorted(NON_SCALAR_FIELD_TYPES))
def test_every_collection_typed_field_refuses_a_scalar_default(tmp_path, field_type):
    """Not a `tags` special case and not a `list` special case: the check
    reads `FieldSpec.type` against the one shared constant, so a scalar
    default is refused on every collection-shaped field type."""
    schema = (
        "site: { title: Shape, out: _site }\n"
        "types:\n"
        "  component:\n"
        "    prefix: CMP\n"
        "    label: Component\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        f'      extra: {{ type: {field_type}, default: "one, two" }}\n'
    )
    write_project_config(tmp_path, schema)
    with pytest.raises(SchemaError) as excinfo:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    assert f"types.component.fields.extra.default on the {field_type} field" in str(
        excinfo.value
    )
