"""Every .yaml/.md under items/, docs-site/, standards/, fixtures parses identically with both loaders."""

from __future__ import annotations

import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from refdes.parse import FRONTMATTER_RE, _LineLoader


class _PurePythonLineLoader(yaml.SafeLoader):
    pass


def _pure_construct_mapping(loader, node):
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_PurePythonLineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _pure_construct_mapping
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


def test_parse_equivalence_with_both_loaders():
    for rel_path in _find_yaml_sources():
        full_path = _repo_path(rel_path)
        with open(full_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if rel_path.endswith(".md"):
            # For .md files, compare each front-matter block independently.
            match = FRONTMATTER_RE.match(text)
            if not match:
                # No front matter; skip parse comparison (not a YAML parse target).
                continue
            blocks = [match.group(1)]  # First front matter only (rest handled by parse_markdown_file)
        else:
            blocks = [text]
        for block_text in blocks:
            pure_result = None
            proj_result = None
            pure_raised = False
            proj_raised = False
            try:
                pure_result = yaml.load(block_text, Loader=_PurePythonLineLoader)
            except yaml.YAMLError:
                pure_raised = True
            try:
                proj_result = yaml.load(block_text, Loader=_LineLoader)
            except yaml.YAMLError:
                proj_raised = True
            # If exactly one loader raises, that is a semantic difference: FAIL.
            if pure_raised != proj_raised:
                assert False, (
                    f"One-sided failure for {rel_path}: "
                    f"pure_raised={pure_raised}, proj_raised={proj_raised}"
                )
            if not pure_raised and not proj_raised:
                assert pure_result == proj_result, (
                    f"Parse mismatch for {rel_path}: {pure_result!r} vs {proj_result!r}"
                )
                def check(obj, label, file_ref=rel_path):
                    if isinstance(obj, dict):
                        assert "__line__" in obj, f"Missing __line__ in {label} of {file_ref}"
                        for k, v in obj.items():
                            if k != "__line__":
                                check(v, f"{label}.{k}", file_ref=file_ref)
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            check(item, f"{label}[{i}]", file_ref=file_ref)
                check(pure_result, "root")
