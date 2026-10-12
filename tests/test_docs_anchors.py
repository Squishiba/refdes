"""Check every in-page and cross-page anchor link in the docs against the
heading ids the docs SITE actually generates.

The ids come from the same code the site build uses -- ``build.
_markdown_parser()`` for the markdown render and ``pages.add_heading_anchors``
for the ids (``pages._slugify``, h2/h3 only, duplicates suffixed ``-2``,
``-3``...) -- so this test follows the docs site's slugs, not GitHub's. The
two can differ (GitHub keeps underscores inside code spans differently, and
only the site is what users browse), which is exactly the class of bug this
catches: links like ``links.md#blocked_by-and-the-cascade-report`` that look
right but slug to ``blocked-by-and-the-cascade-report``.

Scope: every ``[text](target)``-style link in ``docs/*.md`` and
``README.md``, checked against the ids of the target page. External links,
links inside fenced code blocks and links inside inline code spans are
skipped (they are not rendered as links). Every broken link is reported as
``file:line``.
"""

from __future__ import annotations

import re
from pathlib import Path

from refdes.build import _markdown_parser
from refdes.model import Page
from refdes.pages import add_heading_anchors
from refdes.parse import FRONTMATTER_RE

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN_RE = re.compile(r"`+[^`\n]*`+")


def _heading_ids(md_path: Path) -> set[str]:
    body = md_path.read_text(encoding="utf-8")
    front_matter = FRONTMATTER_RE.match(body)
    if front_matter:
        body = front_matter.group(2)
    page = Page(
        slug=md_path.stem, title=md_path.stem, body=body, source_file=str(md_path)
    )
    page.body_html = _markdown_parser().render(body)
    add_heading_anchors(page)
    return {slug for _level, _text, slug in page.headings}


def _iter_links(md_path: Path):
    """Yield (line, target) for rendered inline links, with fenced blocks and
    inline code spans blanked out so examples of link syntax don't count."""
    lines = md_path.read_text(encoding="utf-8").split("\n")
    kept: list[str] = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            kept.append("")
        elif in_fence:
            kept.append("")
        else:
            kept.append(CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line))
    text = "\n".join(kept)
    for match in LINK_RE.finditer(text):
        yield text.count("\n", 0, match.start()) + 1, match.group(1)


def _all_heading_ids() -> dict[Path, set[str]]:
    return {path: _heading_ids(path) for path in sorted(DOCS.rglob("*.md"))}


def _checked_files() -> list[Path]:
    return sorted(p for p in DOCS.glob("*.md")) + [ROOT / "README.md"]


def test_docs_site_slug_rules_are_what_this_check_follows():
    """Sentinel: the site slugifies code-span headings with underscores to
    hyphens. If this ever fails, the id collection above stopped using the
    real slug code -- do not "fix" it by loosening the check."""
    ids = _heading_ids(DOCS / "links.md")
    assert "blocked-by-and-the-cascade-report" in ids
    assert "blocked_by-and-the-cascade-report" not in ids


def test_no_broken_anchor_links_in_docs():
    ids = _all_heading_ids()
    broken: list[str] = []
    for source in _checked_files():
        for line, target in _iter_links(source):
            if "://" in target or target.startswith(("mailto:", "tel:", "/")):
                continue
            page_part, _, fragment = target.partition("#")
            if not fragment:
                continue
            base = DOCS if source.parent == DOCS else ROOT
            page = (base / page_part).resolve() if page_part else source
            rel = source.relative_to(ROOT)
            if page not in ids:
                broken.append(f"{rel}:{line}: links to non-page {page_part!r}")
            elif fragment not in ids[page]:
                broken.append(f"{rel}:{line}: {target}")
    assert not broken, "broken anchor link(s):\n" + "\n".join(broken)
