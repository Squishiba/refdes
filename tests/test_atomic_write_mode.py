"""PERM-OWNER-002: `atomic_write_text` gives a *new* file the umask default.

The helper writes through a same-directory temp renamed into place, and it
copied the old file's mode onto the temp only when an old file existed --
while the temp itself came from `tempfile.mkstemp`, which creates 0600.
Every file an atomic write created new therefore landed 0600, two notches
stricter than the siblings the plain `write_text` path writes at the umask
default: `refdes id` in a fresh project put `.refdes/ids.yaml` at 0600
beside a 0644 `.refdes/schema.json` (umask 022), and under a group-shared
002 umask the ledger was the one file in `.refdes/` the group could not
read. The fix creates the temp itself with `O_CREAT | O_EXCL` at 0666 so
the kernel applies the umask -- so temp creation must never go back to a
0600-creating helper, and `os.umask` must stay untouched: it is
process-wide, and a set-and-restore read has a window in which another
thread's concurrent file creation lands with the wrong mode. Same shape as
the seal fix (PERM-OWNER-001, tests/test_seal.py) on the shared helper.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from refdes import cli as cli_mod
from refdes import scaffold as scaffold_mod
from refdes import textio

needs_chmod = pytest.mark.skipif(
    os.name == "nt", reason="chmod-based: advisory mode bits on Windows"
)


@contextmanager
def _umask(mask: int):
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@needs_chmod
@pytest.mark.parametrize(("umask", "expected"), [(0o022, 0o644), (0o002, 0o664)])
def test_a_new_file_gets_the_umask_default_mode(tmp_path, umask, expected):
    path = tmp_path / "new.yaml"
    assert not path.exists()
    with _umask(umask):
        textio.atomic_write_text(str(path), "items: []\n")
    assert os.stat(path).st_mode & 0o777 == expected


@needs_chmod
def test_a_rewritten_file_keeps_the_mode_it_had(tmp_path):
    """0640 is neither umask default, so a rewrite that recomputed the mode
    instead of copying the old file's would land 0644/0664 and fail here."""
    path = tmp_path / "file.yaml"
    textio.write_text(str(path), "items: []\n")
    os.chmod(path, 0o640)
    with _umask(0o002):
        textio.atomic_write_text(str(path), "items: [1]\n")
    assert os.stat(path).st_mode & 0o777 == 0o640
    assert textio.read_text(str(path)) == "items: [1]\n"


def test_a_colliding_temp_name_is_retried_not_fatal(tmp_path, monkeypatch):
    """`O_EXCL` makes the temp creation collision-safe rather than clobbering,
    so the collision branch must retry, not die: a foreign file holding one
    roll of the name must not fail the write."""
    tokens = iter(["c" * 16])
    real_hex = textio.secrets.token_hex

    def once_colliding(_n):
        try:
            return next(tokens)
        except StopIteration:
            return real_hex(_n)

    decoy = tmp_path / f".target.yaml.refdes-tmp-{'c' * 16}"
    decoy.write_text("", encoding="utf-8")
    monkeypatch.setattr(textio.secrets, "token_hex", once_colliding)
    fd, path = textio._create_temp(str(tmp_path), "target.yaml")
    os.close(fd)
    assert path != str(decoy)
    assert os.path.basename(path).startswith(".target.yaml.refdes-tmp-")
    assert os.path.exists(path)


def test_atomic_write_never_reads_or_writes_the_process_umask(tmp_path, monkeypatch):
    """The new-file mode comes from the kernel (`O_CREAT` mode filtered
    through the umask), not from reading the umask itself: `os.umask` is
    process-wide, so a set-and-restore read has a window in which another
    thread's file creation lands with the wrong mode. Pin that the whole
    write touches it zero times."""
    calls = []
    real = os.umask

    def spy(mask):
        calls.append(mask)
        return real(mask)

    monkeypatch.setattr(os, "umask", spy)
    textio.atomic_write_text(str(tmp_path / "new.yaml"), "items: []\n")
    assert calls == []


# --------------------------------------------------------------- CLI level
#
# The finding's exact shape: `refdes id` in a fresh hardware@3 project
# creates the ledger, and the ledger is the new file. Its sibling
# `.refdes/schema.json` is written by the plain `write_text` path, so
# asserting the two agree pins the CLI behavior, not just the helper.


def _project_needing_ids(tmp_path) -> str:
    scaffold_mod.init(str(tmp_path))
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "first.yaml").write_text(
        "items:\n  - type: requirement\n    body: First.\n  - type: requirement\n    body: Second.\n"
    )
    return str(tmp_path / "refdes-project.yaml")


@needs_chmod
@pytest.mark.parametrize(("umask", "expected"), [(0o022, 0o644), (0o002, 0o664)])
def test_refdes_id_creates_the_ledger_at_the_umask_default(
    tmp_path, capsys, umask, expected
):
    config = _project_needing_ids(tmp_path)
    ledger = tmp_path / ".refdes" / "ids.yaml"
    assert not ledger.exists()
    with _umask(umask):
        status = cli_mod.main(["-c", config, "id"])
    assert status == 0, capsys.readouterr().err
    assert ledger.exists()
    assert os.stat(ledger).st_mode & 0o777 == expected
    assert os.stat(tmp_path / ".refdes" / "schema.json").st_mode & 0o777 == expected
