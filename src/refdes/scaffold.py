"""`refdes init`, `refdes new <type>`, and `refdes standard add-preset` /
`remove-preset` -- project scaffolding and standard-library selection
(docs/design/standard-library.md §3, §6, §8, §12).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import build as build_mod
from . import parse as parse_mod
from . import standards, textio
from .build import _format_required_when
from .model import ItemType, SchemaError
from .parse import yaml_safe_load
from .schema import load_project


def _vscode_schema_path(target_dir: str) -> str:
    """This project's own `.refdes/schema.json`, in the form `yaml.schemas`
    wants it: absolute, with forward slashes even on Windows."""
    return os.path.abspath(
        os.path.join(target_dir, ".refdes", "schema.json")
    ).replace("\\", "/")


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

    The cost of that correctness is that the file names one machine, which is
    why writing it also puts it in `.gitignore` (see
    `_ensure_vscode_settings_gitignored`) and why an existing one is never
    silently skipped (see `vscode_settings_note`).
    """
    settings = {"yaml.schemas": {_vscode_schema_path(target_dir): ["items/**/*.yaml"]}}
    return json.dumps(settings, indent=2) + "\n"


# The block `init` appends to the project's .gitignore, written the way this
# repo's own .gitignore states its reasoning: the per-machine file named, the
# reason in a comment above it, the surrounding directory left alone -- a
# project's `.vscode/extensions.json` or `tasks.json` are shareable and worth
# committing, which is exactly why `.vscode/` as a whole must NOT be ignored.
_VSCODE_GITIGNORE_BLOCK = (
    "# Written by `refdes init`. The yaml.schemas path in this file is an\n"
    "# absolute path into one checkout, so a committed copy hands every other\n"
    "# clone a schema that resolves to nothing -- silently, in both tools.\n"
    "# Editor settings you mean to share belong in a file you write yourself.\n"
    ".vscode/settings.json\n"
)

# Patterns that already cover `.vscode/settings.json`, so appending our own
# would be noise. A small literal set on purpose rather than git's pattern
# language: `init` runs in directories that are not git repositories at all,
# so this cannot ask git what it thinks.
_GITIGNORE_COVERS_VSCODE_SETTINGS = frozenset(
    {
        ".vscode/settings.json",
        "/.vscode/settings.json",
        "**/.vscode/settings.json",
        ".vscode",
        ".vscode/",
        "/.vscode/",
        "**/.vscode/",
    }
)


def _gitignore_addresses_vscode_settings(text: str) -> bool:
    """Whether some pattern in `text` already states the project's position on
    `.vscode/settings.json` -- an ignore pattern or an explicit `!` negation.

    A negation counts: whoever wrote `!.vscode/settings.json` means to track
    that file, and git takes the *last* matching pattern, so appending ours
    would quietly out-rank a deliberate choice. Comments and blank lines do
    not."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lstrip("!") in _GITIGNORE_COVERS_VSCODE_SETTINGS:
            return True
    return False


def _ensure_vscode_settings_gitignored(target_dir: str) -> None:
    """Make sure the project's `.gitignore` ignores `.vscode/settings.json`,
    creating `.gitignore` when the project has none.

    Append-only and idempotent: `.gitignore` is hand-authored and hand-commented
    like refdes-project.yaml, so nothing outside the appended block moves, and
    when some existing pattern already covers the file nothing is written at
    all. Appended block takes the file's own line ending (textio's
    `append_ending` rule), so a CRLF gitignore does not grow an LF island.
    """
    path = os.path.join(target_dir, ".gitignore")
    if not os.path.isfile(path):
        textio.write_text(path, _VSCODE_GITIGNORE_BLOCK)
        return
    existing = textio.read_text(path)
    if _gitignore_addresses_vscode_settings(existing):
        return
    ending = textio.append_ending(existing)
    gap = ending if existing.strip() else ""
    block = _VSCODE_GITIGNORE_BLOCK.replace("\n", ending)
    textio.write_text(path, existing + gap + block)


def _write_vscode_settings(target_dir: str) -> bool:
    """Write `.vscode/settings.json`, unless one is already there -- a file the
    author wrote is not `init`'s to overwrite, and merging into one is not
    safe either: `.vscode/settings.json` is JSONC (VS Code accepts comments,
    and comments in a real settings file are the norm, this repo's own among
    them), so `json.loads` cannot read the common case.

    Returns True when this call wrote the file -- which is exactly when the
    machine-specific absolute path inside it is `init`'s responsibility, and
    so the only case that gets the `.gitignore` entry. A settings file that
    was already there may already be tracked, where a gitignore line would do
    nothing but promise.
    """
    settings_path = os.path.join(target_dir, ".vscode", "settings.json")
    if os.path.isfile(settings_path):
        return False
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    textio.write_text(settings_path, _vscode_settings_text(target_dir))
    return True


def vscode_settings_exists(target_dir: str) -> bool:
    """True when `refdes init` will find an existing `.vscode/settings.json`
    and leave it alone. The caller has to ask BEFORE init runs: afterwards the
    file is present either way, and nothing on disk distinguishes the file
    init wrote from the one it skipped."""
    return os.path.isfile(os.path.join(target_dir, ".vscode", "settings.json"))


def vscode_settings_note(target_dir: str) -> str:
    """The one-line note `refdes init` prints when it left an existing
    `.vscode/settings.json` alone. Without it the command exits 0 having
    silently not wired up schema completion, which is the state a newcomer
    with a workspace settings file already in place lands in (user-sim run 2,
    BUG 3). The absolute path is spelled out rather than left a `<path>`
    placeholder so the line is paste-ready into the file it names. Printed by
    the CLI -- this module does not print.
    """
    return (
        "note: .vscode/settings.json already exists; left it alone. Add "
        f'"yaml.schemas": {{"{_vscode_schema_path(target_dir)}": '
        '["items/**/*.yaml"]} yourself for schema completion.'
    )


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
    """Write a minimal `refdes-project.yaml` that points at the standard rather than
    copying it (docs/design/standard-library.md §3) -- no `types:`,
    `link_types:`, or `sets:` key anywhere in the file; that absence
    is the point. `standard=None` writes `standard: none`, the explicit
    escape hatch. `<version>` is never written as the literal string
    "latest": resolved here, once, to the concrete integer the installed
    tool currently ships as newest.

    Also writes `.vscode/settings.json` for schema completion, and -- because
    the schema path in it is absolute and machine-specific -- makes sure the
    project's `.gitignore` covers that file. An existing `.vscode/settings.json`
    is left exactly as it is and no gitignore entry is added for it; the CLI
    prints `vscode_settings_note` in that case, so the skip is never silent.

    Returns the path written. Raises SchemaError if refdes-project.yaml already
    exists at the target, or if `presets` is given with `standard=None`
    (every preset's types target base types, so presets require a base).
    """
    presets = presets or []
    if standard is None and presets:
        raise SchemaError(
            "presets require a base standard; set standard.base or drop presets:"
        )

    config_path = os.path.join(target_dir, "refdes-project.yaml")
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

    if write_vscode_settings and _write_vscode_settings(target_dir):
        _ensure_vscode_settings_gitignored(target_dir)

    return config_path


# --------------------------------------------------------------- refdes new


def _field_hint(fname: str, fspec) -> str:
    if fspec.type == "enum":
        return "choices: " + ", ".join(fspec.choices or [])
    return fspec.type


def _item_field_line(fname: str, fspec) -> str:
    """One field's line in a `refdes new` skeleton (shared by the single-item
    and --list forms): a required field with a declared `default:` is written
    with that default, a required field with none gets an empty placeholder,
    an optional field is written commented-out, with the same choices:/type
    hint the schema's own `description` carries."""
    hint = _field_hint(fname, fspec)
    if fspec.default is not None:
        return f"{fname}: {fspec.default}  # {hint}"
    if fspec.required:
        return f"{fname}:  # required -- {hint}"
    cond = ""
    if fspec.required_when:
        cond = f"; required when {_format_required_when(fspec.required_when)}"
    return f"# {fname}:  # {hint}{cond}"


def _item_link_line(lname: str, targets) -> str:
    """One link's commented-out line in a `new` skeleton, naming its allowed
    target types the same way the schema's description does."""
    target_desc = ", ".join(targets) if targets else "any"
    return f"# {lname}: []  # target: {target_desc}"


def new_item_text(type_name: str, spec: ItemType) -> str:
    """Scaffold one item's front matter for `type_name`, generated from the
    identical resolved `ItemType` the JSON Schema (schema_json.py) and
    `items.json` (render.py) both read -- not a second, hand-maintained
    template per type that could drift from either (docs/design/
    standard-library.md §12's closing section).
    """
    lines = ["---", "id:", f"type: {type_name}"]
    for fname, fspec in spec.fields.items():
        lines.append(_item_field_line(fname, fspec))
    for lname, targets in spec.links.items():
        lines.append(_item_link_line(lname, targets))
    lines.append("---")
    lines.append("")
    # body: is reserved, not a field, so it never shows up in the loop above
    # -- without this, a type whose entire content lives there (hardware@3's
    # requirement/bound) scaffolds with no hint that anything more is needed.
    if spec.body_required:
        lines.append("<!-- required: the content itself goes here. -->")
    else:
        lines.append("<!-- optional body. -->")
    lines.append("")
    return "\n".join(lines)


def initial_field_values(spec: ItemType, values: dict) -> dict:
    """The field set a created item starts with -- the identical set
    `new_item_text` scaffolds, resolved to values: an author-supplied value
    wins, a field with a declared `default:` falls back to that default (the
    same rule `_item_field_line` writes the default into a skeleton), and
    anything else is left out for the schema's own required/optional checks
    to judge. Shared so the editor's create path and `refdes new` can never
    disagree about which fields an item of this type starts with."""
    out: dict = {}
    for fname, fspec in spec.fields.items():
        if fname in values:
            out[fname] = values[fname]
        elif fspec.default is not None:
            out[fname] = fspec.default
    return out


def new_list_text(type_name: str, spec: ItemType) -> str:
    """Scaffold a list file for `type_name` for `refdes new <type> --list`:
    a `defaults:` block carrying the items' shared type and the status
    field's declared default (omitted entirely when the type declares no
    status field), then one empty entry.

    The file takes the mapping form a list file must have (`defaults:` plus
    an `items:` key) rather than the bare top-level list in the design's
    sketch, so redirecting the output straight into place can't produce a
    file `parse_list_file` rejects. The per-entry fields are exactly what
    `new_item_text` scaffolds for the same type; `type:` and a defaulted
    `status:` live in `defaults:` instead of every entry, and an entry's own
    value wins (the layout's "one status edit" property -- candidate parts
    §6.1/§6.4).
    """
    lines = ["---", "defaults:", f"  type: {type_name}"]
    status = spec.fields.get("status")
    if status is not None and status.default is not None:
        lines.append(f"  status: {status.default}")
    lines.append("")
    lines.append("items:")
    lines.append("  - id:")
    for fname, fspec in spec.fields.items():
        if fname == "status" and status is not None and status.default is not None:
            continue  # already in the defaults: block above
        lines.append(f"    {_item_field_line(fname, fspec)}")
    for lname, targets in spec.links.items():
        lines.append(f"    {_item_link_line(lname, targets)}")
    if spec.body_required:
        lines.append("    # body:  # required: the content itself goes here.")
    else:
        lines.append("    # body:  # optional body.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------- standard.presets


_PRESETS_RE = re.compile(r"(presets:\s*)\[([^\]]*)\]")


def _edit_presets_list(raw_text: str, mutate) -> str:
    """A minimal, comment-preserving text edit of `standard.presets: [...]`
    -- refdes-project.yaml is hand-authored and hand-commented, unlike the tool's
    own machine-owned lockfiles, so this never re-serializes the whole file
    (which would silently drop every comment). Only supports the flow-style
    list `refdes init` itself always writes; a block-style list is left for
    the author to edit by hand."""
    match = _PRESETS_RE.search(raw_text)
    if match is None:
        raise SchemaError(
            "could not find a 'presets: [...]' list to edit in refdes-project.yaml -- "
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
    and sets simply join the merged schema -- no migration step, no
    re-running init (docs/design/standard-library.md §8)."""
    config_path = os.path.join(project_root, "refdes-project.yaml")
    # textio both ways. The read was text mode, so a CRLF config arrived here
    # already folded to LF, and the write was text mode, so the platform
    # translated it again -- adding one preset to an LF config rewrote the
    # whole file to CRLF on Windows, and adding one to a CRLF config rewrote it
    # to LF on Linux. `_edit_presets_list` is a comment-preserving span edit on
    # the raw text precisely so nothing outside `presets: [...]` moves.
    raw_text = textio.read_text(config_path)
    raw = yaml_safe_load(raw_text) or {}
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
    textio.write_text(config_path, new_text)


def remove_preset(project_root: str, preset_name: str) -> list:
    """Remove `preset_name` from `standard.presets:`, reporting what that
    breaks BEFORE writing the change: every type, link, and set the
    preset provided disappears from the merged schema on the next load, so
    an item still using one of them needs to be seen now, not discovered on
    the next unrelated build (docs/design/standard-library.md §8).

    Returns the diagnostics a build against the post-removal config would
    produce. The config is still edited even if that list is non-empty --
    this command's whole job is to surface the consequence, not to block an
    author who has already decided to accept it.
    """
    config_path = os.path.join(project_root, "refdes-project.yaml")
    raw_text = textio.read_text(config_path)
    raw = yaml_safe_load(raw_text) or {}
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
    textio.write_text(scratch_path, new_text)
    try:
        project = load_project(config_path=scratch_path)
        parse_mod.load_items(project, require_ids=False)
        build_mod.build(project, seal_write=False, reseal=False)
        diagnostics = list(project.diagnostics)
    finally:
        os.remove(scratch_path)

    textio.write_text(config_path, new_text)

    return diagnostics
