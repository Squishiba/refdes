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


# --------------------------------------- subtypes of group (`extends: group`)
#
# A type that `extends: group` is a group for the tree's purposes: the tree's
# group decisions must read through `is_subtype`, not a literal type-name test
# (docs/design/extends.md §3.2, §12), so a subtype's members collect under its
# node exactly as under a plain group.

SUBTYPE_GROUP_SCHEMA = """\
site: {title: "Tree test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  board-a: {label: "Board A"}
link_types:
  part_of: { inverse: contains, label: "Part of" }
types:
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true }
    links:
      part_of: [group]
  group:
    prefix: GRP
    coverable: false
    fields:
      title: { type: text, required: true }
    links:
      part_of: [group]
  # The minimal `extends:` delta: identity, everything else inherited.
  subgroup:
    extends: group
    prefix: SGR
    label: Subgroup
    plural: Subgroups
  # A second member type whose id-prefix sorts after SGR, so in the cycle
  # test the subgroup members are unreachable-and-promoted before this member
  # -- the order under which the promoted node must keep its own children.
  widget:
    prefix: WDG
    fields:
      title: { type: text, required: true }
    links:
      part_of: [group]
"""

SUBTYPE_GROUP_ITEMS = {
    "board-a/grp.md": """\
---
id: GRP-001
type: group
title: A plain group on board A.
---
""",
    "board-a/sgr.md": """\
---
id: SGR-001
type: subgroup
title: The subgroup, a specialization of group.
---
""",
    "board-a/cmp-plain.md": """\
---
id: CMP-001
type: component
title: Member of the plain group.
part_of: [GRP-001]
---
""",
    "board-a/cmp-sub.md": """\
---
id: CMP-002
type: component
title: Member of the subgroup.
part_of: [SGR-001]
---
""",
}

SUBTYPE_CYCLE_ITEMS = {
    "board-a/sgr-cy1.md": """\
---
id: SGR-CY-001
type: subgroup
title: Subgroup cycle member one.
part_of: [SGR-CY-002]
---
""",
    "board-a/sgr-cy2.md": """\
---
id: SGR-CY-002
type: subgroup
title: Subgroup cycle member two.
part_of: [SGR-CY-001]
---
""",
    "board-a/wdg-cy.md": """\
---
id: WDG-CY-001
type: widget
title: Member of a subgroup only a cycle can reach.
part_of: [SGR-CY-001]
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


# Boarded items always appear under their own board (finding 37 fix round).
BOARD_GROUP_ITEMS = {
    # Group with no board: it expands under Project-wide.
    "shared/grp-pwr.md": """\
---
id: GRP-PWR-001
type: group
title: Project-wide power group.
---
""",
    # Boarded item whose only group is project-wide: must expand under its
    # OWN board, inside a GRP-PWR-001 node, and be a reference leaf under the
    # expanded project-wide group.
    "board-a/req-a1.md": """\
---
id: REQ-A-001
type: requirement
text: Board A item in a project-wide group.
part_of: [GRP-PWR-001]
---
""",
    # Plain board item, no group: direct child of Board A.
    "board-a/req-a2.md": """\
---
id: REQ-A-002
type: requirement
text: Board A item with no group.
---
""",
}

TWO_BOARD_ITEMS = {
    "shared/grp-two.md": """\
---
id: GRP-T-001
type: group
title: Group with members on two boards.
---
""",
    "board-a/req-ta.md": """\
---
id: REQ-TA-001
type: requirement
text: Member on board A.
part_of: [GRP-T-001]
---
""",
    "board-b/req-tb.md": """\
---
id: REQ-TB-001
type: requirement
text: Member on board B.
part_of: [GRP-T-001]
---
""",
}


def _subtree_tokens(node):
    """(expanded tokens, reference tokens) in the subtree rooted at node."""
    exp, refs = set(), set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.item is not None and not n.duplicate:
            exp.add(tree_mod._ref(n.item))
        elif n.duplicate:
            refs.add(tree_mod._ref(n.item))
        refs.update(tree_mod._ref(r) for r in n.references)
        stack.extend(n.children)
    return exp, refs


def _board_node(forest, label):
    matches = [n for n in forest.roots if n.kind == "board" and n.label == label]
    assert matches, f"no board root {label}"
    return matches[0]


def test_boarded_item_in_project_wide_group_expands_under_its_board(tmp_path):
    """The reported repro: REQ-A-001 (board A, part_of project-wide GRP-PWR)
    must appear under Board A -- expanded, inside a GRP-PWR node -- and as a
    reference leaf under the expanded project-wide group."""
    _write(tmp_path, items=BOARD_GROUP_ITEMS)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)

    board_a = _board_node(forest, "Board A")
    exp_a, _refs_a = _subtree_tokens(board_a)
    assert "REQ-A-001" in exp_a  # expanded, not merely referenced
    assert "REQ-A-002" in exp_a

    # Expanded inside a group node for GRP-PWR-001 inside the board branch.
    views = [
        c for c in board_a.children
        if c.view_of is not None and c.view_of.id == "GRP-PWR-001"
    ]
    assert len(views) == 1
    assert [c.item.id for c in views[0].children] == ["REQ-A-001"]

    # The project-wide group's expanded node lists it as a reference leaf.
    bucket = next(n for n in forest.roots if n.kind == "project-wide")
    grp = [c for c in bucket.children if c.item is not None and c.item.id == "GRP-PWR-001"]
    assert len(grp) == 1
    assert [r.id for r in grp[0].references] == ["REQ-A-001"]

    # Invariant: every item expanded exactly once.
    assert forest.expanded_count == len(project.local_items)

    # Page level: linked twice, once expanded once as reference.
    html = _page(tmp_path)
    assert html.count('data-ref="REQ-A-001"') == 2
    assert "expanded under" in html


def test_item_in_group_on_same_board_expands_under_the_group_node(tmp_path):
    """Board A item whose primary group is also on Board A: expanded under
    the group's own node inside the board branch -- no placeholder, no
    reference leaf for that pairing."""
    _write(tmp_path)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    board_a = _board_node(forest, "Board A")
    grp_a = [
        c for c in board_a.children
        if c.item is not None and c.item.id == "GRP-A-001"
    ]
    assert len(grp_a) == 1
    assert "CMP-M-001" in {c.item.id for c in grp_a[0].children if c.item}
    # no group-view placeholder for GRP-A-001 anywhere in the board branch
    assert not [c for c in board_a.children if c.view_of is not None
                and c.view_of.id == "GRP-A-001"]


def test_group_with_members_on_two_boards_shows_a_node_under_each(tmp_path):
    """A project-wide group with members on both boards: each board branch
    gets a group node holding ONLY that board's members."""
    _write(tmp_path, items=TWO_BOARD_ITEMS)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)

    for label, member in (("Board A", "REQ-TA-001"), ("Board B", "REQ-TB-001")):
        board = _board_node(forest, label)
        views = [c for c in board.children
                 if c.view_of is not None and c.view_of.id == "GRP-T-001"]
        assert len(views) == 1, label
        assert [c.item.id for c in views[0].children] == [member]
        exp, _ = _subtree_tokens(board)
        other = "REQ-TB-001" if label == "Board A" else "REQ-TA-001"
        assert other not in exp  # only this board's members

    assert forest.expanded_count == len(project.local_items)


def test_every_boarded_item_appears_under_its_own_board_branch(tmp_path):
    """The new invariant: nothing may be absent from its own board -- every
    item with a board appears in that board's branch, expanded or as a
    reference leaf."""
    for items in (TREE_ITEMS, BOARD_GROUP_ITEMS, TWO_BOARD_ITEMS):
        _write(tmp_path, items=items)
        project = _render(tmp_path)
        forest = tree_mod.build_forest(project)
        boards = {n.label: n for n in forest.roots if n.kind == "board"}
        for item in project.local_items:
            if not item.board:
                continue
            from refdes import boards as _  # noqa: F401  (board key -> label)
            spec = project.boards.get(item.board)
            node = boards[spec.label if spec else item.board]
            exp, refs = _subtree_tokens(node)
            assert tree_mod._ref(item) in exp | refs, (
                f"{item.id} missing from its own board branch")


def test_primary_placement_stable_across_two_builds_with_group_views(tmp_path):
    _write(tmp_path, items=TWO_BOARD_ITEMS)
    _render(tmp_path)
    first = _page(tmp_path)
    _render(tmp_path)
    assert _page(tmp_path) == first


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


def test_type_that_extends_group_is_treated_as_a_group_in_the_tree(tmp_path):
    """`subgroup` `extends: group`: a same-board member expands under the
    subgroup's own node exactly as it does under the plain group alongside --
    which is the old behaviour, unchanged. Any literal `type == "group"`
    test here would drop the subgroup's member onto the board directly."""
    _write(tmp_path, config=SUBTYPE_GROUP_SCHEMA, items=SUBTYPE_GROUP_ITEMS)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    board_a = _board_node(forest, "Board A")

    grp = [
        c for c in board_a.children if c.item is not None and c.item.id == "GRP-001"
    ]
    assert len(grp) == 1  # plain group still nests its member
    assert [c.item.id for c in grp[0].children if c.item] == ["CMP-001"]

    sgr = [
        c for c in board_a.children if c.item is not None and c.item.id == "SGR-001"
    ]
    assert len(sgr) == 1  # the subtype nests its member the same way
    assert [c.item.id for c in sgr[0].children if c.item] == ["CMP-002"]
    # neither is demoted to a group-view placeholder
    assert not [c for c in board_a.children if c.view_of is not None]

    assert forest.expanded_count == len(project.local_items) == 4

    html = _page(tmp_path)
    under_sgr = html.split('data-ref="SGR-001"', 1)[1].split("</details>", 1)[0]
    assert 'data-ref="CMP-002"' in under_sgr
    assert 'data-ref="CMP-001"' not in under_sgr


def test_subtype_of_group_in_a_cycle_is_promoted_as_a_group_root(tmp_path):
    """Finding 37's cycle rule promotes the smallest unreachable member of a
    `part_of` cycle to a forest root. A subgroup in such a cycle is a group:
    the promoted node keeps its `by_group` children. With a literal
    `type == "group"` test it would be promoted bare and its member would be
    promoted as its own root instead."""
    _write(tmp_path, config=SUBTYPE_GROUP_SCHEMA, items=SUBTYPE_CYCLE_ITEMS)
    project = _render(tmp_path)
    forest = tree_mod.build_forest(project)
    assert forest.expanded_count == len(project.local_items) == 3
    # SGR-CY-001 (smallest id) is the promoted root, anchored under its own
    # board; the other cycle member and the widget member both nest under it
    # (locations double as the breadcrumb in the rendered page). With a literal
    # `type == "group"` test all three would sit directly under Board A.
    assert forest.locations == {
        "SGR-CY-001": "Board A",
        "SGR-CY-002": "Board A > SGR-CY-001",
        "WDG-CY-001": "Board A > SGR-CY-001",
    }


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
