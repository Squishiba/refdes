"""f13-4: an unparseable page front-matter warns exactly once per page, and
names the FILE line of the problem.

Two facts drive this file, both reproduced through the *real* CLI entry
``cli.main([...])`` with ``capsys``:

* The double load. ``cli._load`` -> ``loader.load_tree`` -> (when writable)
  ``image_freeze.freeze_images`` -> ``pages.load_pages`` runs a page load, and
  ``cmd_check``/``cmd_build`` then run ``build()`` -> ``pages.load_pages``
  again. Both append a ``invalid page front-matter:`` warning, so a writable
  ``check``/``build`` printed it twice. (The ``_build_at`` helper does NOT
  reproduce this: it skips ``load_tree``/``freeze_images``, so it loads pages
  once. Only the CLI path reproduces the double load -- which is why every test
  here drives ``cli.main``.)
* The missing line. ``pages._read_page`` warned with ``file=rel_to_root`` and
  no ``line``, so unlike every other page diagnostic it named no line. The
  YAML excerpt embedded in the message ("line 1, column 8") is relative to the
  front-matter text, not the file.

The front-matter text is ``FRONTMATTER_RE.group(1)``: the opening ``---`` fence
is file line 1, so the first line of that group is file line 2 -- and the
regex's ``---\\s*\\n`` swallows blank line(s) after the fence, pushing the group
further down. ``yaml``'s ``problem_mark.line`` is 0-based within the group, so
the file line is ``<group-start file line> + problem_mark.line``. Each test
below computes the expected file line by hand from the text it writes.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import cli

# Pages-only project: a `pages:` site, an id block, and one trivial type so the
# schema is valid. No items are required for a docs site to check/build.
COMBINED = (
    "site:\n  title: Docs\n  out: _site\n  pages: pages\n"
    "id:\n  width: 3\n"
    "types:\n  note:\n    prefix: NOTE\n"
)

MARKER = "invalid page front-matter"
PAGE = "badyaml.md"


def _project(tmp_path, page_text: str):
    write_project_config(tmp_path, COMBINED)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / PAGE).write_text(page_text, encoding="utf-8")
    return tmp_path


def _captured(capsys) -> str:
    """stdout+stderr combined. Diagnostics print to stdout (warnings) / stderr
    (errors); the front-matter warning lands on stdout, but we count over both
    so the assertion does not depend on the stream choice."""
    cap = capsys.readouterr()
    return cap.out + cap.err


# --------------------------------------------------------------- the line cases


def test_bad_front_matter_at_top_names_file_line_on_check(tmp_path, capsys):
    """`title: [unclosed` is the 2nd line of the front-matter text's first
    line, and the front-matter text starts at file line 2 (the opening `---`
    is line 1), so the diagnostic must name `pages/badyaml.md:2` -- not print
    YAML's front-matter-relative "line 1, column 8"."""
    root = _project(tmp_path, "---\ntitle: [unclosed\n---\n\n# Bad\n\nProse.\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out
    assert f"pages/{PAGE}:2" in out, out
    assert f"{MARKER}:" in out, out
    assert "line 1, column" not in out, out


def test_bad_front_matter_on_later_line_names_file_line(tmp_path, capsys):
    """The flow-sequence error is on the 2nd line of the front-matter text
    (0-based ``problem_mark.line`` 1). The text starts at file line 2, so the
    file line is 2 + 1 = 3 (the `status:` line)."""
    root = _project(
        tmp_path, "---\ntitle: Hello\nstatus: [unclosed\n---\n\nBody\n"
    )
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out
    assert f"pages/{PAGE}:3" in out, out
    assert "line 2, column" not in out, out


def test_blank_line_after_fence_shifts_file_line(tmp_path, capsys):
    """FRONTMATTER_RE's opening fence is ``---\\s*\\n``: the ``\\s*`` swallows a
    blank line right after the fence, so the front-matter text starts at file
    line 3 (not 2). ``problem_mark.line`` 0 -> file line 3."""
    root = _project(tmp_path, "---\n\ntitle: [unclosed\n---\n\nBody\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out
    assert f"pages/{PAGE}:3" in out, out
    assert "line 1, column" not in out, out


def test_deep_line_in_front_matter_names_file_line(tmp_path, capsys):
    """Bad value on the 3rd line of the front-matter text (``problem_mark.line``
    2). Text starts at file line 2 -> file line 4 (the `c:` line)."""
    root = _project(tmp_path, "---\na: 1\nb: 2\nc: [x\n---\nBody\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out
    assert f"pages/{PAGE}:4" in out, out
    assert "line 3, column" not in out, out


def test_no_mark_falls_back_to_fence_line(tmp_path, capsys):
    """A NUL byte in the front matter raises a ``ReaderError`` (a ``YAMLError``
    with NO ``problem_mark``). With no mark the diagnostic falls back to the
    line of the opening ``---`` fence -- file line 1."""
    root = _project(tmp_path, "---\ntitle: \x00bad\n---\n\nBody\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out
    assert f"pages/{PAGE}:1" in out, out


# ------------------------------------------------------- exactly-once per command


def test_warning_printed_once_on_check(tmp_path, capsys):
    """Writable ``check`` loads the page twice (freeze_images + build); the
    warning must be reported exactly once."""
    root = _project(tmp_path, "---\ntitle: [unclosed\n---\n\n# Bad\n\nProse.\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out


def test_warning_printed_once_on_build(tmp_path, capsys):
    """Writable ``build`` loads the page twice; the warning must be reported
    exactly once."""
    root = _project(tmp_path, "---\ntitle: [unclosed\n---\n\n# Bad\n\nProse.\n")
    cli.main(
        [
            "-c",
            str(root / "refdes-project.yaml"),
            "build",
            "-o",
            str(root / "_site"),
        ]
    )
    out = _captured(capsys)
    assert out.count(MARKER) == 1, out


# -------------------------------------------------------------------- controls


def test_valid_front_matter_produces_no_warning(tmp_path, capsys):
    """A page with valid front matter is unchanged: no front-matter warning."""
    root = _project(tmp_path, "---\ntitle: Hello\norder: 5\n---\n\n# Hello\n\nProse.\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert MARKER not in out, out


def test_no_front_matter_produces_no_warning(tmp_path, capsys):
    """A page with no front matter at all is unchanged: no front-matter
    warning."""
    root = _project(tmp_path, "# Plain page\n\nJust prose, no fences.\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert MARKER not in out, out


def test_blank_line_before_fence_is_not_front_matter(tmp_path, capsys):
    """FRONTMATTER_RE anchors the opening ``---`` at the very start of the file
    (re.match), so a page whose first line is blank has NO front matter -- the
    unparseable-looking block below is body, and nothing is warned about."""
    root = _project(tmp_path, "\n---\ntitle: [unclosed\n---\n\nBody\n")
    cli.main(["-c", str(root / "refdes-project.yaml"), "check"])
    out = _captured(capsys)
    assert MARKER not in out, out
