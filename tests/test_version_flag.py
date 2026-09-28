"""`refdes --version` prints the version actually installed and exits 0.

Found by the release-gate user simulation
(`in-prog-logs/user-sim-release-gate-run1.md`, finding L2): the flag did not
exist, so `refdes --version` fell through to the top-level usage dump and a
non-zero exit, while the docs tell you "a later `refdes` may write a higher
number here; that is expected" -- advice you cannot check without a way to ask
the tool which version you are holding.

The version comes from the installed distribution's metadata, never from a
constant in the source. `src/refdes/__init__.py` used to hardcode `0.1.0` and
was three minor releases behind `pyproject.toml` when this was written; the
last test here is the guard against that happening again.
"""

from __future__ import annotations

import importlib.metadata

import pytest

from refdes import cli as cli_mod


def _installed_version() -> str | None:
    try:
        return importlib.metadata.version("refdes")
    except importlib.metadata.PackageNotFoundError:
        return None


INSTALLED = _installed_version()

needs_install = pytest.mark.skipif(
    INSTALLED is None,
    reason="refdes is not installed as a package, so there is no metadata version to assert",
)


def _run(*argv: str) -> int:
    """argparse's `version` action prints and then raises SystemExit."""
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(list(argv))
    return excinfo.value.code


@needs_install
def test_long_flag_prints_installed_version_and_exits_zero(capsys):
    code = _run("--version")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == f"refdes {INSTALLED}"
    assert captured.err == ""


@needs_install
def test_short_flag_prints_the_same_thing(capsys):
    code = _run("-V")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == f"refdes {INSTALLED}"


@needs_install
def test_version_needs_no_project_and_no_config(tmp_path, monkeypatch, capsys):
    """Run from an empty directory: no `refdes-project.yaml` anywhere. A
    version question is not a project question, so it must not fail with a
    configuration error or the usage dump."""
    monkeypatch.chdir(tmp_path)
    code = _run("--version")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == f"refdes {INSTALLED}"
    assert "usage:" not in captured.out + captured.err


@needs_install
def test_version_is_advertised_in_help(capsys):
    with pytest.raises(SystemExit):
        cli_mod.main(["--help"])
    assert "--version" in capsys.readouterr().out


def test_falls_back_gracefully_when_not_installed(monkeypatch, capsys):
    """A raw checkout with no `pip install -e .` has no metadata to read. The
    flag still prints something honest and still exits 0 -- it does not raise
    `PackageNotFoundError` into a traceback."""

    def boom() -> str:
        raise importlib.metadata.PackageNotFoundError("refdes")

    monkeypatch.setattr(cli_mod, "get_version", boom)
    code = _run("--version")
    captured = capsys.readouterr()
    assert code == 0
    out = captured.out.strip()
    assert out.startswith("refdes")
    assert "unknown" in out
    assert "Traceback" not in captured.out + captured.err


@needs_install
def test_module_dunder_version_matches_installed():
    """`refdes.__version__` is derived from the same metadata, so it cannot
    drift from `pyproject.toml` the way the old hardcoded constant did."""
    import refdes

    assert refdes.__version__ == INSTALLED
    assert refdes.get_version() == INSTALLED
