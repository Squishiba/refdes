"""Every non-.py file under src/refdes must be covered by a package-data glob.

`[tool.setuptools.package-data]` in pyproject.toml is the only thing that
copies the package's non-Python files (templates, standards yaml, static
assets) into a built distribution. A file matching none of its globs is
silently dropped from the wheel and only fails at RUNTIME on an installed
copy -- exactly how templates/taskpane/ shipped broken in W5a: the pane's
assets are copied to the site by render.py's `_write_taskpane_assets`
(copyfile straight out of the package directory), so a wheel without them
raises FileNotFoundError on any build with a pane. The whole class of
"added a data file, forgot the glob" is guarded here instead of one file
at a time.

Match semantics are `glob.translate(recursive=True)`'s for the tokens the
compiler below understands (`*` and `?` within a path segment, `**` as a
whole segment matching zero or more segments, no leading dot matched),
compiled here instead of imported because `glob.translate` does not exist
on the oldest Python this project supports: CI on 3.11 fails the import
with `ImportError: cannot import name 'translate' from 'glob'` (run
38256138855), so the module never even collected. The compiler's output is
checked against `glob.glob(pattern, recursive=True)` over the real file
set (see the log). setuptools' fnmatch-style matching is at least as
permissive for these patterns, so a glob that matches here is included by
the real build.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "refdes"


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a setuptools-style glob into a pattern for `fullmatch`.

    Understands `*` and `?` within one path segment (never crossing a
    `/`) and `**` as a whole segment matching zero or more segments, and
    never matches a segment starting with a dot -- i.e. what
    `glob.translate(pattern, recursive=True)` produces, on a Python that
    has it at all, for the globs this project declares (each pattern was
    diffed against `glob.glob(pattern, recursive=True)` over the real file
    set; see in-prog-logs/workbench-w5a-task-pane.txt, round 6). A
    trailing `**` is not handled (no declared glob uses one).
    """
    out: list[str] = []
    segments = pattern.split("/")
    previous_was_recursive = False
    for index, segment in enumerate(segments):
        recursive = segment == "**" and index < len(segments) - 1
        if index > 0 and not previous_was_recursive:
            out.append("/")
        previous_was_recursive = recursive
        if recursive:
            out.append("(?:[^/.][^/]*/)*")
            continue
        body = "".join(
            "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
            for char in segment
        )
        out.append("(?!\\.)" + body)
    return re.compile("".join(out))


def _package_data_globs() -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    return pyproject["tool"]["setuptools"]["package-data"]["refdes"]


def _data_files() -> list[str]:
    return sorted(
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".py"
    )


def test_every_data_file_matches_a_package_data_glob() -> None:
    globs = _package_data_globs()
    assert globs, "pyproject.toml declares no refdes package-data globs"
    patterns = [_glob_to_regex(glob) for glob in globs]
    missing = [
        rel
        for rel in _data_files()
        if not any(rx.fullmatch(PurePosixPath(rel).as_posix()) for rx in patterns)
    ]
    assert not missing, (
        "files match no package-data glob and would be dropped from the wheel: "
        + ", ".join(missing)
    )
