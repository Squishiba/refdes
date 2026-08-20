"""`refdes init`, `refdes new <type>`, and `refdes standard add-preset` /
`remove-preset` -- project scaffolding and standard-library selection
(docs/design/standard-library.md §3, §6, §8, §12).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import yaml

from . import build as build_mod
from . import parse as parse_mod
from . import standards
from .build import _format_required_when
from .model import ItemType, Project, SchemaError
from .schema import load_project


def _vscode_settings_text(target_dir: str) -> str:
    """`.vscode/settings.json` content wiring `yaml.schemas` to this project's
    own `.refdes/schema.json`, keyed by an absolute path rather than the bare
    relative `./.refdes/schema.json` every project used to write identically.

    `redhat.vscode-yaml` does not reliably scope a relative schema path to the
    workspace folder that declared it, so two refdes projects open in the same
    VS Code session (a multi-root workspace, or just switching folders without
    a full reload) could end up validating one project's files against the
    other's schema -- a false rejection, not a near-miss, since the two
    schemas can differ arbitrarily (finding 9). An absolute path names one
    specific file unambiguously regardless of how many folders are open.
    """
    schema_path = os.path.abspath(
        os.path.join(target_dir, ".refdes", "schema.json")
    ).replace("\\", "/")
    settings = {"yaml.schemas": {schema_path: ["items/**/*.yaml"]}}
    return json.dumps(settings, indent=2) + "\n"


def _init_yaml(base: str | None, version: int | None, presets: list[str]) -> str:
    if base is None:
        standard_block = "standard: none\n"
    else:
        preset_list = ", ".join(presets)
        standard_block = (
            "standard:\n"
            f"  base: {base}\n"
            f"  version: {version}\n"
            f"  presets: [{preset_list}]\n"
        )
    return (
        "site:\n"
        '  title: "New Project — Design Reference"\n'
        "  out: _site\n"
        "\n"
        f"{standard_block}"
        "\n"
        "id:\n"
        "  width: 3\n"
        "  ledger: .refdes/ids.yaml\n"
    )


def init(
    target_dir: str,
    standard: str | None = "hardware",
    presets: list[str] | None = None,
    write_vscode_settings: bool = True,
) -> str:
    """Write a minimal `refdes.yaml` that points at the standard rather than
    copying it (docs/design/standard-library.md §3) -- no `types:`,
    `link_types:`, or `field_sets:` key anywhere in the file; that absence
    is the point. `standard=None` writes `standard: none`, the explicit
    escape hatch. `<version>` is never written as the literal string
    "latest": resolved here, once, to the concrete integer the installed
    tool currently ships as newest.

    Returns the path written. Raises SchemaError if refdes.yaml already
    exists at the target, or if `presets` is given with `standard=None`
    (every preset's types target base types, so presets require a base).
    """
    presets = presets or []
    if standard is None and presets:
        raise SchemaError(
            "presets require a base standard; set standard.base or drop presets:"
        )

    config_path = os.path.join(target_dir, "refdes.yaml")
    if os.path.exists(config_path):
        raise SchemaError(f"{config_path} already exists -- refdes init refuses to overwrite it")

    version: int | None = None
    if standard is not None:
        version = standards.latest_version(standard)
        available = standards.available_presets(standard, version)
        for preset_name in presets:
            if preset_name not in available:
                import difflib

                close = difflib.get_close_matches(preset_name, available, n=1, cutoff=0.5)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                raise SchemaError(
                    f"preset {preset_name!r} does not exist for {standard}@{version} "
                    f"(available: {available}).{hint}"
                )

    os.makedirs(target_dir, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(_init_yaml(standard, version, presets))

    if write_vscode_settings:
        vscode_dir = os.path.join(target_dir, ".vscode")
        settings_path = os.path.join(vscode_dir, "settings.json")
        if not os.path.isfile(settings_path):
            os.makedirs(vscode_dir, exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as fh:
                fh.write(_vscode_settings_text(target_dir))

    return config_path


# --------------------------------------------------------------- refdes new


def _field_hint(fname: str, fspec) -> str:
    if fspec.type == "enum":
        return "choices: " + ", ".join(fspec.choices or [])
    return fspec.type


def new_item_text(type_name: str, spec: ItemType) -> str:
    """Scaffold one item's front matter for `type_name`, generated from the
    identical resolved `ItemType` the JSON Schema (schema_json.py) and
    `items.json` (render.py) both read -- not a second, hand-maintained
    template per type that could drift from either (docs/design/
    standard-library.md §12's closing section).

    A required field with a declared `default:` is written with that
    default; a required field with none gets an empty placeholder; an
    optional field is written commented-out, with the same choices:/type
    hint the schema's own `description` carries; a link is written
    commented-out, naming its allowed target types the same way.
    """
    lines = ["---", "id:", f"type: {type_name}"]
    for fname, fspec in spec.fields.items():
        hint = _field_hint(fname, fspec)
        if fspec.default is not None:
            lines.append(f"{fname}: {fspec.default}  # {hint}")
        elif fspec.required:
            lines.append(f"{fname}:  # required -- {hint}")
        else:
            cond = ""
            if fspec.required_when:
                cond = f"; required when {_format_required_when(fspec.required_when)}"
            lines.append(f"# {fname}:  # {hint}{cond}")
    for lname, targets in spec.links.items():
        target_desc = ", ".join(targets) if targets else "any"
        lines.append(f"# {lname}: []  # target: {target_desc}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------- standard.presets


_PRESETS_RE = re.compile(r"(presets:\s*)\[([^\]]*)\]")


def _edit_presets_list(raw_text: str, mutate) -> str:
    """A minimal, comment-preserving text edit of `standard.presets: [...]`
    -- refdes.yaml is hand-authored and hand-commented, unlike the tool's
    own machine-owned lockfiles, so this never re-serializes the whole file
    (which would silently drop every comment). Only supports the flow-style
    list `refdes init` itself always writes; a block-style list is left for
    the author to edit by hand."""
    match = _PRESETS_RE.search(raw_text)
    if match is None:
        raise SchemaError(
            "could not find a 'presets: [...]' list to edit in refdes.yaml -- "
            "if standard.presets: is written in block-list style, edit it by hand"
        )
    current = [p.strip() for p in match.group(2).split(",") if p.strip()]
    new_list = mutate(current)
    new_span = f"{match.group(1)}[{', '.join(new_list)}]"
    return raw_text[: match.start()] + new_span + raw_text[match.end() :]


def _read_standard_cfg(raw: dict[str, Any]) -> dict[str, Any]:
    standard_cfg = raw.get("standard")
    if not isinstance(standard_cfg, dict):
        raise SchemaError(
            "standard.presets: requires a base standard -- this project has no "
            "standard: block (or uses standard: none) to add or remove a preset "
            "from"
        )
    return standard_cfg


def add_preset(project_root: str, preset_name: str) -> None:
    """Validate `preset_name` exists at the project's pinned version, then
    append it to `standard.presets:`. On the next load its types, links,
    and field sets simply join the merged schema -- no migration step, no
    re-running init (docs/design/standard-library.md §8)."""
    config_path = os.path.join(project_root, "refdes.yaml")
    with open(config_path, encoding="utf-8") as fh:
        raw_text = fh.read()
    raw = yaml.safe_load(raw_text) or {}
    standard_cfg = _read_standard_cfg(raw)

    base, version = standard_cfg.get("base"), standard_cfg.get("version")
    available = standards.available_presets(base, version)
    if preset_name not in available:
        import difflib

        close = difflib.get_close_matches(preset_name, available, n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        raise SchemaError(
            f"preset {preset_name!r} does not exist for {base}@{version} "
            f"(available: {available}).{hint}"
        )
    current = standard_cfg.get("presets") or []
    if preset_name in current:
        raise SchemaError(f"preset {preset_name!r} is already selected")

    new_text = _edit_presets_list(raw_text, lambda lst: lst + [preset_name])
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)


def remove_preset(project_root: str, preset_name: str) -> list:
    """Remove `preset_name` from `standard.presets:`, reporting what that
    breaks BEFORE writing the change: every type, link, and field set the
    preset provided disappears from the merged schema on the next load, so
    an item still using one of them needs to be seen now, not discovered on
    the next unrelated build (docs/design/standard-library.md §8).

    Returns the diagnostics a build against the post-removal config would
    produce. The config is still edited even if that list is non-empty --
    this command's whole job is to surface the consequence, not to block an
    author who has already decided to accept it.
    """
    config_path = os.path.join(project_root, "refdes.yaml")
    with open(config_path, encoding="utf-8") as fh:
        raw_text = fh.read()
    raw = yaml.safe_load(raw_text) or {}
    standard_cfg = _read_standard_cfg(raw)
    current = standard_cfg.get("presets") or []
    if preset_name not in current:
        raise SchemaError(
            f"preset {preset_name!r} is not currently selected "
            f"(standard.presets: {current})"
        )

    new_text = _edit_presets_list(raw_text, lambda lst: [p for p in lst if p != preset_name])

    # Simulate the removal via a scratch copy in the same directory, so the
    # report reflects the post-removal state before the real file is touched.
    scratch_path = config_path + ".scratch"
    with open(scratch_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    try:
        project = load_project(config_path=scratch_path)
        parse_mod.load_items(project, require_ids=False)
        build_mod.build(project, seal_write=False, reseal=False)
        diagnostics = list(project.diagnostics)
    finally:
        os.remove(scratch_path)

    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)

    return diagnostics
