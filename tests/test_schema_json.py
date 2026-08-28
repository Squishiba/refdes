"""JSON schema.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os

import jsonschema
from helpers import COVERAGE_SCHEMA, _build_at, _build_at_repo_schema

from refdes import cli as cli_mod
from refdes import scaffold as scaffold_mod
from refdes import schema_json as schema_json_mod
from refdes.schema import load_project

# ----------------------------------------------------------------- JSON schema


def test_build_schema_shape():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    assert doc["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert doc["oneOf"] == [
        {"$ref": "#/$defs/list_file"},
        {"$ref": "#/$defs/bare_item"},
    ]
    assert "requirement__bare" in doc["$defs"]
    assert "requirement__entry" in doc["$defs"]
    # JSON-serializable end to end.
    json.dumps(doc)


def test_build_schema_required_only_unconditional():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    branch = doc["$defs"]["decision__bare"]
    assert "title" in branch["required"]
    # rationale is required_when, not unconditionally required.
    assert "rationale" not in branch["required"]


def test_build_schema_enum_field_carries_choices_and_default():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    status = doc["$defs"]["decision__bare"]["properties"]["status"]
    assert status["enum"] == [
        "proposed", "in_progress", "accepted", "on_hold", "rejected", "superseded",
    ]
    assert status["default"] == "proposed"


def test_build_schema_limit_field_carries_quoting_examples():
    """Finding 13, item 3: a `limit:` value starting with '>'/'>=' needs
    quotes in YAML; `examples` on the JSON Schema fragment is a hint for the
    editor's own completion. Verified (not just shipped hopefully) against
    the real yaml-language-server -- see schema_json.py's comment on this
    fragment for how."""
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    limit = doc["$defs"]["bound__bare"]["properties"]["limit"]
    assert limit["type"] == "string"
    assert ">= 9 V" in limit["examples"]
    assert "<= 600 mA" in limit["examples"]


def test_build_schema_link_carries_target_description():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    satisfies = doc["$defs"]["decision__bare"]["properties"]["satisfies"]
    assert satisfies["type"] == "array"
    assert satisfies["description"] == "target: requirement"


def test_build_schema_section_marker_validates_in_a_list_file(tmp_path):
    """Finding 2 (issue #6): a bare `section: <type>` entry -- `_only_key()`'s
    own rule for what makes one -- must validate against the *real* schema
    editors consume, checked with the reference jsonschema library itself,
    the same authoritative proof the finding used, not just a structural
    read of build_schema()'s own output."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    doc = schema_json_mod.build_schema(project)
    validator = jsonschema.Draft7Validator({"$ref": "#/$defs/list_file", "$defs": doc["$defs"]})

    valid = {"items": [{"section": "requirement"}, {"id": "REQ-001", "type": "requirement", "text": "x"}]}
    assert list(validator.iter_errors(valid)) == []

    # additionalProperties: false still holds -- a marker isn't a free-for-all.
    malformed = {"items": [{"section": "requirement", "extra": "bad"}]}
    assert list(validator.iter_errors(malformed)) != []


def test_build_schema_section_marker_is_list_file_only():
    """Scoped to the YAML list-file shape -- a markdown section marker is a
    bare fenced block, not front matter, so bare_item (the .md/single-entry
    branch) has no equivalent to add."""
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    assert "section_marker" in doc["$defs"]
    assert {"$ref": "#/$defs/section_marker"} in doc["$defs"]["list_file"]["properties"]["items"]["items"]["oneOf"]
    bare_refs = doc["$defs"]["bare_item"]["oneOf"]
    assert {"$ref": "#/$defs/section_marker"} not in bare_refs


def test_build_schema_additional_properties_false():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    # A type node must not be stricter than `refdes check`, which only warns
    # on an undeclared field rather than rejecting it (finding 3) -- so
    # additionalProperties is NOT false here, unlike the list_file envelope
    # below, whose {defaults, items} shape isn't an extensible per-type node.
    assert doc["$defs"]["decision__bare"]["additionalProperties"] is not False
    assert doc["$defs"]["list_file"]["additionalProperties"] is False
    # defaults: inside a list file is deliberately unvalidated.
    assert doc["$defs"]["list_file"]["properties"]["defaults"]["additionalProperties"] is True


def test_generated_schema_does_not_reject_what_check_only_warns_about(tmp_path):
    """Finding 3: adding a field a type doesn't declare produced two different
    verdicts -- `refdes check` warns and keeps building, but the generated
    schema's `additionalProperties: false` hard-rejects the identical input in
    the editor. The two must agree, and per instruction the schema is the side
    that has to yield here (an editor red-underlining valid input is worse than
    an editor missing something `check` will catch anyway)."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: REQ-001\n    type: requirement\n    text: A requirement.\n"
        "    datasheets: something extra\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not project.errors
    assert any("unknown field 'datasheets'" in d.message for d in project.warnings)

    doc = schema_json_mod.build_schema(project)
    branch = doc["$defs"]["requirement__entry"]
    assert "datasheets" not in branch["properties"]  # still undeclared, just not fatal
    assert branch["additionalProperties"] is not False, (
        "the generated schema rejects a field the CLI only warns about"
    )


def test_build_schema_body_only_on_the_list_file_entry_branch():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    assert "body" not in doc["$defs"]["decision__bare"]["properties"]
    assert "body" in doc["$defs"]["decision__entry"]["properties"]


def test_build_schema_id_is_never_required():
    project = _build_at_repo_schema()
    doc = schema_json_mod.build_schema(project)
    for key, branch in doc["$defs"].items():
        if key.endswith("__bare") or key.endswith("__entry"):
            assert "id" not in branch["required"]


def test_build_schema_prefix_board_workspace_omitted_when_shadowed(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      text: {type: text, required: true}\n"
        "      board: {type: text}\n",  # shadows the reserved OVERRIDABLE key
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    doc = schema_json_mod.build_schema(project)
    props = doc["$defs"]["requirement__bare"]["properties"]
    assert props["board"] == {"type": "string"}  # the field's own, not the override
    assert "prefix" in props  # not shadowed, still offered


def test_write_schema_creates_the_file_and_detects_staleness(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    was_stale = schema_json_mod.write_schema(project)
    assert was_stale is False  # nothing existed before this write
    schema_path = tmp_path / ".refdes" / "schema.json"
    assert schema_path.is_file()
    json.loads(schema_path.read_text(encoding="utf-8"))  # valid JSON

    # Freshly written -- not stale relative to the config that hasn't changed.
    was_stale_2 = schema_json_mod.write_schema(project)
    assert was_stale_2 is False

    # Make the schema file look older than a just-touched refdes.yaml.
    old = os.path.getmtime(schema_path) - 10
    os.utime(schema_path, (old, old))
    was_stale_3 = schema_json_mod.write_schema(project)
    assert was_stale_3 is True


def test_cli_schema_json_prints_valid_schema(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "schema", "--json"])
    assert status == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert "requirement__bare" in doc["$defs"]


def test_build_graph_emits_one_edge_per_declared_link(tmp_path):
    """Finding 11: the graph is a walk over the same resolved project.types
    build_schema() uses, with a different renderer -- one Mermaid edge per
    (type, link, target) triple, in the direction actually declared."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  satisfies: { inverse: satisfied_by, label: Satisfies }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields: { title: { type: text } }\n"
        "    links: { satisfies: [requirement] }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    graph = schema_json_mod.build_graph(project)
    assert "graph LR" in graph
    assert "decision -- satisfies --> requirement" in graph
    # The inverse is computed, not separately declared -- must not appear as
    # its own edge (that would double the graph for every link verb).
    assert "satisfied_by" not in graph


def test_build_graph_unrestricted_target_draws_to_a_single_any_node():
    """An empty target list (`links: {blocked_by: []}`) means "any type" --
    the graph must draw one edge to a synthetic `any` node, not one edge per
    known type, which would imply N distinct semantic edges instead of one
    general one."""
    project = _build_at_repo_schema()
    graph = schema_json_mod.build_graph(project)
    assert "decision -- blocked_by --> any" in graph


def test_cli_schema_graph_prints_mermaid_source(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "schema", "--graph"])
    assert status == 0
    out = capsys.readouterr().out
    assert out.startswith("%%")
    assert "graph LR" in out
    assert "requirement -- refines --> requirement" in out


def test_check_refreshes_schema_json_and_warns_when_stale(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    schema_path = tmp_path / ".refdes" / "schema.json"

    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "check"])
    assert schema_path.is_file()

    old = os.path.getmtime(schema_path) - 10
    os.utime(schema_path, (old, old))
    capsys.readouterr()
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "check"])
    out = capsys.readouterr().out
    assert "schema.json was older than refdes.yaml" in out
