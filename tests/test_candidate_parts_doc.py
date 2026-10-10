"""The whole-file examples in `docs/design/candidate-parts.md` must load (PR #8 HIGH).

The design names three real list files: the layout it recommends (§6.1's
`items/power/candidates.yaml`), the skeleton `refdes new <type> --list`
prints (§6.4), and the worked example's candidates file (§7.2). All three
were originally written as `defaults:` plus a bare top-level sequence, but
a list file is a mapping with a `defaults:` and an `items:` key
(`parse_list_file`; docs/authoring.md §List files) -- and the sketch shape
is not even valid YAML, so each one failed `refdes check` with
`invalid YAML ... expected <block end>, but found '-'` at exit 1. The
skeleton the phase-4 flag would generate and the fixture the §9 table test
builds on were files no project could load. (The implemented
`scaffold.new_list_text` emits the mapping form for exactly this reason.)

This is the anti-drift gate for that fix: the three fences are extracted
from the doc as authored and run through the real parser, so re-editing
any one of them back into a sketch that does not parse -- in either
spelling -- fails the suite with the parser's own diagnostic.
"""

from __future__ import annotations

import os
import re

from helpers import REPO

from refdes import parse
from refdes import scaffold as scaffold_mod
from refdes.schema import load_project

DOC_PATH = os.path.join(REPO, "docs", "design", "candidate-parts.md")

_FENCE = re.compile(r"^(\s*)(`{3,})(.*)$")


def _fence_after(heading: str, info: str) -> str:
    """The first fenced block that follows the line starting with `heading`,
    opened with exactly `info` as its language, de-indented to the fence's
    own indentation (the §6.4 skeleton is fenced inside a bullet list). An
    inner fence indented deeper than the block's own fence (the §7.2
    fixture's ```` ```calc ```` blocks inside `body: |` scalars) is content,
    not the closing fence."""
    with open(DOC_PATH, "r", encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith(heading)), None
    )
    assert start is not None, f"section {heading!r} no longer in the doc"
    for i in range(start + 1, len(lines)):
        match = _FENCE.match(lines[i])
        if not match or match.group(3).strip() != info:
            continue
        indent, ticks = match.group(1), match.group(2)
        body = []
        for j in range(i + 1, len(lines)):
            closing = _FENCE.match(lines[j])
            if (
                closing
                and len(closing.group(1)) <= len(indent)
                and len(closing.group(2)) >= len(ticks)
                and closing.group(3).strip() == ""
            ):
                return "\n".join(body) + "\n"
            body.append(lines[j][len(indent):])
        raise AssertionError(f"unterminated fence after {heading!r}")
    raise AssertionError(f"no ```{info} fence after {heading!r}")


def _load_list_file(tmp_path, name: str, text: str):
    """Write `text` as `items/<name>.yaml` in a freshly initialized project
    and parse it as a list file: the finding's failure mode is a load-time
    rejection, so that is the layer this pins."""
    scaffold_mod.init(str(tmp_path))
    items_dir = os.path.join(str(tmp_path), "items")
    os.makedirs(items_dir, exist_ok=True)
    path = os.path.join(items_dir, f"{name}.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    project = load_project(start=str(tmp_path))
    items = parse.parse_list_file(project, path)
    assert not [d.message for d in project.errors], project.errors[0].message
    return items


def test_recommendation_list_file_loads(tmp_path):
    """§6.1's recommended `items/power/candidates.yaml` parses as a list
    file: `defaults:` plus `items:`, and the defaults merge under the
    entry (candidate parts §6.1; PR #8 HIGH finding)."""
    items = _load_list_file(
        tmp_path, "recommendation", _fence_after("### 6.1 The recommendation", "yaml")
    )
    assert [item.id for item in items] == ["CMP-PWR-014"]
    assert items[0].type == "component"
    assert items[0].fields["status"] == "candidate"  # inherited from defaults:


def test_new_list_skeleton_shape_loads(tmp_path):
    """§6.4's printed skeleton is the mapping form `parse_list_file`
    requires -- the same shape `scaffold.new_list_text` actually emits --
    so redirecting `refdes new --list` into place cannot produce a rejected
    file (candidate parts §6.4; PR #8 HIGH finding)."""
    items = _load_list_file(tmp_path, "skeleton", _fence_after("### 6.4 Scaffolding", ""))
    assert len(items) == 1
    entry = items[0]
    assert entry.type == "component"
    assert "title" in entry.fields and "part_number" in entry.fields


def test_worked_example_candidates_load(tmp_path):
    """§7.2's `items/power/candidates.yaml` -- the fixture §9's table test
    builds on -- parses as a list file. Its entries' calc blocks live in
    `body: |` scalars, the list-file spelling (docs/authoring.md §Bodies
    in list files), and `status: candidate` is written once in `defaults:`
    with the winner overriding it in place (candidate parts §7.2; PR #8
    HIGH finding)."""
    items = _load_list_file(
        tmp_path, "candidates", _fence_after("### 7.2 Candidates", "yaml")
    )
    by_id = {item.id: item for item in items}
    assert list(by_id) == [
        "CMP-PWR-014",
        "CMP-PWR-015",
        "CMP-PWR-016",
        "CMP-PWR-017",
    ]
    assert by_id["CMP-PWR-014"].fields["status"] == "selected"  # own value wins
    assert by_id["CMP-PWR-017"].fields["status"] == "candidate"  # defaults win
    assert "```calc" in by_id["CMP-PWR-014"].body
