"""Content-revision polling, external-change detection, and advisory git
(docs/design/browser-editor.md, "Preview freshness" / "Revision and conflict
detection"). The revision is a hash of file *content*: never mtime, never git."""

from __future__ import annotations

import os
import subprocess
import time

import pytest
from conftest import write_project_config
from serve_support import SERVE_SCHEMA, Client, make_project

from refdes.serve.server import EditorApp
from refdes.serve.state import Poller, ProjectState, git_status, project_inputs


@pytest.fixture
def state(tmp_path):
    st = ProjectState(make_project(tmp_path))
    st.load()
    return st, tmp_path


def test_revision_is_stable_across_loads_of_the_same_bytes(tmp_path):
    config = make_project(tmp_path)
    a, b = ProjectState(config), ProjectState(config)
    assert a.load().revision == b.load().revision


def test_inputs_cover_config_items_and_state_but_not_disposables(state):
    st, root = state
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "schema.json").write_text("{}", encoding="utf-8")
    (root / ".refdes" / "ids.yaml").write_text("{}\n", encoding="utf-8")
    rels = {
        os.path.relpath(p, str(root)).replace("\\", "/")
        for p in project_inputs(st.snapshot.project)
    }
    assert {"refdes-project.yaml", "refdes-schema.yaml", "items/reqs.yaml", "items/notes.md"} <= rels
    assert ".refdes/ids.yaml" in rels
    assert ".refdes/schema.json" not in rels


# ------------------------------------------------------------- image inputs
#
# Images are project inputs (docs/design/editor-image-upload.md 15.1, decided
# by Jared 2026-09-25): every file under a declared `site.assets:` directory is
# watched, because image resolution is a query over those directories, not a
# fixed reference -- adding a file can retire an absent/ambiguous error and
# deleting one can raise it.

ASSET_SCHEMA = SERVE_SCHEMA.replace(
    'site:\n  title: "Serve test"\n',
    'site:\n  title: "Serve test"\n  assets: [figures, photos/shared]\n',
)


def _assets_project(tmp_path):
    """The serve fixture re-declared with two `site.assets:` directories."""
    config = make_project(tmp_path)
    write_project_config(tmp_path, ASSET_SCHEMA)
    return config


def _rels(st, root):
    return {
        os.path.relpath(p, str(root)).replace("\\", "/")
        for p in project_inputs(st.snapshot.project)
    }


def test_every_file_under_a_declared_asset_dir_is_an_input(tmp_path):
    st = ProjectState(_assets_project(tmp_path))
    st.load()
    (tmp_path / "figures" / "sub").mkdir(parents=True, exist_ok=True)
    (tmp_path / "figures" / "curve.png").write_bytes(b"\x89PNG one")
    (tmp_path / "figures" / "sub" / "deep.png").write_bytes(b"\x89PNG two")
    assert {"figures/curve.png", "figures/sub/deep.png"} <= _rels(st, tmp_path)
    # A declared directory that does not exist is not an error and adds nothing.
    assert not any(r.startswith("photos/") for r in _rels(st, tmp_path))


def test_adding_replacing_or_deleting_an_image_moves_the_revision(tmp_path):
    from refdes.serve.preview import PreviewManager

    preview = PreviewManager()
    try:
        st = ProjectState(_assets_project(tmp_path), preview)
        st.load()
        base_rev, base_gen = st.snapshot.revision, preview.current
        (tmp_path / "figures").mkdir(exist_ok=True)
        image = tmp_path / "figures" / "curve.png"

        image.write_bytes(b"\x89PNG first")
        assert st.refresh() is True
        first_rev, first_gen = st.snapshot.revision, preview.current
        assert first_rev != base_rev and first_gen != base_gen

        # Replacing the bytes of the same path, same name, same size class.
        image.write_bytes(b"\x89PNG second")
        assert st.refresh() is True
        assert st.snapshot.revision not in {base_rev, first_rev}

        # An unreferenced image counts too: nothing in any body names it.
        (tmp_path / "figures" / "unused.png").write_bytes(b"\x89PNG spare")
        assert st.refresh() is True
        unused_rev = st.snapshot.revision

        # Deleting one file returns the fingerprint to the state that had the
        # other one only: the revision is content, not an append log.
        image.unlink()
        assert st.refresh() is True
        assert st.snapshot.revision != unused_rev
    finally:
        preview.close()


def test_a_second_copy_of_a_bare_name_in_another_asset_dir_is_a_change(tmp_path):
    """The ambiguity case: no existing file is touched, and the build changes."""
    st = ProjectState(_assets_project(tmp_path))
    st.load()
    rev = st.snapshot.revision
    (tmp_path / "figures").mkdir(exist_ok=True)
    (tmp_path / "figures" / "curve.png").write_bytes(b"\x89PNG one")
    assert st.refresh() is True
    ambiguous_rev = st.snapshot.revision
    (tmp_path / "photos" / "shared").mkdir(parents=True, exist_ok=True)
    (tmp_path / "photos" / "shared" / "curve.png").write_bytes(b"\x89PNG two")
    assert st.refresh() is True
    assert st.snapshot.revision not in {rev, ambiguous_rev}


def test_files_outside_the_declared_asset_dirs_are_not_inputs(tmp_path):
    st = ProjectState(_assets_project(tmp_path))
    st.load()
    rev = st.snapshot.revision
    stray = tmp_path / "notes" / "curve.png"
    stray.parent.mkdir(exist_ok=True)
    stray.write_bytes(b"\x89PNG not an input")
    (tmp_path / "figures.txt").write_text("not in the asset directory\n", encoding="utf-8")
    assert st.pending_signature() is None
    assert st.refresh() is False
    assert st.snapshot.revision == rev


def test_the_poller_rebuilds_on_an_image_change(tmp_path):
    st = ProjectState(_assets_project(tmp_path))
    st.load()
    poller = Poller(st, interval=0.05)
    poller.start()
    try:
        rev = st.snapshot.revision
        image = tmp_path / "figures" / "curve.png"
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(b"\x89PNG polled")
        deadline = time.time() + 15
        while st.snapshot.revision == rev and time.time() < deadline:
            time.sleep(0.05)
        assert st.snapshot.revision != rev
    finally:
        poller.stop()


def test_a_touch_is_not_a_change(state):
    st, root = state
    revision = st.snapshot.revision
    path = root / "items" / "reqs.yaml"
    later = time.time() + 100
    os.utime(path, (later, later))
    assert st.pending_signature() is not None  # the cheap stage notices...
    assert st.refresh() is False  # ...the content hash says nothing changed
    assert st.snapshot.revision == revision and not st.stale
    assert st.pending_signature() is None


def test_a_content_change_rebuilds_the_model_and_the_revision(tmp_path):
    from refdes.serve.preview import PreviewManager

    preview = PreviewManager()
    try:
        st = ProjectState(make_project(tmp_path), preview)
        st.load()
        old_rev, old_gen = st.snapshot.revision, preview.current
        path = tmp_path / "items" / "reqs.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("3.3 V", "5 V"), encoding="utf-8"
        )
        assert st.refresh() is True
        assert st.snapshot.revision != old_rev
        assert st.snapshot.project.item_by_id("REQ-001").fields["text"].startswith("The rail shall supply 5 V")
        assert preview.current != old_gen and os.path.isdir(preview.current)
        assert not os.path.exists(old_gen)  # the superseded generation is swept
        assert "5 V" in _all_html(preview.current)
    finally:
        preview.close()


def _all_html(root):
    out = ""
    for dirpath, _d, names in os.walk(root):
        for n in names:
            if n.endswith(".html"):
                with open(os.path.join(dirpath, n), encoding="utf-8") as fh:
                    out += fh.read()
    return out


def test_a_new_source_file_and_a_deleted_one_are_both_changes(state):
    st, root = state
    rev = st.snapshot.revision
    (root / "items" / "extra.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - id: REQ-050\n    text: New file.\n",
        encoding="utf-8",
    )
    assert st.refresh() and st.snapshot.revision != rev
    assert st.snapshot.project.item_by_id("REQ-050") is not None
    (root / "items" / "extra.yaml").unlink()
    assert st.refresh()
    assert st.snapshot.project.item_by_id("REQ-050") is None
    assert st.snapshot.revision == rev  # back to the same content, the same revision


def test_a_broken_config_keeps_the_last_good_model_and_says_so(state):
    st, root = state
    rev = st.snapshot.revision
    (root / "refdes-project.yaml").write_text("site: [unbalanced\n", encoding="utf-8")
    assert st.refresh() is False
    assert st.load_error and st.stale
    assert st.snapshot.revision == rev  # the model on offer is still the old one
    assert st.snapshot.project.item_by_id("REQ-001") is not None
    assert st.revision_info()["stale"] is True
    # an unchanged broken file is not rebuilt again
    assert st.pending_signature() is None
    # fixing it recovers
    (root / "refdes-project.yaml").write_text(
        "site: { title: Serve test }\n"
        "id: { width: 3 }\n"
        "boards: { board-a: { label: A }, board-b: { label: B } }\n",
        encoding="utf-8",
    )
    assert st.refresh() and st.load_error is None and not st.stale


def test_a_half_typed_item_file_is_reported_not_fatal(state):
    st, root = state
    path = root / "items" / "reqs.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "  - id: [oops\n", encoding="utf-8")
    assert st.refresh()  # load_readonly reports parse errors on the project
    assert st.snapshot.project.errors
    assert st.load_error is None


def test_the_poller_debounces_then_rebuilds(tmp_path):
    st = ProjectState(make_project(tmp_path))
    st.load()
    poller = Poller(st, interval=0.05)
    poller.start()
    try:
        rev = st.snapshot.revision
        path = tmp_path / "items" / "reqs.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace("2 s", "3 s"), encoding="utf-8")
        deadline = time.time() + 15
        while st.snapshot.revision == rev and time.time() < deadline:
            time.sleep(0.05)
        assert st.snapshot.revision != rev
    finally:
        poller.stop()


def test_revision_endpoint_reports_revision_stale_git_and_serial(tmp_path):
    app = EditorApp(make_project(tmp_path), poll_interval=60)  # poll by hand
    app.start()
    try:
        client = Client(app)
        status, info = client.api_get("/api/revision")
        assert status == 200
        assert info["revision"] == app.state.snapshot.revision
        assert info["stale"] is False and info["load_error"] is None
        assert set(info) >= {"revision", "serial", "stale", "load_error", "git"}
        first_serial = info["serial"]

        path = tmp_path / "items" / "reqs.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace("2 s", "9 s"), encoding="utf-8")
        app.state.refresh()
        _s, after = client.api_get("/api/revision")
        assert after["revision"] != info["revision"] and after["serial"] > first_serial
    finally:
        app.stop()


# ---------------------------------------------------------------- git


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_git_status_is_advisory_and_never_stages_anything(tmp_path):
    config = make_project(tmp_path)
    assert git_status(str(tmp_path)) == {"available": False}

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", "--", "items", ".refdes", "refdes-project.yaml", "refdes-schema.yaml")
    _git(tmp_path, "commit", "-q", "-m", "init")

    clean = git_status(str(tmp_path))
    assert clean["available"] and clean["worktree_dirty"] is False and clean["index_dirty"] is False
    assert clean["branch"] and len(clean["head"]) == 12

    path = tmp_path / "items" / "reqs.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    dirty = git_status(str(tmp_path))
    assert dirty["worktree_dirty"] is True and dirty["index_dirty"] is False
    _git(tmp_path, "add", "--", "items/reqs.yaml")
    staged = git_status(str(tmp_path))
    assert staged["index_dirty"] is True

    # git identity is not part of the revision: staging changed no bytes
    st = ProjectState(config)
    rev_a = st.load().revision
    _git(tmp_path, "commit", "-q", "-m", "second")
    assert ProjectState(config).load().revision == rev_a
