"""`includes:` — shared items displayed on the boards that include them.

docs/design/backlog.md finding 33. A component used by two boards lives in
`items/shared/` and belongs to neither, so it was absent from every board's
pages. A board now declares `includes: [GRP-...]`; the group's members are
DISPLAYED and LISTED on that board's scoped pages, labelled shared, and are
counted by nothing: summary tallies, coverage, the release gate, the seals,
the drift manifest and `item.board` all keep seeing only owned items.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import build as build_mod
from refdes import nav as nav_mod
from refdes import render
from refdes.schema import SchemaError

INCLUDES_SCHEMA = """\
site: {title: "Includes test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  board-a: {label: "Board A", includes: [GRP-COMMON]}
  board-b: {label: "Board B", includes: [GRP-COMMON]}
link_types:
  part_of: { inverse: contains, label: "Part of" }
types:
  component:
    prefix: CMP
    fields:
      title:       { type: text, required: true }
      part_number: { type: text }
      datasheets:  { type: citations }
    links:
      part_of: [group]
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
  log:
    prefix: LOG
    append_only: true
    fields:
      date:    { type: date }
      summary: { type: text }
    links:
      part_of: [group]
"""

ITEMS = {
    # The finding itself: parts shared by both boards, in no board's folder.
    "shared/cmp-s.md": """\
---
id: CMP-S-001
type: component
title: The LDO both boards buy.
part_number: LM358
part_of: [GRP-COMMON]
datasheets:
  - path: "https://example.com/lm358.pdf"
---
""",
    "shared/req-s.md": """\
---
id: REQ-S-001
type: requirement
text: A shared requirement, coverable, counted by no board here.
part_of: [GRP-COMMON]
---
""",
    "shared/log-s.md": """\
---
id: LOG-S-001
type: log
date: 2026-01-02
summary: A shared log entry.
part_of: [GRP-COMMON]
---
""",
    # Board A owns the group and one part of its own.
    "board-a/group.md": """\
---
id: GRP-COMMON
type: group
title: Parts common to both boards.
---
""",
    "board-a/cmp-a.md": """\
---
id: CMP-A-001
type: component
title: Board A's own part.
part_number: STM32G474
---
""",
    # Board B owns nothing at all: its only parts are included ones.
}


def _write(root, config=INCLUDES_SCHEMA, items=ITEMS):
    write_project_config(root, config)
    for relpath, text in items.items():
        path = os.path.join(str(root), "items", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _render(root):
    project = _build_at(root)
    render.render_site(project)
    return project


def _page(root, name):
    return _read(os.path.join(str(root), "_site", name))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ displayed


def test_included_member_appears_on_the_board_parts_page_labelled_shared(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    page = _page(tmp_path, "parts-board-a.html")
    assert "CMP-S-001" in page
    assert "shared, via GRP-COMMON" in page
    # The board's own part is listed without the label.
    assert "CMP-A-001" in page
    assert page.count("shared, via") == 1


def test_included_member_appears_on_the_document_page_labelled_shared(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    page = _page(tmp_path, "document-board-a.html")
    assert "CMP-S-001" in page
    assert "shared, via GRP-COMMON" in page


def test_included_members_appear_on_the_references_and_log_pages(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    refs = _page(tmp_path, "references-board-a.html")
    assert "CMP-S-001" in refs
    assert "shared, via GRP-COMMON" in refs
    log = _page(tmp_path, "log-board-a.html")
    assert "LOG-S-001" in log
    assert "shared, via GRP-COMMON" in log


def test_index_block_lists_included_member_labelled_shared(tmp_path):
    _write(tmp_path)
    pages = tmp_path / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "index.md").write_text(
        '# Overview\n\n{{index by="part_number" type="component" board="board-a"}}\n',
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    page = next(p for p in project.pages if p.slug == "index")
    assert not project.errors
    assert "CMP-S-001" in page.body_html
    assert "shared, via GRP-COMMON" in page.body_html
    assert "CMP-A-001" in page.body_html


# ---------------------------------------------------------------- not counted


def test_included_member_is_not_counted_in_summary_numbers(tmp_path):
    _write(tmp_path)
    project = _build_at(tmp_path)
    # Board A owns exactly GRP-COMMON and CMP-A-001; the three shared items
    # appear on its pages but are not its numbers.
    assert render.summary_payload(project, board="board-a")["item_count"] == 2
    # Board B owns nothing: its summary exists (it has a page set now) and
    # counts zero.
    assert render.summary_payload(project, board="board-b")["item_count"] == 0


def test_included_member_is_not_in_board_coverage_or_gate(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    project = _build_at(tmp_path)
    # The shared requirement is coverable, so it is in the project-wide
    # coverage -- but it is no board's row on a board coverage page.
    assert "REQ-S-001" in project.coverage
    assert [i.id for i, _cov in render._coverage_rows(project, board="board-a")] == []
    assert 'data-ref="REQ-S-001"' not in _page(tmp_path, "coverage-board-a.html")
    assert 'data-ref="REQ-S-001"' in _page(tmp_path, "coverage.html")
    # No conforms_to:, so no per-board obligations were created by includes:.
    assert project.board_coverage == {}


def test_project_wide_pages_carry_no_shared_labels(tmp_path):
    """Display-only scoping is per board; the project-wide pages are exactly
    what they were, with no shared labels anywhere."""
    _write(tmp_path)
    _render(tmp_path)
    for name in ("parts.html", "document.html", "log.html", "references.html"):
        assert "shared, via" not in _page(tmp_path, name)


# ------------------------------------------------------- pages for included-only


def test_board_with_only_included_parts_gets_a_parts_page(tmp_path):
    """Board B owns nothing; before `includes:` it got no page set at all."""
    _write(tmp_path)
    _render(tmp_path)
    assert "parts" in nav_mod.scope_reports(_build_at(tmp_path), board="board-b")
    page = _page(tmp_path, "parts-board-b.html")
    assert "CMP-S-001" in page
    assert "shared, via GRP-COMMON" in page


# ----------------------------------------------------------------- hard errors


def test_includes_as_a_bare_string_is_one_error_not_one_per_letter(tmp_path):
    _write(tmp_path, INCLUDES_SCHEMA.replace("includes: [GRP-COMMON]", "includes: GRP-COMMON"))
    with pytest.raises(SchemaError) as excinfo:
        _build_at(tmp_path)
    message = str(excinfo.value)
    assert "board-a" in message
    assert "must be a list" in message
    assert "does not exist" not in message


def test_includes_naming_an_unknown_group_is_a_hard_error(tmp_path):
    _write(tmp_path, INCLUDES_SCHEMA.replace("[GRP-COMMON]", "[GRP-NOPE]"))
    project = _build_at(tmp_path)
    errors = [d for d in project.errors if "GRP-NOPE" in d.message]
    assert errors, "an unknown includes: group was accepted with no error"
    assert "does not exist" in errors[0].message


def test_includes_naming_a_non_group_is_a_hard_error(tmp_path):
    _write(tmp_path, INCLUDES_SCHEMA.replace("includes: [GRP-COMMON]", "includes: [CMP-A-001]"))
    project = _build_at(tmp_path)
    errors = [d for d in project.errors if "CMP-A-001" in d.message]
    assert errors, "includes: at a component was accepted with no error"
    assert "not a group" in errors[0].message


# ------------------------------------------------- membership stays untouched


def test_manifest_seals_and_item_board_are_unchanged(tmp_path):
    """An included item keeps its own (empty) board: no manifest entry, and
    its seal lives in the unboarded file, not the including board's."""
    _write(tmp_path)
    project = _build_at(tmp_path)
    build_mod.build(project, seal_write=True)
    for item_id in ("CMP-S-001", "REQ-S-001", "LOG-S-001"):
        assert project.item_by_id(item_id).board == ""
    refdes_dir = os.path.join(str(tmp_path), ".refdes")
    manifest = os.path.join(refdes_dir, "boards.yaml")
    text = _read(manifest) if os.path.isfile(manifest) else ""
    assert "CMP-S-001" not in text
    assert "LOG-S-001" not in text
    seal = _read(os.path.join(refdes_dir, "log-seal.yaml"))
    assert "LOG-S-001" in seal
    board_seal = os.path.join(refdes_dir, "log-seal-board-a.yaml")
    assert not os.path.isfile(board_seal) or "LOG-S-001" not in _read(board_seal)
