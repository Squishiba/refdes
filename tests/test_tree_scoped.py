"""Scoped trees and the {{tree}} block (finding 37, chunk 2).

`tree-<board>.html` pages join the scoped report set, board pages show the
board's own items under the chunk-1 home rule plus the groups the board
`includes:` (finding 33) labelled shared, and the `{{tree}}` block joins
the block family with board/workspace/depth parameters. `via` is
deliberately NOT a tree parameter: nesting by an arbitrary relation is
what `{{cascade}}` does; the tree's identity is the containment spine --
so `via=` must surface as an unknown-parameter check error.
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_at

from refdes import render
from refdes import tree as tree_mod

SCHEMA = """\
site: {title: "Scoped tree test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  board-a: {label: "Board A"}
  board-b: {label: "Board B", includes: [GRP-T-001]}
  board-c: {label: "Board C"}
link_types:
  part_of: { inverse: contains, label: "Part of" }
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
    links:
      part_of: [group]
"""

ITEMS = {
    "shared/grp-two.md": """\
---
id: GRP-T-001
type: group
title: Shared group included by board B.
---
""",
    "board-a/req-ta.md": """\
---
id: REQ-TA-001
type: requirement
text: Owned by board A, member of the shared group.
part_of: [GRP-T-001]
---
""",
    "board-a/req-ta2.md": """\
---
id: REQ-TA-002
type: requirement
text: Also owned by board A, also in the shared group.
part_of: [GRP-T-001]
---
""",
    "board-b/req-b1.md": """\
---
id: REQ-B-001
type: requirement
text: Owned by board B, no group.
---
""",
}


def _write(root, items=ITEMS):
    write_project_config(root, SCHEMA)
    for relpath, text in items.items():
        path = os.path.join(str(root), "items", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _render(root):
    project = _build_at(root)
    render.render_site(project)
    return project


def _site_file(root, name):
    with open(os.path.join(str(root), "_site", name), encoding="utf-8") as fh:
        return fh.read()


def _page_with(root, directive):
    pages = os.path.join(str(root), "pages")
    os.makedirs(pages, exist_ok=True)
    with open(os.path.join(pages, "index.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Overview\n\n{directive}\n")


# ------------------------------------------------------------- {{tree}} block


def test_tree_block_renders_in_a_page(tmp_path):
    _write(tmp_path)
    _page_with(tmp_path, "{{tree}}")
    project = _build_at(tmp_path)
    assert not project.errors
    page = next(p for p in project.pages if p.slug == "index")
    assert '<ul class="tree">' in page.body_html
    assert "REQ-TA-001" in page.body_html


def test_tree_block_bad_parameter_is_check_error_with_file_and_line(tmp_path):
    _write(tmp_path)
    _page_with(tmp_path, '{{tree via="part_of"}}')
    project = _build_at(tmp_path)
    diag = [d for d in project.errors if "unknown parameter" in d.message]
    assert diag, [d.message for d in project.errors]
    assert "via" in diag[0].message
    assert diag[0].file and diag[0].file.endswith("index.md")
    assert diag[0].line == 3


def test_tree_block_unknown_board_is_check_error(tmp_path):
    _write(tmp_path)
    _page_with(tmp_path, '{{tree board="board-z"}}')
    project = _build_at(tmp_path)
    assert any("board-z" in d.message for d in project.errors)


def test_tree_block_depth_parameter_is_respected(tmp_path):
    _write(tmp_path)
    _page_with(tmp_path, '{{tree depth="1"}}')
    project = _build_at(tmp_path)
    assert not project.errors
    page = next(p for p in project.pages if p.slug == "index")
    seg = page.body_html.split('<ul class="tree">')[1]
    assert "<details><summary>" in seg  # depth 1: nothing opened
    assert "<details open" not in seg


def test_tree_block_board_scope_narrows_the_forest(tmp_path):
    _write(tmp_path)
    _page_with(tmp_path, '{{tree board="board-b"}}')
    project = _build_at(tmp_path)
    assert not project.errors
    page = next(p for p in project.pages if p.slug == "index")
    assert "REQ-B-001" in page.body_html
    assert "REQ-TA-001" in page.body_html  # shared in via includes
    assert "GRP-T-001" in page.body_html


# ------------------------------------------------------------ scoped pages


def test_tree_board_pages_exist_and_are_scoped(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    a = _site_file(tmp_path, "tree-board-a.html")
    assert "REQ-TA-001" in a
    b = _site_file(tmp_path, "tree-board-b.html")
    assert "REQ-B-001" in b
    assert "REQ-TA-001" in b  # included through includes
    assert "shared" in b  # the finding 33 label


def test_board_node_count_tallies_owned_only(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    b = _site_file(tmp_path, "tree-board-b.html")
    assert "1 own, 2 shared" in b  # REQ-B-001 owns; two GRP-T-001 members shared
    assert '<span class="count">3</span>' not in b
    # A board with nothing shared keeps the plain count.
    a = _site_file(tmp_path, "tree-board-a.html")
    assert '<span class="count">2</span>' in a
    assert " own, " not in a
    # The project-wide tree keeps its counts as they are.
    whole = _site_file(tmp_path, "tree.html")
    assert " own, " not in whole


def test_scoped_intro_opens_with_the_scope(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    b = _site_file(tmp_path, "tree-board-b.html")
    assert "Every item Board B displays" in b
    assert "Every item in the project" not in b
    whole = _site_file(tmp_path, "tree.html")
    assert "Every item in the project" in whole


def test_board_with_nothing_in_scope_gets_no_tree_page(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    assert not os.path.exists(
        os.path.join(str(tmp_path), "_site", "tree-board-c.html")
    )


def test_tree_nav_entries_for_scopes(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    a = _site_file(tmp_path, "summary-board-a.html")
    assert 'href="tree-board-a.html"' in a
    assert not os.path.exists(
        os.path.join(str(tmp_path), "_site", "tree-board-c.html")
    )


# ------------------------------------------------------- scope invariant


def test_scope_invariant_every_displayed_item_expanded_once(tmp_path):
    from refdes import boards as boards_mod

    _write(tmp_path)
    project = _render(tmp_path)
    for board_key in project.boards:
        included = boards_mod.included_map(project, board_key)
        displayed = [
            i for i in project.local_items
            if boards_mod.displays(i, board_key, included)
        ]
        forest = tree_mod.build_forest(project, board=board_key)
        expanded = [i.id for i in forest.expanded]
        assert sorted(expanded) == sorted(i.id for i in displayed)
        assert len(expanded) == len(set(expanded))
