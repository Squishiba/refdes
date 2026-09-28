"""Refdes — reference documentation for hardware design decisions."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version


def get_version() -> str:
    """Version of the installed `refdes` package, read from its own metadata.

    `pyproject.toml`'s `version` is the single source of truth: the installed
    distribution's metadata is generated from it, so this can never drift from
    what is actually on the machine. Raises `PackageNotFoundError` when refdes
    is not installed as a package -- a raw checkout with no `pip install -e .`
    -- and callers decide what that is worth printing.
    """
    return _dist_version("refdes")


try:
    __version__ = get_version()
except PackageNotFoundError:  # raw checkout, nothing installed to read
    __version__ = "0.0.0+unknown"
