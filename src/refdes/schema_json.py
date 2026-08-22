"""Emit a JSON Schema describing the project's actual merged schema --
base at its pinned version, plus selected presets, plus the project overlay
-- for editor completion (docs/design/standard-library.md §12).

`items_json` (render.py) already walks `project.types`/`project.link_types`
-- the fully resolved objects, after every layer of §2's merge -- to build
`items.json`'s lighter `types` key. This is a second, sibling serializer
over the identical objects, shaped as a JSON Schema envelope instead:
`$schema`, `properties`/`required`, a discriminated union across types,
`additionalProperties: false`. Not a second, independently-maintained
mapping of field types -- `field_json_schema` below is the one function
`refdes new` (scaffold.py) also reads, so the two can never independently
drift on what a given field type means.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .model import FieldSpec, ItemType, ON_CHANGE_MODES, Project

SCHEMA_REL_PATH = os.path.join(".refdes", "schema.json")

# Field `type:` -> JSON-Schema fragment, keyed only by the declared type --
# not the field name -- so this generalizes to any project-defined field of
# one of these types, not just the standard's own. `enum` is handled
# separately in field_json_schema, since it needs the field's own choices.
_FIELD_TYPE_MAP: dict[str, dict[str, Any]] = {
    "text": {"type": "string"},
    "person": {"type": "string"},
    # `examples` is not a constraint -- it's a hint for the editor's own
    # completion. Verified against the real yaml-language-server (what
    # redhat.vscode-yaml wraps): a JSON Schema `examples` array on a string
    # property does surface as completion items when finishing a `limit:`
    # value, and the server pre-quotes the one that actually needs quotes
    # (">= 9 V") while leaving the one that doesn't ("<= 600 mA") bare --
    # confirmed by driving the server directly over its LSP stdio protocol,
    # not assumed from documentation (finding 13, item 3).
    "limit": {"type": "string", "examples": [">= 9 V", "<= 600 mA"]},
    "quantity": {"type": "string"},
    "date": {"type": "string", "format": "date"},
    "list": {"type": "array", "items": {"type": "string"}},
    "options": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "verdict": {"type": "string"},
                "because": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "checks": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "against": {"type": "string"},
            },
            "required": ["value", "against"],
            "additionalProperties": False,
        },
    },
    "citations": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "rev": {"type": "string"},
                "page": {"type": "string"},
                "part_number": {"type": "string"},
                "vendor": {"type": "boolean"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}

HISTORY_DEF: dict[str, Any] = {
    "description": "history: <mode> for the whole item, or a per-field override.",
    "oneOf": [
        {"enum": list(ON_CHANGE_MODES)},
        {
            "type": "object",
            "properties": {
                "mode": {"enum": list(ON_CHANGE_MODES)},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"enum": list(ON_CHANGE_MODES)},
                },
                "reason": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ],
}


def field_json_schema(fspec: FieldSpec) -> dict[str, Any]:
    """The JSON-Schema fragment for one declared field, from its `type:`
    alone -- the single mapping both `refdes schema --json` and `refdes
    new` read (see this module's docstring)."""
    if fspec.type == "enum":
        frag: dict[str, Any] = {"enum": list(fspec.choices or [])}
    else:
        frag = dict(_FIELD_TYPE_MAP.get(fspec.type, {"type": "string"}))
    if fspec.default is not None:
        frag["default"] = fspec.default
    return frag


def link_json_schema(targets: list[str]) -> dict[str, Any]:
    """The JSON-Schema fragment for one declared link. The allowed-target
    restriction can't be enforced here -- confirming a listed ID actually
    resolves to an item of an allowed type means reading other files, which
    is `refdes check`'s job -- so it's stated in `description` for a human
    to read on hover, not something the validator itself checks."""
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": f"target: {', '.join(targets) if targets else 'any'}",
    }


def _type_branch(type_name: str, spec: ItemType, include_body: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        # Deliberately unconstrained and never required: an item mid-authoring,
        # before `refdes id` has allocated one, is the tool's own normal
        # two-phase author-then-allocate workflow, not an error state.
        "id": {"type": "string"},
        "type": {"const": type_name},
    }
    required: list[str] = []
    for fname, fspec in spec.fields.items():
        properties[fname] = field_json_schema(fspec)
        if fspec.required:
            required.append(fname)
    for lname, targets in spec.links.items():
        properties[lname] = link_json_schema(targets)
    properties["history"] = {"$ref": "#/$defs/history"}
    # prefix/board/workspace are legal properties only when this type doesn't
    # already declare a same-named field -- mirrors OVERRIDABLE (parse.py)
    # exactly rather than approximating it.
    for key in ("prefix", "board", "workspace"):
        if key not in spec.fields:
            properties[key] = {"type": "string"}
    if include_body:
        # Legal only inside a list-file entry (the markdown body as a plain
        # string) -- never legal in .md front matter, where the body is the
        # text after the closing fence, not a YAML key at all.
        properties["body"] = {"type": "string"}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        # Not `False`: `refdes check` only warns on a field a type doesn't
        # declare (parse.py's unknown-field handling) -- it never rejects the
        # build over it, because the standard's own field-level merge exists
        # specifically to let a project extend a type this way. `false` here
        # would make the editor stricter than the tool it's a convenience
        # layer over, hard-rejecting input the CLI accepts (finding 3). The
        # oneOf discrimination in build_schema() still works with this
        # permissive: each branch's own `type` const rejects every value but
        # its own regardless of this setting.
        "additionalProperties": True,
    }


def build_schema(project: Project) -> dict[str, Any]:
    """The full JSON Schema for this project's resolved types -- base at its
    pinned version, plus selected presets, plus the project's own overlay,
    exactly as `project.types`/`project.link_types` already reflect after
    schema.py's merge. Two document shapes, one schema: a bare item (`.md`
    front matter, or one `items:` array entry) and a list file
    (`{defaults?, items: [...]}`), discriminated structurally at the top
    level since a list file has an `items:` key and a bare item doesn't.
    """
    defs: dict[str, Any] = {"history": HISTORY_DEF}
    bare_refs: list[dict[str, str]] = []
    entry_refs: list[dict[str, str]] = []
    for type_name, spec in sorted(project.types.items()):
        bare_key = f"{type_name}__bare"
        entry_key = f"{type_name}__entry"
        defs[bare_key] = _type_branch(type_name, spec, include_body=False)
        defs[entry_key] = _type_branch(type_name, spec, include_body=True)
        bare_refs.append({"$ref": f"#/$defs/{bare_key}"})
        entry_refs.append({"$ref": f"#/$defs/{entry_key}"})

    # A `section: <type>` marker entry (finding 2, issue #6) -- YAML list
    # files only, mirroring `_only_key()`'s own rule that a marker's one real
    # key must be `section` and nothing else. A markdown section marker is a
    # bare fenced block, not front matter, so there's no bare_item equivalent
    # to add here: it was never something this schema validated.
    defs["section_marker"] = {
        "type": "object",
        "properties": {"section": {"type": "string"}},
        "required": ["section"],
        "additionalProperties": False,
    }
    entry_refs.append({"$ref": "#/$defs/section_marker"})

    defs["bare_item"] = {"oneOf": bare_refs} if bare_refs else {"type": "object"}
    defs["list_file"] = {
        "type": "object",
        "properties": {
            # Not validated against any one type's fields: defaults: merges
            # into whichever type each items: entry declares, and the schema
            # has no way to know that in advance for the block as a whole.
            "defaults": {"type": "object", "additionalProperties": True},
            "items": {
                "type": "array",
                "items": {"oneOf": entry_refs} if entry_refs else {"type": "object"},
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{project.title} item schema",
        "$defs": defs,
        "oneOf": [
            {"$ref": "#/$defs/list_file"},
            {"$ref": "#/$defs/bare_item"},
        ],
    }


def build_graph(project: Project) -> str:
    """Mermaid flowchart source for the project's actual merged type/link
    graph -- the same walk build_schema() does over `project.types`, with a
    different renderer (finding 11). Generated from the resolved schema, not
    hand-drawn, so it reflects a project's own overlay and presets, not just
    whatever the bundled standard ships -- a hand-maintained diagram (or
    table) goes stale the moment a preset or project overlay changes a verb,
    silently, the same way `docs/links.md`'s own link-verb table had (see the
    fix alongside this one).

    A link declared with an empty target list (`links: {blocked_by: []}` --
    "unrestricted target type", per link_json_schema()'s own docstring) draws
    to a single synthetic `any` node rather than one edge per known type,
    matching link_json_schema()'s "target: any" convention: drawing every
    type individually would imply N distinct semantic edges where there is
    exactly one general one.
    """
    lines = ["%% generated by `refdes schema --graph` -- do not hand-edit", "graph LR"]
    for type_name, spec in sorted(project.types.items()):
        for link_name, targets in spec.links.items():
            for target in targets or ["any"]:
                lines.append(f"  {type_name} -- {link_name} --> {target}")
    return "\n".join(lines) + "\n"


def write_schema(project: Project) -> bool:
    """Write `.refdes/schema.json` for the resolved project.

    A pure function of the current merged config -- gitignored, not
    committed, regenerated as a cheap side effect of every command that
    already loads the project (docs/design/standard-library.md §12).
    Returns whether the file that was there before this write was already
    stale (older than `refdes.yaml`) -- `refdes check`'s own narrow
    trip-wire for the one gap aggressive regeneration doesn't close: a bare
    yaml-language-server setup with no refdes-aware watcher has nothing to
    re-trigger a refresh between a `refdes.yaml` edit and the next CLI
    invocation.
    """
    path = os.path.join(project.root, SCHEMA_REL_PATH)
    config_path = os.path.join(project.root, "refdes.yaml")
    was_stale = (
        os.path.isfile(path)
        and os.path.isfile(config_path)
        and os.path.getmtime(path) < os.path.getmtime(config_path)
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_schema(project), fh, indent=2)
        fh.write("\n")
    return was_stale
