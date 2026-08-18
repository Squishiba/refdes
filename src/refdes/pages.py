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
from .parse import FRONTMATTER_RE

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


def _read_page(project: Project, path: str, root: str) -> Page | None:
    rel_to_root = os.path.relpath(path, project.root).replace("\\", "/")
    try:
        text = open(path, "r", encoding="utf-8").read()
    except OSError as exc:
        project.warn(f"could not read page: {exc}", file=rel_to_root)
        return None

    meta: dict = {}
    body = text
    match = FRONTMATTER_RE.match(text)
    if match:
        try:
            loaded = yaml.safe_load(match.group(1)) or {}
            if isinstance(loaded, dict):
                meta = loaded
            body = match.group(2)
        except yaml.YAMLError as exc:
            project.warn(f"invalid page front-matter: {exc}", file=rel_to_root)

    rel = os.path.relpath(path, root).replace("\\", "/")
    slug = re.sub(r"\.md$", "", rel).replace("/", "-")

    title = meta.get("title")
    if not title:
        heading = H1_RE.search(body)
        title = heading.group(1) if heading else slug.replace("-", " ").title()

    return Page(
        slug=slug,
        title=str(title),
        body=body,
        source_file=rel_to_root,
        order=int(meta.get("order", 100)),
        in_nav=bool(meta.get("nav", True)),
        board=str(meta.get("board") or ""),
    )


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
                f"page board: {page.board!r} is not declared in refdes.yaml's "
                f"boards: registry",
                file=page.source_file,
            )
            page.board = ""


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
