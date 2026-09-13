"""Test bootstrap and the fixtures shared by more than one test module.

pytest imports this before any test module, so the sys.path bootstrap below is
what lets every other test file `from refdes import ...` without repeating it.
Fixtures defined here are auto-discovered -- test modules never import them.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import os
import re
from pathlib import Path

import pytest
from helpers import (
    BLOCKS_ITEMS,
    BLOCKS_SCHEMA,
    BOARD_CONFIG,
    COVERAGE_ITEMS,
    COVERAGE_SCHEMA,
    LIFECYCLE_COMPONENT,
    LIFECYCLE_ITEMS,
    LIFECYCLE_SCHEMA,
    REPO,
    SEALED_BOARD_CONFIG,
)


# ------------------------------------------------------- the two-file config split
#
# A project's config is two files now: `refdes-project.yaml`, the marker holding
# every project setting, and the optional `refdes-schema.yaml` holding only the
# project's own `types:`/`link_types:`/`field_sets:`. `refdes.yaml` is retired.
#
# Test fixtures still carry their config as one combined module constant, and
# `write_project_config` is what turns that constant into the two real files.

SCHEMA_KEYS = ("types", "link_types", "field_sets")
PROJECT_FILE = "refdes-project.yaml"
SCHEMA_FILE = "refdes-schema.yaml"

_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:")


def split_project_config(combined_yaml: str) -> tuple[str, str | None]:
    """Split combined config text into (settings text, schema text or None).

    Split by top-level key on the raw text rather than by round-tripping the
    YAML, so every comment and every line of formatting survives into whichever
    file its key ends up in -- the comments are the documentation, in the tests
    as in the real config files.
    """
    lines = combined_yaml.splitlines(keepends=True)
    spans: list[tuple[str, list[str]]] = []  # (key, lines including its preamble)
    preamble: list[str] = []
    for line in lines:
        match = _TOP_LEVEL_KEY.match(line)
        if match:
            spans.append((match.group(0)[:-1], [line]))
        elif spans:
            spans[-1][1].append(line)
        else:
            preamble.append(line)

    settings = preamble[:]
    schema: list[str] = []
    for key, block in spans:
        (schema if key in SCHEMA_KEYS else settings).extend(block)

    schema_text = "".join(schema).strip("\n")
    return "".join(settings), (schema_text + "\n" if schema_text else None)


def write_project_config(root, combined_yaml: str):
    """Write `combined_yaml` into `root` as the two real config files.

    `combined_yaml` is the single combined text a fixture already holds as a
    module constant; it is split by top-level key -- `types:`, `link_types:` and
    `field_sets:` go to `refdes-schema.yaml`, everything else to
    `refdes-project.yaml` -- with comments intact. `refdes-schema.yaml` is only
    written when the config actually declares a schema of its own, matching the
    common real-world case of a project with no overlay file.

    Returns the path of the written `refdes-project.yaml`, so a fixture that
    loads by explicit path can wrap the call:
    `load_project(config_path=str(write_project_config(tmp_path, CONST)))`.
    """
    root = str(root)
    settings_text, schema_text = split_project_config(combined_yaml)
    settings_path = os.path.join(root, PROJECT_FILE)
    with open(settings_path, "w", encoding="utf-8") as fh:
        fh.write(settings_text)
    schema_path = os.path.join(root, SCHEMA_FILE)
    if schema_text is None:
        if os.path.isfile(schema_path):
            os.remove(schema_path)
    else:
        with open(schema_path, "w", encoding="utf-8") as fh:
            fh.write(schema_text)
    return Path(settings_path)


@pytest.fixture
def coverage_project(tmp_path):
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path
# ------------------------------------------------------------------------- pages


@pytest.fixture
def paged_project(tmp_path):
    for name in (PROJECT_FILE, SCHEMA_FILE):
        source = os.path.join(REPO, name)
        if os.path.isfile(source):
            (tmp_path / name).write_text(
                open(source, encoding="utf-8").read(), encoding="utf-8"
            )

    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    body: A requirement.\n",
        encoding="utf-8",
    )

    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(
        "# Board overview\n\nStart with [the power notes](power.md).\n",
        encoding="utf-8",
    )
    (pages / "power.md").write_text(
        "---\norder: 5\n---\n\n# Power\n\nDriven by REQ-001.\n\n"
        "## Rails\n\ntext\n\n## Budget\n\ntext\n",
        encoding="utf-8",
    )
    return tmp_path
@pytest.fixture
def board_project(tmp_path):
    write_project_config(tmp_path, BOARD_CONFIG)

    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-A }\n"
        "items:\n  - id: REQ-A-001\n    text: On board A by its folder.\n",
        encoding="utf-8",
    )

    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-B }\n"
        "items:\n"
        "  - id: REQ-B-001\n    text: On board B by its folder.\n"
        "  - id: REQ-WRONG-001\n    prefix: REQ-WRONG\n"
        "    text: On board B but its own id prefix has no 'B' token.\n",
        encoding="utf-8",
    )

    shared = tmp_path / "items" / "shared"
    shared.mkdir(parents=True)
    (shared / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-S }\n"
        "items:\n"
        "  - id: REQ-S-001\n    text: In an unregistered folder, no board.\n"
        "  - id: REQ-S-002\n    board: board-a\n"
        "    text: Overridden onto board-a despite living in shared/.\n",
        encoding="utf-8",
    )
    return tmp_path
@pytest.fixture
def sealed_board_project(tmp_path):
    write_project_config(tmp_path, SEALED_BOARD_CONFIG)

    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-A }\n"
        "items:\n  - id: LOG-A-001\n    summary: first entry\n",
        encoding="utf-8",
    )

    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-B }\n"
        "items:\n  - id: LOG-B-001\n    summary: first entry\n",
        encoding="utf-8",
    )

    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG-X }\n"
        "items:\n  - id: LOG-X-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    return tmp_path
@pytest.fixture
def lifecycle_project(tmp_path):
    write_project_config(tmp_path, LIFECYCLE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(LIFECYCLE_ITEMS, encoding="utf-8")
    (items / "cmp.yaml").write_text(LIFECYCLE_COMPONENT, encoding="utf-8")
    return tmp_path
@pytest.fixture
def blocks_project(tmp_path):
    write_project_config(tmp_path, BLOCKS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKS_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    return tmp_path
