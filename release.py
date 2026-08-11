#!/usr/bin/env python3
"""Prepare a release of the CLI or the VS Code extension.

Both PyPI and the VS Code Marketplace reject a version that already exists, and
neither lets you overwrite one. That makes the version bump the dangerous step:
build first and you ship stale metadata, bump wrong and you burn the number
permanently. This script does the sequence in the order that cannot go wrong, and
refuses rather than guesses.

It deliberately stops short of uploading. Publishing is the one step that cannot
be undone, so it stays a separate, conscious command.

    python release.py cli 0.1.1
    python release.py extension 0.2.0
    python release.py cli 0.1.1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
EXT_MANIFEST = os.path.join(ROOT, "editors", "vscode", "package.json")
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _fix_console() -> None:
    """Windows consoles default to cp1252, which cannot encode an em dash."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


class Abort(Exception):
    """A precondition failed. Message is already user-facing."""


def say(msg: str) -> None:
    print(f"  {msg}")


def step(msg: str) -> None:
    print(f"\n== {msg}")


def run(cmd: list[str], cwd: str = ROOT) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Abort(
            f"`{' '.join(cmd)}` failed with exit {proc.returncode}\n"
            f"{proc.stdout}\n{proc.stderr}".rstrip()
        )
    return proc.stdout


def python_exe() -> str:
    """Prefer the project venv: `build` and `twine` are installed there, not globally."""
    return VENV_PY if os.path.exists(VENV_PY) else sys.executable


# --------------------------------------------------------------------------- checks


def parse_version(text: str) -> tuple[int, int, int]:
    return tuple(int(p) for p in text.split("."))  # type: ignore[return-value]


def require_clean_tree() -> None:
    if run(["git", "status", "--porcelain"]).strip():
        raise Abort(
            "working tree has uncommitted changes. Commit or stash first — a release "
            "should be reproducible from a known commit."
        )


def current_cli_version() -> str:
    with open(PYPROJECT, encoding="utf-8") as fh:
        match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    if not match:
        raise Abort(f"no version found in {PYPROJECT}")
    return match.group(1)


def current_ext_version() -> str:
    with open(EXT_MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["version"]


def require_newer(old: str, new: str) -> None:
    if not SEMVER.match(new):
        raise Abort(f"{new!r} is not a MAJOR.MINOR.PATCH version")
    if parse_version(new) <= parse_version(old):
        raise Abort(
            f"{new} is not greater than the current {old}. Registries never allow "
            f"reusing or overwriting a version."
        )


def require_unpublished_pypi(version: str) -> None:
    """Ask PyPI directly. Cheaper to fail here than after an irreversible upload."""
    url = f"https://pypi.org/pypi/refdes/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                raise Abort(
                    f"refdes {version} is already on PyPI. That version is permanent — "
                    f"pick a higher one."
                )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            say(f"PyPI: {version} is unpublished, good")
            return
        say(f"PyPI check inconclusive (HTTP {exc.code}); continuing")
    except urllib.error.URLError as exc:
        say(f"PyPI check skipped (offline? {exc.reason}); continuing")


# --------------------------------------------------------------------------- edits


def write_cli_version(version: str) -> None:
    with open(PYPROJECT, encoding="utf-8") as fh:
        text = fh.read()
    # Anchored to the line start so a dependency pin like `version = "x"` inside a
    # nested table is never mistaken for the project version.
    new_text, count = re.subn(
        r'^version\s*=\s*"[^"]+"', f'version = "{version}"', text, count=1, flags=re.M
    )
    if count != 1:
        raise Abort("could not rewrite the version in pyproject.toml")
    with open(PYPROJECT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)


def write_ext_version(version: str) -> None:
    with open(EXT_MANIFEST, encoding="utf-8") as fh:
        text = fh.read()
    new_text, count = re.subn(
        r'"version"\s*:\s*"[^"]+"', f'"version": "{version}"', text, count=1
    )
    if count != 1:
        raise Abort("could not rewrite the version in the extension package.json")
    with open(EXT_MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)


# --------------------------------------------------------------------------- flows


def release_cli(version: str, dry_run: bool) -> None:
    old = current_cli_version()
    step(f"Releasing CLI {old} -> {version}")
    require_newer(old, version)
    require_unpublished_pypi(version)

    step("Running the test suite")
    run([python_exe(), "-m", "pytest", "-q"])
    say("tests passed")

    if dry_run:
        say("dry run: stopping before any file is modified")
        return

    step("Bumping the version")
    write_cli_version(version)
    say(f"pyproject.toml -> {version}")

    step("Cleaning previous build outputs")
    # `build` does not clean up after itself, and `twine upload dist/*` uploads
    # everything it finds. A leftover wheel is how stale metadata gets published.
    for path in ("dist", "build"):
        target = os.path.join(ROOT, path)
        if os.path.isdir(target):
            shutil.rmtree(target)
            say(f"removed {path}/")
    src = os.path.join(ROOT, "src")
    for name in os.listdir(src):
        if name.endswith(".egg-info"):
            shutil.rmtree(os.path.join(src, name))
            say(f"removed src/{name}")

    step("Building")
    run([python_exe(), "-m", "build"])
    built = sorted(os.listdir(os.path.join(ROOT, "dist")))
    for name in built:
        say(name)

    step("Validating metadata")
    run([python_exe(), "-m", "twine", "check", os.path.join(ROOT, "dist", "*")])
    say("twine check passed")

    expected = {f"refdes-{version}-py3-none-any.whl", f"refdes-{version}.tar.gz"}
    if set(built) != expected:
        raise Abort(
            f"dist/ holds {sorted(built)}, expected {sorted(expected)}. Do not upload — "
            f"`twine upload dist/*` would publish the extras too."
        )

    print(
        f"\nReady. Nothing has been published yet.\n\n"
        f"  git commit -am 'Release {version}'\n"
        f"  git tag v{version}\n"
        f"  git push && git push --tags\n"
        f"  {os.path.relpath(python_exe(), ROOT)} -m twine upload dist/*\n"
    )


def release_extension(version: str, dry_run: bool) -> None:
    old = current_ext_version()
    step(f"Releasing extension {old} -> {version}")
    require_newer(old, version)

    if not shutil.which("npx"):
        raise Abort("npx not found. Node is required to package the extension.")

    if dry_run:
        say("dry run: stopping before any file is modified")
        return

    step("Bumping the version")
    write_ext_version(version)
    say(f"editors/vscode/package.json -> {version}")

    step("Packaging")
    ext_dir = os.path.dirname(EXT_MANIFEST)
    for name in os.listdir(ext_dir):
        if name.endswith(".vsix"):
            os.remove(os.path.join(ext_dir, name))
            say(f"removed stale {name}")
    run(["npx", "--yes", "@vscode/vsce@latest", "package"], cwd=ext_dir)
    vsix = os.path.join(ext_dir, f"refdes-{version}.vsix")
    if not os.path.exists(vsix):
        raise Abort(f"expected {vsix} but vsce did not produce it")
    say(f"built {os.path.relpath(vsix, ROOT)}")

    print(
        f"\nReady. Nothing has been published yet.\n\n"
        f"  git commit -am 'Release extension {version}'\n"
        f"  git push\n\n"
        f"Then upload {os.path.relpath(vsix, ROOT)} at\n"
        f"  https://marketplace.visualstudio.com/manage\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("part", choices=["cli", "extension"])
    parser.add_argument("version", help="new version, MAJOR.MINOR.PATCH")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the checks but change nothing",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="skip the clean-working-tree requirement",
    )
    args = parser.parse_args()
    _fix_console()

    try:
        if not args.allow_dirty:
            require_clean_tree()
        if args.part == "cli":
            release_cli(args.version, args.dry_run)
        else:
            release_extension(args.version, args.dry_run)
    except Abort as exc:
        print(f"\nrelease aborted: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
