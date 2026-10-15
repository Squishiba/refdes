"""`site.assets:` directories confined to the project root (IMAGE-ASSET-006).

An escaping entry (`../`, an absolute path, a symlink out of the tree) makes
the build copy, the bare-name image search, the serve poller's revision
hashes, and the upload search-path check walk files outside the project --
the poller silently hashed a byte-matched secret at `proj/../secret.txt`.
The refusal happens at load (`schema._confined_asset_dirs`), the one seam
every asset reader reads through: no Project, no walk, no hash. The rule
mirrors `citations.classify`: project-relative, slash-separated, no
traversal, inside the root by real path.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from conftest import write_project_config
from helpers import COVERAGE_SCHEMA, _build_and_render

from refdes import build as build_mod
from refdes import parse
from refdes.schema import SchemaError, load_project
from refdes.serve import state as state_mod

PNG = b"\x89PNG\r\n\x1a\n"


def _config(assets: str) -> str:
    return COVERAGE_SCHEMA.replace(
        'site: {title: "Coverage Test", out: _site}',
        f'site: {{title: "Coverage Test", out: _site, assets: [{assets}]}}',
    )


def _load(root):
    return load_project(config_path=str(root / "refdes-project.yaml"))


# ------------------------------------------------------------ the refusals


@pytest.mark.parametrize(
    "entry",
    ["../", "../elsewhere", "figures/../../elsewhere", "a/b/../../../c"],
)
def test_a_traversal_entry_is_refused_at_load(tmp_path, entry):
    write_project_config(tmp_path, _config(f'"{entry}"'))
    with pytest.raises(SchemaError, match="escapes the project root"):
        _load(tmp_path)


def test_an_absolute_entry_is_refused_at_load(tmp_path):
    write_project_config(tmp_path, _config('"/tmp/elsewhere"'))
    with pytest.raises(SchemaError, match="is absolute"):
        _load(tmp_path)


def test_a_backslash_entry_is_refused_at_load(tmp_path):
    write_project_config(tmp_path, _config('"figures\\\\..\\\\elsewhere"'))
    with pytest.raises(SchemaError, match="backslash"):
        _load(tmp_path)


@pytest.mark.parametrize("entry", [".", "figures/..", ""])
def test_the_project_root_itself_is_refused_at_load(tmp_path, entry):
    """`.` (and its spellings) would walk the output directory and `.refdes/`
    state back into the published assets -- it is not a directory under the
    root, it is the root."""
    write_project_config(tmp_path, _config(f'"{entry}"'))
    with pytest.raises(SchemaError, match="project root itself"):
        _load(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_symlink_out_of_the_root_is_refused_at_load(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    os.symlink("../outside", str(root / "escape"))
    write_project_config(root, _config("escape"))
    with pytest.raises(SchemaError, match="resolves outside the project root"):
        load_project(config_path=str(root / "refdes-project.yaml"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_symlink_to_the_root_itself_is_refused_at_load(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    os.symlink(".", str(root / "selflink"))
    write_project_config(root, _config("selflink"))
    with pytest.raises(SchemaError, match="resolves to the project root itself"):
        load_project(config_path=str(root / "refdes-project.yaml"))


# --------------------------------------------------- outside bytes never read


def test_outside_root_bytes_are_never_read_or_hashed(tmp_path):
    """The poller's revision inputs stay inside the root: the file next to
    the project that IMAGE-ASSET-006's `assets: ["../"]` reproduction hashed
    byte-matched is neither listed nor digested for a confined project, and
    the escaping config produces no Project to poll at all."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    (root / "figures" / "a.png").write_bytes(PNG)
    secret = tmp_path / "secret.txt"
    secret.write_text("SENTINEL\n", encoding="utf-8")
    secret_digest = hashlib.sha256(b"SENTINEL\n").hexdigest()

    write_project_config(root, _config('"../"'))
    with pytest.raises(SchemaError):
        load_project(config_path=str(root / "refdes-project.yaml"))

    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    inputs = state_mod.project_inputs(project)
    hashes = state_mod.content_hashes(inputs, project.root)
    assert str(secret) not in inputs
    assert secret_digest not in hashes.values()
    root_real = os.path.realpath(str(root))
    assert all(
        os.path.realpath(p).startswith(root_real + os.sep) for p in inputs
    )


# ----------------------------------------------------- valid assets unaffected


def test_entries_are_canonicalized_not_rewritten(tmp_path):
    write_project_config(tmp_path, _config('"./pics/../shots", "shots/"'))
    assert _load(tmp_path).asset_dirs == ["shots", "shots"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_symlink_landing_inside_the_root_still_loads(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "real").mkdir()
    (root / "real" / "x.png").write_bytes(PNG)
    os.symlink("real", str(root / "link"))
    write_project_config(root, _config("link"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    assert project.asset_dirs == ["link"]
    assert str(root / "link" / "x.png") in state_mod.project_inputs(project)


def test_valid_asset_directories_still_build_and_publish(tmp_path):
    write_project_config(tmp_path, _config("figures, photos/shared"))
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(
        "---\nid: DEC-A-001\ntype: decision\ntitle: One image.\nstatus: accepted\n---\n\n"
        "![the board](board.png)\n",
        encoding="utf-8",
    )
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "board.png").write_bytes(PNG)

    project = _load(tmp_path)
    parse.load_items(project)
    build_mod.build(project)

    assert not project.errors
    assert 'src="assets/figures/board.png"' in project.item_by_id("DEC-A-001").body_html
    out = _build_and_render(tmp_path)
    assert os.path.isfile(os.path.join(out, "assets", "figures", "board.png"))


# ------------------------------------------- runtime: the tree moves after load
#
# The load-time refusals above judge the configuration; the tree itself keeps
# moving under the serve poller. `build.walk_site_assets` re-checks at walk
# time: a symlinked file pointing outside is never contained, and a declared
# directory retargeted into a symlink is never even enumerated.


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_file_symlink_out_of_the_root_is_never_hashed_by_the_poller(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    (tmp_path / "outside.png").write_bytes(PNG + b"SENTINEL")
    os.symlink("../../outside.png", str(root / "figures" / "sneaky.png"))
    write_project_config(root, _config("figures"))

    project = load_project(config_path=str(root / "refdes-project.yaml"))
    inputs = state_mod.project_inputs(project)

    assert str(root / "figures" / "sneaky.png") not in inputs
    digest = hashlib.sha256(PNG + b"SENTINEL").hexdigest()
    assert digest not in state_mod.content_hashes(inputs, project.root).values()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_retargeted_asset_directory_is_never_walked(tmp_path, monkeypatch):
    """A directory that was inside the root at load is swapped for a symlink
    out afterwards. The next walk must not enter it -- enumerating the
    outside tree is already reading information out of it."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "items").mkdir()  # a known in-root walk, to prove the spy saw walks at all
    (root / "figures").mkdir()
    (root / "figures" / "real.png").write_bytes(PNG)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.png"
    secret.write_bytes(PNG + b"SENTINEL")
    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))

    os.rename(root / "figures", str(outside / "moved"))
    os.symlink("../outside", str(root / "figures"))

    outside_real = os.path.realpath(str(outside))
    entered: list[str] = []
    real_walk = os.walk

    def spy(top, *args, **kwargs):
        entered.append(os.path.realpath(str(top)))
        return real_walk(top, *args, **kwargs)

    monkeypatch.setattr(os, "walk", spy)
    inputs = state_mod.project_inputs(project)

    assert entered, "the poller walked nothing at all"
    assert all(
        p != outside_real and not p.startswith(outside_real + os.sep) for p in entered
    )
    assert str(secret) not in inputs
    digest = hashlib.sha256(PNG + b"SENTINEL").hexdigest()
    assert digest not in state_mod.content_hashes(inputs, project.root).values()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_build_warns_and_publishes_nothing_from_a_retargeted_directory(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SENTINEL\n", encoding="utf-8")
    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))

    os.rename(root / "figures", str(outside / "moved"))
    os.symlink("../outside", str(root / "figures"))
    build_mod.collect_static_assets(project)

    assert project.assets == {}
    messages = [d.message for d in project.warnings]
    assert any(
        "figures" in m and "resolves outside the project root" in m for m in messages
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_an_escaping_file_symlink_is_not_published_and_warns(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    (tmp_path / "outside.png").write_bytes(PNG)
    os.symlink("../../outside.png", str(root / "figures" / "sneaky.png"))
    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))

    build_mod.collect_static_assets(project)

    assert "figures/sneaky.png" not in project.assets
    messages = [d.message for d in project.warnings]
    assert any(
        "figures/sneaky.png" in m and "resolves outside the project root" in m
        for m in messages
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_an_escaping_file_symlink_cannot_satisfy_the_bare_name_search(tmp_path):
    """The watcher, the publisher, and the image search all read the same
    walk, so a file none of them can read is not an image the search may
    land on either: the reference is the honest unresolved error."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    (tmp_path / "sneaky.png").write_bytes(PNG)
    os.symlink("../../sneaky.png", str(root / "figures" / "sneaky.png"))
    items = root / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(
        "---\nid: DEC-A-001\ntype: decision\ntitle: One image.\nstatus: accepted\n---\n\n"
        "![the board](sneaky.png)\n",
        encoding="utf-8",
    )
    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    assert any("does not exist" in d.message for d in project.errors)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_a_file_symlink_landing_inside_the_root_still_counts(tmp_path):
    """The confinement rule is about the root, not about symlinks per se:
    an interior symlinked file is a perfectly good asset."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "figures").mkdir()
    (root / "inside.png").write_bytes(PNG)
    os.symlink("../inside.png", str(root / "figures" / "linked.png"))
    write_project_config(root, _config("figures"))
    project = load_project(config_path=str(root / "refdes-project.yaml"))

    build_mod.collect_static_assets(project)

    assert "figures/linked.png" in project.assets
    assert str(root / "figures" / "linked.png") in state_mod.project_inputs(project)
    assert project.warnings == []
