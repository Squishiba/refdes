"""workspaces.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os

import pytest
import yaml
from helpers import _build_at

from refdes import boards as boards_mod
from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import nav as nav_mod
from refdes import parse, render
from refdes.schema import SchemaError, load_project

# --------------------------------------------------------------------- workspaces

WORKSPACE_CONFIG = """\
site:
  title: "Workspace test"
  out: _site
id:
  width: 3
workspaces:
  platform:
    label: "Platform"
    shared: true
  product-a:
    label: "Product A"
  product-b:
    label: "Product B"
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""


@pytest.fixture
def workspace_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(WORKSPACE_CONFIG, encoding="utf-8")
    (tmp_path / "refdes-project.yaml").write_text(
        "item_layout: workspace\n", encoding="utf-8"
    )

    platform = tmp_path / "items" / "platform" / "shared"
    platform.mkdir(parents=True)
    (platform / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-PLAT-001\n    text: Shared platform requirement.\n",
        encoding="utf-8",
    )

    a = tmp_path / "items" / "product-a" / "board-a"
    a.mkdir(parents=True)
    (a / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-A-001\n    text: Product A's own requirement.\n",
        encoding="utf-8",
    )
    (a / "decisions.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-001\n    type: decision\n    title: Uses the shared platform.\n"
        "    satisfies: [REQ-PLAT-001]\n"
        "  - id: DEC-A-002\n    type: decision\n    title: Stays within product-a.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )
    # decisions.yaml has no `defaults: {type: decision}` on purpose -- both
    # entries name their own type explicitly, same shape reqs.yaml's items use.

    b = tmp_path / "items" / "product-b" / "board-b"
    b.mkdir(parents=True)
    (b / "decisions.yaml").write_text(
        "items:\n"
        "  - id: DEC-B-001\n    type: decision\n"
        "    title: Secretly depends on product A.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_flat_layout_with_no_workspaces_is_unaffected(board_project):
    """The core regression guarantee: item_layout defaults to flat, and with
    no workspaces: registry, workspace resolution, the lint, and the drift
    manifest's workspaces: section are all complete no-ops."""
    project = _build_at(board_project)
    assert all(item.workspace == "" for item in project.local_items)
    assert not project.workspace_moves
    assert not any("workspace" in d.message.lower() for d in project.diagnostics)
    assert project.items["REQ-A-001"].board == "board-a"  # boards: untouched

    build_mod.build(project, seal_write=True)
    manifest = boards_mod.load_manifest(project)
    assert manifest["workspaces"] == {}
    raw_data = yaml.safe_load(open(boards_mod.manifest_path(project), encoding="utf-8"))
    assert "workspaces" not in raw_data  # key omitted entirely, not just empty


def test_workspace_and_board_derive_from_the_two_path_segments(workspace_project):
    project = _build_at(workspace_project)
    assert project.items["REQ-A-001"].workspace == "product-a"
    assert project.items["REQ-A-001"].board == "board-a"
    assert project.items["DEC-B-001"].workspace == "product-b"
    assert project.items["DEC-B-001"].board == "board-b"


def test_workspace_override_beats_the_path(workspace_project):
    misc = workspace_project / "items" / "misc"
    misc.mkdir(parents=True)
    (misc / "extra.yaml").write_text(
        "items:\n"
        "  - id: REQ-X-001\n    type: requirement\n"
        "    text: Lives outside any workspace folder.\n"
        "    workspace: product-b\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert project.items["REQ-X-001"].workspace == "product-b"


def test_workspace_override_works_even_under_flat_layout(tmp_path):
    """The override is layout-independent; only the path fallback needs
    item_layout: workspace."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "workspaces:\n  platform: { label: Platform }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n      text: { type: text, required: true }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Tagged by hand.\n    workspace: platform\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-001"].workspace == "platform"


def test_unregistered_workspace_override_is_a_build_error(workspace_project):
    (workspace_project / "items" / "product-a" / "board-a" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-A-001\n    text: Bad override.\n    workspace: nope\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert any(
        "workspace: 'nope' is not declared" in d.message and d.item_id == "REQ-A-001"
        for d in project.errors
    )


def test_no_second_path_segment_under_workspace_layout_warns(workspace_project):
    lone = workspace_project / "items" / "platform"
    (lone / "orphan.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-LONE-001\n    text: One segment only.\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert project.items["REQ-LONE-001"].workspace == "platform"
    assert project.items["REQ-LONE-001"].board == ""
    assert any(
        d.item_id == "REQ-LONE-001"
        and "no second items/ path segment" in d.message
        for d in project.warnings
    )


def test_cross_workspace_link_into_a_non_shared_workspace_warns(workspace_project):
    project = _build_at(workspace_project)
    hits = [
        d for d in project.warnings
        if d.item_id == "DEC-B-001" and "workspace" in d.message
    ]
    assert len(hits) == 1
    assert "REQ-A-001" in hits[0].message
    assert "'product-a'" in hits[0].message
    assert "shared: true" in hits[0].message


def test_cross_workspace_link_into_a_shared_workspace_is_silent(workspace_project):
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-001" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_same_workspace_link_never_trips_the_lint(workspace_project):
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-002" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_lint_never_fires_from_the_backlink_direction(workspace_project):
    """DEC-B-001 -> REQ-A-001 crosses workspaces and is flagged once, attributed
    to DEC-B-001 (the authored end). REQ-A-001's computed backlink to DEC-B-001
    must never independently trip a second warning -- proving the lint walks
    item.links exclusively, never item.backlinks."""
    project = _build_at(workspace_project)
    assert "DEC-B-001" in project.items["REQ-A-001"].backlinks.get("satisfied_by", [])
    hits = [d for d in project.diagnostics if "hidden dependency" in d.message]
    assert len(hits) == 1
    assert hits[0].item_id == "DEC-B-001"


def test_derived_coverage_never_trips_the_lint(workspace_project):
    """Coverage is computed from backlinks into project.coverage, a structure
    entirely separate from any item's links -- two items in different,
    non-shared workspaces both contributing to the aggregate coverage picture
    must never be treated as a link between them."""
    project = _build_at(workspace_project)
    assert "REQ-A-001" in project.coverage  # satisfied by DEC-B-001 and DEC-A-002
    assert not any(
        "hidden dependency" in d.message and d.item_id == "REQ-A-001"
        for d in project.diagnostics
    )


def test_cross_workspace_severity_is_configurable(workspace_project):
    (workspace_project / "refdes-project.yaml").write_text(
        "item_layout: workspace\ncross_workspace_severity: error\n", encoding="utf-8"
    )
    project = _build_at(workspace_project)
    assert any(
        d.item_id == "DEC-B-001" and "hidden dependency" in d.message
        for d in project.errors
    )
    assert not any(
        d.item_id == "DEC-B-001" and "hidden dependency" in d.message
        for d in project.warnings
    )


def test_lint_ignores_imported_items_on_either_end(workspace_project):
    """An imported item's `workspace` describes the upstream project's own
    structure, not a dependency inside this one -- imports have their own
    boundary-crossing story and are exempt from this lint entirely."""

    upstream_dir = workspace_project / "upstream"
    upstream_dir.mkdir()
    (upstream_dir / "items.json").write_text(
        json.dumps({
            "items": [{
                "id": "REQ-UP-001",
                "type": "requirement",
                "fields": {"text": "Upstream requirement."},
                "links": {},
                "content_hash": "abc123",
            }]
        }),
        encoding="utf-8",
    )
    config = open(workspace_project / "refdes.yaml", encoding="utf-8").read()
    config += (
        '\nimports:\n  - name: upstream\n    items: upstream/items.json\n'
    )
    (workspace_project / "refdes.yaml").write_text(config, encoding="utf-8")
    (workspace_project / "items" / "product-a" / "board-a" / "extra.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-003\n    type: decision\n    title: Satisfies an import.\n"
        "    satisfies: [REQ-UP-001]\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    assert not any(
        d.item_id == "DEC-A-003" and "hidden dependency" in d.message
        for d in project.diagnostics
    )


def test_board_and_workspace_names_may_not_collide(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  power: { label: Power }\n"
        "workspaces:\n  power: { label: Power }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="declared as both a board and a workspace"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_workspace_drift_warns_and_accept_board_move_clears_it(workspace_project):
    project = _build_at(workspace_project)
    build_mod.build(project, seal_write=True)

    # Move DEC-A-002's file into product-b's tree, crossing the workspace
    # boundary without touching its board.
    src = workspace_project / "items" / "product-a" / "board-a" / "decisions.yaml"
    src.read_text(encoding="utf-8")
    src.write_text(
        "items:\n"
        "  - id: DEC-A-001\n    type: decision\n    title: Uses the shared platform.\n"
        "    satisfies: [REQ-PLAT-001]\n",
        encoding="utf-8",
    )
    dst = workspace_project / "items" / "product-b" / "board-a"
    dst.mkdir(parents=True)
    (dst / "moved.yaml").write_text(
        "items:\n"
        "  - id: DEC-A-002\n    type: decision\n    title: Stays within product-a.\n"
        "    satisfies: [REQ-A-001]\n",
        encoding="utf-8",
    )

    project2 = _build_at(workspace_project)
    assert ("DEC-A-002", "product-a", "product-b") in project2.workspace_moves
    assert any(
        d.item_id == "DEC-A-002" and "moved from workspace" in d.message
        for d in project2.warnings
    )

    project3 = _build_at(workspace_project)
    build_mod.build(project3, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project3)["workspaces"]["DEC-A-002"] == "product-b"

    project4 = _build_at(workspace_project)
    build_mod.build(project4, seal_write=True)
    assert not project4.workspace_moves


def test_audit_reports_workspace_moves(workspace_project):
    project = _build_at(workspace_project)
    build_mod.build(project, seal_write=True)
    (workspace_project / "items" / "product-a" / "board-a" / "reqs.yaml").rename(
        workspace_project / "items" / "product-b" / "board-b" / "moved-req.yaml"
    )
    project2 = load_project(config_path=str(workspace_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "product-a", "product-b") in project2.workspace_moves


def test_check_workspace_flag_scopes_item_count(workspace_project, capsys):
    cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "product-a"]
    )
    out = capsys.readouterr().out
    # product-a has exactly REQ-A-001, DEC-A-001, DEC-A-002.
    assert "3 items," in out


def test_check_workspace_flag_hides_other_workspaces_warnings(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "product-a"]
    )
    # A valid workspace with warnings-only findings exits clean -- the contrast
    # with test_check_unknown_workspace_flag_is_a_clear_error's exit 1 below.
    assert status == 0
    out = capsys.readouterr().out
    assert "DEC-B-001" not in out
    assert "hidden dependency" not in out


def test_check_unknown_workspace_flag_is_a_clear_error(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes.yaml"), "check", "--workspace", "nope"]
    )
    err = capsys.readouterr().err
    assert status == 1
    assert "--workspace 'nope' is not a workspace declared" in err


def test_workspace_pages_render_with_nested_board_groups(workspace_project):
    project = _build_at(workspace_project)
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "coverage-platform.html"))
    assert os.path.isfile(os.path.join(out, "summary-product-a.html"))
    assert os.path.isfile(os.path.join(out, "document-product-b.html"))

    nav = nav_mod.build_nav(project, dashboard_href="index.html")
    labels = {node.label: node for node in nav}
    assert "Product A" in labels
    product_a_children = {
        child.label for child in labels["Product A"].children
    }
    assert "Board A" in product_a_children
    board_a_node = next(
        c for c in labels["Product A"].children if c.label == "Board A"
    )
    assert any(c.href == "coverage-board-a.html" for c in board_a_node.children)


def test_items_json_exports_workspace_registry_and_per_item_workspace(workspace_project):
    project = _build_at(workspace_project)
    payload = render.items_json(project)
    assert set(payload["workspaces"]) == {"platform", "product-a", "product-b"}
    assert payload["workspaces"]["platform"]["shared"] is True
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["REQ-A-001"]["workspace"] == "product-a"


def test_page_workspace_tag_groups_it_and_must_be_registered(workspace_project):
    pages_dir = workspace_project / "pages"
    pages_dir.mkdir()
    (pages_dir / "overview.md").write_text(
        "---\ntitle: Product A overview\nworkspace: product-a\n---\n\nHello.\n",
        encoding="utf-8",
    )
    project = _build_at(workspace_project)
    page = next(p for p in project.pages if p.slug == "overview")
    assert page.workspace == "product-a"

    (pages_dir / "bad.md").write_text(
        "---\ntitle: Bad tag\nworkspace: not-a-real-workspace\n---\n\nHello.\n",
        encoding="utf-8",
    )
    project2 = _build_at(workspace_project)
    bad_page = next(p for p in project2.pages if p.slug == "bad")
    assert bad_page.workspace == ""
    assert any(
        "page workspace: 'not-a-real-workspace' is not declared" in d.message
        for d in project2.errors
    )
