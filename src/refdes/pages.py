"""Narrative markdown pages.

Distinct from items on purpose. An item is a typed, identified, linkable thing that
participates in coverage and traceability. A page is prose — an overview, a primer,
a set of instructions. Pages can reference items and get the same hover previews,
but they carry no ID and no obligations.
"""

from __future__ import annotations

import os
import re

import yaml

from .model import Page, Project
from .parse import FRONTMATTER_RE, yaml_safe_load

H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def pages_root(project: Project) -> str:
    path = project.pages_dir
    if not os.path.isabs(path):
        path = os.path.join(project.root, path)
    return os.path.normpath(path)


def load_pages(project: Project) -> None:
    root = pages_root(project)
    if not os.path.isdir(root):
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for name in sorted(filenames):
            if not name.endswith(".md") or name.startswith("."):
                continue
            page = _read_page(project, os.path.join(dirpath, name), root)
            if page:
                project.pages.append(page)

    explicit = {slug: i for i, slug in enumerate(project.nav_order)}
    project.pages.sort(
        key=lambda p: (explicit.get(p.slug, 10_000 + p.order), p.title.lower())
    )


_YAML_POSITION_TAIL_RE = re.compile(
    r"\n\s*in \"[^\"]*\", (?:line \d+, column \d+|position \d+).*", re.DOTALL
)


def _front_matter_detail(exc: yaml.YAMLError) -> str:
    """The YAML error's own words, without its position part.

    `str(exc)` quotes the front matter as a standalone string, so its
    "line N, column M" / "position N" is front-matter-relative and sends
    the reader to the wrong file line. The diagnostic names the FILE line
    on the Diagnostic itself, so the message keeps context/problem and
    drops the marks. The non-marked path (a ReaderError has no
    context/problem) keeps `str(exc)`'s cause with the
    `in "...", position N` tail stripped -- the same position it is being
    dropped from the marked path.
    """
    context = getattr(exc, "context", None)
    problem = getattr(exc, "problem", None)
    if context is None and problem is None:
        return _YAML_POSITION_TAIL_RE.sub("", str(exc)).strip()
    return "; ".join(part for part in (context, problem) if part)


def _front_matter_file_line(text: str, match: re.Match, exc: yaml.YAMLError) -> int:
    """The FILE line a reader should open for this front-matter YAML error.

    `problem_mark.line` is 0-based within the front-matter text (regex
    group 1), which starts on the line after the opening `---` fence —
    line 2 for a plain file, later if `\\s*` swallowed blank lines after
    the fence. With no mark at all, fall back to the fence's own line.
    """
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is not None and getattr(mark, "line", None) is not None:
        return text.count("\n", 0, match.start(1)) + 1 + mark.line
    return text.count("\n", 0, match.start(0)) + 1


def _read_page(project: Project, path: str, root: str) -> Page | None:
    rel_to_root = os.path.relpath(path, project.root).replace("\\", "/")
    try:
        text = open(path, "r", encoding="utf-8").read()
    except OSError as exc:
        project.warn(f"could not read page: {exc}", file=rel_to_root)
        return None

    meta: dict = {}
    body = text
    front_matter_lines = 0
    match = FRONTMATTER_RE.match(text)
    if match:
        try:
            loaded = yaml_safe_load(match.group(1)) or {}
            if isinstance(loaded, dict):
                meta = loaded
            body = match.group(2)
            # Lines the front matter occupies in the FILE. `body` is stripped,
            # so a line number counted inside it is this many lines short of
            # the file line a reader sees; rendering (blocks.extract_blocks)
            # adds it back so page-block diagnostics name the real line.
            front_matter_lines = text.count("\n", 0, match.start(2))
        except yaml.YAMLError as exc:
            # A writable run loads the pages twice -- once in
            # image_freeze.freeze_images (to scan page bodies for image
            # references) and once in build() (to pick up freeze's disk
            # rewrites) -- so the diagnostic is guarded per page on the
            # project's `front_matter_warned`: the double load is
            # intentional and cheap, the double report is not.
            if rel_to_root not in project.front_matter_warned:
                project.front_matter_warned.add(rel_to_root)
                project.warn(
                    f"invalid page front-matter: {_front_matter_detail(exc)}",
                    file=rel_to_root,
                    line=_front_matter_file_line(text, match, exc),
                )
            # body stays the whole file -- front matter included -- so the
            # body-relative lines are already the file lines.

    rel = os.path.relpath(path, root).replace("\\", "/")
    slug = re.sub(r"\.md$", "", rel).replace("/", "-")

    title = meta.get("title")
    if not title:
        heading = H1_RE.search(body)
        title = heading.group(1) if heading else slug.replace("-", " ").title()

    page = Page(
        slug=slug,
        title=str(title),
        body=body,
        source_file=rel_to_root,
        order=int(meta.get("order", 100)),
        in_nav=bool(meta.get("nav", True)),
        board=str(meta.get("board") or ""),
        workspace=str(meta.get("workspace") or ""),
        front_matter_lines=front_matter_lines,
    )
    return page


def validate_boards(project: Project) -> None:
    """A page's `board:` tag must name a board actually declared in `boards:`.

    Runs after `boards.resolve()` so `project.boards` is settled. An unknown tag
    is reported and cleared rather than left to silently strand the page outside
    every nav group -- the same "name the fix, then keep going" posture
    `boards.resolve()` already takes for an item's own bad `board:` override.
    """
    for page in project.pages:
        if page.board and page.board not in project.boards:
            project.error(
                f"page board: {page.board!r} is not declared in refdes-project.yaml's "
                f"boards: registry",
                file=page.source_file,
            )
            page.board = ""


def validate_workspaces(project: Project) -> None:
    """A page's `workspace:` tag must name a workspace declared in `workspaces:`.

    Mirrors validate_boards() exactly, for the same reason: name the fix,
    then clear it, rather than stranding the page outside every nav group.
    """
    for page in project.pages:
        if page.workspace and page.workspace not in project.workspaces:
            project.error(
                f"page workspace: {page.workspace!r} is not declared in "
                f"refdes-project.yaml's workspaces: registry",
                file=page.source_file,
            )
            page.workspace = ""


# --------------------------------------------------------------------- rendering

# Links between pages are written as they are on disk (`math.md`); on the site they
# have to point at the rendered page instead.
MD_LINK_RE = re.compile(r'href="(?!https?:|mailto:|#)([^"]+?)\.md(#[^"]*)?"')
HEADING_RE = re.compile(r"<h([23])>(.*?)</h\1>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def rewrite_page_links(html: str, known: set[str]) -> str:
    def swap(match: re.Match) -> str:
        target = match.group(1).replace("\\", "/")
        anchor = match.group(2) or ""
        slug = target.split("/")[-1] if target.split("/")[-1] in known else target.replace("/", "-")
        if slug in known:
            return f'href="{slug}.html{anchor}"'
        return match.group(0)

    return MD_LINK_RE.sub(swap, html)


def add_heading_anchors(page: Page) -> None:
    """Give h2/h3 stable ids and collect them for the on-page contents list."""
    seen: dict[str, int] = {}
    collected: list[tuple[int, str, str]] = []

    def anchor(match: re.Match) -> str:
        level = int(match.group(1))
        inner = match.group(2)
        text = TAG_RE.sub("", inner).strip()
        base = _slugify(text)
        seen[base] = seen.get(base, 0) + 1
        slug = base if seen[base] == 1 else f"{base}-{seen[base]}"
        collected.append((level, text, slug))
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    page.body_html = HEADING_RE.sub(anchor, page.body_html)
    page.headings = collected
