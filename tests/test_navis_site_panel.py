"""Navis slice 4a: the read-only site panel (in-prog-logs/navis-design-20261025.md §11, §13).

The published site shows the panel ONLY when the project has at least one
Navi (an active marker or an archive record): active Navis first (text,
source-item link, short key), then a Show-all section carrying the archived
rows marked `[archived]` with the record's snapshot text (plus the §9
row-4 "marker text has changed since archived" note), orphan records
labelled "marker not found", and the restore control rendered DISABLED --
the published site is read-only (PR #396 provisional decision 4; design
§11: restore shown disabled with a "run `refdes navis restore`" hint).

The panel is static HTML+CSS: `<details>` is the open/close control, the
data rides the page server-side (the task pane's "fetches nothing"
contract), and no project with Navis gets a navis.js. The `navis.css`
asset is gated exactly like the task pane's pair (the
`_write_taskpane_assets` posture): a Navi-free project publishes no asset,
no `<link>`, no markup -- byte-identical output, verified against
`origin/main` by the differential at the bottom (with and without a
pre-existing `.refdes/`).

The panel data is one `navis.projection` per render (the standing rule for
task-pane data, PR #197 review P4) -- the render-site test counts the calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile

import pytest
from conftest import write_project_config
from test_navis_archive import SRC, REPO

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys, navis as navis_mod, navis_panel as navis_panel_mod, parse, render
from refdes.schema import load_project

SCHEMA = (
    "site: { title: Navis Panel, out: _site }\n"
    "on_change: { default: invalidate }\n"
    "types:\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields:\n"
    "      title: { type: text, required: true, on_change: invalidate }\n"
    "    body: { on_change: invalidate }\n"
)

ACTIVE_TEXT = "Active alpha reminder."
SNAPSHOT_TEXT = "Gamma before the edit"
EDITED_TEXT = "Gamma after the edit"
ORPHAN_TEXT = "Beta archived then deleted"


def _files(keys: list[str]) -> dict[str, str]:
    return {
        "note-a.md": (
            "---\nid: NOTE-001\ntype: note\ntitle: Alpha\n---\n"
            f"intro\n<!--navi:{keys[0]} {ACTIVE_TEXT}-->\n"
        ),
        # archived, then the marker is hand-deleted: the §9 row-3 orphan.
        "note-b.md": (
            "---\nid: NOTE-002\ntype: note\ntitle: Beta\n---\n"
            f"intro\n<!--navi:{keys[1]} {ORPHAN_TEXT}-->\n"
        ),
        # archived, then the marker text is edited: §9 row 4.
        "note-c.md": (
            "---\nid: NOTE-003\ntype: note\ntitle: Gamma\n---\n"
            f"intro\n<!--navi:{keys[2]} {SNAPSHOT_TEXT}-->\n"
        ),
    }


def _run(config: str, *args: str) -> int:
    return cli_mod.main(["-c", config, *args])


def _navi_project(tmp_path, schema: str = SCHEMA) -> str:
    """A project with one active Navi and two archive records -- one whose
    marker was hand-deleted (orphan), one whose marker text was edited
    after archiving -- built the way the tool builds it: writable CLI run
    (the records), then the plain build+render pass the site ships through."""
    config = str(write_project_config(tmp_path, schema))
    items = tmp_path / "items"
    items.mkdir()
    minted = [keys.mint() for _ in range(3)]
    for name, text in _files(minted).items():
        (items / name).write_text(text, encoding="utf-8", newline="")
    for key in minted[1:]:
        assert _run(config, "navis", "archive", key) == 0
    # the two §9 edits, after the records exist (the archive is the
    # snapshot). The hand-deletion removes ONLY the marker line -- a real
    # author deleting a marker leaves the item's own front-matter (and its
    # minted key) in place, so the orphan row resolves to the item page and
    # must show the §9 row-3 label next to its link, not instead of it.
    note_b = items / "note-b.md"
    note_b.write_text(
        "".join(
            line
            for line in note_b.read_text(encoding="utf-8").splitlines(keepends=True)
            if "navi:" not in line
        ),
        encoding="utf-8",
        newline="",
    )
    (items / "note-c.md").write_text(
        "---\nid: NOTE-003\ntype: note\ntitle: Gamma\n---\n"
        f"intro\n<!--navi:{minted[2]} {EDITED_TEXT}-->\n",
        encoding="utf-8",
        newline="",
    )
    return config


def _render(config: str) -> str:
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors, [str(d) for d in project.errors]
    return render.render_site(project)


def _page(out: str, name: str) -> str:
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def site(tmp_path):
    config = _navi_project(tmp_path)
    return _render(config), config


def test_panel_appears_on_item_and_dashboard_pages(site):
    out, _ = site
    for page in ("index.html", "note-001.html", "note-003.html"):
        assert 'class="refdes-navis"' in _page(out, page), page


def test_active_rows_show_text_short_key_and_source_link(site):
    out, _ = site
    html = _page(out, "index.html")
    assert ACTIVE_TEXT in html
    row = html[html.index(ACTIVE_TEXT) - 400 : html.index(ACTIVE_TEXT)]
    assert 'href="note-001.html"' in row  # the source item's page
    # The 6-char short key (§7), read back from the rendered payload's own
    # first (active) row -- independent of how the fixture minted the key.
    with open(os.path.join(out, "items.json"), encoding="utf-8") as fh:
        active_key = json.load(fh)["navis"][0]["key"]
    assert f'<span class="mono">{active_key[:navis_panel_mod.KEY_PREFIX]}</span>' in row
    assert 'href="note-003.html"' in _page(out, "note-001.html")  # archived link


def test_show_all_lists_archived_by_snapshot_with_its_label(site):
    out, _ = site
    html = _page(out, "index.html")
    assert "Show all" in html
    assert SNAPSHOT_TEXT in html
    assert "[archived]" in html
    # §9 row 4: the panel shows the snapshot, never a re-snapshot: the
    # marker's live text is nowhere on the page (the marker is consumed).
    assert EDITED_TEXT not in html


def test_changed_marker_note_on_the_archived_row(site):
    out, _ = site
    html = _page(out, "index.html")
    assert "marker text has changed since archived" in html
    note_at = html.index("marker text has changed since archived")
    assert SNAPSHOT_TEXT in html[note_at - 600 : note_at]  # rides the same row


def test_orphan_row_labelled_marker_not_found(site):
    out, _ = site
    html = _page(out, "index.html")
    assert "marker not found" in html
    assert ORPHAN_TEXT in html  # the row IS the record (§9 row 3)


def test_orphan_label_and_link_coexist_on_the_row(site):
    """§9 row 3: the SOURCE is labelled "marker not found"; the record's
    stored item key still names a live item, so the row links to its page
    as well (Chromium fixture, 2026-10-31: the label must not be traded
    for the link)."""
    out, _ = site
    html = _page(out, "index.html")
    li = html[html.index("marker not found") - 400 : html.index("marker not found")]
    assert 'href="note-002.html"' in li


def test_active_rows_precede_archived_rows_in_show_all(site):
    out, _ = site
    html = _page(out, "index.html")
    assert html.index(ACTIVE_TEXT) < html.index(SNAPSHOT_TEXT)


def test_restore_control_is_rendered_disabled_with_the_cli_hint(site):
    out, _ = site
    html = _page(out, "index.html")
    assert "<button" in html and "disabled" in html
    assert "refdes navis restore" in html


def test_panel_asset_emitted_and_linked(site):
    out, _ = site
    assert os.path.isfile(os.path.join(out, "assets", "navis.css"))
    assert 'href="assets/navis.css"' in _page(out, "index.html")
    # §11's z-index stack: the panel sits above the task pane's 62/63.
    with open(os.path.join(out, "assets", "navis.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert "z-index: 65" in css
    manifest = _page(out, ".refdes-manifest.json")
    assert "assets/navis.css" in manifest


def test_no_javascript_ships_with_the_panel(site):
    out, _ = site
    assert not os.path.isfile(os.path.join(out, "assets", "navis.js"))


def test_project_asset_named_navis_css_is_refused_when_the_panel_emits(tmp_path):
    schema = SCHEMA.replace(
        "site: { title: Navis Panel, out: _site }",
        "site: { title: Navis Panel, out: _site, assets: [navis.css] }",
    )
    config = _navi_project(tmp_path, schema=schema)
    (tmp_path / "navis.css").mkdir()
    (tmp_path / "navis.css" / "brand.css").write_text(
        "BRANDMARKER\n", encoding="utf-8", newline=""
    )
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project)
    out = render.render_site(project)
    assert any(
        "would be written to assets/navis.css" in d.message for d in project.errors
    )
    with open(os.path.join(out, "assets", "navis.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert "BRANDMARKER" not in css  # the panel's own stylesheet survived
    assert ".refdes-navis" in css


# ---------------------------------------------------------------------------
# the gate: a project with no Navis publishes no panel, no asset, no link
# ---------------------------------------------------------------------------


def test_navis_free_project_emits_no_panel_and_no_asset(tmp_path):
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "note-a.md").write_text(
        "---\nid: NOTE-001\ntype: note\ntitle: Plain\n---\nplain body.\n",
        encoding="utf-8",
        newline="",
    )
    out = _render(config)
    html = _page(out, "index.html")
    assert "refdes-navis" not in html
    assert "assets/navis.css" not in html
    assert not os.path.isfile(os.path.join(out, "assets", "navis.css"))
    assert "assets/navis.css" not in _page(out, ".refdes-manifest.json")


def test_render_site_projects_the_navis_exactly_once(site, monkeypatch):
    out, config = site
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project)
    calls: list = []
    real = navis_mod.projection

    def counting(p):
        calls.append(p)
        return real(p)

    monkeypatch.setattr(navis_mod, "projection", counting)
    render.render_site(project)
    assert len(calls) == 1
    assert os.path.isdir(out)  # the fixture's site is untouched by the probe


# ---------------------------------------------------------------------------
# the differential: a Navi-free project builds byte-identical to main
# ---------------------------------------------------------------------------


def _git_tree(ref: str, dest: str) -> str | None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.run(
        ["git", "-C", REPO, "archive", ref],
        stdout=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    import io

    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        members = [
            m for m in tar.getmembers()
            if m.name == "src" or m.name.startswith("src/")
        ]
        tar.extractall(dest, members=members, filter="data")
    return os.path.join(dest, "src")


DIFFERENTIAL_FILES = {
    "note-a.md": (
        "---\nid: NOTE-001\ntype: note\ntitle: Power\n---\n"
        "plain body, no marker\n"
    ),
    "memo-crlf.md": (
        "---\nid: MEMO-001\ntype: note\ntitle: M\n---\r\n"
        "para\r\nplain\r\n"
    ),
}


def _write_items(root: str) -> None:
    from pathlib import Path

    items = Path(root) / "items"
    items.mkdir(exist_ok=True)
    for name, text in DIFFERENTIAL_FILES.items():
        (items / name).write_text(text, encoding="utf-8", newline="")


def _write_differential_project(root: str) -> str:
    from pathlib import Path

    Path(root).mkdir(parents=True, exist_ok=True)
    write_project_config(Path(root), SCHEMA)
    _write_items(root)
    return str(Path(root) / "refdes-project.yaml")


def _build_with(src_root: str, config: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=src_root)
    return subprocess.run(
        [sys.executable, "-m", "refdes.cli", "-c", config, "--no-write", "build"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _tree_paths(root: str) -> dict[str, bytes]:
    """Every regular file under the project, {relpath: bytes}, the lock
    file excluded -- the published site IS compared: the build is
    deterministic, so `_site` is project output like any other (the
    slice-3 differential's posture, test_navis_archive.py)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if name == ".refdes-write.lock":
                continue
            with open(path, "rb") as fh:
                out[rel] = fh.read()
    return out


@pytest.mark.parametrize("with_refdes", [False, True])
def test_navis_free_project_builds_byte_identical_to_main(tmp_path, with_refdes):
    main_tree = _git_tree("origin/main", str(tmp_path / "main-tree"))
    if main_tree is None:
        pytest.skip("origin/main not available to diff against")
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    cfg_a = _write_differential_project(a)
    cfg_b = _write_differential_project(b)
    if with_refdes:
        # an existing .refdes/: warm build in the main tree (writable),
        # items back to fixture bytes, the warmed state handed to both
        # trees -- exactly the slice-3 differential's choreography.
        warm = subprocess.run(
            [sys.executable, "-m", "refdes.cli", "-c", cfg_a, "build"],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONPATH=main_tree),
            check=False,
        )
        assert warm.returncode == 0, warm.stderr
        import shutil

        shutil.rmtree(os.path.join(a, "items"))
        _write_items(a)
        shutil.copytree(os.path.join(a, ".refdes"), os.path.join(b, ".refdes"))
    ra = _build_with(main_tree, cfg_a)
    rb = _build_with(SRC, cfg_b)
    assert ra.returncode == 0, ra.stderr
    assert rb.returncode == 0, rb.stderr
    tree_a, tree_b = _tree_paths(a), _tree_paths(b)
    assert set(tree_a) == set(tree_b), set(tree_a) ^ set(tree_b)
    for rel in tree_a:
        assert tree_a[rel] == tree_b[rel], f"build output differs: {rel}"
