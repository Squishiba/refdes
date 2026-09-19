"""Bare `<img src>` filenames resolved against the `site.assets:` search path.

docs/design/backlog.md finding 36: `#include <foo.h>` semantics -- the declared
list is `site.assets:` itself, a src that resolves relative to its own source
file keeps winning, and a leaf name found in more than one declared directory
is an error at the reference site, never a silent first-match pick.
"""

from __future__ import annotations

import hashlib
import os

from conftest import write_project_config
from helpers import COVERAGE_SCHEMA, _build_and_render

from refdes import build as build_mod
from refdes import parse
from refdes.schema import load_project

PNG = b"\x89PNG\r\n\x1a\n"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _config(assets: str) -> str:
    return COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        f'site: {{title: "Coverage Test", out: _site, assets: [{assets}]}}',
    )


def _item(root, body: str):
    items = root / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(
        "---\nid: DEC-A-001\ntype: decision\ntitle: One image.\nstatus: accepted\n---\n\n"
        + body,
        encoding="utf-8",
    )


def _load(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


# ---------------------------------------------------------------- the search


def test_bare_filename_resolves_from_a_search_directory(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _load(tmp_path)

    assert not project.errors
    html = project.item_by_id("DEC-A-001").body_html
    assert 'src="assets/shots/board.png"' in html
    out = _build_and_render(tmp_path)
    assert os.path.isfile(os.path.join(out, "assets", "shots", "board.png"))


def test_bare_filename_found_in_two_search_dirs_errors_naming_both(tmp_path):
    write_project_config(tmp_path, _config("power, thermal"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "power").mkdir()
    (tmp_path / "thermal").mkdir()
    (tmp_path / "power" / "board.png").write_bytes(PNG)
    (tmp_path / "thermal" / "board.png").write_bytes(PNG)

    project = _load(tmp_path)

    messages = [d.message for d in project.errors]
    assert any("ambiguous" in m for m in messages)
    failing = next(m for m in messages if "ambiguous" in m)
    assert "power/board.png" in failing and "thermal/board.png" in failing
    # Never a first-match pick: the reference is left unrewritten, so the page
    # cannot silently carry one of the two candidates. (Both files are still
    # copied into _site/assets by `site.assets:` bulk-copy, as always.)
    html = project.item_by_id("DEC-A-001").body_html
    assert 'src="board.png"' in html
    assert "assets/power/board.png" not in html and "assets/thermal/board.png" not in html
    diag = next(d for d in project.errors if "ambiguous" in d.message)
    assert diag.file == "items/dec-a.md"
    assert diag.item_id == "DEC-A-001"


def test_ambiguous_leaf_names_are_silent_when_nothing_references_them(tmp_path):
    write_project_config(tmp_path, _config("power, thermal"))
    _item(tmp_path, "No image here at all.\n")
    (tmp_path / "power").mkdir()
    (tmp_path / "thermal").mkdir()
    (tmp_path / "power" / "board.png").write_bytes(PNG)
    (tmp_path / "thermal" / "board.png").write_bytes(PNG)

    project = _load(tmp_path)

    assert not project.errors
    assert not any("ambiguous" in d.message for d in project.diagnostics)


def test_relative_path_that_exists_wins_over_the_search_path(tmp_path):
    """The precedence rule: a src that resolves relative to its own source file
    is used as-is, even when the same leaf name also sits on the search path."""
    write_project_config(tmp_path, _config("shots"))
    _item(tmp_path, "![the board](board.png)\n")
    beside = tmp_path / "items" / "board.png"
    beside.write_bytes(PNG)
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(b"\x89PNG\r\n\x1a\nOTHER")

    project = _load(tmp_path)

    assert not project.errors
    html = project.item_by_id("DEC-A-001").body_html
    assert f'assets/items/board.{_digest(PNG)}.png' in html
    assert "assets/shots/board.png" not in html


def test_bare_filename_found_nowhere_errors_naming_the_searched_dirs(tmp_path):
    write_project_config(tmp_path, _config("shots, more"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "shots").mkdir()

    project = _load(tmp_path)

    messages = [d.message for d in project.errors]
    failing = next(m for m in messages if "board.png" in m)
    assert "does not exist" in failing
    assert "shots" in failing and "more" in failing


def test_a_multi_segment_path_is_never_searched(tmp_path):
    """`shots/board.png` was written as a specific location; a failing one stays
    a plain does-not-exist error rather than resolving by leaf name."""
    write_project_config(tmp_path, _config("elsewhere"))
    _item(tmp_path, "![the board](shots/board.png)\n")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "board.png").write_bytes(PNG)

    project = _load(tmp_path)

    messages = [d.message for d in project.errors]
    assert any("shots/board.png" in m and "does not exist" in m for m in messages)
    assert not any("ambiguous" in m for m in messages)


def test_figure_attributes_still_work_on_a_searched_image(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    _item(tmp_path, '![the curve](curve.png){width=60% caption="Efficiency"}\n')
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "curve.png").write_bytes(PNG)

    project = _load(tmp_path)

    assert not project.errors
    html = project.item_by_id("DEC-A-001").body_html
    assert '<figure class="md-figure" style="width: 60%">' in html
    assert "<figcaption>Efficiency</figcaption>" in html
    assert 'src="assets/shots/curve.png"' in html


def test_searched_image_on_a_page_resolves_too(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    items = tmp_path / "items"
    items.mkdir()
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text("# Overview\n\n![the board](board.png)\n", encoding="utf-8")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    out = _build_and_render(tmp_path)

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors
    assert 'src="assets/shots/board.png"' in project.pages[0].body_html
    assert os.path.isfile(os.path.join(out, "assets", "shots", "board.png"))
