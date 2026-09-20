"""Resolve `standard:` into merged, plain-dict `link_types:`/`types:`.

Live reference resolution (docs/design/standard-library.md §3): a project's
Neither config file ever contains a copy of the standard's types/link_types/
sets -- `refdes-project.yaml` holds only a pointer to them
(`standard: {base, version, presets}`). This module resolves that pointer fresh
against the bundled package data on every `load_project()` call and returns
plain dicts in exactly the shape `refdes-schema.yaml`'s own
`link_types:`/`types:` would use, so schema.py's existing
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
from .parse import yaml_safe_load

_STANDARDS_ROOT = os.path.join(os.path.dirname(__file__), "standards")
_KNOWN_BASES = ("hardware",)

_NAMESPACE_LABEL = {
    "sets": "set",
    "link_types": "link_type",
    "types": "type",
}


def resolve_namespaces(
    raw: dict[str, Any], require_rejection_rationale: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    """Return (sets, link_types, types, warnings) as plain dicts, fully merged.

    The three namespaces of `refdes-schema.yaml`, resolved base -> presets ->
    project overlay. Types come back `include:`-free; the sets are the
    one namespace the resolved types no longer show any trace of, so anything
    that reports on the vocabulary (vocabulary.py) needs them separately --
    `include:` is expanded into `fields:` and popped.

    `standard:` absent, `None`, or the string "none" is the explicit escape
    hatch (docs/design/standard-library.md §3): today's fully self-declared
    behavior, sets/include still available for the project's own types.
    """
    standard_cfg = raw.get("standard", "none")
    if standard_cfg is None:
        standard_cfg = "none"

    if standard_cfg == "none":
        base_sets: dict[str, Any] = {}
        base_link_types: dict[str, Any] = {}
        base_types: dict[str, Any] = {}
    elif isinstance(standard_cfg, dict):
        base_sets, base_link_types, base_types = _load_standard(
            standard_cfg, require_rejection_rationale
        )
    else:
        raise SchemaError(
            "standard: must be the string 'none' or a mapping with 'base', "
            f"'version', and optional 'presets', got {standard_cfg!r}"
        )

    sets = _merge_sets(base_sets, raw.get("sets") or {})
    link_types = _merge_named_mapping(base_link_types, raw.get("link_types") or {})
    warnings: list[str] = []
    types = _merge_types(base_types, raw.get("types") or {}, sets, warnings)

    # A name may be a type or a set, not both: `include: [x]` and `extends: [x]`
    # would then disagree about what x is, and the resolved schema could not
    # say which namespace a reference meant (docs/design/composition.md §6.1).
    for name in sorted(sets):
        if name in types:
            raise SchemaError(
                f"sets.{name} collides with types.{name}; a name may be a type "
                "or a set, not both"
            )

    return sets, link_types, types, warnings


def resolve_schema(
    raw: dict[str, Any], require_rejection_rationale: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The two-value form of `resolve_namespaces`, for callers that have no
    use for the set namespace."""
    _sets, link_types, types, _warnings = resolve_namespaces(
        raw, require_rejection_rationale
    )
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

    # Released bundles (hardware v1, v2) predate the field_sets -> sets rename
    # and are frozen byte-identical once released (base.yaml's own header), so
    # the loader reads either key from a bundle file. Project overlays and
    # presets -- never frozen -- speak only `sets:`; a `field_sets:` in an
    # overlay is the rename error in schema._load_schema_overlay.
    sets: dict[str, Any] = {
        name: _normalize_set_entry(spec)
        for name, spec in (base_doc.get("sets") or base_doc.get("field_sets") or {}).items()
    }
    link_types: dict[str, Any] = dict(base_doc.get("link_types") or {})
    types: dict[str, Any] = dict(base_doc.get("types") or {})

    # name -> where it came from, for collision diagnostics naming both sides.
    origin: dict[tuple[str, str], str] = {}
    for name in sets:
        origin[("sets", name)] = f"the {base_name} standard"
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
            ("sets", sets),
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
                accumulator[name] = (
                    _normalize_set_entry(spec) if ns_name == "sets" else spec
                )
                origin[key] = f"preset {preset_name!r}"

    return sets, link_types, types


def _read_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml_safe_load(fh) or {}


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


_SET_SPEC_KEYS = frozenset({"fields", "links", "body"})


def _normalize_set_entry(spec: Any) -> Any:
    """Wrap a released bundle's bare {field_name: fieldspec} set in `fields:`.

    hardware v1/v2 declare sets as direct field maps and are frozen
    byte-identical once released (base.yaml's own header), so the loader
    normalizes them into the one shape the engine speaks: a type-spec
    fragment carrying only `fields:`, `links:` and `body:`
    (docs/design/composition.md §1.7). An entry that already carries only
    set-spec keys passes through; no released set has a field named
    `fields`, `links` or `body`, so the test is unambiguous in practice.
    """
    if spec is None or not isinstance(spec, dict):
        return spec
    if spec and not set(spec) <= _SET_SPEC_KEYS:
        return {"fields": spec}
    return spec


def _merge_sets(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge set specs by set name; within a set, `fields:` and `links:`
    merge by key (an overlay may add a field to `provenance` without
    redeclaring it) and `body:` replaces wholesale -- the same rules
    `_merge_type_dict` uses for a type. Entries arrive normalized
    (`_normalize_set_entry`), so every entry has the wrapped shape."""
    result = dict(base)
    for name, spec in overlay.items():
        if spec is None:
            result.pop(name, None)
            continue
        existing = result.get(name) or {}
        merged = dict(existing)
        merged.update(spec)
        merged["fields"] = _merge_named_mapping(
            existing.get("fields") or {}, spec.get("fields") or {}
        )
        merged["links"] = _merge_named_mapping(
            existing.get("links") or {}, spec.get("links") or {}
        )
        result[name] = merged
    return result


def _expand_include(
    type_raw: dict[str, Any],
    sets: dict[str, Any],
    path: str = "types",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve `include:` into `fields:`, `links:` and `body:`, and drop
    `include:` from the result (docs/design/composition.md §2).

    A set is a fragment of the type's own spec. Sets merge in include-list
    order, later wins on a name collision; then the type's own declarations
    merge last and beat anything they include. Every merge is by-name with
    whole-spec replacement -- no field spec, link target list or body block
    is deep-merged across a set boundary.

    Two *sets* fighting is loud: the same verb or body declared with
    different specs by two includes is an error, because neither set's
    author wrote the conflict at the point of use and the later one would
    silently replace the earlier. Identical declarations are benign. The
    type outvoting a set it names on its own line is documented behavior,
    not an error.
    """
    type_raw = dict(type_raw or {})
    includes = type_raw.pop("include", None) or []
    if isinstance(includes, str):
        # A bare `include: common` used to iterate per character and report an
        # unknown set 'c'. configcheck rejects it for a project's own
        # types; this is the same message for the bundle path.
        raise SchemaError(
            f"{path}.include must be a list of set names, got "
            f"{includes!r} -- write include: [{includes}]"
        )
    own_fields = type_raw.get("fields") or {}
    own_links = type_raw.get("links") or {}

    merged_fields: dict[str, Any] = {}
    merged_links: dict[str, Any] = {}
    merged_body: Any = None
    link_from: dict[str, str] = {}
    body_from: str | None = None
    contributions: list[tuple[str, dict, dict, Any]] = []
    # field name -> the spec the sets left it with, for the doc-only patch
    # rule (§3), and which set a patch patched -- so a patched set still
    # counts as having contributed.
    set_provided: dict[str, Any] = {}
    patched_from: dict[str, str] = {}

    for set_name in includes:
        if set_name not in sets:
            close = difflib.get_close_matches(str(set_name), sorted(sets), n=1, cutoff=0.5)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise SchemaError(
                f"{path}.include names unknown set {set_name!r}.{hint}"
            )
        entry = sets[set_name] or {}
        set_fields = entry.get("fields") or {}
        set_links = entry.get("links") or {}
        set_body = entry.get("body")

        for verb, targets in set_links.items():
            if verb in merged_links and merged_links[verb] != targets:
                raise SchemaError(
                    f"{path}.include: sets {link_from[verb]!r} and {set_name!r} both "
                    f"declare link {verb!r} with different targets "
                    f"({merged_links[verb]} vs {targets}); the later would silently "
                    f"replace the earlier -- declare {verb!r} once, on the type"
                )
            if verb not in merged_links:
                merged_links[verb] = targets
                link_from[verb] = set_name
        if set_body is not None:
            if merged_body is not None and merged_body != set_body:
                raise SchemaError(
                    f"{path}.include: sets {body_from!r} and {set_name!r} both declare "
                    f"body with different specs; the later would silently replace the "
                    f"earlier -- declare body on the type instead"
                )
            merged_body = set_body
            body_from = set_name
        merged_fields.update(set_fields)
        for fname, fspec in set_fields.items():
            set_provided[fname] = fspec
        contributions.append((set_name, set_fields, set_links, set_body))

    def _last_provider(fname: str) -> str:
        for sn, sf, _sl, _sb in reversed(contributions):
            if fname in sf:
                return sn
        return ""

    # The type's own fields merge last. Overriding an included field is
    # either a doc-only patch -- a spec whose only key is `doc:`, which
    # inherits type/required/choices/default/on_change from the set and
    # keeps every type's wording as written (§3) -- or a full redeclaration
    # that must carry `type:`. A spec with some semantic keys but no `type:`
    # is neither, and saying so beats defaulting it to text.
    for fname, fspec in own_fields.items():
        if fname in set_provided and isinstance(fspec, dict) and set(fspec) == {"doc"}:
            patched = dict(set_provided[fname] or {})
            patched["doc"] = fspec["doc"]
            merged_fields[fname] = patched
            patched_from[fname] = _last_provider(fname)
        elif (
            fname in set_provided
            and isinstance(fspec, dict)
            and "type" not in fspec
        ):
            raise SchemaError(
                f"{path}.fields.{fname} overrides an included field but is "
                "neither a full definition (missing 'type') nor a doc-only "
                f"patch; keys given: {', '.join(sorted(fspec))}"
            )
        else:
            merged_fields[fname] = fspec
    if merged_links:
        merged_links.update(own_links)
        type_raw["links"] = merged_links
    if merged_body is not None and type_raw.get("body") is None:
        type_raw["body"] = merged_body
    type_raw["fields"] = merged_fields

    if warnings is not None:
        final_body = type_raw.get("body")
        for set_name, cf, cl, cb in contributions:
            survives = (
                any(
                    merged_fields.get(f) == spec or patched_from.get(f) == set_name
                    for f, spec in cf.items()
                )
                or any(type_raw.get("links", {}).get(v) == t for v, t in cl.items())
                or (cb is not None and final_body == cb)
            )
            if not survives:
                warnings.append(
                    f"{path}.include: set {set_name!r} contributes nothing that "
                    "survives the merge"
                )
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
    base_types: dict[str, Any],
    project_types_raw: dict[str, Any],
    sets: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tname, traw in base_types.items():
        result[tname] = _expand_include(traw, sets, f"types.{tname}", warnings)

    for tname, traw in project_types_raw.items():
        if traw is None:
            # `types.<name>: null` -- removes an inherited type entirely. Anything
            # still referencing it (a link target list, satisfying_statuses, ...)
            # surfaces as an ordinary load-time SchemaError from the validation
            # that already runs over the final merged schema in schema.py.
            result.pop(tname, None)
            continue
        expanded_overlay = _expand_include(traw, sets, f"types.{tname}", warnings)
        if tname in result:
            result[tname] = _merge_type_dict(result[tname], expanded_overlay)
        else:
            result[tname] = expanded_overlay

    return result
