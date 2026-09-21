"""Resolved-schema dump for the hardware@3 oracle (tests/test_extends.py).

Everything a resolved standard hands the engine, in declared order, as JSON:
types and link_types field-by-field, link-by-link, scalar-by-scalar.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

from conftest import write_project_config

from refdes.schema import load_project


def _type_dict(item_type) -> dict:
    """The type as the snapshot fixtures recorded it, before `extends:` existed:
    the relation itself is the one thing the oracle is not comparing."""
    out = dataclasses.asdict(item_type)
    out.pop("extends")
    return out


def resolved_dump(presets: list[str]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        preset_yaml = "".join(f"    - {p}\n" for p in presets)
        write_project_config(
            Path(tmp),
            "site: { title: T, out: _site }\n"
            "standard:\n  base: hardware\n  version: 3\n"
            + (f"  presets:\n{preset_yaml}" if presets else ""),
        )
        project = load_project(config_path=str(Path(tmp) / "refdes-project.yaml"))
    payload = {
        "types": {n: _type_dict(t) for n, t in project.types.items()},
        "link_types": {n: dataclasses.asdict(t) for n, t in project.link_types.items()},
    }
    return json.dumps(payload, indent=1)
