"""Completeness lint for the bundled hardware@3 standard (finding 38, chunk 2).

Every type, field, link type and field-set entry the bundled standard declares
carries a `doc:` definition next to the declaration. This is the gate that
keeps the vocabulary dictionary from drifting back into silence: a new v3 term
without a definition fails here, in `pytest`, rather than shipping as a name
nobody can look up.

Scope is the bundled standard only. A project's own `refdes-schema.yaml`
overlay is never required to define its terms -- `doc:` stays optional there,
and nothing in this file reads a project's overlay.

Why the check reads the bundle two ways:
- the raw YAML files catch every declaration where it is written, including
  `sets:` entries, which the resolved schema pops after expanding
  `include:` into `fields:`;
- the resolved-schema pass catches anything a merge could introduce -- a field
  that reaches a type by `include:` without a definition, a preset layered on
  base -- which is exactly how an author's editor sees the vocabulary.
"""

from __future__ import annotations

import os
import tempfile

import yaml
from helpers import REPO

from refdes.schema import load_project

V3_DIR = os.path.join(REPO, "src", "refdes", "standards", "hardware", "v3")
PRESET_DIR = os.path.join(V3_DIR, "presets")


def _bundle_files() -> list[tuple[str, dict]]:
    """(name, parsed) for base.yaml and every v3 preset, read raw."""
    files = [("base.yaml", os.path.join(V3_DIR, "base.yaml"))]
    if os.path.isdir(PRESET_DIR):
        for name in sorted(os.listdir(PRESET_DIR)):
            if name.endswith(".yaml"):
                files.append((f"presets/{name}", os.path.join(PRESET_DIR, name)))
    out = []
    for label, path in files:
        with open(path, "r", encoding="utf-8") as fh:
            out.append((label, yaml.safe_load(fh) or {}))
    return out


def _missing_definitions(label: str, doc: dict) -> list[str]:
    """Every declaration path in one bundle file that has no non-empty `doc:`."""
    missing: list[str] = []

    def needs(path: str, block: dict) -> None:
        text = block.get("doc")
        if not isinstance(text, str) or not text.strip():
            missing.append(path)

    for name, spec in (doc.get("types") or {}).items():
        if spec is None:  # a deletion, not a declaration
            continue
        needs(f"types.{name}", spec)
        for fname, fspec in (spec.get("fields") or {}).items():
            if fspec is None:
                continue
            needs(f"types.{name}.fields.{fname}", fspec)
    for name, spec in (doc.get("link_types") or {}).items():
        if spec is None:
            continue
        needs(f"link_types.{name}", spec)
    for set_name, entry in (doc.get("sets") or {}).items():
        if entry is None:
            continue
        for fname, fspec in (entry.get("fields") or {}).items():
            if fspec is None:
                continue
            needs(f"sets.{set_name}.fields.{fname}", fspec)
    return missing


def test_every_bundled_v3_declaration_has_a_definition():
    """Raw-file pass: every type, field, link type and field-set entry in
    base.yaml and each v3 preset declares a non-empty `doc:`."""
    problems = []
    for label, doc in _bundle_files():
        for path in _missing_definitions(label, doc):
            problems.append(f"{label}: {path}")
    assert not problems, "bundled hardware@3 declarations without a doc:\n" + "\n".join(problems)


def _resolved(presets: list[str]):
    """A scratch project resolving the bundled standard with no overlay --
    the same no-overlay replay `docs-site/gen_examples.py` uses, so a
    project's own schema can never satisfy (or break) this lint."""
    with tempfile.TemporaryDirectory(prefix="refdes-docs-complete-") as tmp:
        config = os.path.join(tmp, "refdes-project.yaml")
        with open(config, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {
                    "site": {"title": "Lint", "out": "_site"},
                    "id": {"width": 3, "ledger": ".refdes/ids.yaml"},
                    "standard": {"base": "hardware", "version": 3, "presets": presets},
                },
                fh,
                sort_keys=False,
            )
        return load_project(config_path=config)


def test_resolved_standard_and_preset_export_definitions_everywhere():
    """Resolved pass: base plus every bundled preset, seen the way an editor
    sees it -- every type, every field (including `include:`d ones) and every
    link type carries a non-empty doc."""
    presets = (
        sorted(n[: -len(".yaml")] for n in os.listdir(PRESET_DIR) if n.endswith(".yaml"))
        if os.path.isdir(PRESET_DIR)
        else []
    )
    project = _resolved(presets)
    missing = [
        f"types.{tname}" for tname, spec in project.types.items() if not spec.doc.strip()
    ]
    missing += [
        f"types.{tname}.fields.{fname}"
        for tname, spec in project.types.items()
        for fname, fspec in spec.fields.items()
        if not fspec.doc.strip()
    ]
    missing += [
        f"link_types.{name}" for name, lt in project.link_types.items() if not lt.doc.strip()
    ]
    assert not missing, "resolved hardware@3 terms without a doc:\n" + "\n".join(missing)
