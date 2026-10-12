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

Match semantics follow `glob.translate(recursive=True)` (setuptools'
fnmatch-style matching is at least as permissive for these patterns, so a
glob that matches here is included by the real build).
"""

from __future__ import annotations

import tomllib
from glob import translate
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "refdes"


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
    patterns = [re.compile(translate(glob, recursive=True)) for glob in globs]
    missing = [
        rel
        for rel in _data_files()
        if not any(rx.fullmatch(PurePosixPath(rel).as_posix()) for rx in patterns)
    ]
    assert not missing, (
        "files match no package-data glob and would be dropped from the wheel: "
        + ", ".join(missing)
    )
