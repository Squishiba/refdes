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


@pytest.fixture
def coverage_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path
# ------------------------------------------------------------------------- pages


@pytest.fixture
def paged_project(tmp_path):
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")

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
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")

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
    (tmp_path / "refdes.yaml").write_text(SEALED_BOARD_CONFIG, encoding="utf-8")

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
    (tmp_path / "refdes.yaml").write_text(LIFECYCLE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(LIFECYCLE_ITEMS, encoding="utf-8")
    (items / "cmp.yaml").write_text(LIFECYCLE_COMPONENT, encoding="utf-8")
    return tmp_path
@pytest.fixture
def blocks_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BLOCKS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKS_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    return tmp_path
