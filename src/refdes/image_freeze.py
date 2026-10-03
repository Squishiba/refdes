"""Pin searched Markdown images to project-root-relative source paths."""

from __future__ import annotations

import os
import re

import yaml

from . import build, textio
from .model import Project

# Markdown-it supplies the authority on which source lines contain real images.
# This pattern only locates the spelling to change on those lines; it does not
# turn images in code fences or escaped literal markup into references.
_IMAGE = re.compile(
    r'(?<!\\)!\[[^]]*\]\(\s*(?P<src><[^>\n]+>|[^\s()]+)(?:\s+[^)]*)?\)',
    re.DOTALL,
)
_CODE_SPAN = re.compile(r"(?P<ticks>`+).*?(?P=ticks)", re.DOTALL)


def _image_count(markdown: str) -> int:
    return sum(
        child.type == "image"
        for token in build._markdown_parser().parse(markdown)
        for child in token.children or ()
    )


def _freeze_span(project: Project, source: str, rel: str) -> tuple[str, int]:
    replacements: list[tuple[int, int, str]] = []
    prior_count = 0
    code_spans = [(match.start(), match.end()) for match in _CODE_SPAN.finditer(source)]
    for match in _IMAGE.finditer(source):
        if any(start <= match.start() < end for start, end in code_spans):
            continue
        count = _image_count(source[:match.end()])
        if count <= prior_count:
            continue
        prior_count = count
        spelling = match.group("src")
        angled = spelling.startswith("<") and spelling.endswith(">")
        src = spelling[1:-1] if angled else spelling
        if build._URL_SCHEME_RE.match(src) or "/" in src or "\\" in src:
            continue
        beside = os.path.join(project.root, os.path.dirname(rel), src)
        if os.path.isfile(beside):
            continue
        matches = build._search_image_matches(project, src)
        if len(matches) == 1:
            # A leading slash is the explicit project-root anchor. It avoids
            # re-resolving against the document's directory after a move.
            replacement = "/" + matches[0]
            if angled:
                replacement = f"<{replacement}>"
            replacements.append((match.start("src"), match.end("src"), replacement))
    for start, end, replacement in reversed(replacements):
        source = source[:start] + replacement + source[end:]
    return source, len(replacements)


def _yaml_body_nodes(source: str) -> list[yaml.ScalarNode]:
    """Only the Markdown-bearing `body:` scalars in a list source file."""
    try:
        root = yaml.compose(source)
    except yaml.YAMLError:
        return []
    if not isinstance(root, yaml.MappingNode):
        return []
    nodes: list[yaml.ScalarNode] = []
    for key, value in root.value:
        if key.value == "defaults" and isinstance(value, yaml.MappingNode):
            entries = [value]
        elif key.value == "items" and isinstance(value, yaml.SequenceNode):
            entries = [entry for entry in value.value if isinstance(entry, yaml.MappingNode)]
        else:
            continue
        for entry in entries:
            nodes.extend(
                field_value
                for field_key, field_value in entry.value
                if field_key.value == "body" and isinstance(field_value, yaml.ScalarNode)
            )
    return nodes


def _freeze_yaml_bodies(project: Project, lines: list[str], source: str, rel: str) -> int:
    changed = 0
    for node in _yaml_body_nodes(source):
        start = node.start_mark.line
        if node.style in ("|", ">"):
            first, last = start + 1, node.end_mark.line
            if last > len(lines):
                last = len(lines)
            raw = lines[first:last]
            nonempty = [line for line in raw if line.strip()]
            if not nonempty:
                continue
            indent = min(len(line) - len(line.lstrip(" ")) for line in nonempty)
            body_lines = [line[indent:] if line.strip() else "" for line in raw]
            body = "\n".join(body_lines)
            after, count = _freeze_span(project, body, rel)
            if count:
                lines[first:last] = [
                    (" " * indent + line) if line else raw[index]
                    for index, line in enumerate(after.split("\n"))
                ]
                changed += count
        elif node.end_mark.line == start:
            first, last = node.start_mark.column, node.end_mark.column
            raw = lines[start][first:last]
            after, count = _freeze_span(project, raw, rel)
            if count:
                lines[start] = lines[start][:first] + after + lines[start][last:]
                changed += count
    return changed


def freeze_images(project: Project) -> int:
    """Write unique searched image locations on a writable project load.

    Only parsed Markdown body lines are edited. Missing and ambiguous images
    remain unchanged so the existing render diagnostics report them at the
    reference site. Every rewrite preserves source line endings.
    """
    from . import pages
    from .revise import FileRewrite, write_rewrites_verified

    pages.load_pages(project)
    bodies: dict[str, list[tuple[int, str]]] = {}
    for item in project.local_items:
        if item.source_file.endswith(".md") and item.body and item.body_line is not None:
            bodies.setdefault(item.source_file, []).append((item.body_line - 1, item.body))
    for page in project.pages:
        if page.body:
            path = os.path.join(project.root, page.source_file)
            source = textio.SourceText.of(path).text
            offset = source.find(page.body)
            if offset >= 0:
                bodies.setdefault(page.source_file, []).append(
                    (source[:offset].count("\n"), page.body)
                )
    for item in project.local_items:
        if item.source_file.endswith((".yaml", ".yml")):
            bodies.setdefault(item.source_file, [])

    rewrites = []
    counts: dict[str, int] = {}
    for rel, entries in bodies.items():
        path = os.path.join(project.root, rel)
        source = textio.SourceText.of(path)
        lines = source.lines
        changed = 0
        for offset, body in entries:
            # Block tokens locate actual inline Markdown. A code fence never
            # contributes an inline token, even if its text looks like an image.
            spans = [
                token.map
                for token in build._markdown_parser().parse(body)
                if token.type == "inline" and token.map
            ]
            for start, end in spans:
                first, last = offset + start, offset + end
                if first >= len(lines) or last > len(lines):
                    continue
                span = "\n".join(lines[first:last])
                after, count = _freeze_span(project, span, rel)
                lines[first:last] = after.split("\n")
                changed += count
        if rel.endswith((".yaml", ".yml")):
            changed += _freeze_yaml_bodies(project, lines, source.text, rel)
        after = source.render(lines)
        if after != source.text:
            rewrites.append(FileRewrite(path=path, rel=rel, before=source.text, after=after))
            counts[rel] = changed
    refused = write_rewrites_verified(project, rewrites)
    project.pages.clear()  # build() loads the current page text in its normal phase
    return sum(count for rel, count in counts.items() if rel not in refused)
