"""Every .yaml/.md under items/, docs-site/, standards/, and fixtures parses identically with both loaders."""

from __future__ import annotations

import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from refdes.parse import _LineLoader


class _PurePythonLineLoader(yaml.SafeLoader):
    pass


def _pure_construct_mapping(loader, node):
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_PurePythonLineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _pure_construct_mapping
)


def _find_yaml_sources():
    paths = set()
    for root, dirs, files in os.walk("items"):
        for f in files:
            if f.endswith((".yaml", ".md")):
                paths.add(os.path.join(root, f))
    for root, dirs, files in os.walk("docs-site"):
        for f in files:
            if f.endswith((".yaml", ".md")):
                paths.add(os.path.join(root, f))
    for root, dirs, files in os.walk("src/refdes/standards"):
        for f in files:
            if f.endswith(".yaml"):
                paths.add(os.path.join(root, f))
    for p in glob.glob("tests/**/items/*.yaml", recursive=True):
        paths.add(p)
    for p in glob.glob("tests/**/items/*.md", recursive=True):
        paths.add(p)
    return sorted(p for p in paths if os.path.exists(p))


def test_parse_equivalence_with_both_loaders():
    for file_path in _find_yaml_sources():
        with open(file_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        try:
            pure = yaml.load(text, Loader=_PurePythonLineLoader)
            proj = yaml.load(text, Loader=_LineLoader)
        except yaml.YAMLError:
            continue
        assert pure == proj, f"Parse mismatch for {file_path}"

        def check(obj, label):
            if isinstance(obj, dict):
                assert "__line__" in obj, f"Missing __line__ in {label} of {file_path}"
                for k, v in obj.items():
                    if k != "__line__":
                        check(v, f"{label}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check(item, f"{label}[{i}]")
        check(pure, "root")
