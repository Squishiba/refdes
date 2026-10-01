"""workspaces.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os
import re

import pytest
import yaml
from conftest import write_project_config
from helpers import REPO, _build_at

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
    # `item_layout: workspace` is a setting, so it belongs in the marker the
    # helper just wrote -- appended there rather than written over it.
    config = write_project_config(tmp_path, WORKSPACE_CONFIG)
    with config.open("a", encoding="utf-8") as fh:
        fh.write("item_layout: workspace\n")

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
    assert project.item_by_id("REQ-A-001").board == "board-a"  # boards: untouched

    build_mod.build(project, seal_write=True)
    manifest = boards_mod.load_manifest(project)
    assert manifest["workspaces"] == {}
    raw_data = yaml.safe_load(open(boards_mod.manifest_path(project), encoding="utf-8"))
    assert "workspaces" not in raw_data  # key omitted entirely, not just empty


def test_workspace_and_board_derive_from_the_two_path_segments(workspace_project):
    project = _build_at(workspace_project)
    assert project.item_by_id("REQ-A-001").workspace == "product-a"
    assert project.item_by_id("REQ-A-001").board == "board-a"
    assert project.item_by_id("DEC-B-001").workspace == "product-b"
    assert project.item_by_id("DEC-B-001").board == "board-b"


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
    assert project.item_by_id("REQ-X-001").workspace == "product-b"


def test_workspace_override_works_even_under_flat_layout(tmp_path):
    """The override is layout-independent; only the path fallback needs
    item_layout: workspace."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "workspaces:\n  platform: { label: Platform }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n      text: { type: text, required: true }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Tagged by hand.\n    workspace: platform\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.item_by_id("REQ-001").workspace == "platform"


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
    assert project.item_by_id("REQ-LONE-001").workspace == "platform"
    assert project.item_by_id("REQ-LONE-001").board == ""
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
    assert "DEC-B-001" in project.item_by_id("REQ-A-001").backlinks.get("satisfied_by", [])
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
    # The marker already carries the fixture's settings (item_layout included),
    # so the severity is appended rather than written over them.
    config = workspace_project / "refdes-project.yaml"
    with config.open("a", encoding="utf-8") as fh:
        fh.write("cross_workspace_severity: error\n")
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
    config = open(workspace_project / "refdes-project.yaml", encoding="utf-8").read()
    config += (
        '\nimports:\n  - name: upstream\n    items: upstream/items.json\n'
    )
    # Already-split text read back from the marker: written straight back, so
    # the helper cannot mistake it for a combined config and drop the overlay.
    (workspace_project / "refdes-project.yaml").write_text(config, encoding="utf-8")
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
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "boards:\n  power: { label: Power }\n"
        "workspaces:\n  power: { label: Power }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
    )
    with pytest.raises(SchemaError, match="declared as both a board and a workspace"):
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))


COLLIDING_CONFIG = (
    "site: { title: T, out: _site }\n"
    "boards:\n  power: { label: Power }\n"
    "workspaces:\n  power: { label: Power }\n"
    "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
)


def test_workspaces_doc_warns_about_the_shared_name_namespace_before_it_bites(tmp_path):
    """The collision is refused at load with a good message, but a newcomer
    only meets it after both blocks are already written -- docs/workspaces.md
    said so only in the middle of the `workspace:` override section (user-sim
    run 2, "Lower severity" list). The warning has to sit where the registries
    are first introduced, and give the error's own reason rather than a
    paraphrase that can drift from it.
    """
    with open(os.path.join(REPO, "docs", "workspaces.md"), encoding="utf-8") as fh:
        doc = fh.read()

    # "Declaring workspaces" is where the two registries get their names; the
    # section after it is the first thing a reader does once they start
    # writing, so the note has to be before that line.
    declaring = doc.split("## The two-level layout")[0]
    assert declaring != doc, "docs/workspaces.md lost the section this test anchors on"
    assert "namespace" in declaring

    write_project_config(tmp_path, COLLIDING_CONFIG)
    with pytest.raises(SchemaError) as exc:
        load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    message = str(exc.value)

    # the reason the error gives is a generated filename, and the doc names
    # that same filename -- if the report names change, both have to move
    assert "coverage-power.html" in message
    assert "coverage-power.html" in declaring
    assert "coverage-<key>.html" in declaring


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
    project2 = load_project(config_path=str(workspace_project / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "product-a", "product-b") in project2.workspace_moves


def test_check_workspace_flag_scopes_item_count(workspace_project, capsys):
    cli_mod.main(
        ["-c", str(workspace_project / "refdes-project.yaml"), "check", "--workspace", "product-a"]
    )
    out = capsys.readouterr().out
    # product-a has exactly REQ-A-001, DEC-A-001, DEC-A-002.
    assert "3 items," in out


def test_check_workspace_flag_hides_other_workspaces_warnings(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes-project.yaml"), "check", "--workspace", "product-a"]
    )
    # A valid workspace with warnings-only findings exits clean -- the contrast
    # with test_check_unknown_workspace_flag_is_a_clear_error's exit 1 below.
    assert status == 0
    out = capsys.readouterr().out
    assert "DEC-B-001" not in out
    assert "hidden dependency" not in out


def test_check_unknown_workspace_flag_is_a_clear_error(workspace_project, capsys):
    status = cli_mod.main(
        ["-c", str(workspace_project / "refdes-project.yaml"), "check", "--workspace", "nope"]
    )
    err = capsys.readouterr().err
    assert status == 1
    assert "--workspace 'nope' is not a workspace declared" in err


def test_ls_workspace_flag_lists_only_that_workspaces_items(workspace_project, capsys):
    """F1: `check --workspace` could scope to a workspace, `ls` could not, so
    "what's in product-a?" had no answer in the listing command."""
    status = cli_mod.main(
        [
            "-c",
            str(workspace_project / "refdes-project.yaml"),
            "ls",
            "--workspace",
            "product-a",
        ]
    )
    assert status == 0
    out = capsys.readouterr().out
    # product-a has exactly REQ-A-001, DEC-A-001, DEC-A-002 -- the same three
    # `check --workspace product-a` counts above.
    assert "REQ-A-001" in out and "DEC-A-001" in out and "DEC-A-002" in out
    assert "REQ-PLAT-001" not in out and "DEC-B-001" not in out


def test_ls_workspace_flag_is_a_shared_workspace_its_own_row(workspace_project, capsys):
    cli_mod.main(
        [
            "-c",
            str(workspace_project / "refdes-project.yaml"),
            "ls",
            "--workspace",
            "platform",
        ]
    )
    out = capsys.readouterr().out
    assert "REQ-PLAT-001" in out
    assert "DEC-A-001" not in out and "DEC-B-001" not in out


def test_ls_workspace_flag_combines_as_and_with_type_and_board(workspace_project, capsys):
    """Board and workspace are independent fields -- a workspace groups boards
    one level above the hardware grouping (docs/workspaces.md) -- so both
    combinations are meaningful, and both AND like every other `ls` filter."""
    cli_mod.main(
        [
            "-c",
            str(workspace_project / "refdes-project.yaml"),
            "ls",
            "--workspace",
            "product-a",
            "--type",
            "decision",
        ]
    )
    out = capsys.readouterr().out
    assert "DEC-A-001" in out and "DEC-A-002" in out
    assert "REQ-A-001" not in out

    cli_mod.main(
        [
            "-c",
            str(workspace_project / "refdes-project.yaml"),
            "ls",
            "--workspace",
            "product-a",
            "--board",
            "board-b",
        ]
    )
    assert "no items match" in capsys.readouterr().out


def test_ls_unknown_workspace_matches_nothing_rather_than_erroring(workspace_project, capsys):
    """Deliberate asymmetry with `check`: `check --workspace nope` is a registry
    error and exit 1 because `check` is a gate, while `ls` is a query and
    `ls --board nosuch` already answers a typo with "no items match", exit 0.
    `--workspace` follows `--board`, which is what "filter the same way" means
    here."""
    status = cli_mod.main(
        [
            "-c",
            str(workspace_project / "refdes-project.yaml"),
            "ls",
            "--workspace",
            "nope",
        ]
    )
    assert status == 0
    assert "no items match" in capsys.readouterr().out


# ------------------------------------------------- the ls workspace column (N5)


def _steady_state_ls(capsys, cfg, *args):
    """`ls`'s output on a project whose keys already exist.

    The first load of a fresh project mints surrogate keys and says so, and that
    notice is line one of stdout -- these tests match the listing exactly, so
    they read the run after it. The notice is real and wanted (load-writes
    reporting); a test about column layout is not where it belongs.
    """
    cli_mod.main(["-c", cfg, "ls", *args])
    capsys.readouterr()
    cli_mod.main(["-c", cfg, "ls", *args])
    return capsys.readouterr().out


def test_ls_shows_a_workspace_column_when_the_project_declares_workspaces(
    workspace_project, capsys
):
    """N5: `--workspace` could filter but nothing in the plain listing said a
    workspace existed or where an item's came from, so the flag was
    undiscoverable from the listing it filters. Exact lines, not a substring --
    a bare "product-a" in out would pass just as well with the column in the
    wrong place, or twice.

    Column order is workspace then board, mirroring the two groupings' real
    relationship (a workspace groups boards one level up, docs/workspaces.md)
    and the order the filters are documented in.
    """
    out = _steady_state_ls(capsys, str(workspace_project / "refdes-project.yaml"))
    assert out.splitlines() == [
        "DEC-A-001     decision     product-a  board-a  Uses the shared platform.",
        "DEC-A-002     decision     product-a  board-a  Stays within product-a.",
        "DEC-B-001     decision     product-b  board-b  Secretly depends on product A.",
        "REQ-A-001     requirement  product-a  board-a  Product A's own requirement.",
        # platform's folder has no second segment that is a registered board, so
        # REQ-PLAT-001 has no board -- and an absent board is blank padding, the
        # same treatment it gets in the board column's own place today.
        "REQ-PLAT-001  requirement  platform            Shared platform requirement.",
    ]


def test_ls_omits_the_workspace_column_entirely_without_a_workspaces_registry(
    board_project, capsys
):
    """The byte-for-byte guarantee. `workspaces.resolve` is a no-op with no
    `workspaces:` registry, so no item can have a workspace and a column of
    blanks would be pure noise -- this project's listing must be exactly what
    it was before the column existed, including the widths and the blank where
    an item has no board."""
    out = _steady_state_ls(capsys, str(board_project / "refdes-project.yaml"))
    assert out.splitlines() == [
        "REQ-A-001      requirement  board-a  On board A by its folder.",
        "REQ-B-001      requirement  board-b  On board B by its folder.",
        "REQ-S-001      requirement           In an unregistered folder, no board.",
        "REQ-S-002      requirement  board-a  Overridden onto board-a despite living in shared/.",
        "REQ-WRONG-001  requirement  board-b  On board B but its own id prefix has no 'B' token.",
    ]


def test_ls_shows_an_item_in_no_workspace_as_a_blank_and_never_matches_it(
    workspace_project, capsys
):
    """What the column shows for an item in no workspace has to agree with what
    `--workspace` does with it. `item.workspace` is "" for such an item and
    cmd_ls filters on `if args.workspace and item.workspace != args.workspace`
    -- so every real name excludes it, and `--workspace ''` is a falsy flag that
    filters nothing at all and lists the whole project. There is no name to type
    for "no workspace", which is why the column is blank padding rather than a
    placeholder: a marker there would name something `--workspace` cannot be
    asked for."""
    # The fixture's schema declares requirement and decision only, so this is a
    # requirement -- and it sits directly in items/, outside every workspace
    # folder, which is how an item ends up in no workspace under
    # `item_layout: workspace`.
    (workspace_project / "items" / "can.md").write_text(
        "---\nid: REQ-CAN-001\ntype: requirement\n"
        "text: The CAN bus shall carry 1 Mbit/s.\n---\n",
        encoding="utf-8",
    )
    cfg = str(workspace_project / "refdes-project.yaml")

    # Filtered to just that item it is the whole listing, and no row in it has a
    # workspace, so there is no column to leave blank -- the same suppression
    # the board column already does (a row where nothing has a board prints no
    # board column), which is what keeps a stray space out of the title.
    assert _steady_state_ls(capsys, cfg, "--file", "items/can.md") == (
        "REQ-CAN-001  requirement  The CAN bus shall carry 1 Mbit/s.\n"
    )

    # In the full listing it is a row like any other: the workspace column is
    # blank padding of the full column width, so the title still starts in the
    # one place it starts everywhere else.
    rows = {
        line.split()[0]: line
        for line in _steady_state_ls(capsys, cfg).splitlines()
    }
    assert rows["REQ-CAN-001"] == (
        "REQ-CAN-001   requirement                      The CAN bus shall carry 1 Mbit/s."
    )

    # Every declared workspace excludes it, and an empty --workspace is a no-op
    # that lists everything rather than selecting the no-workspace items.
    for name in ("platform", "product-a", "product-b"):
        assert "REQ-CAN-001" not in _steady_state_ls(capsys, cfg, "--workspace", name)
    listed = _steady_state_ls(capsys, cfg, "--workspace", "")
    assert "REQ-CAN-001" in listed and "REQ-PLAT-001" in listed


def test_ls_help_says_the_workspace_column_is_conditional(capsys):
    """The column exists only on a project that declares `workspaces:`, so the
    help that advertises it has to say so -- otherwise "where's the workspace
    column?" is the next question, and the answer ("your project declares no
    workspaces:") is nowhere near `ls --help`."""
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(["ls", "--help"])
    assert excinfo.value.code == 0
    help_text = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "the workspace column only on a project that declares workspaces:" in help_text


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
