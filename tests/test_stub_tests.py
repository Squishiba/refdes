"""stub-tests.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import pytest

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import ids, parse
from refdes import stub_tests as stub_tests_mod
from refdes.schema import SchemaError, load_project

# --------------------------------------------------------------- stub-tests

STUB_SCHEMA = """\
site: {title: "Stub Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
boards:
  power: {label: Power}
  thermal: {label: Thermal}
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies:  { inverse: verified_by,  label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted], default: proposed, on_change: invalidate }
    satisfying_statuses: [accepted]
    links:
      satisfies: [requirement]
    body: { on_change: invalidate }
  test:
    prefix: TST
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [planned, passing, failing], default: planned, on_change: invalidate }
      method: { type: text, on_change: invalidate }
    verifying_statuses: [passing]
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""


STUB_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Fully open, nothing touches it.
board: power
---
""",
    "req-002.md": """\
---
id: REQ-002
type: requirement
text: Satisfied by an accepted decision, no test yet.
board: power
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Settle REQ-002.
status: accepted
board: power
satisfies: [REQ-002]
---
""",
}


@pytest.fixture
def stub_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(STUB_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in STUB_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _stub_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_generate_writes_one_stub_per_uncovered_item(stub_project):
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project)
    assert len(written) == 1
    path, item_ids = written[0]
    assert path == "items/power/stub-tests.md"
    assert sorted(item_ids) == ["REQ-001", "REQ-002"]

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert "type: test" in text
    assert "title: Verify REQ-001" in text
    assert "status: planned" in text
    assert 'method: ""' in text
    assert "verifies: [REQ-001]" in text
    assert "verifies: [REQ-002]" in text


def test_generate_dry_run_writes_nothing(stub_project):
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project, dry_run=True)
    assert len(written) == 1
    assert not (stub_project / "items" / "power" / "stub-tests.md").exists()


def test_a_stub_status_planned_never_counts_as_verified(stub_project):
    """The prerequisite this feature relies on: verifying_statuses already
    means a status: planned test doesn't settle coverage, so a generated
    stub never retroactively marks its target verified. Getting this wrong
    would recreate, at scale, the exact coverage bug this project already
    fixed once in the verify half."""
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    project = _stub_build(stub_project)  # reload with real ids now in place

    cov1 = project.coverage["REQ-001"]
    assert cov1.verified_by == []
    assert cov1.stage != "verified"

    cov2 = project.coverage["REQ-002"]
    assert cov2.verified_by == []
    assert cov2.stage == "satisfied"  # not bumped to "verified"


def test_rerun_before_id_allocation_does_not_duplicate(stub_project):
    """A generated stub has no id yet, so resolve_links() never sees its
    verifies: edge -- the dedup check has to look at project.pending too,
    or running this twice in a row (with no `refdes id` in between) would
    generate a second stub for the same requirement."""
    project = _stub_build(stub_project)
    first = stub_tests_mod.generate(project)
    assert sum(len(ids) for _p, ids in first) == 2

    project2 = _stub_build(stub_project)  # re-parse; new items are still pending
    second = stub_tests_mod.generate(project2)
    assert second == []

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert text.count("verifies: [REQ-001]") == 1
    assert text.count("verifies: [REQ-002]") == 1


def test_rerun_after_id_allocation_does_not_duplicate(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)

    project2 = _stub_build(stub_project)
    second = stub_tests_mod.generate(project2)
    assert second == []


def test_deleting_a_stub_makes_its_target_eligible_again(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)

    text = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    # Remove the REQ-002 stub block entirely, leaving REQ-001's alone.
    blocks = text.split("---\n")
    kept = [b for b in blocks if "REQ-002" not in b]
    (stub_project / "items" / "power" / "stub-tests.md").write_text(
        "---\n".join(kept), encoding="utf-8"
    )

    project2 = _stub_build(stub_project)
    third = stub_tests_mod.generate(project2)
    assert len(third) == 1
    _path, covered_ids = third[0]
    assert covered_ids == ["REQ-002"]


def test_new_requirement_appends_without_touching_existing_stubs(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    before = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")

    (stub_project / "items" / "req-003.md").write_text(
        "---\nid: REQ-003\ntype: requirement\ntext: Added later.\nboard: power\n---\n",
        encoding="utf-8",
    )
    project2 = _stub_build(stub_project)
    stub_tests_mod.generate(project2)

    after = (stub_project / "items" / "power" / "stub-tests.md").read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "verifies: [REQ-003]" in after

    ids.allocate(project2)
    project3 = _stub_build(stub_project)
    assert not project3.errors


def test_groups_by_board(stub_project):
    (stub_project / "items" / "req-t1.md").write_text(
        "---\nid: REQ-T1\ntype: requirement\ntext: Thermal one.\nboard: thermal\n---\n",
        encoding="utf-8",
    )
    project = _stub_build(stub_project)
    written = stub_tests_mod.generate(project)
    paths = {p for p, _ids in written}
    assert paths == {"items/power/stub-tests.md", "items/thermal/stub-tests.md"}


def test_no_verifier_type_is_an_error(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n  requirement: {prefix: REQ, coverable: true, "
        "fields: {text: {type: text, required: true}}}\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.md").write_text(
        "---\nid: REQ-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    project = _stub_build(tmp_path)
    with pytest.raises(SchemaError, match="no type declares a 'verifies' link"):
        stub_tests_mod.generate(project)


def test_ambiguous_verifier_type_requires_type_flag(stub_project):
    text = STUB_SCHEMA + (
        "  inspection:\n"
        "    prefix: INSP\n"
        "    fields:\n"
        "      title: {type: text, required: true}\n"
        "    links:\n"
        "      verifies: [requirement]\n"
    )
    (stub_project / "refdes.yaml").write_text(text, encoding="utf-8")
    project = _stub_build(stub_project)
    with pytest.raises(SchemaError, match="multiple types declare 'verifies'"):
        stub_tests_mod.generate(project)
    written = stub_tests_mod.generate(project, verifier_type="test")
    assert written


def test_nothing_to_do_returns_empty_list(stub_project):
    project = _stub_build(stub_project)
    stub_tests_mod.generate(project)
    ids.allocate(project)
    project2 = _stub_build(stub_project)
    assert stub_tests_mod.generate(project2) == []


def test_cli_stub_tests_end_to_end(stub_project, capsys):
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 0
    out = capsys.readouterr().out
    assert "wrote 2 stub test(s)" in out
    assert "Run 'refdes id'" in out
    assert (stub_project / "items" / "power" / "stub-tests.md").is_file()


def test_cli_stub_tests_refuses_when_the_project_has_errors(stub_project, capsys):
    (stub_project / "items" / "broken.md").write_text(
        "---\nid: BAD-001\ntype: nonexistent\ntitle: t.\n---\n", encoding="utf-8"
    )
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 1
    assert not (stub_project / "items" / "power" / "stub-tests.md").exists()


def test_cli_stub_tests_reports_nothing_to_do(stub_project, capsys):
    cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    ids.allocate(_stub_build(stub_project))
    capsys.readouterr()
    status = cli_mod.main(["-c", str(stub_project / "refdes.yaml"), "stub-tests"])
    assert status == 0
    out = capsys.readouterr().out
    assert "no coverable item is missing a verifying test" in out
