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
from refdes import loader, parse
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


def test_the_missing_image_sentence_is_grammatical_with_and_without_assets(tmp_path):
    """Both branches share one parenthetical, and neither may run on. With
    `site.assets:` declared the clause is "searched the site.assets
    directories: ..."; with none declared there is nothing that was searched,
    so the sentence has to end differently rather than prefixing a second
    clause with "searched"."""
    write_project_config(tmp_path, _config("shots, more"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "shots").mkdir()

    declared = _load(tmp_path)
    with_assets = next(
        d.message for d in declared.errors if "board.png" in d.message
    )
    assert with_assets == (
        "image src 'board.png' does not exist "
        "(searched the site.assets directories: shots, more)"
    )

    bare = tmp_path / "bare"
    bare.mkdir()
    write_project_config(bare, COVERAGE_SCHEMA)
    _item(bare, "![the board](board.png)\n")

    undeclared = _load(bare)
    without_assets = next(
        d.message for d in undeclared.errors if "board.png" in d.message
    )
    assert without_assets == (
        "image src 'board.png' does not exist "
        "(no site.assets directories are declared to search)"
    )
    # The specific failure this pins: two clauses welded into one.
    assert "searched no site.assets" not in without_assets


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


# ----------------------------------------------------------- resolve and freeze


def _writable_load(root, write=True):
    project, _stale = loader.load_tree(str(root / "refdes-project.yaml"), write=write)
    build_mod.build(project)
    return project


def test_unique_search_freezes_source_and_survives_later_collision_and_document_move(tmp_path):
    write_project_config(tmp_path, _config("shots, later"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    first = _writable_load(tmp_path)
    source = tmp_path / "items" / "dec-a.md"
    assert not first.errors
    assert "![the board](/shots/board.png)" in source.read_text()
    assert first.load_writes.rewritten_images == 1

    (tmp_path / "later").mkdir()
    (tmp_path / "later" / "board.png").write_bytes(b"other")
    moved = tmp_path / "items" / "nested" / "dec-a.md"
    moved.parent.mkdir()
    source.rename(moved)
    again = _writable_load(tmp_path)
    assert not again.errors
    assert again.load_writes.rewritten_images == 0
    assert 'src="assets/shots/board.png"' in again.item_by_id("DEC-A-001").body_html


def test_freeze_skips_relative_url_missing_ambiguous_multisegment_and_code(tmp_path):
    write_project_config(tmp_path, _config("shots, later"))
    body = (
        "![beside](beside.png)\n\n![url](https://example.com/image.png)\n\n"
        "![missing](missing.png)\n\n![ambiguous](dupe.png)\n\n"
        "![specific](wrong/unique.png)\n\n```md\n![code](unique.png)\n```\n\n"
        "![unique](unique.png)\n"
    )
    _item(tmp_path, body)
    (tmp_path / "items" / "beside.png").write_bytes(PNG)
    (tmp_path / "shots").mkdir()
    (tmp_path / "later").mkdir()
    for directory in ("shots", "later"):
        (tmp_path / directory / "dupe.png").write_bytes(PNG)
    (tmp_path / "shots" / "unique.png").write_bytes(PNG)

    project = _writable_load(tmp_path)
    source = (tmp_path / "items" / "dec-a.md").read_text()
    assert project.load_writes.rewritten_images == 1
    assert "![unique](/shots/unique.png)" in source
    for original in (
        "![beside](beside.png)", "![url](https://example.com/image.png)",
        "![missing](missing.png)", "![ambiguous](dupe.png)",
        "![specific](wrong/unique.png)", "![code](unique.png)",
    ):
        assert original in source
    messages = [d.message for d in project.errors]
    assert any("missing.png" in m and "does not exist" in m for m in messages)
    assert any("dupe.png" in m and "ambiguous" in m for m in messages)
    assert any("wrong/unique.png" in m and "does not exist" in m for m in messages)


def test_no_write_keeps_bare_source_but_resolves_in_memory(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    _item(tmp_path, "![the board](board.png)\n")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _writable_load(tmp_path, write=False)
    assert not project.errors
    assert project.load_writes.rewritten_images == 0
    assert "![the board](board.png)" in (tmp_path / "items" / "dec-a.md").read_text()
    assert 'src="assets/shots/board.png"' in project.item_by_id("DEC-A-001").body_html


def test_page_search_freezes_source(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    (tmp_path / "items").mkdir()
    (tmp_path / "pages").mkdir()
    page = tmp_path / "pages" / "index.md"
    # pages._read_page normalizes these line endings when it loads the body;
    # the freeze writer must still locate that body in the raw source bytes.
    page.write_bytes(b"# Overview\r\n\r\n![the board](board.png)\r\n")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _writable_load(tmp_path)
    assert not project.errors
    assert page.read_bytes() == b"# Overview\r\n\r\n![the board](/shots/board.png)\r\n"
    assert 'src="assets/shots/board.png"' in project.pages[0].body_html

    # The body starts after front matter here, so its normalized offset is
    # nonzero even though the physical file still uses CRLF throughout.
    page.write_bytes(b"---\r\ntitle: Overview\r\n---\r\n\r\n![the board](board.png)\r\n")
    project = _writable_load(tmp_path)
    assert not project.errors
    assert page.read_bytes() == (
        b"---\r\ntitle: Overview\r\n---\r\n\r\n![the board](/shots/board.png)\r\n"
    )


def test_multiline_and_angle_spelling_freeze_without_touching_code(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    _item(
        tmp_path,
        "![multiline](\nboard.png)\n\n![angle](<board.png>)\n\n"
        "`![code](board.png)`\n",
    )
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _writable_load(tmp_path)
    source = (tmp_path / "items" / "dec-a.md").read_text()
    assert not project.errors
    assert project.load_writes.rewritten_images == 2
    assert "![multiline](\n/shots/board.png)" in source
    assert "![angle](</shots/board.png>)" in source
    assert "`![code](board.png)`" in source


def test_yaml_list_bodies_freeze_without_reformatting(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    (tmp_path / "items").mkdir()
    source = tmp_path / "items" / "decisions.yaml"
    source.write_text(
        "items:\n"
        "  - id: DEC-A-001\n    type: decision\n    title: Block\n"
        "    status: accepted\n    body: |\n      ![block](board.png)\n"
        "      `![code](board.png)`\n"
        "  - id: DEC-A-002\n    type: decision\n    title: Inline\n"
        "    status: accepted\n    body: \"![inline](board.png)\"\n"
    )
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _writable_load(tmp_path)
    contents = source.read_text()
    assert not project.errors
    assert project.load_writes.rewritten_images == 2
    assert "      ![block](/shots/board.png)\n" in contents
    assert 'body: "![inline](/shots/board.png)"' in contents
    assert "`![code](board.png)`" in contents


def test_freeze_preserves_crlf_source(tmp_path):
    write_project_config(tmp_path, _config("shots"))
    _item(tmp_path, "![board](board.png)\n")
    source = tmp_path / "items" / "dec-a.md"
    # Path.write_text in _item already writes CRLF on Windows. Normalize the
    # fixture first, then write exact bytes so a doubled CR cannot be mistaken
    # for a failure of the freeze writer.
    source.write_bytes(source.read_text().replace("\n", "\r\n").encode("utf-8"))
    before = source.read_bytes()
    assert b"\r\r\n" not in before
    assert before.count(b"\r\n") == before.count(b"\n")
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "board.png").write_bytes(PNG)

    project = _writable_load(tmp_path)
    data = source.read_bytes()
    assert not project.errors
    assert b"![board](/shots/board.png)\r\n" in data
    assert b"\r\r\n" not in data
    assert data.count(b"\n") == data.count(b"\r\n")
