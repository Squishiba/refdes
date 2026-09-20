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

from . import diagram
from .model import ON_CHANGE_MODES, FieldSpec, ItemType, Project

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
                "path": {"type": "string"},
                "rev": {"type": "string"},
                "page": {"type": "string"},
                "section": {"type": "string", "minLength": 1},
                "part_number": {"type": "string"},
                "keep_copy": {"type": "boolean"},
                "id": {"type": "string"},
            },
            "required": ["path"],
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
    # A `doc:` definition, shown by the editor on hover and in completion docs
    # (finding 38). Absent, not empty, when the field has none: a project that
    # writes no `doc:` keys gets byte-identical output.
    if fspec.doc:
        frag["description"] = fspec.doc
    return frag


def link_json_schema(targets: list[str], doc: str = "") -> dict[str, Any]:
    """The JSON-Schema fragment for one declared link. The allowed-target
    restriction can't be enforced here -- confirming a listed ID actually
    resolves to an item of an allowed type means reading other files, which
    is `refdes check`'s job -- so it's stated in `description` for a human
    to read on hover, not something the validator itself checks.

    A verb's own `doc:` definition goes in the same `description`, ahead of the
    target line, which is what was already there (finding 38).
    """
    target = f"target: {', '.join(targets) if targets else 'any'}"
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": f"{doc} ({target})" if doc else target,
    }


def _type_branch(
    type_name: str,
    spec: ItemType,
    include_body: bool,
    link_docs: dict[str, str] | None = None,
) -> dict[str, Any]:
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
        properties[lname] = link_json_schema(targets, (link_docs or {}).get(lname, ""))
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
    branch: dict[str, Any] = {
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
    if spec.doc:
        branch["description"] = spec.doc
    return branch


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
    link_docs = {name: lt.doc for name, lt in project.link_types.items() if lt.doc}
    bare_refs: list[dict[str, str]] = []
    entry_refs: list[dict[str, str]] = []
    for type_name, spec in sorted(project.types.items()):
        bare_key = f"{type_name}__bare"
        entry_key = f"{type_name}__entry"
        defs[bare_key] = _type_branch(type_name, spec, include_body=False, link_docs=link_docs)
        defs[entry_key] = _type_branch(type_name, spec, include_body=True, link_docs=link_docs)
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
    """The project's per-type connection diagrams, one SVG document per
    type in sorted order -- the same walk build_schema() does over
    `project.types`, with a different renderer (finding 11; the one
    whole-graph drawing of finding 38 chunk 3b was rejected as unreadable
    and replaced by these).

    It used to print Mermaid source. That made the picture someone else's
    problem: the reader needed a Mermaid renderer, and the docs page that
    embedded it went stale anyway. This emits the drawings themselves, from
    the resolved schema, so they reflect a project's own overlay and
    presets and cannot drift the way a hand-drawn diagram (or table) does.

    The rows, the fixed three-column layout and the empty-target convention
    (one box labelled *any type*, not one per known type) all live in
    `diagram.py`, which is also what every built site's vocabulary page
    embeds beside each term: one generator, so the CLI's output and the
    page can never disagree.
    """
    spine = diagram.render_spine_svg(project)
    terms = "".join(
        diagram.render_term_svg(project, name) for name in sorted(project.types)
    )
    return spine + terms


def newest_config_file(project: Project) -> str | None:
    """The config file in `project.root` that changed most recently -- the one
    whose mtime drives `write_schema`'s staleness check -- or None when
    neither config file exists. `cli.py` names this file in the staleness
    warning, so it must come from the same computation that decided the
    schema was stale."""
    return max(
        (
            name
            for name in ("refdes-project.yaml", "refdes-schema.yaml")
            if os.path.isfile(os.path.join(project.root, name))
        ),
        key=lambda name: os.path.getmtime(os.path.join(project.root, name)),
        default=None,
    )


def write_schema(project: Project, write: bool = True) -> bool:
    """Write `.refdes/schema.json` for the resolved project.

    A pure function of the current merged config -- gitignored, not
    committed, regenerated as a cheap side effect of every command that
    already loads the project (docs/design/standard-library.md §12).
    Returns whether the file that was there before this write was already
    stale (older than whichever of the two config files changed most recently,
    per `newest_config_file`) -- `refdes check`'s own narrow trip-wire for
    the one gap aggressive regeneration doesn't close: a bare
    yaml-language-server setup with no refdes-aware watcher has nothing to
    re-trigger a refresh between a config edit and the next CLI invocation.

    `write=False` (the global `--no-write`, docs/design/keys.md §2) skips the
    write but still computes and returns the same staleness verdict, so the
    trip-wire diagnostic survives a read-only pass -- the user still learns
    the file is stale, only it isn't fixed under their feet.
    """
    path = os.path.join(project.root, SCHEMA_REL_PATH)
    newest = newest_config_file(project)
    was_stale = (
        os.path.isfile(path)
        and newest is not None
        and os.path.getmtime(path)
        < os.path.getmtime(os.path.join(project.root, newest))
    )
    if not write:
        return was_stale
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_schema(project), fh, indent=2)
        fh.write("\n")
    return was_stale
