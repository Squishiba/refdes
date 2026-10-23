"""CHK-ATTR-002: an imported item's diagnostic is attributed to its real upstream
`file:line`, not a fabricated `<import:NAME>:1`.

The upstream artifact records where each item is defined -- `source: {file, line}`
(docs/output.md "Field notes"). `imports.py` used to throw that away and build every
imported item with `source_file=f"<import:{origin}>"`, `source_line=1`, so `refdes
check` reported an imported item's diagnostic against a pseudo-path that is not a
file, at a line that was never parsed from anything -- while local items report the
true `file:line`.

The decided fix: when the record carries a usable `source` (a string `file` and an
integer `line`), the imported item gets `source_file = f"{origin}:{file}"` and
`source_line = line`, so the diagnostic reads
`platform:items/interfaces/req.md:2 [REQ-IF001] - ...`. A record without a usable
`source` keeps today's `<import:NAME>` / line 1 so old artifacts do not break.
"""

from __future__ import annotations

import json

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import cli as cli_mod
from refdes.patcher import SetField
from refdes.serve import edit as edit_mod
from refdes.serve.edit import EditRequest, Refused

SCHEMA = """\
site: { title: Platform Interfaces, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  refines: { inverse: refined_by, label: Refines }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
    links:
      refines: [requirement]
"""

# The upstream item's definition line drives the expected location. REQ-IF001 is the
# 3rd line (1-indexed) of items/req.yaml, so a faithful fix reports `...:3`.
UPSTREAM_REQS = """\
defaults: { type: requirement }
items:
  - id: REQ-IF001
    text: Refines a requirement that does not exist upstream.
    refines: [REQ-MISSING]
  - id: REQ-IF002
    text: A self-contained upstream requirement.
"""

# A local downstream item with its own dangling link, as the control: its diagnostic
# location must be the real local file:line, unchanged by the fix.
LOCAL_REQS = """\
defaults: { type: requirement }
items:
  - id: REQ-DOWN-001
    text: Refines a requirement that does not exist here.
    refines: [REQ-GONE]
"""


def _write_downstream(root, artifact_rel="../upstream/_site/items.json"):
    write_project_config(
        root,
        SCHEMA
        + "\nimports:\n"
        f"  - name: platform\n    items: {artifact_rel}\n",
    )
    items = root / "items"
    items.mkdir()
    (items / "local.yaml").write_text(LOCAL_REQS, encoding="utf-8")
    return root


@pytest.fixture
def imported_project(tmp_path):
    """A real upstream project built to an items.json artifact (its REQ-IF001 has a
    dangling `refines`), imported by a downstream project with a clean local item and
    one local item whose own link dangles."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    write_project_config(upstream, SCHEMA)
    up_items = upstream / "items"
    up_items.mkdir()
    (up_items / "req.yaml").write_text(UPSTREAM_REQS, encoding="utf-8")
    assert (
        cli_mod.main(["-c", str(upstream / "refdes-project.yaml"), "build", "--keep-going"])
        == 0
    )
    # The artifact is the one the fix must read `source` out of.
    artifact = upstream / "_site" / "items.json"
    record = next(
        i for i in json.loads(artifact.read_text(encoding="utf-8"))["items"]
        if i["id"] == "REQ-IF001"
    )
    assert record["source"] == {"file": "items/req.yaml", "line": 3}

    downstream = tmp_path / "downstream"
    downstream.mkdir()
    _write_downstream(downstream)
    return downstream


def _diagnostic_for(project, item_id):
    found = [
        d
        for d in project.diagnostics
        if d.item_id == item_id and "points at" in d.message
    ]
    assert found, [str(d) for d in project.diagnostics]
    return found[0]


# --------------------------------------------------------------- the fix (new)


def test_imported_diagnostic_uses_upstream_source_location(imported_project):
    """An imported item's diagnostic is attributed to `platform:items/req.yaml:3` --
    the import name, a colon, the upstream-relative file, and the recorded line --
    instead of the fabricated `<import:platform>:1`."""
    project = _build_at(imported_project)
    diag = _diagnostic_for(project, "REQ-IF001")
    assert diag.file == "platform:items/req.yaml", diag.file
    assert diag.line == 3, diag.line


def test_imported_diagnostic_text_in_check_output(imported_project, capsys):
    """`refdes check` prints the imported item's diagnostic at the real location:
    `platform:items/req.yaml:3 [REQ-IF001] - refines points at 'REQ-MISSING', ...`."""
    status = cli_mod.main(
        [
            "-c",
            str(imported_project / "refdes-project.yaml"),
            "--no-write",
            "check",
        ]
    )
    captured = capsys.readouterr()
    assert status == 1
    lines = [
        line
        for line in captured.err.splitlines()
        if "[REQ-IF001]" in line
    ]
    assert len(lines) == 1, captured.err
    assert "platform:items/req.yaml:3" in lines[0], lines[0]
    assert "refines points at 'REQ-MISSING'" in lines[0]


# ------------------------------------------------------------- controls (base)


def test_local_item_diagnostic_unchanged(imported_project):
    """Control: a local item's diagnostic keeps the true local file:line."""
    project = _build_at(imported_project)
    diag = _diagnostic_for(project, "REQ-DOWN-001")
    assert diag.file == "items/local.yaml", diag.file
    assert diag.line == 3, diag.line


def test_artifact_record_without_source_keeps_import_pseudo_path(tmp_path):
    """Control: a hand-written artifact record with NO `source` object keeps today's
    `<import:platform>` / line 1 -- old artifacts must not break, and must not crash."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    record = {
        "id": "REQ-IF001",
        "type": "requirement",
        "fields": {"text": "Refines a missing requirement."},
        "links": {"refines": ["REQ-MISSING"]},
    }
    (upstream / "items.json").write_text(
        json.dumps({"version": "2026.3", "items": [record]}), encoding="utf-8"
    )
    downstream = tmp_path / "downstream"
    downstream.mkdir()
    _write_downstream(downstream, artifact_rel="../upstream/items.json")

    project = _build_at(downstream)
    diag = _diagnostic_for(project, "REQ-IF001")
    assert diag.file == "<import:platform>", diag.file
    assert diag.line == 1, diag.line


def test_artifact_record_with_incomplete_source_keeps_import_pseudo_path(tmp_path):
    """Control: a record whose `source` is not usable (a file with no integer line)
    falls back to `<import:platform>` / line 1."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    record = {
        "id": "REQ-IF001",
        "type": "requirement",
        "fields": {"text": "Refines a missing requirement."},
        "links": {"refines": ["REQ-MISSING"]},
        "source": {"file": "items/interfaces/req.md"},
    }
    (upstream / "items.json").write_text(
        json.dumps({"version": "2026.3", "items": [record]}), encoding="utf-8"
    )
    downstream = tmp_path / "downstream"
    downstream.mkdir()
    _write_downstream(downstream, artifact_rel="../upstream/items.json")

    project = _build_at(downstream)
    diag = _diagnostic_for(project, "REQ-IF001")
    assert diag.file == "<import:platform>", diag.file
    assert diag.line == 1, diag.line


def test_imported_item_stays_external_readonly(imported_project):
    """Control: the new location does not make the imported item writable locally --
    it stays external, and the editor still refuses to write it."""
    project = _build_at(imported_project)
    item = project.item_by_id("REQ-IF001")
    assert item.external is True
    assert item.origin == "platform"

    request = EditRequest(
        who="local-author",
        ref="REQ-IF001",
        op=SetField("text", "Rewritten from the downstream editor."),
        expected_revision=edit_mod.file_revision(
            str(imported_project / "items" / "local.yaml")
        ),
    )
    result = edit_mod.apply_edit(str(imported_project), request)
    assert isinstance(result, Refused), result
    assert "read-only" in result.message
