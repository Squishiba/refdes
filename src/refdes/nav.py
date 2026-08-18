"""Generated site navigation.

The nav bar is derived from project structure -- boards today, a workspace
layer potentially wrapping them later -- plus page type (an authored
narrative page versus a generated report), instead of being hand-maintained.
A project with no `boards:` registry gets the same flat list of links this
always produced; adopting boards is what turns each one into its own group,
with no config beyond the registry that already exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import citations as citations_mod
from .model import Project


@dataclass
class NavNode:
    """One nav bar entry: a link, or a labeled group of further entries.

    `href` set means this is a link. `href` empty means this is a group and
    `children` holds its own nodes -- which are the same `NavNode` type, so a
    group can itself hold groups. Nothing here assumes exactly two levels
    (project -> board); a workspace layer, if it's ever built, is just
    another group wrapping the board groups below it.
    """

    label: str
    href: str = ""
    children: list["NavNode"] = field(default_factory=list)


def _report_links(
    project: Project,
    board: str | None,
    workspace: str | None,
    dashboard_href: str,
) -> list[NavNode]:
    """The generated-report links for one scope: the whole project, one board,
    or one workspace. Callers pass at most one of `board`/`workspace`.

    Mirrors exactly which report files `render.render_site` actually writes for
    that scope, so a nav link never dangles: the project-wide dashboard and
    `items.json` only exist unscoped; every other report has a `-<board>` or
    `-<workspace>` variant once that registry is in use.
    """
    if not project.items:
        return []
    scope_key = board or workspace
    suffix = f"-{scope_key}" if scope_key else ""
    has_log = any(
        i.type == "log"
        and (board is None or i.board == board)
        and (workspace is None or i.workspace == workspace)
        for i in project.local_items
    )
    has_citations = bool(citations_mod.by_url(project, board=board, workspace=workspace))

    unscoped = board is None and workspace is None
    links = [NavNode("Summary", f"summary{suffix}.html")]
    if unscoped:
        links.append(NavNode("Items", dashboard_href))
    links.append(NavNode("Coverage", f"coverage{suffix}.html"))
    if has_log:
        links.append(NavNode("Design log", f"log{suffix}.html"))
    if has_citations:
        links.append(NavNode("References", f"references{suffix}.html"))
    links.append(NavNode("Full record", f"document{suffix}.html"))
    if unscoped:
        links.append(NavNode("JSON", "items.json"))
    return links


def _board_node(project: Project, board_key: str, spec) -> NavNode | None:
    children = [
        NavNode(page.title, f"{page.slug}.html")
        for page in project.pages
        if page.in_nav and page.board == board_key
    ]
    children.extend(_report_links(project, board=board_key, workspace=None, dashboard_href=""))
    return NavNode(spec.label, children=children) if children else None


def build_nav(project: Project, dashboard_href: str) -> list[NavNode]:
    """The nav tree: ungrouped pages and reports, then one group per workspace
    (nesting the board groups whose items fall inside it), then one group for
    every remaining board that isn't part of any workspace's own nesting.

    An author supplements or overrides this with the same knobs that already
    govern page nav placement: `site.nav:` still orders pages (within
    whichever scope they land in), and a page's own `nav: false` still hides
    it. Tagging a page's front matter `board:`/`workspace:` is what moves that
    page out of the top-level list and into that group, alongside its
    generated reports, instead of requiring a hand-written row of links at the
    top of the page body to reach them.

    Board-to-workspace nesting is derived from resolved item data, not a
    static declaration -- a board isn't owned by a workspace in the registry,
    only items are (docs/workspaces.md). A board with at least one item
    resolving into a given workspace nests there; a board with none (not yet
    populated, or spanning none) falls back to the top level, same as it
    would with no workspaces: registry at all.
    """
    root: list[NavNode] = [
        NavNode(page.title, f"{page.slug}.html")
        for page in project.pages
        if page.in_nav and not page.board and not page.workspace
    ]
    root.extend(_report_links(project, board=None, workspace=None, dashboard_href=dashboard_href))

    boards_by_workspace: dict[str, set[str]] = {}
    for item in project.local_items:
        if item.workspace and item.board:
            boards_by_workspace.setdefault(item.workspace, set()).add(item.board)

    nested_boards: set[str] = set()
    for ws_key, ws_spec in project.workspaces.items():
        children = [
            NavNode(page.title, f"{page.slug}.html")
            for page in project.pages
            if page.in_nav and page.workspace == ws_key and not page.board
        ]
        children.extend(
            _report_links(project, board=None, workspace=ws_key, dashboard_href="")
        )
        for board_key in sorted(boards_by_workspace.get(ws_key, ())):
            board_spec = project.boards.get(board_key)
            if board_spec is None:
                continue
            board_node = _board_node(project, board_key, board_spec)
            if board_node is not None:
                children.append(board_node)
                nested_boards.add(board_key)
        if children:
            root.append(NavNode(ws_spec.label, children=children))

    for board_key, spec in project.boards.items():
        if board_key in nested_boards:
            continue
        board_node = _board_node(project, board_key, spec)
        if board_node is not None:
            root.append(board_node)

    return root
