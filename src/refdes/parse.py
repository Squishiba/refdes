"""Read source files into Items.

Two serializations, one object model:

  items/**/*.md    one or more items, each YAML front-matter + markdown body
                   (decisions, anything with a body, calcs, or options) --
                   see parse_markdown_file for the several-items-in-one-file rules
  items/**/*.yaml  a list of items sharing `defaults:` (bulk requirements)
"""

from __future__ import annotations

import difflib
import os
import re
from typing import Any

import yaml

from .model import ON_CHANGE_MODES, Item, Project

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# A candidate fence line: `---` alone on its line.
FENCE_RE = re.compile(r"^---[ \t]*$")
# A YAML mapping key opening a line at column 0 -- what has to follow a `---` for it
# to be read as a new item's front-matter rather than a literal horizontal rule.
KEY_LINE_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*:(\s|$)")
# `body` is the markdown body, not a field. In a .md file it is the text after the
# front-matter; in a list file it is a `body:` key, so a running log can be written
# as a list without one file per daily entry.
RESERVED = {"id", "type", "history", "body", "former_ids"}
# Reserved, but only when the item's own type does not already declare a field of
# the same name -- so a schema that predates one of these keys keeps working
# unchanged instead of having the field silently shadowed.
OVERRIDABLE = {"prefix", "board", "workspace"}

# Fields renamed by a standard-library version bump, keyed by (type name, old
# key) -> new key. A plain rename would otherwise surface as an unknown-field
# warning on the old key plus a missing-required error on the new one --
# accurate, but a miserable way to discover that the fix is "rename this key"
# (finding 4: hardware v1's constraint.title -> v2's constraint.text). Scoped
# to the type name alone, so it also flags a hand-rolled schema that happens
# to name a type `constraint` and drop `title` for unrelated reasons -- an
# acceptable false positive given how narrowly this table is meant to stay.
_RENAMED_FIELDS: dict[tuple[str, str], str] = {
    ("constraint", "title"): "text",
}


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that tags each mapping with the source line of its first key."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _strip_lines(obj: Any) -> Any:
    """Remove the __line__ bookkeeping key from nested structures."""
    if isinstance(obj, dict):
        return {k: _strip_lines(v) for k, v in obj.items() if k != "__line__"}
    if isinstance(obj, list):
        return [_strip_lines(v) for v in obj]
    return obj


def _relpath(project: Project, path: str) -> str:
    try:
        return os.path.relpath(path, project.root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


# Substrings PyYAML's own exception carries when a bare '>'/'>=' is misread as
# a folded-block-scalar indicator rather than a comparison -- checked with
# `or` (either is sufficient) because the exact wording of `.problem` differs
# by what immediately follows the '>' (see finding 13's own repro: '>= ' fails
# with "chomping or indentation indicators", a bare '> 9' fails with "expected
# a comment or a line break" instead), while `.context` stays this one string
# either way.
_CHOMPING_PROBLEM = "chomping or indentation indicators"
_BLOCK_SCALAR_CONTEXT = "while scanning a block scalar"


def _yaml_error_report(exc: yaml.YAMLError, lines: list[str], offset: int) -> tuple[str, int]:
    """(message, line) for a YAMLError raised while parsing part of a file.

    `line` is the real, 1-indexed source line the exception's own mark names,
    falling back to 1 only when no mark is set at all -- not a blanket
    default, which was the actual bug (finding 13's real point: this was
    wrong for every malformed YAML file, not just the '>' gotcha). `lines` is
    the *whole file's* lines (0-indexed); `offset` is how many of them
    precede the text actually handed to the YAML parser (0 for a full-file
    parse; the first content line's index for a slice, e.g. front matter),
    since a mark's own `.line` is relative to whatever text was parsed, not
    the file it came from.

    `message` adds a targeted hint for the single most common way this fails:
    a bare '>' or '>=' value, which YAML reads as a folded-block-scalar
    indicator rather than a comparison. Detection is scoped to the source
    line's actual content at the failure point, not to any particular field
    name -- the same gotcha hits any field, not just `limit:`.
    """
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return str(exc), 1

    line = offset + mark.line + 1
    message = str(exc)

    is_block_scalar_failure = _CHOMPING_PROBLEM in (
        getattr(exc, "problem", None) or ""
    ) or _BLOCK_SCALAR_CONTEXT in (getattr(exc, "context", None) or "")
    if is_block_scalar_failure:
        # context_mark, when present, points at the '>' itself; problem_mark
        # points at whatever character broke the scan just after it (the '='
        # in '>=', for instance) -- prefer the more precise one.
        pointer = getattr(exc, "context_mark", None) or mark
        real_idx = offset + pointer.line
        source_line = lines[real_idx] if 0 <= real_idx < len(lines) else ""
        value = source_line[pointer.column :]
        if value.startswith(">"):
            operator = ">=" if value.startswith(">=") else ">"
            message += (
                f" -- a value starting with {operator!r} needs quotes here: YAML "
                f"reads a bare '>' as the start of a block scalar, not a "
                f'comparison. Try "{value.strip()}".'
            )

    return message, line


def _suggest(name: str, known: list[str]) -> str:
    close = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
    return f" Did you mean {close[0]!r}?" if close else ""


def _build_item(
    project: Project,
    raw: dict[str, Any],
    rel: str,
    line: int,
    body: str = "",
) -> Item | None:
    type_name = raw.get("type")
    if not type_name:
        project.error("item has no 'type'", file=rel, line=line)
        return None
    spec = project.types.get(str(type_name))
    if spec is None:
        preset_name = project.preset_provided_types.get(str(type_name))
        if preset_name:
            project.error(
                f"unknown type {type_name!r} -- it was provided by the "
                f"{preset_name!r} preset, which is not listed under "
                f"standard.presets:. Add it back, or migrate this item to a "
                f"declared type.",
                file=rel, line=line,
            )
        else:
            project.error(
                f"unknown type {type_name!r}.{_suggest(str(type_name), list(project.types))}",
                file=rel,
                line=line,
            )
        return None

    item = Item(
        id=str(raw["id"]) if raw.get("id") else "",
        type=spec.name,
        source_file=rel,
        source_line=line,
        body=body,
    )

    if not item.body and raw.get("body"):
        item.body = str(raw["body"])

    former_ids = raw.get("former_ids")
    if former_ids:
        item.former_ids = [str(v) for v in (former_ids if isinstance(former_ids, list) else [former_ids]) if v]

    history = raw.get("history")
    if isinstance(history, str):
        if history not in ON_CHANGE_MODES:
            project.error(
                f"history: {history!r} must be one of {list(ON_CHANGE_MODES)}",
                file=rel, line=line, item_id=item.id,
            )
        else:
            item.history = {"mode": history}
    elif isinstance(history, dict):
        item.history = _strip_lines(history)
        if item.history.get("fields") and not item.history.get("reason"):
            project.warn(
                "item-level history override has no 'reason'; suppression should be "
                "self-documenting",
                file=rel, line=line, item_id=item.id,
            )

    known_keys = set(spec.fields) | set(spec.links) | RESERVED | OVERRIDABLE
    for key, value in raw.items():
        if key == "__line__" or key in RESERVED:
            continue
        if key in OVERRIDABLE and key not in spec.fields:
            if key == "prefix" and value:
                item.prefix_hint = str(value)
            elif key == "board" and value:
                item.board_hint = str(value)
            elif key == "workspace" and value:
                item.workspace_hint = str(value)
            continue
        if key in spec.links:
            targets = value if isinstance(value, list) else [value]
            item.links[key] = [str(t) for t in targets if t]
        elif key in spec.fields:
            item.fields[key] = _strip_lines(value)
        elif (spec.name, key) in _RENAMED_FIELDS:
            new_key = _RENAMED_FIELDS[(spec.name, key)]
            project.error(
                f"'{spec.name}.{key}' is now '{spec.name}.{new_key}' -- rename this "
                f"key in the source file. Its value is used for {new_key!r} in this "
                f"build so the rest of it doesn't also report a missing required "
                f"field.",
                file=rel, line=line, item_id=item.id or "?",
            )
            item.fields[new_key] = _strip_lines(value)
        else:
            # A typo'd link name (`sattisfies:` for `satisfies:`) doesn't just lose a
            # field -- it drops a traceability edge, so it must fail the build rather
            # than pass with a warning that's easy to miss.
            link_match = difflib.get_close_matches(key, sorted(spec.links), n=1, cutoff=0.6)
            preset_name = project.preset_provided_links.get(key)
            if preset_name and key not in project.link_types:
                project.error(
                    f"unknown field {key!r} on {spec.label.lower()} -- it was "
                    f"provided by the {preset_name!r} preset, which is not listed "
                    f"under standard.presets:. Add it back, or remove this link.",
                    file=rel, line=line, item_id=item.id or "?",
                )
            elif link_match:
                project.error(
                    f"unknown field {key!r} on {spec.label.lower()} -- did you mean "
                    f"the link {link_match[0]!r}? A misspelled link name silently "
                    f"drops the edge instead of erroring.",
                    file=rel, line=line, item_id=item.id or "?",
                )
            else:
                project.warn(
                    f"unknown field {key!r} on {spec.label.lower()}."
                    f"{_suggest(key, sorted(known_keys))}",
                    file=rel, line=line, item_id=item.id or "?",
                )
            item.fields[key] = _strip_lines(value)

    for fname, fspec in spec.fields.items():
        if fname not in item.fields:
            if fspec.default is not None:
                item.fields[fname] = fspec.default
        elif item.fields[fname] is None and fspec.default is not None:
            # A bare `key:` with nothing after the colon is YAML null, not absence --
            # left alone, it would look "already resolved" to validate_items() and skip
            # both the default and the enum/limit/etc. check right below it, silently
            # dropping whatever the author meant to write. Coalesce it into absent so
            # it gets the same default an omitted key would, and say so: unlike an
            # omitted key, an explicit null was something the author typed, so it's
            # worth a warning rather than a silent correction.
            item.fields[fname] = fspec.default
            project.warn(
                f"{fname!r} was written as an explicit null (a bare {fname}: with no "
                f"value) -- treating it as absent and using the default {fspec.default!r} "
                f"instead of leaving it unset and unvalidated.",
                file=rel, line=line, item_id=item.id or "?",
            )

    return item


def _yaml_mapping(text: str) -> dict | None:
    """Parse `text` as YAML, returning it only if it is a mapping (empty -> {})."""
    parsed = yaml.load(text, Loader=_LineLoader)
    if parsed is None:
        return {}
    return parsed if isinstance(parsed, dict) else None


def parse_markdown_file(project: Project, path: str) -> list[Item]:
    """Read one or more `---`-fenced item documents from a single .md file.

    A file must open with `---`, YAML, `---` -- exactly today's single-item form,
    matched the same way so a plain file is unaffected byte-for-byte. After that,
    a further `---` only starts a new item if the line right after it looks like a
    YAML key, a closing `---` exists later, and the text between actually parses as
    a YAML mapping. Failing any of those, it is left alone as a literal horizontal
    rule inside the previous item's body -- which is what makes a today-style file
    with a `---` in its prose keep working unmigrated.

    If the first block's only key is `defaults:`, it is not an item -- its mapping
    is merged under every item that follows, the same way `defaults:` works in a
    list file.
    """
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")

    fence_idx = [i for i, l in enumerate(lines) if FENCE_RE.match(l)]
    if len(fence_idx) < 2 or fence_idx[0] != 0:
        project.error("no YAML front-matter (file must start with '---')", file=rel, line=1)
        return []

    close0 = fence_idx[1]
    head_text = "\n".join(lines[1:close0])
    try:
        parsed0 = _yaml_mapping(head_text)
    except yaml.YAMLError as exc:
        message, err_line = _yaml_error_report(exc, lines, offset=1)
        project.error(f"invalid YAML front-matter: {message}", file=rel, line=err_line)
        return []
    if parsed0 is None:
        project.error("front-matter must be a mapping", file=rel, line=1)
        return []

    blocks: list[tuple[int, int, dict]] = [(0, close0, parsed0)]

    # Every remaining fence is independently a candidate to open the next item,
    # paired with whichever fence comes right after it -- including a fence that is
    # already serving as the previous item's close, which is what lets one `---`
    # between two back-to-back items do double duty as both. A fence with nothing
    # later to close it (the last one in the file) is never reachable as an opener
    # here, which is exactly "a closing fence exists later".
    for k in range(1, len(fence_idx) - 1):
        open_i = fence_idx[k]
        close_i = fence_idx[k + 1]
        next_line = lines[open_i + 1] if open_i + 1 < len(lines) else ""
        if not KEY_LINE_RE.match(next_line):
            continue
        try:
            parsed = _yaml_mapping("\n".join(lines[open_i + 1 : close_i]))
        except yaml.YAMLError:
            parsed = None
        if parsed is None:
            continue
        blocks.append((open_i, close_i, parsed))

    defaults: dict[str, Any] = {}
    start = 0
    first_keys = {k for k in blocks[0][2] if k != "__line__"}
    if first_keys == {"defaults"} and isinstance(blocks[0][2].get("defaults"), dict):
        defaults = _strip_lines(blocks[0][2]["defaults"])
        start = 1

    item_blocks = blocks[start:]
    if not item_blocks:
        project.error("file has no items after 'defaults:'", file=rel, line=1)
        return []

    out: list[Item] = []
    for index, (open_i, close_i, parsed) in enumerate(item_blocks):
        body_end = item_blocks[index + 1][0] if index + 1 < len(item_blocks) else len(lines)
        body = "\n".join(lines[close_i + 1 : body_end])
        merged: dict[str, Any] = dict(defaults)
        merged.update({k: v for k, v in parsed.items() if k != "__line__"})
        item = _build_item(project, merged, rel, line=open_i + 2, body=body)
        if item:
            out.append(item)
    return out


def parse_list_file(project: Project, path: str) -> list[Item]:
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        raw = yaml.load(text, Loader=_LineLoader) or {}
    except yaml.YAMLError as exc:
        message, err_line = _yaml_error_report(exc, text.split("\n"), offset=0)
        project.error(f"invalid YAML: {message}", file=rel, line=err_line)
        return []

    if not isinstance(raw, dict) or "items" not in raw:
        project.error("list file must be a mapping with an 'items:' key", file=rel, line=1)
        return []

    defaults = _strip_lines(raw.get("defaults") or {})

    out: list[Item] = []
    entries = raw.get("items") or []
    if not isinstance(entries, list):
        project.error("'items:' must be a list", file=rel, line=1)
        return []

    for entry in entries:
        if not isinstance(entry, dict):
            project.error(f"list entry must be a mapping, got {type(entry).__name__}",
                          file=rel, line=1)
            continue
        line = entry.get("__line__", 1)
        merged: dict[str, Any] = dict(defaults)
        merged.update({k: v for k, v in entry.items() if k != "__line__"})
        item = _build_item(project, merged, rel, line=line)
        if item:
            out.append(item)
    return out


def source_files(project: Project) -> list[str]:
    items_dir = os.path.join(project.root, "items")
    found: list[str] = []
    if not os.path.isdir(items_dir):
        return found
    for dirpath, dirnames, filenames in os.walk(items_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if name.endswith((".md", ".yaml", ".yml")):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def load_items(project: Project, require_ids: bool = True) -> None:
    """Parse every source file into project.items, reporting duplicate IDs.

    Items with no id yet go to project.pending so `refdes id` can allocate one.
    """
    for path in source_files(project):
        if path.endswith(".md"):
            items = parse_markdown_file(project, path)
        else:
            items = parse_list_file(project, path)
        for item in items:
            if not item.id:
                project.pending.append(item)
                if require_ids:
                    project.error(
                        "item has no id — run 'refdes id' to allocate one",
                        file=item.source_file, line=item.source_line,
                    )
                continue
            existing = project.items.get(item.id)
            if existing:
                project.error(
                    f"duplicate id {item.id!r} (also defined at "
                    f"{existing.source_file}:{existing.source_line})",
                    file=item.source_file, line=item.source_line, item_id=item.id,
                )
                continue
            project.items[item.id] = item
