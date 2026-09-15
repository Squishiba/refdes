"""Load errors must never be invisible: a file that fails to parse has to be
reported, not silently dropped from the command's view of the project.

`refdes fetch` had this bug and was fixed in 9d52a5f; these are the same
shape for the commands that were still reporting success while items from an
unparsed file went missing. One broken YAML file alongside one valid file is
the repro: the valid item still has to appear, and the broken file has to be
named on stderr.
"""

from __future__ import annotations

import json

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import lifecycle, parse
from refdes.schema import load_project

SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
)

VALID = (
    "defaults: { type: requirement }\n"
    "items:\n"
    "  - id: REQ-001\n    text: Loads fine.\n"
)

BROKEN = "items:\n  - id: CMP-001\n    title: [broken\n"


def _project(tmp_path, broken=True):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "good.yaml").write_text(VALID, encoding="utf-8")
    if broken:
        (items / "bad.yaml").write_text(BROKEN, encoding="utf-8")
    return tmp_path


def _cli(root, *argv):
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), *argv])


def test_index_prints_load_errors_to_stderr_but_exits_zero(tmp_path, capsys):
    """`index` is the one command that keeps its exit code: the VS Code
    extension throws the whole index away on a non-zero exit, so a
    half-typed file mid-edit must not blank the editor. The load error is
    reported, the JSON still comes out complete for what did load."""
    root = _project(tmp_path)
    code = _cli(root, "index")
    captured = capsys.readouterr()
    assert code == 0
    assert "invalid YAML" in captured.err
    payload = json.loads(captured.out)
    assert [i["id"] for i in payload["items"]] == ["REQ-001"]


def test_ls_reports_load_errors_and_exits_nonzero(tmp_path, capsys):
    root = _project(tmp_path)
    code = _cli(root, "ls")
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid YAML" in captured.err
    assert "REQ-001" in captured.out and "Loads fine." in captured.out


def test_id_reports_load_errors_when_nothing_pending(tmp_path, capsys):
    """Every loaded item already has an id, so `id` used to say "no items
    are missing an id" and exit 0 -- while the items in the file that failed
    to load were never checked at all."""
    root = _project(tmp_path)
    code = _cli(root, "id")
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid YAML" in captured.err
    assert "no items are missing an id" not in captured.out
    assert "failed to load" in captured.out


def test_audit_reports_load_errors_and_exits_nonzero(tmp_path, capsys):
    root = _project(tmp_path)
    code = _cli(root, "audit")
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid YAML" in captured.err
    assert "items audited" in captured.out
    assert "1 items audited (1 local)" in captured.out


def test_former_ids_propose_reports_load_errors(tmp_path, capsys):
    """No candidates because nothing was renumbered -- but a file that never
    parsed was never searched either, and that has to be said and failed on."""
    root = _project(tmp_path, broken=False)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")
    (root / "items" / "bad.yaml").write_text(BROKEN, encoding="utf-8")

    code = _cli(root, "former-ids", "propose")
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid YAML" in captured.err
    assert "no candidate former-id mappings found" in captured.out
    assert "files that failed to load were not searched" in captured.out


def test_clean_project_index_and_ls_unchanged(tmp_path, capsys):
    """No load errors -> byte-identical behaviour: same stdout, nothing on
    stderr, exit 0."""
    root = _project(tmp_path, broken=False)

    code = _cli(root, "index")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert [i["id"] for i in payload["items"]] == ["REQ-001"]

    code = _cli(root, "ls")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out == "REQ-001  requirement  Loads fine.\n"
