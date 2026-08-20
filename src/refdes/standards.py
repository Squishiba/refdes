"""Resolve `standard:` into merged, plain-dict `link_types:`/`types:`.

Live reference resolution (docs/design/standard-library.md §3): a project's
refdes.yaml never contains a copy of the standard's types/link_types/field_sets
-- only a pointer to them (`standard: {base, version, presets}`). This module
resolves that pointer fresh against the bundled package data on every
`load_project()` call and returns plain dicts in exactly the shape
refdes.yaml's own `link_types:`/`types:` would use, so schema.py's existing
per-type/per-field parsing loop can consume them without caring whether they
came from the bundle, a preset, a project overlay, or some mix of the three.

Nothing here constructs FieldSpec/ItemType/LinkType objects -- that stays
schema.py's job, applied uniformly to the merged result.
"""

from __future__ import annotations

import difflib
import os
from typing import Any

import yaml

from .model import SchemaError

_STANDARDS_ROOT = os.path.join(os.path.dirname(__file__), "standards")
_KNOWN_BASES = ("hardware",)

_NAMESPACE_LABEL = {
    "field_sets": "field_set",
    "link_types": "link_type",
    "types": "type",
}


def resolve_schema(
    raw: dict[str, Any], require_rejection_rationale: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (link_types, types) as plain dicts, fully merged and `include:`-free.

    `standard:` absent, `None`, or the string "none" is the explicit escape
    hatch (docs/design/standard-library.md §3): today's fully self-declared
    behavior, field_sets/include still available for the project's own types.
    """
    standard_cfg = raw.get("standard", "none")
    if standard_cfg is None:
        standard_cfg = "none"

    if standard_cfg == "none":
        base_field_sets: dict[str, Any] = {}
        base_link_types: dict[str, Any] = {}
        base_types: dict[str, Any] = {}
    elif isinstance(standard_cfg, dict):
        base_field_sets, base_link_types, base_types = _load_standard(
            standard_cfg, require_rejection_rationale
        )
    else:
        raise SchemaError(
            "standard: must be the string 'none' or a mapping with 'base', "
            f"'version', and optional 'presets', got {standard_cfg!r}"
        )

    field_sets = _merge_field_sets(base_field_sets, raw.get("field_sets") or {})
    link_types = _merge_named_mapping(base_link_types, raw.get("link_types") or {})
    types = _merge_types(base_types, raw.get("types") or {}, field_sets)

    return link_types, types


# ------------------------------------------------------------- loading the bundle


def _load_standard(
    cfg: dict[str, Any], require_rejection_rationale: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_name = cfg.get("base")
    if base_name not in _KNOWN_BASES:
        raise SchemaError(
            f"standard.base must be one of {list(_KNOWN_BASES)}, got {base_name!r}"
        )

    version = cfg.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise SchemaError(
            f"standard.version must be a pinned integer (e.g. 1), got {version!r} "
            "-- refdes never resolves 'latest' automatically; pin a concrete "
            "version"
        )

    presets = cfg.get("presets") or []
    if not isinstance(presets, list):
        raise SchemaError("standard.presets must be a list of preset names")

    version_dir = os.path.join(_STANDARDS_ROOT, base_name, f"v{version}")
    base_path = os.path.join(version_dir, "base.yaml")
    if not os.path.isfile(base_path):
        available = _available_versions(base_name)
        raise SchemaError(
            f"standard.version {version} does not exist for base {base_name!r} "
            f"(available: {available})"
        )

    base_doc = _read_yaml(base_path)

    field_sets: dict[str, Any] = dict(base_doc.get("field_sets") or {})
    link_types: dict[str, Any] = dict(base_doc.get("link_types") or {})
    types: dict[str, Any] = dict(base_doc.get("types") or {})

    # name -> where it came from, for collision diagnostics naming both sides.
    origin: dict[tuple[str, str], str] = {}
    for name in field_sets:
        origin[("field_sets", name)] = f"the {base_name} standard"
    for name in link_types:
        origin[("link_types", name)] = f"the {base_name} standard"
    for name in types:
        origin[("types", name)] = f"the {base_name} standard"

    # The require_rejection_rationale toggle applies to the *bundled*
    # decision.rationale before any preset or project overlay is merged in --
    # see docs/design/standard-library.md §2 "The toggle." A project can still
    # override rationale's required_when directly regardless of this flag; that
    # raw override path is untouched by this.
    if not require_rejection_rationale:
        decision = types.get("decision")
        if isinstance(decision, dict):
            fields = decision.get("fields") or {}
            rationale = fields.get("rationale")
            if isinstance(rationale, dict) and "required_when" in rationale:
                rationale = dict(rationale)
                del rationale["required_when"]
                fields = dict(fields)
                fields["rationale"] = rationale
                decision = dict(decision)
                decision["fields"] = fields
                types = dict(types)
                types["decision"] = decision

    for preset_name in presets:
        preset_path = os.path.join(version_dir, "presets", f"{preset_name}.yaml")
        if not os.path.isfile(preset_path):
            available = _available_presets(version_dir)
            raise SchemaError(
                f"preset {preset_name!r} does not exist for {base_name}@{version} "
                f"(available: {available})"
            )
        preset_doc = _read_yaml(preset_path)
        for ns_name, accumulator in (
            ("field_sets", field_sets),
            ("link_types", link_types),
            ("types", types),
        ):
            for name, spec in (preset_doc.get(ns_name) or {}).items():
                key = (ns_name, name)
                if key in origin:
                    label = _NAMESPACE_LABEL[ns_name]
                    raise SchemaError(
                        f"preset {preset_name!r} declares {label} {name!r}, which "
                        f"{origin[key]} also declares. Presets must not collide "
                        "with the base standard or with each other -- this is a "
                        "bug in the preset bundle, or drop one of the two presets."
                    )
                accumulator[name] = spec
                origin[key] = f"preset {preset_name!r}"

    return field_sets, link_types, types


def _read_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _available_versions(base_name: str) -> list[str]:
    base_dir = os.path.join(_STANDARDS_ROOT, base_name)
    if not os.path.isdir(base_dir):
        return []
    return sorted(
        name for name in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, name))
    )


def _available_presets(version_dir: str) -> list[str]:
    presets_dir = os.path.join(version_dir, "presets")
    if not os.path.isdir(presets_dir):
        return []
    return sorted(
        name[:-5] for name in os.listdir(presets_dir) if name.endswith(".yaml")
    )


def known_bases() -> tuple[str, ...]:
    return _KNOWN_BASES


def latest_version(base_name: str) -> int:
    """The concrete integer `refdes init` pins -- never the literal string
    "latest" (docs/design/standard-library.md §3): resolved once, here,
    against whichever versions the installed tool actually bundles, and
    written as a real number so the pin is verifiable from the moment the
    project file exists."""
    if base_name not in _KNOWN_BASES:
        raise SchemaError(f"standard.base must be one of {list(_KNOWN_BASES)}, got {base_name!r}")
    versions = [
        int(name[1:]) for name in _available_versions(base_name) if name.startswith("v")
    ]
    if not versions:
        raise SchemaError(f"no bundled versions found for base {base_name!r}")
    return max(versions)


def available_presets(base_name: str, version: int) -> list[str]:
    """Every preset name bundled for `base_name@version`, for `refdes init
    --preset` and `refdes standard add-preset` to validate against."""
    version_dir = os.path.join(_STANDARDS_ROOT, base_name, f"v{version}")
    return _available_presets(version_dir)


def preset_providers(base_name: str, version: int) -> tuple[dict[str, str], dict[str, str]]:
    """(types, link_types), each {name: preset_name}, for every preset
    bundled at this base@version -- regardless of which presets the project
    currently selects. Lets a diagnostic name the specific preset a since-
    removed type or link used to come from, rather than a bare "unknown"
    (docs/design/standard-library.md §8's two extended diagnostics)."""
    version_dir = os.path.join(_STANDARDS_ROOT, base_name, f"v{version}")
    types: dict[str, str] = {}
    link_types: dict[str, str] = {}
    for preset_name in _available_presets(version_dir):
        preset_doc = _read_yaml(os.path.join(version_dir, "presets", f"{preset_name}.yaml"))
        for tname in preset_doc.get("types") or {}:
            types[tname] = preset_name
        for lname in preset_doc.get("link_types") or {}:
            link_types[lname] = preset_name
    return types, link_types


def load_migration_raw(base_name: str, version: int) -> dict[str, Any] | None:
    """`hardware/v<version>/migration.yaml` as a plain dict -- the delta from
    `version - 1` to `version`, in the same shape a hand-written revise.py
    mapping file uses (types:/fields:/links:/prefixes:), or None if this
    version ships no migration (v1, the first version, always doesn't; a
    later version might not either, if nothing in it needed a rename).

    Returned as a plain dict, not a revise.Mapping, so this module never has
    to import revise.py -- revise.py imports standards.py for the upgrade
    chain, not the other way around. Establishes the convention every future
    standard version follows: shipping this file alongside base.yaml is what
    makes `refdes standard upgrade --to N` need no hand-written mapping for
    the bundled vocabulary, the same way base.yaml itself needs no project
    ever to copy it.
    """
    path = os.path.join(_STANDARDS_ROOT, base_name, f"v{version}", "migration.yaml")
    if not os.path.isfile(path):
        return None
    return _read_yaml(path)


# --------------------------------------------------------------------- merging


def _merge_named_mapping(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge two {name: spec} maps by key.

    overlay wins per key; a spec of None deletes an inherited key. Each spec
    itself is not merged -- redeclaring a name means redeclaring its whole spec.
    """
    result = dict(base)
    for name, spec in overlay.items():
        if spec is None:
            result.pop(name, None)
        else:
            result[name] = spec
    return result


def _merge_field_sets(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Each field_set is itself a {field_name: fieldspec} map, merged by key --
    the same rule a type's own `fields:` uses against its inherited fields."""
    result = dict(base)
    for name, spec in overlay.items():
        if spec is None:
            result.pop(name, None)
            continue
        result[name] = _merge_named_mapping(result.get(name) or {}, spec or {})
    return result


def _expand_include(type_raw: dict[str, Any], field_sets: dict[str, Any]) -> dict[str, Any]:
    """Resolve `include:` into `fields:`, and drop `include:` from the result.

    Field sets are merged in list order (a later include wins over an earlier
    one on a name collision), then the type's own `fields:` are overlaid on top
    -- a type's own declaration always wins over anything it includes.
    """
    type_raw = dict(type_raw or {})
    includes = type_raw.pop("include", None) or []
    own_fields = type_raw.get("fields") or {}

    merged_fields: dict[str, Any] = {}
    for set_name in includes:
        if set_name not in field_sets:
            close = difflib.get_close_matches(str(set_name), sorted(field_sets), n=1, cutoff=0.5)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise SchemaError(f"include: names unknown field_set {set_name!r}.{hint}")
        merged_fields.update(field_sets[set_name] or {})
    merged_fields.update(own_fields)

    type_raw["fields"] = merged_fields
    return type_raw


def _merge_type_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge one type's resolved dict form (docs/design/standard-library.md §2).

    `fields:` and `links:` merge by key; every other scalar (label, prefix,
    check_severity, coverable, ...) is replaced wholesale when the overlay
    gives it, left untouched otherwise. Both `base` and `overlay` must already
    have `include:` expanded into `fields:`.
    """
    result = dict(base)
    result.update(overlay)
    result["fields"] = _merge_named_mapping(base.get("fields") or {}, overlay.get("fields") or {})
    result["links"] = _merge_named_mapping(base.get("links") or {}, overlay.get("links") or {})
    return result


def _merge_types(
    base_types: dict[str, Any], project_types_raw: dict[str, Any], field_sets: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tname, traw in base_types.items():
        result[tname] = _expand_include(traw, field_sets)

    for tname, traw in project_types_raw.items():
        if traw is None:
            # `types.<name>: null` -- removes an inherited type entirely. Anything
            # still referencing it (a link target list, satisfying_statuses, ...)
            # surfaces as an ordinary load-time SchemaError from the validation
            # that already runs over the final merged schema in schema.py.
            result.pop(tname, None)
            continue
        expanded_overlay = _expand_include(traw, field_sets)
        if tname in result:
            result[tname] = _merge_type_dict(result[tname], expanded_overlay)
        else:
            result[tname] = expanded_overlay

    return result
