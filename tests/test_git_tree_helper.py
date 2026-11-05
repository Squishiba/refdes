"""The differential tests' git-tree helper is environment-proof.

`_git_tree` (defined once in test_navis_archive.py, imported by
test_navis_site_panel.py) feeds the "byte-identical to origin/main"
differential. It must SKIP (return None) when the checkout cannot support
the diff -- not raise. Run from a `git archive` extract that sits inside
another repo's gitignored directory, `git -C REPO archive` climbs to the
parent repo, archives a subpath absent from that tree, exits 0 with a
zero-filled tar, and `tarfile.open` raises ReadError -- the failure this
guard exists to turn into a skip.
"""

from __future__ import annotations

import os
import subprocess

import test_navis_archive as archive_mod


def _git(root, *args) -> None:
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=x", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


def _commit_a_src_repo(root) -> None:
    """A git repo at `root` with one commit whose tree carries src/keystone.py."""
    (root / "src").mkdir()
    (root / "src" / "keystone.py").write_text("X = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "--", "src/keystone.py")
    _git(root, "commit", "-q", "-m", "init")


def test_git_tree_returns_none_when_repo_is_not_a_git_checkout(tmp_path, monkeypatch):
    # A plain directory with no repo at or above it: rev-parse fails, skip.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(archive_mod, "REPO", str(tmp_path))
    assert archive_mod._git_tree("HEAD", str(tmp_path / "dest")) is None


def test_git_tree_returns_none_inside_a_parent_repo(tmp_path, monkeypatch):
    # The reported case: the extract is a subdir of a parent repo, so git
    # climbs to the parent and archives an absent subpath -> zero tar. The
    # old helper raised tarfile.ReadError here; it must skip (None) now.
    parent = tmp_path / "parent"
    parent.mkdir()
    _commit_a_src_repo(parent)
    subdir = parent / "extracted"
    subdir.mkdir()
    monkeypatch.setattr(archive_mod, "REPO", str(subdir))
    assert archive_mod._git_tree("HEAD", str(tmp_path / "dest")) is None


def test_git_tree_extracts_src_from_its_own_repo(tmp_path, monkeypatch):
    # A real checkout keeps behaving exactly as before: it returns a usable tree.
    repo = tmp_path / "repo"
    repo.mkdir()
    _commit_a_src_repo(repo)
    monkeypatch.setattr(archive_mod, "REPO", str(repo))
    dest = str(tmp_path / "dest")
    tree = archive_mod._git_tree("HEAD", dest)
    assert tree == os.path.join(dest, "src")
    assert os.path.isfile(os.path.join(tree, "keystone.py"))
