"""`refdes init`, `refdes new <type>`, and `refdes standard add-preset` /
`remove-preset` -- project scaffolding and standard-library selection
(docs/design/standard-library.md §3, §6, §8, §12).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
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
    `_ensure_gitignore_entries`) and why an existing one is never silently
    skipped (see `vscode_settings_note`).
    """
    settings = {"yaml.schemas": {_vscode_schema_path(target_dir): ["items/**/*.yaml"]}}
    return json.dumps(settings, indent=2) + "\n"


# What `init` makes the project's .gitignore ignore: one entry per file it
# writes or leaves behind that must not be committed, each stated the way this
# repo's own .gitignore states its reasoning -- the path named, the reason in a
# comment above it, the surrounding directory left alone. `.vscode/` as a whole
# must NOT be ignored (a project's `tasks.json`/`extensions.json` are shareable
# -- this repo commits its own) and neither must `.refdes/`, which holds the
# project's own record: the ID ledger, the citation lockfile, seals and board
# manifests all belong in git. So the patterns name the one file or the one
# subdirectory.
#
# No leading slash on any pattern, deliberately. Every one of them contains a
# slash away from its end, so git reads it as relative to the directory holding
# the `.gitignore` (gitignore(5): "if there is a separator at the beginning or
# middle of the pattern, then the pattern is relative to the directory level of
# the particular .gitignore file itself"). That is what a `.gitignore` `init`
# writes at the project root needs whether the project IS the repository root
# or one subdirectory of a larger repository -- verified with `git
# check-ignore -v` in both layouts. A leading `/` would anchor it the same way
# but would also read as a claim about a repository root we may not be in.


@dataclass(frozen=True)
class _GitignoreEntry:
    """One ignore pattern `init` ensures, with the comment block above it and
    the patterns that already cover it."""

    pattern: str
    covers: frozenset[str]
    block: str


def _covers(pattern: str, *whole_dirs: str) -> frozenset[str]:
    """The patterns that already state a position on `pattern`, in all the
    forms git accepts for the same intent.

    `whole_dirs` are directories whose own ignore covers everything inside
    them, so a project that ignores `.refdes/` has already said its piece about
    a file in there.

    A small literal set on purpose rather than a walk of git's pattern
    language: `init` runs in directories that are not git repositories at all,
    so this cannot ask git what it thinks.
    """
    forms = {pattern, "/" + pattern, "**/" + pattern}
    for directory in whole_dirs:
        for spelling in (directory, directory + "/"):
            forms |= {spelling, "/" + spelling, "**/" + spelling}
    return frozenset(forms)


_VSCODE_SETTINGS_GITIGNORE = _GitignoreEntry(
    pattern=".vscode/settings.json",
    covers=_covers(".vscode/settings.json", ".vscode"),
    block=(
        "# Written by `refdes init`. The yaml.schemas path in this file is an\n"
        "# absolute path into one checkout, so a committed copy hands every other\n"
        "# clone a schema that resolves to nothing -- silently, in both tools.\n"
        "# Editor settings you mean to share belong in a file you write yourself.\n"
        ".vscode/settings.json\n"
    ),
)

_COPIES_GITIGNORE = _GitignoreEntry(
    pattern=".refdes/copies/",
    covers=_covers(".refdes/copies/", ".refdes"),
    block=(
        "# Written by `refdes init`. Kept local copies of datasheet bytes, one\n"
        "# per citation with `keep_copy: true`, and manufacturer datasheets are\n"
        "# generally copyrighted -- re-fetch them rather than commit them. The\n"
        "# rest of `.refdes/` is this project's own record (the ID ledger, the\n"
        "# citation lockfile, seals) and does belong in git, which is why this\n"
        "# names the one directory rather than `.refdes/` as a whole.\n"
        ".refdes/copies/\n"
    ),
)

_SCHEMA_JSON_GITIGNORE = _GitignoreEntry(
    pattern=".refdes/schema.json",
    covers=_covers(".refdes/schema.json", ".refdes"),
    block=(
        "# Written by `refdes init`. The merged JSON Schema is regenerated by\n"
        "# every command that loads the project, so a committed copy can only\n"
        "# ever disagree with the project config -- silently, in the editor.\n"
        ".refdes/schema.json\n"
    ),
)

# The two `.refdes/` entries do not depend on anything else `init` does: those
# files are written by `build`, `check`, `fetch` and friends whatever happened
# here, so their ignore is written on every init. The `.vscode` entry is only
# wanted when `init` actually wrote that file (see `_write_vscode_settings`).
_REFDES_GITIGNORE = (_COPIES_GITIGNORE, _SCHEMA_JSON_GITIGNORE)


def _gitignore_addresses(text: str, entry: _GitignoreEntry) -> bool:
    """Whether some pattern in `text` already states the project's position on
    `entry.pattern` -- an ignore pattern or an explicit `!` negation.

    A negation counts: whoever wrote `!` + that pattern means to track the file,
    and git takes the *last* matching pattern, so appending ours would quietly
    out-rank a deliberate choice. Comments and blank lines do not."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lstrip("!") in entry.covers:
            return True
    return False


def _gitignore_patterns(text: str) -> list[str]:
    """The ignore patterns (not comments) written in `text`, in order."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _ensure_gitignore_entries(target_dir: str, entries: list[_GitignoreEntry]) -> None:
    """Make sure the project's `.gitignore` ignores each entry's path,
    creating `.gitignore` when the project has none.

    Append-only and idempotent: `.gitignore` is hand-authored and hand-commented
    like refdes-project.yaml, so nothing outside the appended blocks moves, and
    when some existing pattern already covers a path nothing is written for that
    path at all. Each block takes the file's own line ending (textio's
    `append_ending` rule), so a CRLF gitignore does not grow an LF island.
    """
    path = os.path.join(target_dir, ".gitignore")
    if not os.path.isfile(path):
        textio.write_text(path, _joined_blocks(entries, textio.LF))
        return
    existing = textio.read_text(path)
    missing = [entry for entry in entries if not _gitignore_addresses(existing, entry)]
    if not missing:
        return
    ending = textio.append_ending(existing)
    gap = ending if existing.strip() else ""
    textio.write_text(path, existing + gap + _joined_blocks(missing, ending))


def _joined_blocks(entries: list[_GitignoreEntry], ending: str) -> str:
    """The comment blocks of `entries`, one blank line apart, on `ending`'s line
    endings."""
    parts = [entries[0].block.replace("\n", ending)]
    parts += [ending + entry.block.replace("\n", ending) for entry in entries[1:]]
    return "".join(parts)


def added_gitignore_patterns(before: str | None, after: str) -> list[str]:
    """Which ignore patterns a `.gitignore` write added, given its text before
    (`None` when there was no file) and after. Pure, so `cmd_init` can announce
    exactly what appeared without `init` having to report anything -- and an
    announcement that stays true when `init` appended nothing."""
    prior = set(_gitignore_patterns(before)) if before is not None else set()
    return [p for p in _gitignore_patterns(after) if p not in prior]


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
    nothing but promise. (The `.refdes/` entries are wanted either way -- see
    `_ensure_gitignore_entries` -- which is why this return value no longer
    decides whether `.gitignore` gets written at all.)
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

    Also writes `.vscode/settings.json` for schema completion, and makes sure
    the project's `.gitignore` covers the three files that must not be
    committed: `.vscode/settings.json` (the schema path in it is absolute and
    machine-specific), `.refdes/copies/` (kept datasheet bytes, generally
    copyrighted) and `.refdes/schema.json` (regenerated by every command that
    loads the project). The last two were a promise the docs made three times
    with nothing behind it -- `git add -A` in a fresh `init` project staged a
    6 MB datasheet and a 1696-line generated schema. An existing
    `.vscode/settings.json` is left exactly as it is and no gitignore entry is
    added for it.

    Both outcomes are announced by the caller, which is the only printer here:
    `cmd_init` asks `vscode_settings_exists` before calling this and prints
    `wrote .vscode/settings.json` when init wrote it and `vscode_settings_note`
    when it did not, so neither the write nor the skip is silent. The return
    value stays the config path alone -- this function reports nothing about
    the second file, and `cmd_init` diffs `.gitignore` itself for the third
    (`added_gitignore_patterns`).

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

    # The `.refdes/` entries always: those files are written by `build`,
    # `check`, `fetch` and the rest whatever happened with the editor files, so
    # a project that skipped schema completion is exactly the one still holding
    # a multi-megabyte datasheet copy. The `.vscode` entry only when we wrote
    # that file ourselves.
    wanted: list[_GitignoreEntry] = []
    if write_vscode_settings and _write_vscode_settings(target_dir):
        wanted.append(_VSCODE_SETTINGS_GITIGNORE)
    wanted += _REFDES_GITIGNORE
    _ensure_gitignore_entries(target_dir, wanted)

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
