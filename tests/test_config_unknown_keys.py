"""Unknown and wrong-typed keys in *nested* config blocks must be reported the
way top-level settings already are.

`refdes-project.yaml`'s top-level settings are validated: an unknown key is a
configuration error naming the key, with a did-you-mean hint (`_KNOWN_SETTINGS`
and the check in `schema._validate_settings`), and `release_gate:` extends the
same style one level deeper -- unknown rule, non-mapping rule, unknown subkey,
non-boolean value, all errors. `equations:` does it too.

Everything else in the two config files is read with a bare `.get()`, so a typo
in a nested key is not an error at all: `site.titel` silently leaves the title
at "Design Reference", `boards.<b>.labl` silently leaves the label at the
default, `standard.preset: [design-debate]` silently loads no preset. A
wrong-typed *block* is worse than silent -- `site: mysite`, `id: 3`,
`imports: {up: {pat: ../x}}`, `types: requirement`, `boards.board-a: whatever`
all raise a raw `AttributeError`/`ValueError`/`TypeError` out of
`load_project`, which `cli.main` only catches for `SchemaError`, so the user
gets a traceback instead of a configuration error.

These tests assert the behaviour we want, per block:

* an unknown key is a `SchemaError` naming the block path and the key;
* a close match gets a `Did you mean 'x'?` hint;
* a wrong-typed value or block is a `SchemaError` (exit 2 through the CLI),
  never a traceback.

They are expected to FAIL until the nested blocks are validated. The two
tests at the bottom (`test_model_blocks_...`, `test_legitimate_shapes_...`)
document the house style and the shapes the fix must keep accepting, and pass
today.
"""

from __future__ import annotations

import os

import pytest

from refdes import cli as cli_mod
from refdes.model import SchemaError
from refdes.schema import load_project

# A project small enough that any diagnostic is unambiguous: one type, one
# item, nothing optional turned on.
MIN_SETTINGS = """\
site: {title: T, out: _site}
id: {width: 3}
history: {default: invalidate}
units: {preferred: []}
"""

MIN_SCHEMA = """\
types:
  note:
    prefix: NTE
    fields:
      title: {type: text}
"""

ITEM = (
    "defaults: { type: note, prefix: NTE }\n"
    "items:\n  - id: NTE-001\n    title: A valid item.\n"
)


def _write(tmp_path, settings="", schema=MIN_SCHEMA, item=ITEM):
    """Write the two config files directly rather than through
    `write_project_config`: which file a key lives in is the thing under test
    here, and the split helper would route it either way."""
    (tmp_path / "refdes-project.yaml").write_text(
        MIN_SETTINGS + settings, encoding="utf-8"
    )
    if schema is not None:
        (tmp_path / "refdes-schema.yaml").write_text(schema, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    if item is not None:
        (items / "r.yaml").write_text(item, encoding="utf-8")
    return tmp_path


def _error(tmp_path) -> str:
    with pytest.raises(SchemaError) as exc:
        load_project(start=str(tmp_path))
    return str(exc.value)


def _unknown(tmp_path, path: str, key: str, hint: str | None = None):
    """An unknown nested key: a configuration error naming block.path and key."""
    message = _error(tmp_path)
    assert path in message, message
    assert key in message, message
    if hint is not None:
        assert f"Did you mean {hint!r}" in message, message


def _wrong_type(tmp_path, needle: str):
    """A wrong-typed value: a configuration error, not a raw exception."""
    message = _error(tmp_path)
    assert needle in message, message


def _schema(extra: str) -> str:
    return MIN_SCHEMA + extra


# ------------------------------------------------------------------- site


def test_site_unknown_key_is_an_error(tmp_path):
    _write(tmp_path, "site:\n  titel: Typo Test\n")
    _unknown(tmp_path, "site.titel", "titel", hint="title")


def test_site_second_unknown_key_is_an_error(tmp_path):
    """The orchestrator's repro: `them:` is not a site key at all, and no
    close match excuses it -- the project still has to hear about it."""
    _write(tmp_path, "site:\n  title: Fine\n  them: slate\n")
    _unknown(tmp_path, "site.them", "them")


def test_site_wrong_type_title_is_an_error(tmp_path):
    _write(tmp_path, "site:\n  title: {en: Typo}\n")
    _wrong_type(tmp_path, "site.title")


def test_site_nav_must_be_a_list(tmp_path):
    """`nav: index` currently becomes ['i','n','d','e','x']."""
    _write(tmp_path, "site:\n  nav: index\n")
    _wrong_type(tmp_path, "site.nav")


def test_site_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "site: mysite\n")
    _wrong_type(tmp_path, "site")


# --------------------------------------------------------------------- id


def test_id_unknown_key_is_an_error(tmp_path):
    _write(tmp_path, "id:\n  widht: 4\n")
    _unknown(tmp_path, "id.widht", "widht", hint="width")


def test_id_width_must_be_an_integer(tmp_path):
    """`width: four` is a ValueError out of int() today."""
    _write(tmp_path, "id:\n  width: four\n")
    _wrong_type(tmp_path, "id.width")


def test_id_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "id: 3\n")
    _wrong_type(tmp_path, "id")


# ----------------------------------------------------------------- history


def test_history_unknown_key_is_an_error(tmp_path):
    _write(tmp_path, "history:\n  defualt: invalidate\n")
    _unknown(tmp_path, "history.defualt", "defualt", hint="default")


def test_history_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "history: invalidate\n")
    _wrong_type(tmp_path, "history")


# ------------------------------------------------------------------- units


def test_units_unknown_key_is_an_error(tmp_path):
    _write(tmp_path, "units:\n  preferrd: [W]\n")
    _unknown(tmp_path, "units.preferrd", "preferrd", hint="preferred")


def test_units_preferred_must_be_a_list(tmp_path):
    """`preferred: ohm` becomes ['o','h','m'] today."""
    _write(tmp_path, "units:\n  preferred: ohm\n")
    _wrong_type(tmp_path, "units.preferred")


def test_units_aliases_must_be_a_mapping(tmp_path):
    _write(tmp_path, "units:\n  aliases: mil=thou\n")
    _wrong_type(tmp_path, "units.aliases")


def test_units_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "units: [W, V]\n")
    _wrong_type(tmp_path, "units")


# ---------------------------------------------------------------- standard


def test_standard_unknown_key_is_an_error(tmp_path):
    """`preset: [design-debate]` loads no preset and says nothing."""
    _write(tmp_path, "standard:\n  base: hardware\n  version: 3\n  preset: []\n", schema=None)
    _unknown(tmp_path, "standard.preset", "preset", hint="presets")


def test_standard_version_typo_names_the_typo(tmp_path):
    """Today: "standard.version must be a pinned integer, got None" -- the
    real problem is that the key was spelled `versoin`."""
    _write(tmp_path, "standard:\n  base: hardware\n  versoin: 3\n", schema=None)
    _unknown(tmp_path, "standard.versoin", "versoin", hint="version")


# ------------------------------------------------------------------ boards


def test_board_unknown_key_is_an_error(tmp_path):
    _write(tmp_path, "boards:\n  board-a:\n    labl: A\n    path: items/a\n")
    _unknown(tmp_path, "boards.board-a.labl", "labl", hint="label")


def test_board_entry_must_be_a_mapping(tmp_path):
    _write(tmp_path, "boards:\n  board-a: whatever\n")
    _wrong_type(tmp_path, "boards.board-a")


def test_boards_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "boards: board-a\n")
    _wrong_type(tmp_path, "boards")


# --------------------------------------------------------------- workspaces


def test_workspace_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        "item_layout: workspace\nworkspaces:\n  ws:\n    labl: W\n    boards: [board-a]\n",
    )
    _unknown(tmp_path, "workspaces.ws.labl", "labl", hint="label")


def test_workspace_shared_must_be_a_boolean(tmp_path):
    """`shared: "no"` is truthy, so it means yes today."""
    _write(tmp_path, 'item_layout: workspace\nworkspaces:\n  ws:\n    shared: "no"\n')
    _wrong_type(tmp_path, "workspaces.ws.shared")


def test_workspaces_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, "item_layout: workspace\nworkspaces: ws\n")
    _wrong_type(tmp_path, "workspaces")


# ----------------------------------------------------------------- imports


def test_imports_block_must_be_a_list(tmp_path):
    """The orchestrator's repro: a mapping where a list is expected raises
    `AttributeError: 'str' object has no attribute 'get'`."""
    _write(tmp_path, "imports:\n  up:\n    pat: ../x\n")
    _wrong_type(tmp_path, "imports")


def test_import_entry_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        "imports:\n  - name: up\n    items: ../x/items.json\n    pat: ../x\n",
    )
    _unknown(tmp_path, "imports", "pat")


def test_import_entry_must_be_a_mapping(tmp_path):
    _write(tmp_path, "imports:\n  - up\n")
    _wrong_type(tmp_path, "imports")


def test_imports_traceback_becomes_a_configuration_error(tmp_path, capsys):
    """Through the CLI: exit 2 and a `configuration error:` line, never a
    traceback on stderr."""
    _write(tmp_path, "imports:\n  up:\n    pat: ../x\n")
    code = cli_mod.main(
        ["-c", str(tmp_path / "refdes-project.yaml"), "--no-write", "check"]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "configuration error" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------- types:


def test_type_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefx: NTE\n    fields:\n      title: {type: text}\n",
    )
    _unknown(tmp_path, "types.note.prefx", "prefx", hint="prefix")


def test_type_unknown_key_coverable_typo(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    coverble: true\n"
        "    fields:\n      title: {type: text}\n",
    )
    _unknown(tmp_path, "types.note.coverble", "coverble", hint="coverable")


def test_type_entry_must_be_a_mapping(tmp_path):
    """`types.note: whatever` is a ValueError from a dict update today."""
    _write(tmp_path, schema="types:\n  note: whatever\n")
    _wrong_type(tmp_path, "types.note")


def test_types_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, schema="types: note\n")
    _wrong_type(tmp_path, "types")


# ------------------------------------------------- types.<name>.fields.<name>


def test_field_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n"
        "      title: {typ: text, requird: true}\n",
    )
    _unknown(tmp_path, "types.note.fields.title.requird", "requird", hint="required")


def test_field_on_change_typo_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n"
        "      title: {type: text, on_chang: invalidate}\n",
    )
    _unknown(
        tmp_path, "types.note.fields.title.on_chang", "on_chang", hint="on_change"
    )


def test_field_choices_typo_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n"
        "      status: {type: enum, choic: [a, b]}\n      title: {type: text}\n",
    )
    _unknown(
        tmp_path, "types.note.fields.status.choic", "choic", hint="choices"
    )


def test_field_required_when_typo_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n"
        "      status: {type: enum, choices: [a, b]}\n"
        "      title: {type: text, required_whn: {status: a}}\n",
    )
    _unknown(
        tmp_path,
        "types.note.fields.title.required_whn",
        "required_whn",
        hint="required_when",
    )


def test_field_entry_must_be_a_mapping(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n      title: text\n",
    )
    _wrong_type(tmp_path, "types.note.fields.title")


def test_fields_block_must_be_a_mapping(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields: title\n",
    )
    _wrong_type(tmp_path, "types.note.fields")


def test_field_type_value_is_validated(tmp_path):
    """`type: txt` is accepted today and the field behaves as text."""
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields:\n      title: {type: txt}\n",
    )
    _wrong_type(tmp_path, "types.note.fields.title.type")


# ------------------------------------------------------ types.<name>.body


def test_body_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields: {title: {type: text}}\n"
        "    body:\n      requird: true\n",
    )
    _unknown(tmp_path, "types.note.body.requird", "requird", hint="required")


def test_body_must_be_a_mapping(tmp_path):
    _write(
        tmp_path,
        schema="types:\n  note:\n    prefix: NTE\n    fields: {title: {type: text}}\n"
        "    body: invalidate\n",
    )
    _wrong_type(tmp_path, "types.note.body")


# ------------------------------------------------------------- link_types:


def test_link_type_unknown_key_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="link_types:\n  satisfies: {invers: satisfied_by, lbel: Satisfies}\n"
        + MIN_SCHEMA,
    )
    _unknown(tmp_path, "link_types.satisfies.invers", "invers", hint="inverse")


def test_link_type_trace_typo_is_an_error(tmp_path):
    _write(
        tmp_path,
        schema="link_types:\n  satisfies: {inverse: satisfied_by, trac: false}\n"
        + MIN_SCHEMA,
    )
    _unknown(tmp_path, "link_types.satisfies.trac", "trac", hint="trace")


def test_link_type_entry_must_be_a_mapping(tmp_path):
    _write(
        tmp_path,
        schema="link_types:\n  satisfies: whatever\n" + MIN_SCHEMA,
    )
    _wrong_type(tmp_path, "link_types.satisfies")


def test_link_types_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, schema="link_types: satisfies\n" + MIN_SCHEMA)
    _wrong_type(tmp_path, "link_types")


# -------------------------------------------------------------- field_sets:


def test_field_set_field_unknown_key_is_an_error(tmp_path):
    """A field_set's entries go through the same field-spec parsing as a
    type's own `fields:`, so they get the same validation."""
    _write(
        tmp_path,
        schema="field_sets:\n  common:\n    title: {typ: text, requird: true}\n"
        "types:\n  note:\n    prefix: NTE\n    include: [common]\n"
        "    fields:\n      body: {type: text}\n",
    )
    _unknown(tmp_path, "field_sets.common.title.requird", "requird", hint="required")


def test_field_set_must_be_a_mapping(tmp_path):
    _write(
        tmp_path,
        schema="field_sets:\n  common: whatever\n" + MIN_SCHEMA,
    )
    _wrong_type(tmp_path, "field_sets.common")


def test_field_sets_block_must_be_a_mapping(tmp_path):
    _write(tmp_path, schema="field_sets: common\n" + MIN_SCHEMA)
    _wrong_type(tmp_path, "field_sets")


# ---------------------------------------------------------------- CLI shape


def test_cli_reports_nested_unknown_key_as_configuration_error(tmp_path, capsys):
    """Whatever the fix looks like, the user-visible contract is the existing
    one for settings: exit 2, `configuration error:` on stderr, no traceback."""
    _write(tmp_path, "site:\n  titel: Typo Test\n")
    code = cli_mod.main(
        ["-c", str(tmp_path / "refdes-project.yaml"), "--no-write", "check"]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "configuration error" in captured.err
    assert "Traceback" not in captured.err


# ------------------------------------------------- already-correct behaviour


def test_model_blocks_are_still_validated(tmp_path):
    """`release_gate:` and `equations:` already do this; they are the style
    the rest of the blocks are being brought up to. Green today."""
    _write(tmp_path, "release_gate:\n  draft_itemz: {release: true}\n")
    message = _error(tmp_path)
    assert "draft_itemz" in message and "Did you mean 'draft_items'" in message

    _write(tmp_path, "equations:\n  e:\n    params: [x]\n    expr: x\n    nte: hi\n")
    message = _error(tmp_path)
    assert "equations.e.nte" in message


def test_legitimate_shapes_still_load(tmp_path):
    """The validation must not eat the shapes that are legal today: `null`
    deletes an inherited type/link type/field set, a board or workspace entry
    may be empty, and a project with no overlay file is the common case."""
    _write(
        tmp_path,
        "boards:\n  board-a: {}\n",
        schema="link_types:\n  satisfies: {inverse: satisfied_by}\n"
        "field_sets:\n  common: {title: {type: text}}\n"
        "types:\n  note:\n    prefix: NTE\n    fields: {title: {type: text}}\n"
        "  removed: null\n",
    )
    project = load_project(start=str(tmp_path))
    assert "note" in project.types
    assert "removed" not in project.types
    assert project.boards["board-a"].label == "board-a"


REPO = os.path.join(os.path.dirname(__file__), "..")


def test_this_repository_and_its_docs_site_still_load():
    """The two real projects in this repo, loaded verbatim: a config that was
    right yesterday has to load today, or the validation has eaten a legal
    shape. This is the acceptance test for the whole file."""
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    assert project.title.startswith("Example Board")
    assert project.standard_base == "hardware"
    assert project.standard_version == 3
    assert project.id_width == 3
    assert "W" in project.preferred_units
    assert project.boards["board-b"].token == "B"
    assert "log" in project.types and "requirement" in project.types
    assert project.types["log"].fields["board"].type == "text"

    docs = load_project(
        config_path=os.path.join(REPO, "docs-site", "refdes-project.yaml")
    )
    assert docs.title == "Refdes"
    assert docs.out_dir == "../_docs"
    assert docs.nav_order[:2] == ["index", "getting-started"]
    assert list(docs.types) == ["note"]
