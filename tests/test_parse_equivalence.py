"""Every .yaml/.md under items/, docs-site/, standards/, fixtures parses identically with both loaders."""

from __future__ import annotations

import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from refdes.parse import (
    FENCE_RE,
    FRONTMATTER_RE,
    KEY_LINE_RE,
    _LineLoader,
    _PurePythonLineLoader,
)


def _repo_path(p):
    # Resolve relative to repo root (where this file lives: tests/)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, p)


def _find_yaml_sources():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = set()
    for root, dirs, files in os.walk(os.path.join(base, "items")):
        for f in files:
            if f.endswith((".yaml", ".md")):
                paths.add(os.path.join(root, f)[len(base) + 1:])
    for root, dirs, files in os.walk(os.path.join(base, "docs-site")):
        for f in files:
            if f.endswith((".yaml", ".md")):
                paths.add(os.path.join(root, f)[len(base) + 1:])
    for root, dirs, files in os.walk(os.path.join(base, "src", "refdes", "standards")):
        for f in files:
            if f.endswith(".yaml"):
                paths.add(os.path.join(root, f)[len(base) + 1:])
    for p in glob.glob(os.path.join(base, "tests/**/items/*.yaml"), recursive=True):
        paths.add(p[len(base) + 1:])
    for p in glob.glob(os.path.join(base, "tests/**/items/*.md"), recursive=True):
        paths.add(p[len(base) + 1:])
    return sorted(p for p in paths if os.path.exists(os.path.join(base, p)))


def _frontmatter_blocks(text):
    """Yield only the YAML blocks that parse_markdown_file can treat as items."""
    offset = 0
    for line in text.splitlines(keepends=True):
        if FENCE_RE.match(line.rstrip("\r\n")):
            candidate = text[offset:]
            match = FRONTMATTER_RE.match(candidate)
            first_content = candidate.splitlines()[1:2]
            if match and (
                offset == 0 or (first_content and KEY_LINE_RE.match(first_content[0]))
            ):
                yield match.group(1)
        offset += len(line)


def test_parse_equivalence_with_both_loaders():
    for rel_path in _find_yaml_sources():
        full_path = _repo_path(rel_path)
        with open(full_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        blocks = _frontmatter_blocks(text) if rel_path.endswith(".md") else [text]
        for block_text in blocks:
            pure_result = None
            project_result = None
            pure_raised = False
            project_raised = False
            try:
                pure_result = yaml.load(block_text, Loader=_PurePythonLineLoader)
            except yaml.YAMLError:
                pure_raised = True
            try:
                project_result = yaml.load(block_text, Loader=_LineLoader)
            except yaml.YAMLError:
                project_raised = True
            assert pure_raised == project_raised, (
                f"One-sided failure for {rel_path}: "
                f"pure_raised={pure_raised}, project_raised={project_raised}"
            )
            if not pure_raised:
                assert pure_result == project_result, (
                    f"Parse mismatch for {rel_path}: {pure_result!r} vs {project_result!r}"
                )

                def check(obj, label, file_ref=rel_path):
                    if isinstance(obj, dict):
                        assert "__line__" in obj, f"Missing __line__ in {label} of {file_ref}"
                        for key, value in obj.items():
                            if key != "__line__":
                                check(value, f"{label}.{key}", file_ref=file_ref)
                    elif isinstance(obj, list):
                        for index, item in enumerate(obj):
                            check(item, f"{label}[{index}]", file_ref=file_ref)

                check(pure_result, "root")
