"""A list-of-strings field refuses an element that is not a string.

Run 6a's B6 and F9 are the same keystroke in the two halves of the schema: an
element written in the shape of the *mapping*-shaped field sitting beside it.
On `hardware@3` the list-of-strings fields are `tags:` (every type) and
`refdes:` (component) -- `type: list`, which the emitted schema declares as an
array of string (`schema_json._FIELD_TYPE_MAP`) -- and the fifteen link verbs,
which the same emission declares the same way.

B6 was the silent half. The exact repro, on a v3 `refdes init` project:

    items/one.yaml
      items:
      - id: CMP-001
        type: component
        title: TPS62130
        status: selected
        part_number: TPS62130DRRT
        tags:
          - power
          - name: not-a-string     # a mapping, where the schema says string
            verdict: x

`refdes check` and `refdes build` both reported `0 errors` and exited 0; the
built page rendered the tags row as a Python dict repr, and `refdes ls --tag x`
*matched the item on the mapping's value*. The asymmetry that made it a bug:
the scalar form of the same field is refused by name (`field 'tags' is a list
field ... write it as a list`, `parse._reject_scalar_collection`), and the four
mapping-shaped fields refuse a wrong-typed *element* by name
(`options[0]: ... is not an option`, `build.validate_items`) -- the string-shaped
fields simply had no element check.

F9 was the loud half, on a link verb with the same element: the entry is
caught, but by the dangling-reference rule, quoting the loader's own
line-tagged dict -- `satisfies points at "{'name': ..., '__line__': 6}"` --
because `parse._build_item` stringified every target with `str(t)`. Internal
bookkeeping in the message a person has to act on.

The fixes are the missing branches, in the posture of the neighbours:
`build.validate_items` names the field and the index for a `list` field's
element, and `parse._link_targets` does the same for a link verb and drops the
non-string entry, so the dangling rule never sees the dict. The scalar link
target (`satisfies: REQ-001`) stays one edge, and an empty entry stays the
field's own business -- both pinned below so a future sweep at "strictness"
cannot take them with it.
"""

from __future__ import annotations

from conftest import write_project_config
from helpers import _build_at

from refdes import cli as cli_mod

CONFIG = (
    "site: { title: Element shapes, out: _site }\n"
    "standard: { base: hardware, version: 3, presets: [] }\n"
)

MAPPING_TAG = (
    "items:\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: TPS62130\n"
    "    status: selected\n"
    "    part_number: TPS62130DRRT\n"
    "    tags:\n"
    "      - power\n"
    "      - name: not-a-string\n"
    "        verdict: x\n"
    "    refdes:\n"
    "      - U1\n"
    "      - name: also-not-a-string\n"
    "        verdict: y\n"
)

CLEAN_COMPONENT = (
    "items:\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: TPS62130\n"
    "    status: selected\n"
    "    part_number: TPS62130DRRT\n"
    "    tags: [power, analog]\n"
    "    refdes: [U1, U2]\n"
)

MAPPING_LINK_TARGET = (
    "items:\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: TPS62130\n"
    "    status: selected\n"
    "    part_number: TPS62130DRRT\n"
    "    satisfies:\n"
    "      - name: not-a-string\n"
    "        verdict: x\n"
)

SCALAR_LINK_TARGET = (
    "items:\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    body: The rail shall hold 3V3.\n"
    "    status: active\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: TPS62130\n"
    "    status: selected\n"
    "    part_number: TPS62130DRRT\n"
    "    satisfies: REQ-001\n"
)

# A hand-rolled schema, so the class -- `type: list`, any field of it -- is
# what is asserted, not the bundled standard's two field names.
HAND_SCHEMA = (
    "site: { title: Hand schema, out: _site }\n"
    "types:\n"
    "  part:\n"
    "    prefix: CMP\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      tags: { type: list, on_change: ignore }\n"
    "      aliases: { type: list, on_change: ignore }\n"
)

SCALAR_ELEMENTS = (
    "defaults: { type: part, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-001\n"
    "    title: A part\n"
    "    tags: [power, 3.3, true]\n"
    "    aliases:\n"
    "      - [nested, list]\n"
)


def _project(tmp_path, *files: tuple[str, str], config: str = CONFIG):
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in files:
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])


# ------------------------------------------------------------------ B6, verbatim


def test_a_mapping_element_in_tags_is_a_build_error(tmp_path, capsys):
    """B6's repro exits 1 now, naming the field, the index, and what the entry
    has to be. The dict is shown as written, not as the loader stored it."""
    root = _project(tmp_path, ("one.yaml", MAPPING_TAG))
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "tags[1]:" in err
    assert "is not a string" in err
    assert "'name': 'not-a-string'" in err
    assert "items/one.yaml" in err
    assert "CMP-001" in err


def test_refdes_gets_the_same_check_on_the_same_item(tmp_path, capsys):
    """Not a `tags` special case: `refdes:` is the other `type: list` field on
    hardware@3, and the element that is not a string is named by index."""
    root = _project(tmp_path, ("one.yaml", MAPPING_TAG))
    _check(root)
    err = capsys.readouterr().err
    assert "refdes[1]:" in err
    assert "also-not-a-string" in err


def test_the_clean_list_of_strings_still_builds_green(tmp_path, capsys):
    """The other half of the pair: the shape the schema declares is silent."""
    root = _project(tmp_path, ("one.yaml", CLEAN_COMPONENT))
    assert _check(root) == 0
    assert "0 errors" in capsys.readouterr().out


def test_build_reports_the_same_errors_with_no_traceback(tmp_path, capsys):
    """The B1 posture: `check` and `build` agree, and the build that is red
    prints the diagnostic instead of dying in a template (run 5's half-written
    `_site/` with no summary line)."""
    root = _project(tmp_path, ("one.yaml", MAPPING_TAG))
    rc = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "build"],
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "tags[1]:" in captured.err
    assert "Traceback" not in captured.out + captured.err


def test_the_class_is_the_field_type_not_the_field_name(tmp_path, capsys):
    """Every list-of-strings field, on any schema: a number, a boolean and a
    nested list in a hand-declared `type: list` field are all refused, per
    entry, on both fields of that type in the file."""
    root = _project(
        tmp_path, ("part.yaml", SCALAR_ELEMENTS), config=HAND_SCHEMA
    )
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "tags[1]: 3.3 is not a string" in err
    assert "tags[2]: True is not a string" in err
    assert "aliases[0]: ['nested', 'list'] is not a string" in err


# -------------------------------------------------------------------- F9, verbatim


def test_a_link_verb_refuses_an_element_that_is_not_a_string(tmp_path, capsys):
    """F9's repro: the element is named by verb and index and the message says
    what it has to be -- and the loader's `__line__` is nowhere in it, because
    a non-string entry never reaches the dangling-reference rule."""
    root = _project(tmp_path, ("one.yaml", MAPPING_LINK_TARGET))
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "satisfies[0]:" in err
    assert "is not a string" in err
    assert "'name': 'not-a-string'" in err
    assert "__line__" not in err
    # The dangling-reference rule got no dict to quote.
    assert "points at \"{'name'" not in err


def test_the_bad_link_entry_is_dropped_and_the_good_ones_survive(tmp_path):
    """Red build, usable data: an entry that cannot name a target is not
    stored as one, and the entries that can are edges. `resolved_links` is
    what a graph consumer reads (AGENTS.md), so that is what is asserted."""
    root = _project(
        tmp_path,
        (
            "two.yaml",
            (
                "items:\n"
                "  - id: REQ-001\n"
                "    type: requirement\n"
                "    body: The rail shall hold 3V3.\n"
                "    status: active\n"
                "  - id: CMP-001\n"
                "    type: component\n"
                "    title: TPS62130\n"
                "    status: selected\n"
                "    part_number: TPS62130DRRT\n"
                "    satisfies:\n"
                "      - REQ-001\n"
                "      - name: not-a-string\n"
                "        verdict: x\n"
            ),
        ),
    )
    project = _build_at(root)
    item = next(i for i in project.local_items if i.id == "CMP-001")
    assert item.links["satisfies"] == ["REQ-001"]
    assert item.resolved_links["satisfies"] == ["REQ-001"]
    assert [d for d in project.errors if "satisfies[1]:" in d.message]


def test_a_scalar_link_target_is_still_one_edge(tmp_path):
    """The leniency model.py documents and `test_scalar_for_list_field.py`
    pins: `satisfies: REQ-001` is a list of one, not a mis-written scalar.
    The element check runs on the entries of that one-element list, so the
    scalar form must stay green."""
    root = _project(tmp_path, ("two.yaml", SCALAR_LINK_TARGET))
    assert _check(root) == 0
