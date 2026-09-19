"""The project tree page (finding 37, chunk 1).

The containment-spine forest -- workspace, board, `part_of` group, item --
with expand-once-reference-elsewhere for multi-parent items, the mandatory
`Project-wide` bucket, and the mechanical totality invariant: the number of
expanded nodes equals `len(project.local_items)`, on every fixture.
"""

from __future__ import annotations

import os

from conftest import write_project_config
from helpers import _build_at

from refdes import render
from refdes import tree as tree_mod

TREE_SCHEMA = """\
site: {title: "Tree test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  board-a: {label: "Board A"}
  board-b: {label: "Board B"}
link_types:
  part_of: { inverse: contains, label: "Part of" }
types:
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
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
    links:
      part_of: [group]
"""

TREE_ITEMS = {
    "board-a/grp-a.md": """\
---
id: GRP-A-001
type: group
title: Group A on board A.
---
""",
    "board-a/grp-b.md": """\
---
id: GRP-B-001
type: group
title: Group B on board A.
---
""",
    # Multi-parent item: primary parent is GRP-A-001 (smallest id), reference
    # leaf under GRP-B-001.
    "board-a/cmp-multi.md": """\
---
id: CMP-M-001
type: component
title: Filed under both groups.
part_of: [GRP-B-001, GRP-A-001]
---
""",
    # Board item with no group: sits directly under Board A.
    "board-a/cmp-own.md": """\
---
id: CMP-A-001
type: component
title: Board A's own, no group.
---
""",
    # A part_of cycle between two groups: neither is reachable from a board,
    # so the smallest-id member is promoted to a forest root.
    "board-a/grp-cy1.md": """\
---
id: GRP-CY-001
type: group
title: Cycle group one.
part_of: [GRP-CY-002]
---
""",
    "board-a/grp-cy2.md": """\
---
id: GRP-CY-002
type: group
title: Cycle group two.
part_of: [GRP-CY-001]
---
""",
    # No board and no group: must land in Project-wide, never dropped.
    "shared/cmp-plain.md": """\
---
id: CMP-S-001
type: component
title: Shared part with no board and no group.
---
""",
}


def _write(root, config=TREE_SCHEMA, items=TREE_ITEMS):
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


def _page(root, name="tree.html"):
    with open(os.path.join(str(root), "_site", name), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ invariant


def test_invariant_expanded_count_equals_local_items(tmp_path):
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    assert forest.expanded_count == len(project.local_items)


def test_invariant_holds_on_a_project_with_multi_parent_items(tmp_path):
    """The named test: multi-parent items, a cycle and board-less items all
    present, the expanded count still equals the item count exactly."""
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    expanded_ids = sorted(i.id for i in forest.expanded)
    assert expanded_ids == sorted(i.id for i in project.local_items)
    # and no item expanded twice
    assert len(expanded_ids) == len(set(expanded_ids))


def test_part_of_cycle_terminates_and_keeps_every_item(tmp_path):
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    ids = {i.id for i in forest.expanded}
    assert {"GRP-CY-001", "GRP-CY-002"} <= ids


# ------------------------------------------------- expand once, reference else


def test_multi_parent_item_expanded_once_and_referenced_elsewhere(tmp_path):
    import re

    _write(tmp_path)
    _render(tmp_path)
    html = _page(tmp_path)

    # The item is linked exactly twice on the page: once expanded, once as a
    # reference leaf.
    assert html.count('data-ref="CMP-M-001"') == 2

    # Exactly one reference leaf for it (the cycle fixture adds its own).
    refs = [r for r in re.findall(r'<li class="tree-ref">.*?</li>', html)
            if 'data-ref="CMP-M-001"' in r]
    assert len(refs) == 1
    assert "expanded under" in refs[0]
    assert "GRP-A-001" in refs[0]  # breadcrumb names the primary location

    # The reference sits under the non-primary group GRP-B-001's branch.
    under_b = html.split('data-ref="GRP-B-001"')[1].split('data-ref="GRP-A-001"')[0]
    assert 'class="tree-ref"' in under_b


def test_primary_parent_is_the_smallest_group_id(tmp_path):
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    loc = forest.locations["CMP-M-001"]
    assert loc.endswith("GRP-A-001")


def test_primary_parent_stable_across_two_builds(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    first = _page(tmp_path)
    _render(tmp_path)
    assert _page(tmp_path) == first


# ------------------------------------------------------------ Project-wide


def test_item_with_no_board_and_no_group_lands_under_project_wide(tmp_path):
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    bucket = [n for n in forest.roots if n.kind == "project-wide"]
    assert len(bucket) == 1
    assert [c.item.id for c in bucket[0].children] == ["CMP-S-001"]
    # rendered last
    assert forest.roots[-1].kind == "project-wide"


def test_project_wide_bucket_shows_a_count(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    html = _page(tmp_path)
    assert 'Project-wide <span class="count">1</span>' in html


# ------------------------------------------------------------ empty project


def test_empty_project_renders_a_sensible_tree_page(tmp_path):
    """No items at all: `scope_reports`' existing no-items-no-page rule keeps
    the whole report set (tree included) unwritten, and the model still
    renders an empty forest without crashing."""
    _write(tmp_path, items={})
    project = _render(tmp_path)
    assert not os.path.exists(os.path.join(str(tmp_path), "_site", "tree.html"))
    markup = tree_mod.render_tree_html(project)
    assert markup.startswith('<ul class="tree">')
    assert "CMP-" not in markup
    assert tree_mod.build_forest(project).expanded_count == 0


# ----------------------------------------------------------- no JavaScript


def test_tree_markup_contains_no_script(tmp_path):
    _write(tmp_path)
    project = _build_at(tmp_path)
    markup = tree_mod.render_tree_html(project)
    assert "<script" not in markup
    assert "onclick" not in markup
    # collapse is plain <details>
    assert "<details" in markup


def test_tree_page_links_are_all_plain_anchors(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    html = _page(tmp_path)
    # The tree's own markup: everything from its root <ul> up to the first
    # <script> the page contains (the base template's site-wide preview
    # payload, which sits after the content block). The tree must be fully
    # rendered before that point, so nothing tree-related is script-driven.
    tree_seg = html.split('<ul class="tree">')[1].split("<script")[0]
    assert "<details" in tree_seg
    assert "onclick" not in tree_seg
    assert tree_seg.count("</ul>") >= tree_seg.count("<ul") - 1


# ------------------------------------------------------------------- nav


def test_tree_page_is_registered_in_nav(tmp_path):
    _write(tmp_path)
    _render(tmp_path)
    html = _page(tmp_path)
    assert 'href="tree.html"' in html
    assert tree_mod.PROJECT_WIDE_LABEL == "Project-wide"
