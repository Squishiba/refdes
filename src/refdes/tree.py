"""The project tree: a total containment forest over every local item.

docs/design/backlog.md finding 37, chunk 1: the model behind the generated
`tree.html` page. The nesting is the containment spine -- workspace, then
board, then `part_of` group, then item -- because it is the only nesting
where every item has a place without the author having declared anything.

**Expand once, reference everywhere else.** An item with several `part_of`
groups is expanded under exactly one *primary* parent and appears as a
reference leaf under every other one. This is `walk_cascade`'s visited-set
rule (blocks.py) generalised from a single rooted walk to a forest: one
shared `visited` set across the whole render, a re-visited node rendered as
a terminal leaf annotated with where it was expanded, never recursed.

**The primary-home rule, stated:** an item that has a board is expanded
under ITS OWN BOARD. If it is also in a group that shares that board, it
expands under the group's node inside the board branch; if its groups all
live elsewhere, a group node for its lexicographically smallest group (by
display id, surrogate key as fallback) appears inside the board branch
holding that board's members -- the group item itself is still expanded
once, elsewhere. Every other group lists the item as a reference leaf.
An item with no board keeps the old rule: smallest `part_of` group, else
the synthetic `Project-wide` bucket. Id-based and registry-order-based, so
it is stable across builds. A group node may therefore appear in more than
one board branch, each showing only that board's members. A `part_of` cycle makes its members unreachable
from any root; the smallest-id member is promoted to a root of the forest
and the visited-set rule terminates the rest, exactly as cascade's rule
terminates a cycle inside one tree.

**The invariants, tested mechanically:** every local item is expanded
exactly once -- `expanded_count == len(project.local_items)` -- every item
that has a board appears under that board's branch, expanded or as a
reference leaf, and `Project-wide` (rendered last, with a count) catches
everything with no board and no group. Nothing is ever silently dropped.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from . import boards as boards_mod
from .model import Item, Project

DEFAULT_DEPTH = 2  # spine levels expanded before collapsing to counts
PROJECT_WIDE_LABEL = "Project-wide"


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _ref(item: Item) -> str:
    """An item's stable sort/identity token: display id, else surrogate key."""
    return item.id or item.key


def _display(item: Item) -> str:
    return item.id or item.key


@dataclass
class TreeNode:
    """One expanded node of the forest: a workspace, a board, an item
    (group or not), or the Project-wide bucket."""

    kind: str  # workspace | board | item | project-wide | group-view
    label: str
    item: Item | None = None
    # A group-view placeholder: the group item named here is expanded
    # elsewhere; this node only holds this board's members of that group.
    view_of: Item | None = None
    # The placeholder stands for an `includes:` group on a scoped board
    # page (finding 33): labelled shared, like the parts rows already are.
    shared: bool = False
    children: list[TreeNode] = field(default_factory=list)
    references: list[Item] = field(default_factory=list)
    # A cycle revisit: this item was already expanded elsewhere in the
    # forest, so it renders as a reference leaf, cascade's "already shown
    # above" rule, instead of a second subtree.
    duplicate: bool = False


@dataclass
class TreeForest:
    roots: list[TreeNode]
    expanded: list[Item] = field(default_factory=list)
    # item identity token -> breadcrumb of the node it was expanded under
    locations: dict[str, str] = field(default_factory=dict)
    # The board this forest is scoped to, if any: a board node's count then
    # tallies only what the board owns, with shared members counted apart
    # (finding 33: a board's numbers count only what it owns).
    board: str | None = None

    @property
    def expanded_count(self) -> int:
        return len(self.expanded)


def _group_parents(project: Project, item: Item, local_keys: set[str]) -> list[Item]:
    """Local group items this item declares `part_of:`, sorted by display id."""
    parents = []
    for ref in item.resolved_links.get("part_of", []):
        target = project.item_by_ref(ref)
        if (
            target is not None
            and project.is_subtype(target.type, "group")
            and (target.id or target.key) in local_keys
        ):
            parents.append(target)
    parents.sort(key=_ref)
    return parents


def build_forest(
    project: Project, board: str | None = None, workspace: str | None = None
) -> TreeForest:
    """The containment forest for one scope (see the module docstring).

    `board`/`workspace` scope the forest exactly like the other reports:
    a board's forest holds the items it displays -- owned plus the members
    of its `includes:` groups, which hang under a shared group node -- and
    has that single board as its only root. Both None is the whole project.
    """
    included = boards_mod.included_map(project, board) if board is not None else {}
    items = sorted(
        [
            i
            for i in project.local_items
            if boards_mod.displays(i, board, included)
            and (workspace is None or i.workspace == workspace)
        ],
        key=_ref,
    )
    local_keys = {_ref(i) for i in items}
    parents = {_ref(item): _group_parents(project, item, local_keys) for item in items}

    # Primary home per item: its own board (inside a same-board group node
    # where one fits), else smallest part_of group, else the bucket.
    by_group: dict[str, list[Item]] = {}  # group token -> children to expand
    ref_groups: dict[str, list[Item]] = {}  # group token -> reference leaves
    by_board: dict[str, list[Item]] = {}
    by_board_view: dict[tuple[str, str], list[Item]] = {}
    groups_by_token: dict[str, Item] = {}
    shared_views: set[tuple[str, str]] = set()
    bucket: list[Item] = []
    for item in items:
        group_list = parents[_ref(item)]
        shared_group = None
        if board is not None and item.board != board and item.id in included:
            shared_group = project.item_by_id(included[item.id])
        if shared_group is not None:
            # A member shared onto this board by `includes:`: it hangs under
            # a shared node for the including group, wherever it is owned.
            key = (board, _ref(shared_group))
            by_board_view.setdefault(key, []).append(item)
            groups_by_token.setdefault(_ref(shared_group), shared_group)
            shared_views.add(key)
        elif board is not None or item.board:
            same_board = [
                g for g in group_list if board is not None or g.board == item.board
            ]
            if same_board:
                primary = same_board[0]
                by_group.setdefault(_ref(primary), []).append(item)
                for other in group_list:
                    if other is not primary:
                        ref_groups.setdefault(_ref(other), []).append(item)
            elif group_list:
                primary = group_list[0]
                by_board_view.setdefault(
                    (item.board, _ref(primary)), []
                ).append(item)
                groups_by_token[_ref(primary)] = primary
                for other in group_list:
                    ref_groups.setdefault(_ref(other), []).append(item)
            else:
                by_board.setdefault(item.board, []).append(item)
        elif group_list:
            primary = group_list[0]
            by_group.setdefault(_ref(primary), []).append(item)
            for other in group_list[1:]:
                ref_groups.setdefault(_ref(other), []).append(item)
        else:
            bucket.append(item)

    if board is not None:
        roots = [
            _board_node(
                project, board, by_board, by_board_view, groups_by_token, shared_views
            )
        ]
    else:
        roots = _scope_roots(
            project, by_board, by_board_view, groups_by_token, shared_views
        )
    bucket_node = None
    if bucket:
        bucket_node = TreeNode(
            kind="project-wide",
            label=PROJECT_WIDE_LABEL,
            children=[
                TreeNode(kind="item", label=_display(i), item=i) for i in bucket
            ],
        )
        roots.append(bucket_node)
    for node in roots:
        _attach_groups(node, project, by_group, ref_groups, ())

    forest = TreeForest(roots=roots, board=board)
    _visit_all(forest, roots, ())
    # Cycle members unreachable from any root: promote the smallest remaining
    # to a root and keep going until every item has been expanded once.
    while forest.expanded_count < len(items):
        remaining = [i for i in items if _ref(i) not in forest.locations]
        head = remaining[0]
        extra = TreeNode(kind="item", label=_display(head), item=head)
        if project.is_subtype(head.type, "group"):
            token = _ref(head)
            extra.children = [
                TreeNode(kind="item", label=_display(c), item=c)
                for c in by_group.get(token, ())
            ]
            extra.references = list(ref_groups.get(token, ()))
            _attach_groups(extra, project, by_group, ref_groups, (token,))
        # A boarded cycle member belongs to its board's branch, not to a new
        # root: nothing may be absent from its own board.
        anchor = board or head.board
        parent = _find_board_node(forest.roots, _board_label(project, anchor)) if anchor else None
        if parent is not None:
            parent.children.append(extra)
            _visit_all(forest, [extra], (parent.label,))
            continue
        # `Project-wide` stays last, whatever gets promoted.
        if bucket_node is not None:
            forest.roots.insert(forest.roots.index(bucket_node), extra)
        else:
            forest.roots.append(extra)
        _visit_all(forest, [extra], ())
    return forest


def _board_label(project: Project, board_key: str) -> str:
    spec = project.boards.get(board_key)
    return spec.label if spec else board_key


def _find_board_node(node_list: list[TreeNode], label: str) -> TreeNode | None:
    for node in node_list:
        if node.kind == "board" and node.label == label:
            return node
        found = _find_board_node(node.children, label)
        if found is not None:
            return found
    return None


def _scope_roots(
    project: Project,
    by_board: dict[str, list[Item]],
    by_board_view: dict[tuple[str, str], list[Item]],
    groups_by_token: dict[str, Item],
    shared_views: set[tuple[str, str]],
) -> list[TreeNode]:
    """Workspace nodes (registry order) nesting their boards, then the
    remaining boards -- the same derivation `nav.build_nav` uses."""
    boards_by_workspace: dict[str, set[str]] = {}
    for item in project.local_items:
        if item.workspace and item.board:
            boards_by_workspace.setdefault(item.workspace, set()).add(item.board)

    nodes: list[TreeNode] = []
    nested: set[str] = set()
    for ws_key, ws_spec in project.workspaces.items():
        ws_boards = sorted(
            b for b in boards_by_workspace.get(ws_key, ()) if b in project.boards
        )
        nodes.append(
            TreeNode(
                kind="workspace",
                label=ws_spec.label,
                children=[
                _board_node(
                    project, b, by_board, by_board_view, groups_by_token, shared_views
                )
                for b in ws_boards
            ],
            )
        )
        nested.update(ws_boards)
    for board_key in project.boards:
        if board_key in nested:
            continue
        nodes.append(
            _board_node(
                project, board_key, by_board, by_board_view, groups_by_token,
                shared_views,
            )
        )
    return nodes


def _board_node(
    project: Project,
    board_key: str,
    by_board: dict[str, list[Item]],
    by_board_view: dict[tuple[str, str], list[Item]],
    groups_by_token: dict[str, Item],
    shared_views: set[tuple[str, str]],
) -> TreeNode:
    spec = project.boards.get(board_key)
    children = [
        TreeNode(kind="item", label=_display(i), item=i)
        for i in by_board.get(board_key, ())
    ]
    views = sorted(
        (gtok, members)
        for (bk, gtok), members in by_board_view.items()
        if bk == board_key
    )
    for gtok, members in views:
        group_item = groups_by_token[gtok]
        children.append(
            TreeNode(
                kind="group-view",
                label=_display(group_item),
                view_of=group_item,
                shared=(board_key, gtok) in shared_views,
                children=[
                    TreeNode(kind="item", label=_display(m), item=m)
                    for m in members
                ],
            )
        )
    return TreeNode(
        kind="board",
        label=spec.label if spec else board_key,
        children=children,
    )


def _attach_groups(
    node: TreeNode,
    project: Project,
    by_group: dict[str, list[Item]],
    ref_groups: dict[str, list[Item]],
    path: tuple[str, ...],
) -> None:
    """Hang each group child's own children (and reference leaves) under it,
    recursively. `path` is the chain of group tokens above `node`: a group
    already on it is a cycle member, left as a leaf here and marked a
    duplicate by `_visit_all` rather than recursed into forever."""
    for child in node.children:
        if child.item is None or not project.is_subtype(child.item.type, "group"):
            continue
        token = _ref(child.item)
        if token in path:
            continue
        child.children = [
            TreeNode(kind="item", label=_display(c), item=c)
            for c in by_group.get(token, ())
        ]
        child.references = list(ref_groups.get(token, ()))
        _attach_groups(child, project, by_group, ref_groups, path + (token,))


def _visit_all(
    forest: TreeForest, roots: list[TreeNode], path: tuple[str, ...]
) -> None:
    """Expand every reachable node once -- cascade's visited rule
    generalised to the forest: one shared visited set, a re-visited item
    keeps no subtree here because the reference leaves already point at the
    single expansion."""
    for node in roots:
        node_path = path + (node.label,)
        if node.item is not None:
            token = _ref(node.item)
            if token in forest.locations:
                node.duplicate = True
                node.children = []
                continue
            # Breadcrumb: the containing spine, not the item itself.
            forest.locations[token] = " > ".join(path) or node.label
            forest.expanded.append(node.item)
        _visit_all(forest, node.children, node_path)


def render_tree_html(
    project: Project,
    board: str | None = None,
    workspace: str | None = None,
    open_depth: int = DEFAULT_DEPTH,
) -> str:
    """The `<ul class="tree">` markup for a tree page or the `{{tree}}`
    block: `<details>` collapse, open above `open_depth`, zero JavaScript."""
    forest = build_forest(project, board=board, workspace=workspace)
    return _render_list(forest, forest.roots, 1, open_depth)


def _render_list(
    forest: TreeForest, nodes: list[TreeNode], depth: int, open_depth: int
) -> str:
    if not nodes and depth > 1:
        return ""
    return (
        ('<ul class="tree">' if depth == 1 else "<ul>")
        + "".join(_render_node(forest, node, depth, open_depth) for node in nodes)
        + "</ul>"
    )


def _render_node(
    forest: TreeForest, node: TreeNode, depth: int, open_depth: int
) -> str:
    if node.duplicate:
        return _render_reference(forest, node.item)
    if node.view_of is not None:
        if node.shared:
            hint = f"shared, via {_esc(node.label)}"
        else:
            where = forest.locations.get(_ref(node.view_of), "")
            hint = f"group expanded under {_esc(where)}"
        label = (
            f'<a class="ref" href="{_esc(node.view_of.slug)}.html" '
            f'data-ref="{_esc(node.view_of.id)}">{_esc(node.label)}</a> '
            f'<span class="tree-seen">({_esc(hint)})</span>'
        )
        inner = _render_list(forest, node.children, depth + 1, open_depth)
        open_attr = " open" if depth < open_depth else ""
        return (
            f"<li><details{open_attr}><summary>{label} "
            f'<span class="count">{_item_count(node)}</span></summary>'
            f"{inner}</details></li>"
        )
    if node.item is not None:
        label = (
            f'<a class="ref" href="{_esc(node.item.slug)}.html" '
            f'data-ref="{_esc(node.item.id)}">{_esc(node.label)}</a>'
            f' <span class="muted">{_esc(node.item.title)}</span>'
        )
    else:
        label = _esc(node.label)
    inner = _render_list(forest, node.children, depth + 1, open_depth) + "".join(
        _render_reference(forest, item) for item in node.references
    )
    if not inner:
        return f"<li>{label}</li>"
    open_attr = " open" if depth < open_depth else ""
    if node.kind == "board" and forest.board is not None:
        own, shared = _own_shared(node)
        text = f"{own} own, {shared} shared" if shared else str(own)
    else:
        text = str(_item_count(node))
    return (
        f"<li><details{open_attr}><summary>{label} "
        f'<span class="count">{text}</span></summary>{inner}</details></li>'
    )


def _own_shared(node: TreeNode) -> tuple[int, int]:
    """Own and shared item counts inside a scoped board node's branch:
    everything under a shared `includes:` node is shared, everything else
    the board owns. Group nodes keep their plain counts."""
    own = shared = 0
    stack = [(c, c.shared) for c in node.children]
    while stack:
        n, is_shared = stack.pop()
        if n.item is not None:
            if is_shared:
                shared += 1
            else:
                own += 1
        stack.extend((c, is_shared) for c in n.children)
    return own, shared


def _render_reference(forest: TreeForest, item: Item) -> str:
    where = forest.locations.get(_ref(item), "")
    return (
        f'<li class="tree-ref"><a class="ref" href="{_esc(item.slug)}.html" '
        f'data-ref="{_esc(item.id)}">{_esc(_display(item))}</a> '
        f'<span class="muted">{_esc(item.title)}</span> '
        f'<span class="tree-seen">(expanded under {_esc(where)})</span></li>'
    )


def _item_count(node: TreeNode) -> int:
    n = 1 if node.item is not None else 0
    return n + sum(_item_count(c) for c in node.children)
