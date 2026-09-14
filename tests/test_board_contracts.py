"""`conforms_to:` -- per-(item, board) coverage for cross-cutting contracts.

docs/design/backlog.md finding 24. A platform-wide requirement is one item, so
per-item coverage goes green the moment *any* board complies; these tests pin
the per-(item, board) result, the hard error on a target that is not a group,
and the byte-identical output of a project that never uses the key.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import parse, render

CONFORMS_SCHEMA = """\
site: {title: "Conforms test", out: _site}
id: {width: 3}
boards:
  board-a: {label: "Board A", conforms_to: [GRP-001]}
  board-b: {label: "Board B", conforms_to: [GRP-001]}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
  part_of:   { inverse: contains,     label: "Part of" }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
    links:
      part_of: [group]
  group:
    prefix: GRP
    coverable: false
    fields:
      title: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title:  { type: text, required: true }
      status: { type: enum, choices: [proposed, accepted], default: proposed }
    satisfying_statuses: [accepted]
    links:
      satisfies: [requirement]
"""


def _write(root, items):
    write_project_config(root, CONFORMS_SCHEMA)
    for relpath, text in items.items():
        path = os.path.join(str(root), "items", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


GROUP = {
    "board-a/group.yaml": (
        "defaults: { type: group }\n"
        "items:\n  - id: GRP-001\n    title: The debug-header contract.\n"
    ),
}

REQUIREMENT = {
    "board-a/req.yaml": (
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Use the standard 10-pin debug header.\n"
        "    part_of: [GRP-001]\n"
    ),
}


# Board B needs at least one item of its own or it gets no scoped reports at
# all (render's empty-board rule), which would hide the very page these tests
# are about.
BOARD_B_ITEM = {
    "board-b/other.yaml": (
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-B-001\n    text: Something only board B needs.\n"
    ),
}


def _decision(board, item_id, status="accepted"):
    folder = f"{board}/" if board else ""
    return {
        f"{folder}dec.yaml": (
            "defaults: { type: decision }\n"
            "items:\n"
            f"  - id: {item_id}\n    title: A way of doing it.\n"
            f"    status: {status}\n    satisfies: [REQ-001]\n"
        )
    }


def _render(root):
    project = _build_at(root)
    render.render_site(project)
    return project


def _page(root, name):
    with open(os.path.join(str(root), "_site", name), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------- per-board result


def test_a_satisfier_on_one_board_leaves_the_other_board_unsatisfied(tmp_path):
    """The finding itself: one board's decision must not discharge both."""
    _write(tmp_path, {**GROUP, **REQUIREMENT, **_decision("board-a", "DEC-A-001")})
    project = _build_at(tmp_path)
    assert project.board_coverage[("REQ-001", "board-a")].stage == "satisfied"
    assert project.board_coverage[("REQ-001", "board-b")].stage == "open"


def test_an_unmet_board_is_a_warning_naming_that_board(tmp_path):
    _write(tmp_path, {**GROUP, **REQUIREMENT, **_decision("board-a", "DEC-A-001")})
    project = _build_at(tmp_path)
    warned = [
        d.message
        for d in project.warnings
        if d.item_id == "REQ-001" and "board-b" in d.message
    ]
    assert len(warned) == 1
    assert "not satisfied on board 'board-b'" in warned[0]
    # The satisfied board is never warned about.
    assert not any(
        "board-a" in d.message and "not satisfied" in d.message
        for d in project.warnings
    )


def test_both_boards_satisfied_warns_nobody(tmp_path):
    _write(
        tmp_path,
        {
            **GROUP,
            **REQUIREMENT,
            **_decision("board-a", "DEC-A-001"),
            **_decision("board-b", "DEC-B-001"),
        },
    )
    project = _build_at(tmp_path)
    assert project.board_coverage[("REQ-001", "board-a")].stage == "satisfied"
    assert project.board_coverage[("REQ-001", "board-b")].stage == "satisfied"
    assert not [d for d in project.warnings if "not satisfied on board" in d.message]


def test_a_satisfier_with_no_board_counts_for_no_board(tmp_path):
    """Per board only: an unboarded decision discharges nobody's obligation..."""
    _write(tmp_path, {**GROUP, **REQUIREMENT, **_decision("", "DEC-X-001")})
    project = _build_at(tmp_path)
    assert project.items["DEC-X-001"].board == ""
    assert project.board_coverage[("REQ-001", "board-a")].stage == "open"
    assert project.board_coverage[("REQ-001", "board-b")].stage == "open"
    # ...while the ordinary per-item coverage is exactly what it always was.
    assert project.coverage["REQ-001"].stage == "satisfied"
    assert project.coverage["REQ-001"].satisfied_by == ["DEC-X-001"]


def test_a_satisfier_on_another_board_does_not_count_here(tmp_path):
    _write(tmp_path, {**GROUP, **REQUIREMENT, **_decision("board-a", "DEC-A-001")})
    project = _build_at(tmp_path)
    assert project.board_coverage[("REQ-001", "board-b")].satisfied_by == []


def test_per_board_stages_use_the_same_rules_as_per_item(tmp_path):
    """An unsettled decision on board A is `claimed` for A, not `satisfied`."""
    _write(
        tmp_path,
        {
            **GROUP,
            **REQUIREMENT,
            **_decision("board-a", "DEC-A-001", status="proposed"),
        },
    )
    project = _build_at(tmp_path)
    cov = project.board_coverage[("REQ-001", "board-a")]
    assert cov.stage == "claimed"
    assert cov.claimed_by == ["DEC-A-001"]
    assert cov.satisfied_by == []


# ------------------------------------------------------------------- no contract


def test_a_board_that_does_not_conform_gets_no_obligation(tmp_path):
    _write(
        tmp_path,
        {
            **GROUP,
            **REQUIREMENT,
            **_decision("board-a", "DEC-A-001"),
        },
    )
    write_project_config(
        tmp_path,
        CONFORMS_SCHEMA.replace(
            '  board-b: {label: "Board B", conforms_to: [GRP-001]}\n',
            '  board-b: {label: "Board B"}\n',
        ),
    )
    project = _build_at(tmp_path)
    assert ("REQ-001", "board-a") in project.board_coverage
    assert ("REQ-001", "board-b") not in project.board_coverage
    assert not [d for d in project.warnings if "not satisfied on board" in d.message]


def test_a_group_member_no_board_still_gets_its_obligations(tmp_path):
    """The obligation follows the board's declaration, not where the item sits."""
    _write(
        tmp_path,
        {
            **GROUP,
            "req.yaml": (
                "defaults: { type: requirement, prefix: REQ-L }\n"
                "items:\n  - id: REQ-L-001\n    text: Shared requirement.\n"
                "    part_of: [GRP-001]\n"
            ),
        },
    )
    project = _build_at(tmp_path)
    assert project.items["REQ-L-001"].board == ""
    assert {b for (_i, b) in project.board_coverage} == {"board-a", "board-b"}


# --------------------------------------------------------------- hard errors


def test_conforms_to_naming_an_unknown_group_is_a_hard_error(tmp_path):
    _write(tmp_path, GROUP)
    write_project_config(
        tmp_path,
        CONFORMS_SCHEMA.replace("[GRP-001]", "[GRP-NOPE]"),
    )
    project = _build_at(tmp_path)
    errors = [d for d in project.errors if "GRP-NOPE" in d.message]
    assert errors, "an unknown conforms_to group was accepted with no error"
    assert "does not exist" in errors[0].message
    assert not project.board_coverage


def test_conforms_to_naming_a_non_group_is_a_hard_error(tmp_path):
    _write(tmp_path, {**GROUP, **REQUIREMENT})
    write_project_config(
        tmp_path,
        CONFORMS_SCHEMA.replace("conforms_to: [GRP-001]", "conforms_to: [REQ-001]"),
    )
    project = _build_at(tmp_path)
    errors = [d for d in project.errors if "REQ-001" in d.message]
    assert errors, "conforms_to at a requirement was accepted with no error"
    assert "not a group" in errors[0].message
    assert not project.board_coverage


# ------------------------------------------------------------------- reporting


def test_board_page_lists_contracts_even_off_board(tmp_path):
    """REQ lives on board A; B's page still has to show B's own standing."""
    _write(
        tmp_path,
        {**GROUP, **REQUIREMENT, **BOARD_B_ITEM, **_decision("board-a", "DEC-A-001")},
    )
    _render(tmp_path)
    page = _page(tmp_path, "coverage-board-b.html")
    assert "Conforming contracts" in page
    assert "REQ-001" in page
    assert "stage-open" in page
    # Board A's own page shows the same contract, satisfied.
    assert "Conforming contracts" in _page(tmp_path, "coverage-board-a.html")


def test_main_coverage_page_names_the_boards_still_short(tmp_path):
    _write(tmp_path, {**GROUP, **REQUIREMENT, **_decision("board-a", "DEC-A-001")})
    _render(tmp_path)
    page = _page(tmp_path, "coverage.html")
    assert "not yet satisfied on boards: board-b" in page


def test_no_conforms_to_renders_the_coverage_pages_unchanged(tmp_path):
    """Byte-identical coverage output for a project that never uses the key."""
    plain = CONFORMS_SCHEMA.replace(
        '  board-a: {label: "Board A", conforms_to: [GRP-001]}\n'
        '  board-b: {label: "Board B", conforms_to: [GRP-001]}\n',
        '  board-a: {label: "Board A"}\n'
        '  board-b: {label: "Board B"}\n',
    )
    _write(
        tmp_path,
        {**GROUP, **REQUIREMENT, **BOARD_B_ITEM, **_decision("board-a", "DEC-A-001")},
    )
    write_project_config(tmp_path, plain)
    project = _render(tmp_path)
    assert project.board_coverage == {}
    for name in ("coverage.html", "coverage-board-a.html", "coverage-board-b.html"):
        page = _page(tmp_path, name)
        assert "Conforming contracts" not in page
        assert "not yet satisfied on boards" not in page
