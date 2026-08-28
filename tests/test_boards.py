"""boards -- and: board drift.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import BOARD_CONFIG, _build_at, _project

from refdes import boards as boards_mod
from refdes import build as build_mod
from refdes import nav as nav_mod
from refdes import parse, render
from refdes.schema import SchemaError, load_project


def test_board_is_derived_from_the_first_path_segment_under_items(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-A-001"].board == "board-a"
    assert project.items["REQ-B-001"].board == "board-b"


def test_unregistered_path_segment_gets_no_board(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-S-001"].board == ""


def test_unregistered_path_segment_warns_that_it_has_no_board(board_project):
    project = _build_at(board_project)
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-S-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1
    message = warned[0].message
    assert "'shared' is not in the boards: registry" in message
    # Both remedies named: the file's defaults:, or moving it under a real board.
    assert "board: <name>" in message
    assert "items/<registered-board>/" in message


def test_item_directly_under_items_warns_that_it_has_no_board(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir(parents=True, exist_ok=True)
    (items / "loose.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-L }\n"
        "items:\n  - id: REQ-L-001\n    text: Sits directly in items/, no board folder.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-L-001"].board == ""
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-L-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1
    assert "outside any board folder" in warned[0].message


def test_item_level_board_override_beats_the_path(board_project):
    project = _build_at(board_project)
    assert project.items["REQ-S-002"].board == "board-a"


def test_item_level_board_override_does_not_warn_about_no_board(board_project):
    project = _build_at(board_project)
    assert not any(
        d.item_id == "REQ-S-002" and d.message.startswith("no board")
        for d in project.warnings
    )


def test_explicit_board_override_must_be_registered(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BOARD_CONFIG, encoding="utf-8")
    items = tmp_path / "items" / "shared"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-Z }\n"
        "items:\n  - id: REQ-Z-001\n    board: nonexistent\n    text: Bad board.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert any("nonexistent" in d.message and "not declared" in d.message for d in project.errors)


def test_token_lint_warns_on_prefix_mismatch(board_project):
    project = _build_at(board_project)
    warned = {d.item_id for d in project.warnings if "does not contain that token" in d.message}
    assert "REQ-WRONG-001" in warned
    assert "REQ-A-001" not in warned
    assert "REQ-B-001" not in warned


def test_token_lint_is_silent_without_a_declared_token(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  board-a: { label: Board A }\n"  # no token
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "board-a"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-ANYTHING }\n"
        "items:\n  - id: REQ-ANYTHING-001\n    text: No token declared, nothing to check.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert not any("does not contain that token" in d.message for d in project.warnings)


def test_boards_registry_absent_is_inert(tmp_path):
    """No `boards:` block: every item's board stays empty, matching today.

    A dedicated, standalone fixture on purpose -- not a copy of this repo's own
    `refdes.yaml`, and not built from `_project()`, because that config now
    registers real boards (see test_real_project_registers_boards_and_renders_
    board_pages below). This is the regression guarantee that a project with no
    `boards:` block at all stays completely unaffected, kept independent of
    whatever the sample project does.
    """
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.boards == {}
    assert project.items["REQ-001"].board == ""
    out = render.render_site(project)
    assert not any(name.startswith("document-") for name in os.listdir(out))
    payload = render.items_json(project)
    assert "boards" not in payload
    assert "board" not in payload["items"][0]


def test_real_project_registers_boards_and_renders_board_pages(tmp_path):
    """This repo's own project now demonstrates the boards: registry itself.

    Board A is the existing items, retrofitted with a `board: board-a` default
    (their folders predate the registry, so path-based resolution alone would
    not reach them). Board B is a small, separate items/board-b/ tree that
    resolves purely from its folder name, with no override needed.
    """
    project = _project()
    assert set(project.boards) == {"board-a", "board-b"}
    assert project.items["REQ-PWR-001"].board == "board-a"
    assert project.items["REQ-B-PWR-001"].board == "board-b"
    project.out_dir = str(tmp_path / "_site")  # absolute: render outside the repo
    out = render.render_site(project)
    for board in ("board-a", "board-b"):
        for page in ("document", "coverage", "summary"):
            assert os.path.isfile(os.path.join(out, f"{page}-{board}.html"))
    # Board A has the design log; Board B has none, so no log-board-b.html is
    # written -- the nav never linked one, and an empty report page nothing
    # points at is not a page.
    assert os.path.isfile(os.path.join(out, "log-board-a.html"))
    assert not os.path.exists(os.path.join(out, "log-board-b.html"))
    payload = render.items_json(project)
    assert set(payload["boards"]) == {"board-a", "board-b"}


def _nav_hrefs(nodes):
    out = []
    for node in nodes:
        if node.href:
            out.append(node.href)
        out.extend(_nav_hrefs(node.children))
    return out


@pytest.fixture
def empty_board_project(tmp_path):
    """A registry declaring two boards where only one has any items."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n"
        "  board-a: { label: Board A }\n"
        "  board-z: { label: Board Z }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "board-a"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: The only item in the project.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_board_with_no_items_gets_no_report_pages(empty_board_project, tmp_path):
    """A registered but unpopulated board used to get a full set of six report
    pages describing nothing -- and the nav linked only three of them, so the
    other three were unreachable as well as empty. The mirror image of the
    boardless-items bug: pages with no items behind them."""
    project = _build_at(empty_board_project)
    project.out_dir = str(tmp_path / "out")
    out = render.render_site(project)

    for page in ("document", "coverage", "summary", "log", "references", "parts"):
        assert not os.path.exists(os.path.join(out, f"{page}-board-z.html")), page
    # The populated board is unaffected.
    assert os.path.isfile(os.path.join(out, "coverage-board-a.html"))


def test_an_empty_board_gets_no_nav_group_either(empty_board_project):
    project = _build_at(empty_board_project)
    tree = nav_mod.build_nav(project, dashboard_href="index.html")
    labels = [n.label for n in tree]
    assert "Board A" in labels
    assert "Board Z" not in labels


def test_every_report_the_nav_links_is_written_and_vice_versa(
    empty_board_project, tmp_path
):
    """The invariant nav.py's docstring claims and previously did not hold in
    either direction. Both sides now come from `nav.scope_reports`, so they
    cannot drift apart again."""
    project = _build_at(empty_board_project)
    project.out_dir = str(tmp_path / "out")
    out = render.render_site(project)

    linked = {
        h for h in _nav_hrefs(nav_mod.build_nav(project, dashboard_href="index.html"))
        if h.endswith(".html")
    }
    on_disk = {
        name for name in os.listdir(out)
        if name.endswith(".html") and "-" in name and not name.startswith("req-")
    }
    scoped_links = {h for h in linked if "-" in h and not h.startswith("req-")}
    assert scoped_links == on_disk, (scoped_links, on_disk)


def test_a_populated_board_with_no_log_gets_no_log_page(tmp_path):
    """Not only the empty-board case: a board that has items but no log
    entries was still given a `log-<board>.html` the nav declined to link."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  board-a: { label: Board A }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
        "  log:\n    prefix: LOG\n    append_only: true\n    fields:\n"
        "      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "board-a"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n  - id: REQ-001\n    text: No log anywhere in this project.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    project.out_dir = str(tmp_path / "out")
    out = render.render_site(project)
    assert os.path.isfile(os.path.join(out, "summary-board-a.html"))
    assert not os.path.exists(os.path.join(out, "log-board-a.html"))


def test_board_path_alias_matches_a_differently_named_folder(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n  board-a: { label: Board A, path: brdA }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items" / "brdA"
    items.mkdir(parents=True)
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ-A }\n"
        "items:\n  - id: REQ-A-001\n    text: Folder spelled differently from the key.\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-A-001"].board == "board-a"


def test_boards_registry_rejects_duplicate_path_segments(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "boards:\n"
        "  board-a: { label: A, path: shared }\n"
        "  board-b: { label: B, path: shared }\n"
        "types:\n  requirement: { prefix: REQ }\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="items/shared/"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


# --------------------------------------------------------------- board drift


def test_first_build_records_the_manifest_without_warning(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    assert not project.board_moves
    manifest = boards_mod.load_manifest(project)
    assert manifest["boards"]["REQ-A-001"] == "board-a"


def test_moving_a_file_to_another_board_warns_but_does_not_error(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)  # records the manifest

    # Move REQ-A-001's file under board-b.
    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )

    project2 = _build_at(board_project)
    assert project2.items["REQ-A-001"].board == "board-b"
    assert ("REQ-A-001", "board-a", "board-b") in project2.board_moves
    assert not project2.errors
    assert any(
        "moved from board" in d.message and d.item_id == "REQ-A-001"
        for d in project2.warnings
    )
    # Not accepted: the manifest still remembers the old board.
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-a"


def test_accept_board_move_updates_the_manifest_and_silences_future_builds(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)

    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-b"

    project3 = _build_at(board_project)
    build_mod.build(project3, seal_write=True)
    assert not project3.board_moves


def test_audit_reports_board_moves(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a" / "r.yaml").rename(
        board_project / "items" / "board-b" / "moved.yaml"
    )
    project2 = load_project(config_path=str(board_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "board-a", "board-b") in project2.board_moves


def test_a_move_off_the_registry_is_drift_too(board_project):
    """Finding 17: leaving the registry entirely is the drift most worth catching."""
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)  # records REQ-A-001 -> board-a

    # Rename board-a's folder to something the registry doesn't know -- same
    # repro shape as finding 16: the item now resolves to no board at all.
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )

    project2 = _build_at(board_project)
    assert project2.items["REQ-A-001"].board == ""
    assert ("REQ-A-001", "board-a", "") in project2.board_moves
    assert not project2.errors
    assert any(
        d.item_id == "REQ-A-001"
        and "was on board 'board-a' and now resolves to no board" in d.message
        for d in project2.warnings
    )
    # Not accepted: the manifest still remembers the old board.
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == "board-a"


def test_accept_board_move_off_the_registry_records_the_empty_board(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )

    project2 = _build_at(board_project)
    build_mod.build(project2, seal_write=True, accept_board_move=True)
    assert boards_mod.load_manifest(project2)["boards"]["REQ-A-001"] == ""

    project3 = _build_at(board_project)
    assert not project3.board_moves  # drift silenced: recorded "" matches resolved ""


def test_audit_reports_a_board_move_off_the_registry(board_project):
    project = _build_at(board_project)
    build_mod.build(project, seal_write=True)
    (board_project / "items" / "board-a").rename(
        board_project / "items" / "board-a-renamed"
    )
    project2 = load_project(config_path=str(board_project / "refdes.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)  # audit never writes
    assert ("REQ-A-001", "board-a", "") in project2.board_moves


def test_item_that_never_had_a_board_does_not_trigger_drift(board_project):
    """REQ-S-001 lives in an unregistered folder from its very first build: it is
    never in the manifest, so verify() must stay silent about it. Finding 16's
    diagnostic covers it instead, and the two must not double up on one file."""
    seed = _build_at(board_project)
    build_mod.build(seed, seal_write=True)
    assert "REQ-S-001" not in boards_mod.load_manifest(seed)

    project = _build_at(board_project)
    assert not any(item_id == "REQ-S-001" for item_id, _, _ in project.board_moves)
    warned = [
        d for d in project.warnings
        if d.item_id == "REQ-S-001" and d.message.startswith("no board")
    ]
    assert len(warned) == 1
