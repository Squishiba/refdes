"""Text checks over the VS Code extension source (docs/design/editor-vscode-adapter.md §7.2).

There is no JS test harness in this repo, so the extension's own invariants are
driven from pytest by reading the source as text. This module carries exactly
one of the named tests: the activation-marker regression that made the whole
extension dead in the water (§2.3) -- the activation glob and `findRoot` both
looked for the retired `refdes.yaml` instead of `refdes-project.yaml`, so the
extension never activated in a real project (fixed in PR #58).

Read-only by construction: nothing here writes to `editors/vscode/`.
"""

from __future__ import annotations

import json
import os
import re

VSCODE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "editors", "vscode"
)
PACKAGE_JSON = os.path.join(VSCODE_DIR, "package.json")
EXTENSION_JS = os.path.join(VSCODE_DIR, "extension.js")

PROJECT_MARKER = "refdes-project.yaml"
# The retired name. `refdes.yaml` is not a substring of `refdes-project.yaml`,
# so this only ever matches the old, wrong marker.
RETIRED_MARKER = re.compile(r"(?<![\w.-])refdes\.yaml\b")

FIND_ROOT = re.compile(r"function\s+findRoot\s*\([^)]*\)\s*\{(.*?)\n\}", re.DOTALL)


def _find_root_body(source: str) -> str:
    """Return the body of `findRoot`, or fail loudly if the function is gone."""
    match = FIND_ROOT.search(source)
    assert match, "editors/vscode/extension.js no longer defines a findRoot() function"
    return match.group(1)


def test_extension_activates_on_current_project_marker():
    """Both halves of activation name `refdes-project.yaml`, neither names `refdes.yaml`."""
    with open(PACKAGE_JSON, encoding="utf-8") as fh:
        manifest = json.load(fh)
    activation_events = manifest["activationEvents"]

    assert any(PROJECT_MARKER in event for event in activation_events), (
        "editors/vscode/package.json activationEvents does not name "
        f"{PROJECT_MARKER!r}; it is {activation_events!r}, so the extension never "
        "activates in a current project"
    )
    retired_in_manifest = [event for event in activation_events if RETIRED_MARKER.search(event)]
    assert not retired_in_manifest, (
        f"editors/vscode/package.json activationEvents names the retired "
        f"'refdes.yaml': {retired_in_manifest!r}"
    )

    with open(EXTENSION_JS, encoding="utf-8") as fh:
        source = fh.read()
    body = _find_root_body(source)

    assert PROJECT_MARKER in body, (
        "editors/vscode/extension.js findRoot() does not check for "
        f"{PROJECT_MARKER!r}, so it cannot find a current project's root"
    )
    retired_in_find_root = RETIRED_MARKER.findall(body)
    assert not retired_in_find_root, (
        "editors/vscode/extension.js findRoot() checks for the retired "
        f"'refdes.yaml' ({len(retired_in_find_root)} occurrence(s))"
    )
