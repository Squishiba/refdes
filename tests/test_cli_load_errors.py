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


def test_id_prints_each_load_error_once_when_allocation_runs(tmp_path, capsys):
    """`id` printed the load errors before allocating, then printed
    `project.errors` -- the cumulative list, load errors still in it --
    after, so a project with unparseable files and one item needing an id
    said every load error twice (DIAG-WORD-006). Each load error exactly
    once, the allocation-time collision (added to the same list by
    allocate()) exactly once, and the allocation report intact. --dry-run
    so nothing is written: the collision check runs before the dry-run
    return, which is what puts an allocation-time error on the list."""
    root = _project(tmp_path)
    for n in ("bad2", "bad3", "bad4"):
        (root / "items" / f"{n}.yaml").write_text(BROKEN, encoding="utf-8")
    (root / "items" / "good.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Taken.\n"
        '  - id: "001"\n    text: Collides.\n'
        "  - text: Needs an id.\n",
        encoding="utf-8",
    )

    code = _cli(root, "id", "--dry-run")
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.count("invalid YAML") == 4, captured.err
    assert captured.err.count("would expand to 'REQ-001'") == 1, captured.err
    assert "would allocate REQ-002  (items/good.yaml:7) Needs an id." in captured.out
    assert "would allocate 1 id(s)" in captured.out


def test_audit_reports_load_errors_and_exits_nonzero(tmp_path, capsys):
    root = _project(tmp_path)
    code = _cli(root, "audit")
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid YAML" in captured.err
    assert "items audited" in captured.out
    assert "1 items audited (1 local)" in captured.out
    # Once. `audit` prints load errors after the load, and then prints the
    # project-wide build diagnostics too (a file with no item id, which no
    # section of the report can speak for) -- and a load error is still in
    # `project.errors` at that point, so a list built without excluding them
    # says every one of them twice.
    assert captured.err.count("invalid YAML") == 1, captured.err


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
    """No load errors -> same stdout, exit 0.

    stderr is no longer empty on the first run: this fixture's item has no
    key, so the load minted one into the item file, and every command that
    loads writable now says what its load wrote (in-prog-logs/
    load-writes-everywhere-bug1.md). `index` says it on stderr because its
    stdout is JSON for the editor. The second run is the steady state -- the
    key is on disk now -- so `ls` prints nothing about writes, exactly as
    before."""
    root = _project(tmp_path, broken=False)

    code = _cli(root, "index")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == "(minted 1 key(s) while loading)\n"
    payload = json.loads(captured.out)
    assert [i["id"] for i in payload["items"]] == ["REQ-001"]

    code = _cli(root, "ls")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out == "REQ-001  requirement  Loads fine.\n"
