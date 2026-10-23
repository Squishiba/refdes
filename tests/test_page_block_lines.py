"""CHK-ATTR-001: page `{{...}}` block diagnostics report the line in the FILE.

A page's front matter is stripped before `Page.body` is stored (pages.py),
and `render_pages` hands that stripped body to `blocks.extract_blocks`
(build.py), which counts newlines from the top of the *body* (blocks.py).
So a page with front matter gets its block diagnostics reported a few lines
early -- front-matter lines worth of them. The requirement: every registered
block type's diagnostic names the line in the file, front matter included,
and a page without front matter keeps naming the true line it names today.

Each test builds the project the way the rest of the block tests do
(`_build_at` from helpers -- load, parse, build, the same pipeline `refdes
check` runs) and asserts the diagnostic's `.file`/`.line` against the file
layout written below.
"""

from __future__ import annotations

from helpers import _build_at

# Front matter occupies file lines 1-4; the page body then starts at line 5.
FRONT_MATTER = "---\ntitle: Overview\norder: 10\n---\n"

# ...intro prose lands on lines 5-7, so the directive on the next line is
# file line 8 -- counted from the written text, not trusted from a constant.
FM_PAGE_TAIL = "\nIntro prose.\n\n"

# A page with no front matter at all: the control. Body line == file line
# is true today and must stay true.
CONTROL_TAIL = "# Control overview\n\nProse first.\n\n"
CONTROL_DIRECTIVE_LINE = 5


def _write_page(root, name: str, directive: str, front_matter: bool) -> int:
    """Write `pages/<name>` with `directive` last; return its file line."""
    tail = FM_PAGE_TAIL if front_matter else CONTROL_TAIL
    text = (FRONT_MATTER if front_matter else "") + tail + directive + "\n"
    (root / "pages" / name).write_text(text, encoding="utf-8")
    lines = text.split("\n")
    directive_line = next(
        i for i, line in enumerate(lines) if line.startswith("{{")
    ) + 1
    return directive_line


def _block_diagnostic(project, needle: str, file: str):
    matches = [
        d for d in project.errors if needle in d.message and d.file == file
    ]
    assert len(matches) == 1, (
        f"expected exactly one error on {file} containing {needle!r}, got "
        f"{[str(d) for d in project.errors]}"
    )
    return matches[0]


# ----------------------------------------------------------- with front matter


def test_index_block_diagnostic_reports_file_line(blocks_project):
    line = _write_page(
        blocks_project, "overview.md", '{{index type="decision"}}', front_matter=True
    )
    assert line == 8  # front matter 1-4, prose 5-7, directive 8
    project = _build_at(blocks_project)
    d = _block_diagnostic(project, "missing required parameter 'by'", "pages/overview.md")
    assert d.line == line


def test_compare_block_diagnostic_reports_file_line(blocks_project):
    line = _write_page(blocks_project, "overview.md", "{{compare}}", front_matter=True)
    assert line == 8
    project = _build_at(blocks_project)
    d = _block_diagnostic(
        project, "compare is missing required parameter 'type'", "pages/overview.md"
    )
    assert d.line == line


def test_cascade_block_diagnostic_reports_file_line(blocks_project):
    line = _write_page(blocks_project, "overview.md", "{{cascade}}", front_matter=True)
    assert line == 8
    project = _build_at(blocks_project)
    d = _block_diagnostic(
        project, "missing required parameter 'from'", "pages/overview.md"
    )
    assert d.line == line


def test_tree_block_diagnostic_reports_file_line(blocks_project):
    line = _write_page(
        blocks_project, "overview.md", '{{tree bogus="x"}}', front_matter=True
    )
    assert line == 8
    project = _build_at(blocks_project)
    d = _block_diagnostic(project, "unknown parameter 'bogus'", "pages/overview.md")
    assert d.line == line


def test_calcblock_block_diagnostic_reports_file_line(blocks_project):
    line = _write_page(
        blocks_project, "overview.md", "{{calcblock}}", front_matter=True
    )
    assert line == 8
    project = _build_at(blocks_project)
    d = _block_diagnostic(
        project, "missing required parameter 'item'", "pages/overview.md"
    )
    assert d.line == line


# ----------------------------------------------------------------- the control


def test_page_without_front_matter_keeps_reporting_true_line(blocks_project):
    """No front matter -> body line == file line today; the fix must not
    shift these diagnostics."""
    line = _write_page(
        blocks_project, "control.md", '{{index type="decision"}}', front_matter=False
    )
    assert line == CONTROL_DIRECTIVE_LINE
    project = _build_at(blocks_project)
    d = _block_diagnostic(
        project, "missing required parameter 'by'", "pages/control.md"
    )
    assert d.line == line


# ------------------------------------------------------- invalid front matter


def test_invalid_front_matter_page_reports_true_line(blocks_project):
    """Invalid YAML front matter is not stripped: pages.py keeps the whole
    file as the body, so front_matter_lines stays 0 and the directive's
    body-relative line is already its file line."""
    text = "---\ntitle: [unclosed\n---\n\nProse first.\n\n{{compare}}\n"
    (blocks_project / "pages" / "broken.md").write_text(text, encoding="utf-8")
    directive_line = text.split("\n").index("{{compare}}") + 1
    assert directive_line == 7  # front matter 1-3, prose 5, directive 7
    project = _build_at(blocks_project)
    d = _block_diagnostic(
        project, "compare is missing required parameter 'type'", "pages/broken.md"
    )
    assert d.line == directive_line
