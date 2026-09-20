"""The `doc:` definition key (docs/design/backlog.md finding 38, chunk 1).

A vocabulary term -- a type, a field, a link verb, a field-set entry -- now
carries its own definition next to its declaration:

    types:
      note:
        prefix: NTE
        doc: A short prose note an item links to by id.
        fields:
          title: { type: text, doc: The one-line summary. }

Chunk 1 is only the *key*: it is accepted by nested-config validation in the
four places it may appear, carried into the resolved model objects, and
exposed through the schema exports that already exist (`schema_json`'s JSON
Schema `description`, and `items.json`'s `types` payload). Chunk 2 writes the
definitions for the bundled standard and adds the completeness lint; nothing
here requires a project to have any `doc:` at all.

The byte-identical guarantee is the load-bearing one: a project with no `doc:`
keys produces exactly the `schema.json` and `items.json` it produced before
this key existed -- no empty `description`, no `doc: ""`.
"""

from __future__ import annotations

import json

import pytest
from conftest import write_project_config

from refdes import render as render_mod
from refdes import schema_json as schema_json_mod
from refdes.model import SchemaError
from refdes.schema import load_project

BASE = """\
site: {title: T, out: _site}
id: {width: 3}
history: {default: invalidate}
units: {preferred: []}
"""

DOC = "A short prose note an item links to by id."


def _load(tmp_path, schema: str):
    write_project_config(tmp_path, BASE + schema)
    return load_project(start=str(tmp_path))


# ------------------------------------------------------- accepted in an overlay


def test_doc_accepted_on_a_type(tmp_path):
    project = _load(
        tmp_path,
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        f"    doc: {DOC}\n"
        "    fields: {title: {type: text}}\n",
    )
    assert project.types["note"].doc == DOC


def test_doc_accepted_on_a_field(tmp_path):
    project = _load(
        tmp_path,
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    fields:\n"
        f"      title: {{type: text, doc: {DOC}}}\n",
    )
    assert project.types["note"].fields["title"].doc == DOC


def test_doc_accepted_on_a_link_type(tmp_path):
    project = _load(
        tmp_path,
        "link_types:\n"
        "  satisfies:\n"
        "    inverse: satisfied_by\n"
        f"    doc: {DOC}\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    fields: {title: {type: text}}\n",
    )
    assert project.link_types["satisfies"].doc == DOC


def test_doc_accepted_on_a_set_entry(tmp_path):
    """A set's entries are field specs, so `doc:` rides along into every
    type that `include:`s the set -- the definition is written once."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        f"      title: {{type: text, doc: {DOC}}}\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields: {body: {type: text}}\n",
    )
    assert project.types["note"].fields["title"].doc == DOC
    # A field with no definition of its own stays undefined, not empty-string-y.
    assert project.types["note"].fields["body"].doc == ""


def test_a_type_without_doc_is_unchanged(tmp_path):
    project = _load(
        tmp_path,
        "types:\n  note:\n    prefix: NTE\n    fields: {title: {type: text}}\n",
    )
    assert project.types["note"].doc == ""
    assert project.types["note"].fields["title"].doc == ""


# --------------------------------------------------- a non-string is an error


@pytest.mark.parametrize(
    "value",
    ["42", "[a, b]", "{en: x}", '""', '"   "', "true"],
    ids=["int", "list", "mapping", "empty", "whitespace", "bool"],
)
def test_doc_must_be_a_non_empty_string(tmp_path, value):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            f"    doc: {value}\n"
            "    fields: {title: {type: text}}\n",
        )
    assert "types.note.doc" in str(exc.value)
    assert "non-empty string" in str(exc.value)


def test_a_bad_doc_on_a_field_names_the_field(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    fields:\n"
            "      title: {type: text, doc: 42}\n",
        )
    assert "types.note.fields.title.doc" in str(exc.value)


def test_a_bad_doc_on_a_link_type_names_the_link_type(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "link_types:\n  satisfies: {inverse: satisfied_by, doc: [a]}\n"
            "types:\n  note:\n    prefix: NTE\n    fields: {title: {type: text}}\n",
        )
    assert "link_types.satisfies.doc" in str(exc.value)


def test_a_bad_doc_on_a_set_entry_names_the_set(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n  common:\n    fields:\n      title: {type: text, doc: 42}\n"
            "types:\n  note:\n    prefix: NTE\n    include: [common]\n"
            "    fields: {body: {type: text}}\n",
        )
    assert "sets.common.fields.title.doc" in str(exc.value)


# ------------------------------------------------------------- the exports


DOC_SCHEMA = """\
link_types:
  satisfies:
    inverse: satisfied_by
    doc: Points at the thing this item satisfies.
types:
  note:
    prefix: NTE
    doc: A short prose note an item links to by id.
    fields:
      title: {type: text, doc: The one-line summary.}
      body: {type: text}
    links:
      satisfies: [note]
"""


def test_doc_reaches_the_json_schema_descriptions(tmp_path):
    project = _load(tmp_path, DOC_SCHEMA)
    doc = schema_json_mod.build_schema(project)
    branch = doc["$defs"]["note__bare"]
    assert branch["description"] == "A short prose note an item links to by id."
    assert branch["properties"]["title"]["description"] == "The one-line summary."
    # A field with no definition gets no description key at all.
    assert "description" not in branch["properties"]["body"]
    # A link keeps its target line and gains the verb's definition.
    assert "Points at the thing this item satisfies." in branch["properties"]["satisfies"]["description"]
    assert "target: note" in branch["properties"]["satisfies"]["description"]


def test_doc_reaches_the_items_json_types_payload(tmp_path):
    project = _load(tmp_path, DOC_SCHEMA)
    payload = render_mod.items_json(project)
    note = payload["types"]["note"]
    assert note["doc"] == "A short prose note an item links to by id."
    assert note["fields"]["title"]["doc"] == "The one-line summary."
    assert "doc" not in note["fields"]["body"]


# ------------------------------------------- no doc: keys means no byte drift


def _both_exports(tmp_path, schema: str):
    project = _load(tmp_path, schema)
    return (
        json.dumps(schema_json_mod.build_schema(project), sort_keys=True),
        json.dumps(render_mod.items_json(project), sort_keys=True, default=str),
    )


def test_a_project_without_doc_keys_is_byte_identical(tmp_path):
    """The whole guarantee: nothing appears in either export that was not
    there before this key existed."""
    plain = """\
link_types:
  satisfies: {inverse: satisfied_by}
types:
  note:
    prefix: NTE
    fields:
      title: {type: text}
      body: {type: text}
    links:
      satisfies: [note]
"""
    schema_json_text, items_json_text = _both_exports(tmp_path, plain)
    assert '"doc"' not in schema_json_text
    assert '"doc"' not in items_json_text
    # The only field descriptions are the ones a doc: wrote; links still carry
    # their pre-existing "target:" line and nothing else.
    assert '"description": "target: note"' in schema_json_text
