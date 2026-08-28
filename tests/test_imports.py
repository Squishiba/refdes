"""imports.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os

import pytest
from helpers import REPO, _build_at

# ------------------------------------------------------------------------ imports

UPSTREAM = {
    "title": "Platform Interfaces",
    "version": "2026.3",
    "items": [
        {
            "id": "IFC-CAN-001",
            "type": "bound",
            "title": "Per-pin current rating",
            "fields": {"title": "Per-pin current rating", "limit": "<= 3 A"},
            "links": {},
            "content_hash": "upstreamhash01",
        }
    ],
}


BOARD_DECISION = """\
---
id: DEC-X-001
type: decision
title: Connector pin allocation
status: accepted
constrained_by: [IFC-CAN-001]
checks:
  - value: I_pin
    against: IFC-CAN-001
---

```calc
I_total   = 4.8 A
n_pins    = 2
I_pin : A = I_total / n_pins
```
"""


@pytest.fixture
def importing_project(tmp_path):

    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "items.json").write_text(
        json.dumps(UPSTREAM), encoding="utf-8"
    )
    config = open(os.path.join(REPO, "refdes.yaml"), encoding="utf-8").read()
    config += (
        '\nimports:\n  - name: platform\n'
        '    items: upstream/items.json\n    version: "2026.3"\n'
    )
    (tmp_path / "refdes.yaml").write_text(config, encoding="utf-8")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "pins.md").write_text(BOARD_DECISION, encoding="utf-8")
    return tmp_path


def test_imported_items_resolve_links_and_checks(importing_project):
    project = _build_at(importing_project)
    assert not project.errors
    upstream = project.items["IFC-CAN-001"]
    assert upstream.external is True
    assert upstream.origin == "platform"
    # 4.8 A over 2 pins is 2.4 A, inside the 3 A rating.
    assert project.items["DEC-X-001"].checks[0].ok is True


def test_upstream_change_fails_the_downstream_board(importing_project):

    tightened = json.loads(json.dumps(UPSTREAM))
    tightened["items"][0]["fields"]["limit"] = "<= 2 A"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(tightened), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert project.items["DEC-X-001"].checks[0].ok is False


def test_version_pin_mismatch_refuses_the_import(importing_project):

    moved = json.loads(json.dumps(UPSTREAM))
    moved["version"] = "2026.4"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(moved), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert any("pinned to" in d.message for d in project.errors)
    assert "IFC-CAN-001" not in project.items


def test_id_collision_across_projects_is_an_error(importing_project):
    colliding = (importing_project / "items" / "decisions" / "dup.yaml")
    colliding.write_text(
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: IFC-CAN-001\n"
        "    title: Locally redefined\n"
        '    limit: "<= 9 A"\n',
        encoding="utf-8",
    )
    project = _build_at(importing_project)
    assert any("already exists" in d.message for d in project.errors)


def test_imported_items_are_excluded_from_local_coverage(importing_project):
    """Upstream's coverage gaps are upstream's problem, not this board's."""
    project = _build_at(importing_project)
    assert "IFC-CAN-001" not in project.coverage
    assert project.items["IFC-CAN-001"].content_hash == "upstreamhash01"
