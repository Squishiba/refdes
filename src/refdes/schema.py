"""Load refdes.yaml into a Project."""

from __future__ import annotations

import difflib
import os
from typing import Any

import yaml

from . import standards
from .model import (
    BASELINE_IDENTITIES,
    DIAGNOSTIC_LEVELS,
    ERROR,
    ITEM_LAYOUTS,
    ON_CHANGE_MODES,
    RELEASE_GATE_DEFAULTS,
    WARNING,
    BoardSpec,
    FieldSpec,
    ImportSpec,
    ItemType,
    LinkType,
    Project,
    SchemaError,
    WorkspaceSpec,
)

CONFIG_NAME = "refdes.yaml"

# Project-level presentation/behaviour settings, committed alongside refdes.yaml
# but deliberately not in it -- refdes.yaml is schema (types, links, boards);
# this is process policy and formatting preference. See docs/design/lifecycle.md
# and docs/design/standard-library.md for the design discussions behind these.
PROJECT_SETTINGS_NAME = "refdes-project.yaml"

_KNOWN_SETTINGS = {
    "sigfigs",
    "item_layout",
    "baseline_identity",
    "require_rejection_rationale",
    "publish_datasheets",
    "release_gate",
    "cross_workspace_severity",
}


def _settings_error(message: str) -> SchemaError:
    return SchemaError(f"{PROJECT_SETTINGS_NAME}: {message}")


def _load_project_settings(root: str) -> dict[str, Any]:
    """Load and validate `refdes-project.yaml`, sibling to `refdes.yaml`.

    Absent entirely, every setting takes the default matching pre-config
    behaviour -- except `publish_datasheets`, whose default is a deliberate
    behaviour change (see `Project.publish_datasheets`'s docstring).
    """
    path = os.path.join(root, PROJECT_SETTINGS_NAME)
    if not os.path.isfile(path):
        raw: dict[str, Any] = {}
    else:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            raise _settings_error("must be a mapping of setting name to value")

    for key in raw:
        if key not in _KNOWN_SETTINGS:
            import difflib

            close = difflib.get_close_matches(str(key), sorted(_KNOWN_SETTINGS), n=1, cutoff=0.5)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise _settings_error(f"unknown setting {key!r}.{hint}")

    sigfigs = raw.get("sigfigs", 4)
    if isinstance(sigfigs, bool) or not isinstance(sigfigs, int) or not (1 <= sigfigs <= 15):
        raise _settings_error(
            f"sigfigs must be an integer between 1 and 15, got {sigfigs!r}"
        )

    item_layout = raw.get("item_layout", "flat")
    if item_layout not in ITEM_LAYOUTS:
        raise _settings_error(
            f"item_layout must be one of {list(ITEM_LAYOUTS)}, got {item_layout!r}"
        )

    baseline_identity = raw.get("baseline_identity", "os_user")
    if baseline_identity not in BASELINE_IDENTITIES:
        raise _settings_error(
            f"baseline_identity must be one of {list(BASELINE_IDENTITIES)}, "
            f"got {baseline_identity!r}"
        )

    require_rejection_rationale = raw.get("require_rejection_rationale", True)
    if not isinstance(require_rejection_rationale, bool):
        raise _settings_error(
            f"require_rejection_rationale must be true or false, got "
            f"{require_rejection_rationale!r}"
        )

    publish_datasheets = raw.get("publish_datasheets", False)
    if not isinstance(publish_datasheets, bool):
        raise _settings_error(
            f"publish_datasheets must be true or false, got {publish_datasheets!r}"
        )

    cross_workspace_severity = raw.get("cross_workspace_severity", WARNING)
    if cross_workspace_severity not in DIAGNOSTIC_LEVELS:
        raise _settings_error(
            f"cross_workspace_severity must be one of {list(DIAGNOSTIC_LEVELS)}, "
            f"got {cross_workspace_severity!r}"
        )

    release_gate = {name: dict(rule) for name, rule in RELEASE_GATE_DEFAULTS.items()}
    overlay = raw.get("release_gate") or {}
    if not isinstance(overlay, dict):
        raise _settings_error(
            "release_gate must be a mapping of rule name to {release, revision}"
        )
    for rule_name, rule_cfg in overlay.items():
        if rule_name not in RELEASE_GATE_DEFAULTS:
            import difflib

            close = difflib.get_close_matches(
                str(rule_name), sorted(RELEASE_GATE_DEFAULTS), n=1, cutoff=0.5
            )
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise _settings_error(
                f"release_gate.{rule_name} is not a known rule "
                f"(one of {list(RELEASE_GATE_DEFAULTS)}).{hint}"
            )
        rule_cfg = rule_cfg or {}
        if not isinstance(rule_cfg, dict):
            raise _settings_error(
                f"release_gate.{rule_name} must be a mapping with 'release' "
                f"and/or 'revision' keys, got {rule_cfg!r}"
            )
        for key, value in rule_cfg.items():
            if key not in ("release", "revision"):
                raise _settings_error(
                    f"release_gate.{rule_name}.{key} is not valid -- only "
                    f"'release' and 'revision' are recognized"
                )
            if not isinstance(value, bool):
                raise _settings_error(
                    f"release_gate.{rule_name}.{key} must be true or false, "
                    f"got {value!r}"
                )
            release_gate[rule_name][key] = value

    return {
        "sigfigs": sigfigs,
        "item_layout": item_layout,
        "baseline_identity": baseline_identity,
        "require_rejection_rationale": require_rejection_rationale,
        "publish_datasheets": publish_datasheets,
        "release_gate": release_gate,
        "cross_workspace_severity": cross_workspace_severity,
    }


def find_config(start: str = ".") -> str:
    """Walk up from `start` looking for refdes.yaml."""
    here = os.path.abspath(start)
    while True:
        candidate = os.path.join(here, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            raise SchemaError(
                f"no {CONFIG_NAME} found in {os.path.abspath(start)} or any parent directory"
            )
        here = parent


def _validate_required_when(types: dict[str, ItemType]) -> None:
    """Cross-validate every `required_when:` against the fully merged schema.

    Runs after base, presets, and the project overlay have all been applied --
    only the final resolved schema matters (docs/design/standard-library.md §2).
    An override that drops an enum value or a link a `required_when:` still
    references fails the build here, naming both sides, rather than silently
    leaving a dead condition in the merged schema.
    """
    for tname, spec in types.items():
        for fname, fspec in spec.fields.items():
            if not fspec.required_when:
                continue
            for key, raw_values in fspec.required_when.items():
                values = raw_values if isinstance(raw_values, list) else [raw_values]
                if key == "links":
                    for lname in values:
                        if lname not in spec.links:
                            close = difflib.get_close_matches(
                                str(lname), sorted(spec.links), n=1, cutoff=0.5
                            )
                            hint = f" Did you mean {close[0]!r}?" if close else ""
                            raise SchemaError(
                                f"types.{tname}.fields.{fname}.required_when.links "
                                f"names {lname!r}, which is not a declared link on "
                                f"{tname}.{hint}"
                            )
                    continue
                if key == fname:
                    raise SchemaError(
                        f"types.{tname}.fields.{fname}.required_when cannot name "
                        "itself"
                    )
                cond_field = spec.fields.get(key)
                if cond_field is None:
                    close = difflib.get_close_matches(
                        str(key), sorted(spec.fields), n=1, cutoff=0.5
                    )
                    hint = f" Did you mean {close[0]!r}?" if close else ""
                    raise SchemaError(
                        f"types.{tname}.fields.{fname}.required_when references "
                        f"field {key!r}, which is not declared on {tname}.{hint}"
                    )
                if cond_field.type != "enum":
                    raise SchemaError(
                        f"types.{tname}.fields.{fname}.required_when references "
                        f"{key!r}, which is type {cond_field.type!r} -- "
                        "required_when condition fields must be type: enum"
                    )
                choices = cond_field.choices or []
                for value in values:
                    if value not in choices:
                        raise SchemaError(
                            f"types.{tname}.fields.{fname}.required_when "
                            f"references {key}: {value!r}, which is not among "
                            f"{key}'s declared choices: {choices}. Update or "
                            "remove the required_when clause."
                        )


def _validate_link_targets(types: dict[str, ItemType]) -> None:
    """A link's declared target types must still exist after any override.

    An empty target list means "unrestricted" (docs/design/standard-library.md
    §9) and is exempt. This is what turns `types.component: null` into a hard,
    specific error when something still declares `selects: [component]`,
    instead of a silent no-op at build time.
    """
    for tname, spec in types.items():
        for lname, targets in spec.links.items():
            for target in targets:
                if target not in types:
                    raise SchemaError(
                        f"types.{tname}.links.{lname} names target type "
                        f"{target!r}, which is not declared (removed by an "
                        "override?)"
                    )


def load_project(config_path: str | None = None, start: str = ".") -> Project:
    path = config_path or find_config(start)
    with open(path, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    root = os.path.dirname(os.path.abspath(path))
    settings = _load_project_settings(root)

    site = raw.get("site") or {}
    id_cfg = raw.get("id") or {}
    history = raw.get("history") or {}
    units = raw.get("units") or {}

    default_on_change = history.get("default", "invalidate")
    if default_on_change not in ON_CHANGE_MODES:
        raise SchemaError(
            f"history.default must be one of {list(ON_CHANGE_MODES)}, got {default_on_change!r}"
        )

    # standard: {base, version, presets} resolves fresh, here, on every load --
    # never a scaffold copy. See standards.py and docs/design/standard-library.md
    # §3. `resolved_link_types`/`resolved_types` are plain dicts in exactly the
    # shape refdes.yaml's own link_types:/types: would use, already merged across
    # base -> presets -> this project's own overlay, with `include:` resolved
    # into `fields:` -- everything below reads them exactly as it always read
    # raw.get("link_types")/raw.get("types") directly.
    resolved_link_types, resolved_types = standards.resolve_schema(
        raw, settings["require_rejection_rationale"]
    )

    link_types: dict[str, LinkType] = {}
    inverse_of: dict[str, str] = {}
    for name, spec in resolved_link_types.items():
        spec = spec or {}
        inverse = spec.get("inverse", f"{name}_by")
        link_types[name] = LinkType(
            name=name,
            inverse=inverse,
            label=spec.get("label", name),
            trace=bool(spec.get("trace", True)),
        )
        inverse_of[name] = inverse

    # A link may be declared from either end -- a requirement's `verified_by` and a
    # test's `verifies` are the same edge -- so the map has to resolve both ways.
    for name, inverse in list(inverse_of.items()):
        inverse_of.setdefault(inverse, name)

    types: dict[str, ItemType] = {}
    for tname, tspec in resolved_types.items():
        tspec = tspec or {}
        fields: dict[str, FieldSpec] = {}
        for fname, fspec in (tspec.get("fields") or {}).items():
            fspec = fspec or {}
            on_change = fspec.get("on_change", default_on_change)
            if on_change not in ON_CHANGE_MODES:
                raise SchemaError(
                    f"types.{tname}.fields.{fname}.on_change must be one of "
                    f"{list(ON_CHANGE_MODES)}, got {on_change!r}"
                )
            required = bool(fspec.get("required", False))
            required_when = fspec.get("required_when")
            if required_when is not None:
                if not isinstance(required_when, dict) or not required_when:
                    raise SchemaError(
                        f"types.{tname}.fields.{fname}.required_when must be a "
                        "mapping of field or link name to the value(s) that make "
                        "this field required"
                    )
                if required:
                    raise SchemaError(
                        f"types.{tname}.fields.{fname} declares both "
                        "'required: true' and 'required_when:' -- unconditional "
                        "requiredness already implies every condition; use one "
                        "or the other"
                    )
            fields[fname] = FieldSpec(
                name=fname,
                type=fspec.get("type", "text"),
                on_change=on_change,
                required=required,
                choices=fspec.get("choices"),
                default=fspec.get("default"),
                required_when=required_when,
            )

        links: dict[str, list[str]] = {}
        for lname, targets in (tspec.get("links") or {}).items():
            if lname not in link_types and lname not in inverse_of.values():
                raise SchemaError(
                    f"types.{tname}.links.{lname} is not a declared link_type"
                )
            links[lname] = list(targets or [])

        body_cfg = tspec.get("body") or {}
        body_on_change = body_cfg.get("on_change", default_on_change)
        if body_on_change not in ON_CHANGE_MODES:
            raise SchemaError(
                f"types.{tname}.body.on_change must be one of {list(ON_CHANGE_MODES)}"
            )

        satisfying_statuses = tspec.get("satisfying_statuses")
        if satisfying_statuses is not None:
            if "status" not in fields:
                raise SchemaError(
                    f"types.{tname}.satisfying_statuses requires a 'status' field "
                    f"on {tname}"
                )
            satisfying_statuses = [str(s) for s in satisfying_statuses]

        check_severity = tspec.get("check_severity", ERROR)
        if check_severity not in DIAGNOSTIC_LEVELS:
            raise SchemaError(
                f"types.{tname}.check_severity must be one of {list(DIAGNOSTIC_LEVELS)}, "
                f"got {check_severity!r}"
            )

        coverable_raw = tspec.get("coverable")
        coverable = None if coverable_raw is None else bool(coverable_raw)

        coverable_statuses = tspec.get("coverable_statuses")
        if coverable_statuses is not None:
            coverable_statuses = [str(s) for s in coverable_statuses]

        verifying_statuses = tspec.get("verifying_statuses")
        if verifying_statuses is not None:
            verifying_statuses = [str(s) for s in verifying_statuses]

        types[tname] = ItemType(
            name=tname,
            prefix=tspec.get("prefix", tname[:3].upper()),
            label=tspec.get("label", tname.title()),
            plural=tspec.get("plural", "") or f"{tspec.get('label', tname.title())}s",
            fields=fields,
            links=links,
            preview=list(tspec.get("preview") or []),
            body_on_change=body_on_change,
            append_only=bool(tspec.get("append_only", False)),
            satisfying_statuses=satisfying_statuses,
            check_severity=check_severity,
            coverable=coverable,
            coverable_statuses=coverable_statuses,
            verifying_statuses=verifying_statuses,
        )

    if not types:
        raise SchemaError(f"{path} declares no item types")

    _validate_required_when(types)
    _validate_link_targets(types)

    import_specs: list[ImportSpec] = []
    for entry in raw.get("imports") or []:
        entry = entry or {}
        if not entry.get("name") or not entry.get("items"):
            raise SchemaError("each imports: entry needs 'name' and 'items'")
        import_specs.append(
            ImportSpec(
                name=str(entry["name"]),
                items_path=str(entry["items"]),
                version=str(entry["version"]) if entry.get("version") else None,
            )
        )

    boards: dict[str, BoardSpec] = {}
    path_owner: dict[str, str] = {}
    for bname, bspec in (raw.get("boards") or {}).items():
        bspec = bspec or {}
        spec = BoardSpec(
            name=bname,
            label=bspec.get("label", bname),
            token=str(bspec.get("token") or ""),
            path=str(bspec.get("path") or ""),
        )
        segment = spec.path_segment
        if segment in path_owner:
            raise SchemaError(
                f"boards.{bname} and boards.{path_owner[segment]} both map to "
                f"items/{segment}/ — path segments must be unique"
            )
        path_owner[segment] = bname
        boards[bname] = spec

    # Own path-segment namespace -- a workspace is a different level under
    # items/ than a board (items/<workspace>/<board>/), so a workspace's
    # segment never collides with a board's own.
    workspaces: dict[str, WorkspaceSpec] = {}
    workspace_path_owner: dict[str, str] = {}
    for wname, wspec in (raw.get("workspaces") or {}).items():
        wspec = wspec or {}
        spec = WorkspaceSpec(
            name=wname,
            label=wspec.get("label", wname),
            shared=bool(wspec.get("shared", False)),
            path=str(wspec.get("path") or ""),
        )
        segment = spec.path_segment
        if segment in workspace_path_owner:
            raise SchemaError(
                f"workspaces.{wname} and workspaces.{workspace_path_owner[segment]} "
                f"both map to items/{segment}/ — path segments must be unique"
            )
        workspace_path_owner[segment] = wname
        workspaces[wname] = spec

    # A board and a workspace share one generated-filename namespace
    # (`<report>-<key>.html`, and `<report>-<key>` in the drift manifest), so a
    # name used for both would collide there even though their path levels
    # don't collide above.
    name_collision = set(boards) & set(workspaces)
    if name_collision:
        clashing = sorted(name_collision)[0]
        raise SchemaError(
            f"{clashing!r} is declared as both a board and a workspace — boards "
            f"and workspaces share one namespace for generated report names "
            f"(e.g. coverage-{clashing}.html); rename one of them"
        )

    return Project(
        title=site.get("title", "Design Reference"),
        out_dir=site.get("out", "_site"),
        version=str(site.get("version") or ""),
        pages_dir=str(site.get("pages") or "pages"),
        nav_order=[str(s) for s in (site.get("nav") or [])],
        asset_dirs=[str(s) for s in (site.get("assets") or [])],
        imports=import_specs,
        types=types,
        link_types=link_types,
        inverse_of=inverse_of,
        default_on_change=default_on_change,
        id_width=int(id_cfg.get("width", 3)),
        id_ledger=id_cfg.get("ledger", ".refdes/ids.yaml"),
        preferred_units=list(units.get("preferred") or []),
        unit_aliases=dict(units.get("aliases") or {}),
        root=root,
        boards=boards,
        workspaces=workspaces,
        sigfigs=settings["sigfigs"],
        item_layout=settings["item_layout"],
        baseline_identity=settings["baseline_identity"],
        require_rejection_rationale=settings["require_rejection_rationale"],
        publish_datasheets=settings["publish_datasheets"],
        release_gate=settings["release_gate"],
        cross_workspace_severity=settings["cross_workspace_severity"],
    )
