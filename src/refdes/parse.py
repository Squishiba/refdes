"""Read source files into Items.

Two serializations, one object model:

  items/**/*.md    one item: YAML front-matter + markdown body (decisions, anything
                   with a body, calcs, or options)
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
# `body` is the markdown body, not a field. In a .md file it is the text after the
# front-matter; in a list file it is a `body:` key, so a running log can be written
# as a list without one file per daily entry.
RESERVED = {"id", "type", "history", "body"}


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

    known_keys = set(spec.fields) | set(spec.links) | RESERVED
    for key, value in raw.items():
        if key in RESERVED or key == "__line__":
            continue
        if key in spec.links:
            targets = value if isinstance(value, list) else [value]
            item.links[key] = [str(t) for t in targets if t]
        elif key in spec.fields:
            item.fields[key] = _strip_lines(value)
        else:
            # A typo'd link name (`sattisfies:` for `satisfies:`) doesn't just lose a
            # field -- it drops a traceability edge, so it must fail the build rather
            # than pass with a warning that's easy to miss.
            link_match = difflib.get_close_matches(key, sorted(spec.links), n=1, cutoff=0.6)
            if link_match:
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
        if fname not in item.fields and fspec.default is not None:
            item.fields[fname] = fspec.default

    return item


def parse_markdown_file(project: Project, path: str) -> list[Item]:
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    match = FRONTMATTER_RE.match(text)
    if not match:
        project.error("no YAML front-matter (file must start with '---')", file=rel, line=1)
        return []

    try:
        raw = yaml.load(match.group(1), Loader=_LineLoader) or {}
    except yaml.YAMLError as exc:
        project.error(f"invalid YAML front-matter: {exc}", file=rel, line=1)
        return []
    if not isinstance(raw, dict):
        project.error("front-matter must be a mapping", file=rel, line=1)
        return []

    item = _build_item(project, raw, rel, line=2, body=match.group(2))
    return [item] if item else []


def parse_list_file(project: Project, path: str) -> list[Item]:
    rel = _relpath(project, path)
    with open(path, "r", encoding="utf-8") as fh:
        try:
            raw = yaml.load(fh, Loader=_LineLoader) or {}
        except yaml.YAMLError as exc:
            project.error(f"invalid YAML: {exc}", file=rel, line=1)
            return []

    if not isinstance(raw, dict) or "items" not in raw:
        project.error("list file must be a mapping with an 'items:' key", file=rel, line=1)
        return []

    defaults = _strip_lines(raw.get("defaults") or {})
    defaults.pop("prefix", None)  # consumed by the ID allocator, not a field

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


def list_file_prefix(path: str) -> str | None:
    """Read defaults.prefix from a list file without a full parse."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return None
    if isinstance(raw, dict):
        defaults = raw.get("defaults") or {}
        if isinstance(defaults, dict):
            prefix = defaults.get("prefix")
            return str(prefix) if prefix else None
    return None


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
            prefix = None
        else:
            items = parse_list_file(project, path)
            prefix = list_file_prefix(path)
        for item in items:
            if prefix:
                item.prefix_hint = prefix
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
