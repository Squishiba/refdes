"""WRITE-ATOMIC-003: `standard add-preset` / `remove-preset` write the config
atomically, so a mid-write failure never lands a partial config and never
leaves litter.

The finding (`.scratch` probes, in-prog-logs) reproduced on a real ENOSPC:
`refdes standard add-preset` on a tmpfs with no space left exited 2 saying the
config was "exactly as it was" while the truncate-on-open had already
destroyed it (the tail of the file was gone and the presets line had moved).
`remove-preset` left a truncated `refdes-project.yaml.scratch` behind while
saying "Nothing changed." -- its refusal raises from inside `except OSError`,
so the `finally` that deletes the copy is never reached.

These tests inject the same failure mechanically -- ENOSPC raised against the
temporary fd `textio.atomic_write_text` creates, either at the first write or
at the fsync before the rename -- so they run anywhere, without a tmpfs or
root. The tmpfs reproduction of the same two shapes lives in
`.scratch/wa003/probe.sh`.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from refdes import cli as cli_mod
from refdes import scaffold as scaffold_mod

# chmod is not a thing on Windows; the mode-preservation test needs it.
needs_chmod = pytest.mark.skipif(os.name == "nt", reason="needs POSIX chmod bits")

# Symlinks need POSIX (or elevated Windows privileges), same as `probe.py`.
needs_symlink = pytest.mark.skipif(os.name == "nt", reason="needs POSIX symlinks")

# The temp `textio.atomic_write_text` makes for a target is named
# `.{target basename}.refdes-tmp-{random}`, so a scratch-copy temp and a
# real-config temp are told apart by their prefix.
CONFIG_TMP_PREFIX = ".refdes-project.yaml.refdes-tmp-"
SCRATCH_TMP_PREFIX = ".refdes-project.yaml.scratch.refdes-tmp-"


def _init_preset_project(tmp_path, presets: list[str]) -> str:
    """A hardware@2 project (the version `design-debate` exists for) with
    `presets` selected, as a config path string."""
    scaffold_mod.init(str(tmp_path))
    config = tmp_path / "refdes-project.yaml"
    config.write_text(config.read_text().replace("version: 3", "version: 2"))
    for preset in presets:
        scaffold_mod.add_preset(str(tmp_path), preset)
    return str(config)


def _symlink_preset_project(tmp_path, presets: list[str]) -> tuple[str, str]:
    """The same hardware@2 project, but its `refdes-project.yaml` is a symlink
    to a real `actual-project.yaml` beside it.

    The WRITE-ATOMIC-003 review regression's exact shape: the command is
    pointed at the marker, but the bytes it must edit live behind the link.
    Returns `(marker, real)` -- pass `marker` to the CLI, check the bytes on
    `real`.
    """
    scaffold_mod.init(str(tmp_path))
    marker = tmp_path / "refdes-project.yaml"
    real = tmp_path / "actual-project.yaml"
    real.write_text(marker.read_text().replace("version: 3", "version: 2"))
    marker.unlink()
    marker.symlink_to(real.name)
    for preset in presets:
        scaffold_mod.add_preset(str(tmp_path), preset)
    return str(marker), str(real)


class _FailingDisk:
    """ENOSPC injection aimed at `textio.atomic_write_text`'s temp file.

    Only fds minted by `mkstemp` whose temp name matches `targets(tmp)` fail;
    everything else on the machine (pytest's own writes, the project write
    lock, other temp files) is untouched, which is what makes this safe to
    install over the real `os`/`tempfile` for the length of one command.
    """

    def __init__(self, monkeypatch, targets):
        self.monkeypatch = monkeypatch
        self.targets = targets
        self.victims: set[int] = set()

    def install(self, *, at_write: bool) -> None:
        real_mkstemp, real_fsync, real_fdopen = (
            tempfile.mkstemp,
            os.fsync,
            os.fdopen,
        )
        victims, targets = self.victims, self.targets

        def recording_mkstemp(*args, **kwargs):
            fd, tmp = real_mkstemp(*args, **kwargs)
            if targets(os.path.basename(tmp)):
                victims.add(fd)
            return fd, tmp

        if at_write:

            class _NoSpaceHandle:
                """The fd, but the first `write` fails the way a full tmpfs
                fails it: ENOSPC, with nothing of the new text landed."""

                def __init__(self, real, fd):
                    self._real, self._fd = real, fd

                def write(self, text):
                    if self._fd in victims:
                        raise OSError(28, "No space left on device")
                    return self._real.write(text)

                def __enter__(self):
                    self._real.__enter__()
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return self._real.__exit__(exc_type, exc, tb)

                def __getattr__(self, name):
                    return getattr(self._real, name)

            def fdopen_at_write(fd, *args, **kwargs):
                real = real_fdopen(fd, *args, **kwargs)
                return _NoSpaceHandle(real, fd) if fd in victims else real

            self.monkeypatch.setattr(os, "fdopen", fdopen_at_write)
        else:

            def fsync(fd):
                if fd in victims:
                    raise OSError(28, "No space left on device")
                return real_fsync(fd)

            self.monkeypatch.setattr(os, "fsync", fsync)

        self.monkeypatch.setattr(tempfile, "mkstemp", recording_mkstemp)

    def temp_survivors(self, directory) -> list[str]:
        return [
            p.name for p in os.scandir(directory) if ".refdes-tmp-" in p.name
        ]


def _no_litter(root) -> None:
    names = sorted(os.listdir(root))
    assert not [n for n in names if ".refdes-tmp-" in n], names
    assert "refdes-project.yaml.scratch" not in names, names


# ------------------------------------------------------------------ add-preset


@pytest.mark.parametrize("at_write", [True, False], ids=["at-write", "at-fsync"])
def test_add_preset_failure_keeps_the_config_byte_identical(
    tmp_path, capsys, monkeypatch, at_write
):
    """The destroyed-config half of the finding: with ENOSPC injected at the
    temp, the real `refdes-project.yaml` is not truncated at all -- the bytes
    on disk are the ones that were there before, presets line and all -- and
    the exit 2 refusal that says "exactly as it was" is finally true."""
    config = _init_preset_project(tmp_path, presets=[])
    with open(config, "rb") as fh:
        before = fh.read()
    disk = _FailingDisk(monkeypatch, lambda name: name.startswith(CONFIG_TMP_PREFIX))
    disk.install(at_write=at_write)

    status = cli_mod.main(
        ["-c", config, "standard", "add-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 2, captured.out + captured.err
    assert "cannot write refdes-project.yaml" in captured.err, captured.err
    assert "exactly as it was" in captured.err, captured.err
    with open(config, "rb") as fh:
        assert fh.read() == before
    _no_litter(tmp_path)
    assert disk.temp_survivors(tmp_path) == []


# --------------------------------------------------------------- remove-preset


@pytest.mark.parametrize("at_write", [True, False], ids=["at-write", "at-fsync"])
def test_remove_preset_scratch_failure_leaves_no_litter(
    tmp_path, capsys, monkeypatch, at_write
):
    """The litter half of the finding: when the simulation copy cannot be
    written, the old code left a truncated `refdes-project.yaml.scratch` in
    the project root (the refusal raises from the `except`, so the `finally`
    that deletes the copy never runs) while saying "Nothing changed." The
    atomic copy takes its partial temp with it, so the refusal is true on both
    halves: nothing changed, and nothing was left behind."""
    config = _init_preset_project(tmp_path, presets=["design-debate"])
    with open(config, "rb") as fh:
        before = fh.read()
    disk = _FailingDisk(
        monkeypatch, lambda name: name.startswith(SCRATCH_TMP_PREFIX)
    )
    disk.install(at_write=at_write)

    status = cli_mod.main(
        ["-c", config, "standard", "remove-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 2, captured.out + captured.err
    assert "still selected" in captured.err, captured.err
    assert "Nothing changed." in captured.err, captured.err
    with open(config, "rb") as fh:
        assert fh.read() == before
    _no_litter(tmp_path)
    assert disk.temp_survivors(tmp_path) == []


@pytest.mark.parametrize("at_write", [True, False], ids=["at-write", "at-fsync"])
def test_remove_preset_real_write_failure_after_a_ran_simulation(
    tmp_path, capsys, monkeypatch, at_write
):
    """The other half: the simulation runs and reports, the scratch copy is
    deleted, and then the real write fails. The config must survive byte for
    byte (preset still selected), the scratch copy must be gone, and no temp
    may remain -- which is what makes the "Nothing changed." on this refusal
    literal rather than aspirational."""
    config = _init_preset_project(tmp_path, presets=["design-debate"])
    with open(config, "rb") as fh:
        before = fh.read()
    disk = _FailingDisk(monkeypatch, lambda name: name.startswith(CONFIG_TMP_PREFIX))
    disk.install(at_write=at_write)

    status = cli_mod.main(
        ["-c", config, "standard", "remove-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 2, captured.out + captured.err
    assert "still selected. Nothing changed." in captured.err, captured.err
    with open(config, "rb") as fh:
        assert fh.read() == before
    _no_litter(tmp_path)
    assert disk.temp_survivors(tmp_path) == []


# ------------------------------------------------------------- mode and litter


@needs_chmod
def test_add_preset_keeps_the_existing_configs_mode(tmp_path, capsys):
    """The atomic replacement must not quietly re-mode the project config:
    a project that keeps `refdes-project.yaml` at 0640 still finds it at 0640
    after a successful add, and the write still lands."""
    config = _init_preset_project(tmp_path, presets=[])
    os.chmod(config, 0o640)

    status = cli_mod.main(
        ["-c", config, "standard", "add-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.out + captured.err
    assert oct(os.stat(config).st_mode & 0o777) == "0o640"
    with open(config, encoding="utf-8") as fh:
        assert "design-debate" in fh.read()
    _no_litter(tmp_path)


# ----------------------------------------------------- symlinked config target
#
# WRITE-ATOMIC-003 review regression. `atomic_write_text` renames a temp over
# its target, and `rename` swaps the *symlink itself* for the temp rather than
# following it -- the opposite of the truncate-on-open `write_text` it
# replaced, which wrote through the link. So on a branch that pointed at the
# symlink, `add-preset` replaced `refdes-project.yaml` with a regular file and
# left `actual-project.yaml` untouched (`.scratch/review_atomic_symlink/
# probe.py`: marker_symlink False, target_changed False). The fix resolves the
# write to the link's target, so the link survives and the bytes land behind
# it. These three pin both halves: success keeps the link and edits the real
# file, and a failed atomic write through the link still changes nothing.

# The real write now targets the resolved `actual-project.yaml`, so its temp
# carries that basename -- tell it apart from the marker and the scratch copy.
REAL_TMP_PREFIX = ".actual-project.yaml.refdes-tmp-"


@needs_symlink
def test_add_preset_through_a_symlink_keeps_the_link_and_edits_the_target(
    tmp_path, capsys
):
    """Successful add through a symlinked config: the marker is still a
    symlink, the preset landed in the file behind it, and it reads back
    through the link."""
    marker, real = _symlink_preset_project(tmp_path, presets=[])
    with open(real, "rb") as fh:
        before = fh.read()

    status = cli_mod.main(
        ["-c", marker, "standard", "add-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.out + captured.err
    assert os.path.islink(marker), "the symlink must not be replaced by a file"
    with open(real, "rb") as fh:
        after = fh.read()
    assert after != before, "the write must land in the file behind the link"
    assert b"design-debate" in after
    with open(marker, "rb") as fh:  # reads through the link
        assert b"design-debate" in fh.read()
    _no_litter(tmp_path)


@needs_symlink
def test_remove_preset_through_a_symlink_keeps_the_link_and_edits_the_target(
    tmp_path, capsys
):
    """The same through remove-preset, which also runs the scratch-copy
    simulation first: the marker stays a symlink and the real file loses the
    preset, with no scratch or temp litter."""
    marker, real = _symlink_preset_project(tmp_path, presets=["design-debate"])
    with open(real, "rb") as fh:
        before = fh.read()
    assert b"design-debate" in before

    status = cli_mod.main(
        ["-c", marker, "standard", "remove-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.out + captured.err
    assert os.path.islink(marker), "the symlink must not be replaced by a file"
    with open(real, "rb") as fh:
        after = fh.read()
    assert after != before and b"design-debate" not in after
    _no_litter(tmp_path)


@needs_symlink
@pytest.mark.parametrize("at_write", [True, False], ids=["at-write", "at-fsync"])
def test_add_preset_failure_through_a_symlink_changes_nothing(
    tmp_path, capsys, monkeypatch, at_write
):
    """A failed atomic write aimed at the resolved target: the real file
    behind the link is byte-identical, the marker is still a symlink (a rename
    of the link itself would have changed that), and the refusal is true."""
    marker, real = _symlink_preset_project(tmp_path, presets=[])
    with open(real, "rb") as fh:
        before = fh.read()
    disk = _FailingDisk(
        monkeypatch, lambda name: name.startswith(REAL_TMP_PREFIX)
    )
    disk.install(at_write=at_write)

    status = cli_mod.main(
        ["-c", marker, "standard", "add-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 2, captured.out + captured.err
    assert "cannot write refdes-project.yaml" in captured.err, captured.err
    assert "exactly as it was" in captured.err, captured.err
    with open(real, "rb") as fh:
        assert fh.read() == before
    assert os.path.islink(marker), "a refused write must not have replaced the link"
    _no_litter(tmp_path)
    assert disk.temp_survivors(tmp_path) == []


@needs_symlink
@pytest.mark.parametrize("at_write", [True, False], ids=["at-write", "at-fsync"])
def test_remove_preset_real_failure_through_a_symlink_changes_nothing(
    tmp_path, capsys, monkeypatch, at_write
):
    """remove-preset with the failure aimed only at the resolved real write:
    the scratch simulation still runs and is cleaned up, then the real write
    fails -- the real file is untouched, the link intact, nothing left behind,
    so "Nothing changed." holds through the symlink too."""
    marker, real = _symlink_preset_project(tmp_path, presets=["design-debate"])
    with open(real, "rb") as fh:
        before = fh.read()
    disk = _FailingDisk(
        monkeypatch, lambda name: name.startswith(REAL_TMP_PREFIX)
    )
    disk.install(at_write=at_write)

    status = cli_mod.main(
        ["-c", marker, "standard", "remove-preset", "design-debate"]
    )

    captured = capsys.readouterr()
    assert status == 2, captured.out + captured.err
    assert "still selected. Nothing changed." in captured.err, captured.err
    with open(real, "rb") as fh:
        assert fh.read() == before
    assert os.path.islink(marker), "a refused write must not have replaced the link"
    _no_litter(tmp_path)
    assert disk.temp_survivors(tmp_path) == []
