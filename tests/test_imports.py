"""imports.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest
from conftest import write_project_config
from helpers import REPO, _build_at

from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import render

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


KEYED_IMPORT_SCHEMA = """\
site: { title: T, out: _site }
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  bound:
    prefix: IFC
    fields:
      title: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [bound]
"""


def _keyed_import_projects(tmp_path):
    upstream = tmp_path / "upstream"
    downstream = tmp_path / "downstream"
    upstream.mkdir()
    downstream.mkdir()
    write_project_config(upstream, KEYED_IMPORT_SCHEMA)
    write_project_config(
        downstream,
        KEYED_IMPORT_SCHEMA
        + "\nimports:\n  - name: upstream\n    items: ../upstream/_site/items.json\n",
    )
    (upstream / "items").mkdir()
    (upstream / "items" / "bounds.yaml").write_text(
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: IFC-001\n"
        "    title: Original interface\n",
        encoding="utf-8",
    )
    (downstream / "items").mkdir()
    (downstream / "items" / "decision.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    title: Uses the interface\n"
        "    satisfies: [IFC-001]\n",
        encoding="utf-8",
    )
    return upstream, downstream


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
    shutil.copy(
        os.path.join(REPO, "refdes-project.yaml"), tmp_path / "refdes-project.yaml"
    )
    shutil.copy(
        os.path.join(REPO, "refdes-schema.yaml"), tmp_path / "refdes-schema.yaml"
    )
    with (tmp_path / "refdes-project.yaml").open("a", encoding="utf-8") as fh:
        fh.write(
            '\nimports:\n  - name: platform\n'
            '    items: upstream/items.json\n    version: "2026.3"\n'
        )
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "pins.md").write_text(BOARD_DECISION, encoding="utf-8")
    return tmp_path


def test_imported_items_resolve_links_and_checks(importing_project):
    project = _build_at(importing_project)
    assert not project.errors
    upstream = project.item_by_id("IFC-CAN-001")
    assert upstream.external is True
    assert upstream.origin == "platform"
    # 4.8 A over 2 pins is 2.4 A, inside the 3 A rating.
    assert project.item_by_id("DEC-X-001").checks[0].ok is True


def test_upstream_change_fails_the_downstream_board(importing_project):

    tightened = json.loads(json.dumps(UPSTREAM))
    tightened["items"][0]["fields"]["limit"] = "<= 2 A"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(tightened), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert project.item_by_id("DEC-X-001").checks[0].ok is False


def test_version_pin_mismatch_refuses_the_import(importing_project):

    moved = json.loads(json.dumps(UPSTREAM))
    moved["version"] = "2026.4"
    (importing_project / "upstream" / "items.json").write_text(
        json.dumps(moved), encoding="utf-8"
    )
    project = _build_at(importing_project)
    assert any("pinned to" in d.message for d in project.errors)
    assert project.item_by_id("IFC-CAN-001") is None


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
    assert project.item_by_id("IFC-CAN-001").content_hash == "upstreamhash01"


def test_items_json_exports_each_items_key_or_null(importing_project):
    project = _build_at(importing_project)
    decision = project.item_by_id("DEC-X-001")

    assert next(
        entry for entry in render.items_json(project)["items"] if entry["id"] == decision.id
    )["key"] is None

    decision.key = keys_mod.mint()
    assert next(
        entry for entry in render.items_json(project)["items"] if entry["id"] == decision.id
    )["key"] == decision.key


def test_imported_key_collision_across_origins_is_a_layer_two_error(tmp_path):
    key = keys_mod.mint()
    for origin, item_id in (("first", "IFC-001"), ("second", "IFC-002")):
        artifact = tmp_path / origin
        artifact.mkdir()
        (artifact / "items.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": item_id,
                            "key": key,
                            "type": "bound",
                            "fields": {"title": origin},
                            "links": {},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    write_project_config(
        tmp_path,
        KEYED_IMPORT_SCHEMA
        + "\nimports:\n"
        "  - name: first\n    items: first/items.json\n"
        "  - name: second\n    items: second/items.json\n",
    )
    project = _build_at(tmp_path)

    assert any(
        key in diagnostic.message
        and "import 'first'" in diagnostic.message
        and "import 'second'" in diagnostic.message
        for diagnostic in project.errors
    )


def test_malformed_imported_key_is_a_layer_one_error_on_its_import(tmp_path):
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "items.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "IFC-001",
                        "key": "not-a-key",
                        "type": "bound",
                        "fields": {"title": "bad key"},
                        "links": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    write_project_config(
        tmp_path,
        KEYED_IMPORT_SCHEMA + "\nimports:\n  - name: upstream\n    items: upstream/items.json\n",
    )

    project = _build_at(tmp_path)

    assert any(
        "not-a-key" in diagnostic.message
        and diagnostic.file == "refdes-project.yaml"
        and diagnostic.item_id is None
        for diagnostic in project.errors
    )


def test_imported_key_survives_upstream_rename_and_refreshes_link_label(tmp_path):
    upstream, downstream = _keyed_import_projects(tmp_path)
    upstream_config = str(upstream / "refdes-project.yaml")
    downstream_config = str(downstream / "refdes-project.yaml")

    assert cli_mod.main(["-c", upstream_config, "build"]) == 0
    upstream_payload = json.loads((upstream / "_site" / "items.json").read_text(encoding="utf-8"))
    key = upstream_payload["items"][0]["key"]
    assert key

    assert cli_mod.main(["-c", downstream_config, "check"]) == 0
    downstream_source = downstream / "items" / "decision.yaml"
    assert f"satisfies: [IFC-001@{key}]" in downstream_source.read_text(encoding="utf-8")
    before = _build_at(downstream)
    hash_before = before.item_by_id("DEC-001").content_hash
    assert before.items[key].external is True

    upstream_source = upstream / "items" / "bounds.yaml"
    upstream_source.write_text(
        upstream_source.read_text(encoding="utf-8").replace("IFC-001", "IFC-009"),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", upstream_config, "build"]) == 0

    assert cli_mod.main(["-c", downstream_config, "check"]) == 0
    assert f"satisfies: [IFC-009@{key}]" in downstream_source.read_text(encoding="utf-8")
    after = _build_at(downstream)
    assert not after.errors
    assert after.item_by_id("DEC-001").resolved_links["satisfies"] == ["IFC-009"]
    assert after.item_by_id("DEC-001").content_hash == hash_before
