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


def _report_links(project: Project, board: str | None, dashboard_href: str) -> list[NavNode]:
    """The generated-report links for one scope: the whole project, or one board.

    Mirrors exactly which report files `render.render_site` actually writes for
    that scope, so a nav link never dangles: the project-wide dashboard and
    `items.json` only exist unscoped; every other report has a `-<board>`
    variant once boards are registered.
    """
    if not project.items:
        return []
    suffix = f"-{board}" if board else ""
    has_log = any(
        i.type == "log" and (board is None or i.board == board)
        for i in project.local_items
    )
    has_citations = bool(citations_mod.by_url(project, board=board))

    links = [NavNode("Summary", f"summary{suffix}.html")]
    if board is None:
        links.append(NavNode("Items", dashboard_href))
    links.append(NavNode("Coverage", f"coverage{suffix}.html"))
    if has_log:
        links.append(NavNode("Design log", f"log{suffix}.html"))
    if has_citations:
        links.append(NavNode("References", f"references{suffix}.html"))
    links.append(NavNode("Full record", f"document{suffix}.html"))
    if board is None:
        links.append(NavNode("JSON", "items.json"))
    return links


def build_nav(project: Project, dashboard_href: str) -> list[NavNode]:
    """The nav tree: ungrouped pages and reports, then one group per board.

    An author supplements or overrides this with the same knobs that already
    govern page nav placement: `site.nav:` still orders pages (within
    whichever scope they land in), and a page's own `nav: false` still hides
    it. Tagging a page's front matter `board: <name>` is the one new knob --
    it moves that page out of the top-level list and into that board's group,
    alongside its generated reports, instead of requiring a hand-written row
    of links at the top of the page body to reach them.
    """
    root: list[NavNode] = [
        NavNode(page.title, f"{page.slug}.html")
        for page in project.pages
        if page.in_nav and not page.board
    ]
    root.extend(_report_links(project, board=None, dashboard_href=dashboard_href))

    for board_key, spec in project.boards.items():
        children = [
            NavNode(page.title, f"{page.slug}.html")
            for page in project.pages
            if page.in_nav and page.board == board_key
        ]
        children.extend(_report_links(project, board=board_key, dashboard_href=dashboard_href))
        if children:
            root.append(NavNode(spec.label, children=children))

    return root
