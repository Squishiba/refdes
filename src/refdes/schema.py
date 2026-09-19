"""Load a project's two config files into a Project.

`refdes-project.yaml` is the project marker and holds every project setting;
`refdes-schema.yaml` is the optional overlay holding only the project's own
`types:`/`link_types:`/`field_sets:`. `refdes.yaml` is retired -- a project
carrying one gets an error naming both replacements, never a silent ignore.
"""

from __future__ import annotations

import difflib
import os
from typing import Any

import yaml

from . import calc, dates, standards
from .configcheck import EQUATION_KEYS, BlockChecker, validate_overlay, validate_settings
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
from .parse import yaml_safe_load

# The project marker: every project setting lives here, and finding this file
# is what makes a directory a refdes project.
PROJECT_SETTINGS_NAME = "refdes-project.yaml"

# The project's own schema overlay -- `types:`, `link_types:`, `field_sets:`
# only. Optional: most projects take their whole vocabulary from the bundled
# standard and never need one.
SCHEMA_NAME = "refdes-schema.yaml"

# Retired. A project still carrying it gets LEGACY_CONFIG_ERROR, never a
# silent ignore: a setting left behind in it would stop applying quietly.
LEGACY_CONFIG_NAME = "refdes.yaml"

# Back-compatible alias: CONFIG_NAME now names the marker.
CONFIG_NAME = PROJECT_SETTINGS_NAME

# The three namespaces the overlay file owns.
SCHEMA_KEYS = frozenset({"types", "link_types", "field_sets"})

# The setting keys that moved here from the retired refdes.yaml.
_PROJECT_SETTING_KEYS = {
    "site",
    "id",
    "boards",
    "workspaces",
    "units",
    "date_format",
    "history",
    "standard",
    "equations",
    "imports",
}

_KNOWN_SETTINGS = {
    "sigfigs",
    "item_layout",
    "baseline_identity",
    "require_rejection_rationale",
    "publish_datasheets",
    "lint_own_tags",
    "release_gate",
    "cross_workspace_severity",
} | _PROJECT_SETTING_KEYS

LEGACY_CONFIG_ERROR = (
    f"{LEGACY_CONFIG_NAME} is retired. Split it into the two files it became: "
    f"move every project setting (site:, id:, boards:, workspaces:, units:, "
    f"history:, standard:, equations:, imports:, and the process settings like "
    f"sigfigs: and release_gate:) into {PROJECT_SETTINGS_NAME}, which is now the "
    f"project marker, and move any schema overlay (types:, link_types:, "
    f"field_sets:) into {SCHEMA_NAME}, which is optional -- omit it entirely if "
    f"the project declares no types of its own. Then delete {LEGACY_CONFIG_NAME}: "
    f"nothing is read from it any more, so a key left behind there is a setting "
    f"that silently stops applying."
)


def _legacy_config_error() -> SchemaError:
    return SchemaError(LEGACY_CONFIG_ERROR)


def _settings_error(message: str) -> SchemaError:
    return SchemaError(f"{PROJECT_SETTINGS_NAME}: {message}")


def _validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a project settings mapping and resolve every default.

    A setting left at its default behaves exactly as pre-config behaviour did --
    except `publish_datasheets`, whose default is a deliberate change (see
    `Project.publish_datasheets`'s docstring).
    """
    for key in raw:
        if key in SCHEMA_KEYS:
            raise _settings_error(
                f"{key} does not belong here -- the project's own schema overlay "
                f"lives in {SCHEMA_NAME}, which holds types:, link_types: and "
                f"field_sets: and nothing else"
            )
        if key not in _KNOWN_SETTINGS:
            import difflib

            close = difflib.get_close_matches(str(key), sorted(_KNOWN_SETTINGS), n=1, cutoff=0.5)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise _settings_error(f"unknown setting {key!r}.{hint}")

    date_format = raw.get("date_format", dates.DEFAULT_DATE_FORMAT)
    try:
        dates.validate_format(date_format)
    except (TypeError, ValueError) as exc:
        raise _settings_error(f"date_format {exc}, got {date_format!r}") from exc

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

    lint_own_tags = raw.get("lint_own_tags", False)
    if not isinstance(lint_own_tags, bool):
        raise _settings_error(
            f"lint_own_tags must be true or false, got {lint_own_tags!r}"
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
        "date_format": date_format,
        "sigfigs": sigfigs,
        "item_layout": item_layout,
        "baseline_identity": baseline_identity,
        "require_rejection_rationale": require_rejection_rationale,
        "publish_datasheets": publish_datasheets,
        "lint_own_tags": lint_own_tags,
        "release_gate": release_gate,
        "cross_workspace_severity": cross_workspace_severity,
    }


def _load_schema_overlay(root: str) -> dict[str, Any]:
    """Load the project's own `refdes-schema.yaml`, or {} when it has none.

    Optional by design: a project taking its whole vocabulary from the bundled
    standard declares nothing here and the file simply does not exist. It owns
    exactly three keys -- anything else in it is a setting that belongs in
    `refdes-project.yaml`, and saying so is what keeps a half-migrated project
    from losing a setting in silence.
    """
    path = os.path.join(root, SCHEMA_NAME)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml_safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise SchemaError(f"{SCHEMA_NAME}: must be a mapping of schema key to value")
    for key in raw:
        if key in SCHEMA_KEYS:
            continue
        what = "a project setting" if key in _KNOWN_SETTINGS else "not a schema key"
        raise SchemaError(
            f"{SCHEMA_NAME}: {key!r} is {what} -- this file holds only types:, "
            f"link_types: and field_sets:; every setting lives in "
            f"{PROJECT_SETTINGS_NAME}"
        )
    return raw


def _load_equations(raw: dict[str, Any]) -> dict[str, calc.Equation]:
    """Load and validate the project's `equations:` block.

    A project-wide vocabulary of named expressions callable from any calc block
    (docs/math.md), sitting alongside `units:` because it plays the same role:
    project-wide vocabulary that fixes how an expression is read.

    Structure is checked here because that is where a bad definition has a file and
    a name to report against; the two semantic rules (no built-in shadowing, no
    cycles) are `calc.validate_equations`'s, and run again inside
    `calc.set_equations` so nothing can install a registry that skipped them.
    """
    check = BlockChecker(PROJECT_SETTINGS_NAME)
    block = raw.get("equations") or {}
    if not isinstance(block, dict):
        raise SchemaError(
            "equations must be a mapping of equation name to its definition"
        )

    equations: dict[str, calc.Equation] = {}
    for name, spec in block.items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise SchemaError(
                f"equations.{name} must be a mapping with 'params' and 'expr'"
            )
        check.keys(spec, EQUATION_KEYS, f"equations.{name}", "an equations: entry")

        params = spec.get("params") or []
        if not isinstance(params, list):
            raise SchemaError(
                f"equations.{name}.params must be a list of parameter names"
            )
        params = [str(p) for p in params]
        for param in params:
            if not calc.EQUATION_NAME_RE.match(param):
                raise SchemaError(
                    f"equations.{name}.params names {param!r}, which is not a "
                    "usable name (letters, digits, underscores)"
                )
        if len(set(params)) != len(params):
            raise SchemaError(
                f"equations.{name}.params lists a parameter twice -- a parameter "
                "can only be bound once"
            )

        expr = spec.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            raise SchemaError(
                f"equations.{name}.expr must be a non-empty expression"
            )
        try:
            calc.parse_expression(expr)
        except calc.CalcError as exc:
            raise SchemaError(f"equations.{name}.expr: {exc}") from exc

        equations[str(name)] = calc.Equation(
            str(name), params, expr.strip(), str(spec.get("note") or "")
        )

    try:
        calc.validate_equations(equations)
    except calc.CalcError as exc:
        raise SchemaError(f"equations: {exc}") from exc
    return equations


def find_config(start: str = ".") -> str:
    """Walk up from `start` looking for the project marker, refdes-project.yaml.

    A directory holding only the retired refdes.yaml is not a project: the walk
    reports the split rather than the generic "not found", because that error is
    how a user discovers the change.
    """
    here = os.path.abspath(start)
    legacy: str | None = None
    while True:
        candidate = os.path.join(here, PROJECT_SETTINGS_NAME)
        if os.path.isfile(candidate):
            return candidate
        if legacy is None and os.path.isfile(os.path.join(here, LEGACY_CONFIG_NAME)):
            legacy = os.path.join(here, LEGACY_CONFIG_NAME)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    if legacy is not None:
        raise _legacy_config_error()
    raise SchemaError(
        f"no {PROJECT_SETTINGS_NAME} found in {os.path.abspath(start)} or any parent "
        f"directory -- that file is the project marker, and holds every project "
        f"setting; {SCHEMA_NAME} is the optional overlay holding only types:, "
        f"link_types: and field_sets:"
    )


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
    if os.path.basename(os.path.abspath(path)) == LEGACY_CONFIG_NAME:
        raise _legacy_config_error()
    with open(path, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml_safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise _settings_error("must be a mapping of setting name to value")

    root = os.path.dirname(os.path.abspath(path))
    # Checked against the resolved root, not just the path we were handed: a
    # project carrying both files is half-migrated, and reading only one of
    # them is the silent partial load this split exists to make impossible.
    if os.path.isfile(os.path.join(root, LEGACY_CONFIG_NAME)):
        raise _legacy_config_error()

    # Settings are validated first, against the settings file's own keys: a
    # `types:` left in refdes-project.yaml is a half-migration, and merging
    # before checking would let it pass as a schema key instead of naming it.
    settings = _validate_settings(raw)
    overlay = _load_schema_overlay(root)
    # Every nested block of both files is validated here, before anything reads
    # it: an unknown key is a configuration error naming its block path, and a
    # wrong type is one naming what it expected. Nothing below this line takes a
    # config value on trust -- see configcheck.py.
    blocks = validate_settings(raw, PROJECT_SETTINGS_NAME)
    validate_overlay(overlay, SCHEMA_NAME)
    # The two are disjoint by validation, so one dict is all
    # standards.resolve_schema needs: `standard:` from the settings, the
    # project's own types:/link_types:/field_sets: from the overlay.
    raw = {**raw, **overlay}

    equations = _load_equations(raw)

    site = blocks["site"]
    id_cfg = blocks["id"]
    units = blocks["units"]
    default_on_change = blocks["history"]["default"]

    # standard: {base, version, presets} resolves fresh, here, on every load --
    # never a scaffold copy. See standards.py and docs/design/standard-library.md
    # §3. `resolved_link_types`/`resolved_types` are plain dicts in exactly the
    # shape refdes-schema.yaml's own link_types:/types: would use, already merged across
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
        body_required = bool(body_cfg.get("required", False))

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
            body_required=body_required,
            append_only=bool(tspec.get("append_only", False)),
            satisfying_statuses=satisfying_statuses,
            check_severity=check_severity,
            coverable=coverable,
            coverable_statuses=coverable_statuses,
            verifying_statuses=verifying_statuses,
        )

    if not types:
        raise SchemaError(
            f"{path} declares no item types -- add a standard: block, or a "
            f"types: block in {SCHEMA_NAME}"
        )

    _validate_required_when(types)
    _validate_link_targets(types)

    import_specs = [
        ImportSpec(
            name=entry["name"],
            items_path=entry["items"],
            version=entry["version"],
        )
        for entry in blocks["imports"]
    ]

    boards: dict[str, BoardSpec] = {}
    path_owner: dict[str, str] = {}
    for bname, bspec in blocks["boards"].items():
        spec = BoardSpec(
            name=bname,
            label=bspec["label"],
            token=bspec["token"],
            path=bspec["path"],
            conforms_to=bspec["conforms_to"],
            includes=bspec["includes"],
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
    for wname, wspec in blocks["workspaces"].items():
        spec = WorkspaceSpec(
            name=wname,
            label=wspec["label"],
            shared=wspec["shared"],
            path=wspec["path"],
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

    preset_provided_types: dict[str, str] = {}
    preset_provided_links: dict[str, str] = {}
    standard_base = ""
    standard_version: int | None = None
    standard_cfg = raw.get("standard")
    if isinstance(standard_cfg, dict) and standard_cfg.get("base") in standards.known_bases():
        version = standard_cfg.get("version")
        if isinstance(version, int) and not isinstance(version, bool):
            standard_base = str(standard_cfg["base"])
            standard_version = version
            preset_provided_types, preset_provided_links = standards.preset_providers(
                standard_cfg["base"], version
            )

    project = Project(
        title=site["title"],
        out_dir=site["out"],
        version=site["version"],
        pages_dir=site["pages"],
        nav_order=site["nav"],
        asset_dirs=site["assets"],
        imports=import_specs,
        types=types,
        link_types=link_types,
        inverse_of=inverse_of,
        default_on_change=default_on_change,
        id_width=id_cfg["width"],
        id_ledger=id_cfg["ledger"],
        preferred_units=units["preferred"],
        unit_aliases=units["aliases"],
        equations=equations,
        root=root,
        boards=boards,
        workspaces=workspaces,
        date_format=settings["date_format"],
        sigfigs=settings["sigfigs"],
        item_layout=settings["item_layout"],
        baseline_identity=settings["baseline_identity"],
        require_rejection_rationale=settings["require_rejection_rationale"],
        publish_datasheets=settings["publish_datasheets"],
        lint_own_tags=settings["lint_own_tags"],
        release_gate=settings["release_gate"],
        cross_workspace_severity=settings["cross_workspace_severity"],
        preset_provided_types=preset_provided_types,
        preset_provided_links=preset_provided_links,
        standard_base=standard_base,
        standard_version=standard_version,
    )
    # Install the equation registry alongside the unit config. Loading a project
    # is what fixes how its expressions read, and build.py applies unit aliases
    # the same way -- a project with no `equations:` resets it to empty.
    calc.set_equations(equations)
    return project
