"""integration.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil

import pytest
from helpers import CHECK_SEVERITY_SCHEMA, REPO, _build_at, _check_severity_project, _project

from refdes import build as build_mod
from refdes import seal
from refdes.schema import SchemaError, load_project

# -------------------------------------------------------------------- integration


def test_example_project_builds_and_catches_the_thermal_violation():
    project = _project()
    decision = project.items["DEC-PWR-001"]
    by_name = {c.value_name: c for c in decision.checks}
    assert by_name["eff"].ok is True
    assert by_name["P_dens"].ok is False
    assert "violates BND-THM-001" in " ".join(d.message for d in project.errors)


def _io_check_project(tmp_path, *, tolerance):
    """A single toleranced (or exact) check violating a `<=` constraint."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items"
    items.mkdir()
    (items / "io.yaml").write_text(
        "defaults: { type: bound }\n"
        "items:\n"
        "  - id: BND-IO-004\n"
        "    title: Input current budget\n"
        '    limit: "<= 600 mA"\n',
        encoding="utf-8",
    )
    calc_line = "CLIM : A = 0.6061 A ± 15%" if tolerance else "CLIM : A = 0.697 A"
    (items / "dec-io-002.md").write_text(
        "---\n"
        "id: DEC-IO-002\n"
        "type: decision\n"
        "title: Input current draw\n"
        "status: accepted\n"
        "constrained_by: [BND-IO-004]\n"
        "checks:\n"
        "  - value: CLIM\n"
        "    against: BND-IO-004\n"
        "---\n\n"
        f"```calc\n{calc_line}\n```\n",
        encoding="utf-8",
    )
    return _build_at(tmp_path)


def test_check_error_reports_worst_case_with_nominal_in_parens(tmp_path):
    """A toleranced breach must report its worst-case bound, not just the nominal.

    Reporting only the nominal (0.6061 A) makes a 97 mA / 16% worst-case breach
    read as a 6 mA overshoot. The nominal stays in a parenthetical because it is
    the number a reader recognises from the calc block.
    """
    project = _io_check_project(tmp_path, tolerance=True)
    check = project.items["DEC-IO-002"].checks[0]
    assert check.ok is False
    message = next(d.message for d in project.errors if "BND-IO-004" in d.message)
    assert (
        "CLIM violates BND-IO-004: worst case 0.697 A vs <= 600 mA (nominal 0.6061 A)"
        in message
    )


def test_check_error_omits_nominal_when_worst_case_equals_it(tmp_path):
    """No tolerance means worst case and nominal are the same number.

    The parenthetical would be pure noise here, so it must not appear.
    """
    project = _io_check_project(tmp_path, tolerance=False)
    check = project.items["DEC-IO-002"].checks[0]
    assert check.ok is False
    message = next(d.message for d in project.errors if "BND-IO-004" in d.message)
    assert "CLIM violates BND-IO-004: worst case 0.697 A vs <= 600 mA" in message
    assert "nominal" not in message


def test_check_severity_info_does_not_error_or_block_the_build(tmp_path):
    """finding 18: a candidate type can mark failing checks as findings, not defects."""
    project = _check_severity_project(
        tmp_path, item_type="option", item_id="OPT-IO-001", prefix="opt"
    )
    check = project.items["OPT-IO-001"].checks[0]
    assert check.ok is False  # the Checks table must still show the failure
    assert not project.errors
    info_messages = [d.message for d in project.infos]
    assert any("CLIM violates CON-IO-004" in m for m in info_messages)


def test_check_severity_defaults_to_error_when_unconfigured(tmp_path):
    """Back-compat: a type with no check_severity: still errors, same as before this existed."""
    project = _check_severity_project(
        tmp_path, item_type="decision", item_id="DEC-IO-001", prefix="dec"
    )
    check = project.items["DEC-IO-001"].checks[0]
    assert check.ok is False
    assert any("CLIM violates CON-IO-004" in d.message for d in project.errors)
    assert not project.infos


def test_check_severity_rejects_an_unrecognized_value(tmp_path):
    bad_schema = CHECK_SEVERITY_SCHEMA.replace(
        "check_severity: info", "check_severity: nonsense"
    )
    (tmp_path / "refdes.yaml").write_text(bad_schema, encoding="utf-8")
    with pytest.raises(SchemaError, match="check_severity"):
        load_project(config_path=str(tmp_path / "refdes.yaml"))


def test_check_severity_info_still_errors_on_a_malformed_check_entry(tmp_path):
    """Only a failing (evaluated) check is downgraded -- a broken checks: entry is
    always an authoring mistake, regardless of the item's type."""
    project = _check_severity_project(
        tmp_path,
        item_type="option",
        item_id="OPT-IO-002",
        prefix="opt",
        checks_extra="  - value: CLIM\n    against: CON-DOES-NOT-EXIST\n",
    )
    assert any("does not exist" in d.message for d in project.errors)


def test_backlinks_resolve_from_either_end_of_an_edge():
    """A test declaring `verifies` must appear as `verified_by` on the requirement."""
    project = _project()
    assert project.items["REQ-PWR-002"].backlinks["verified_by"] == ["TST-PWR-002"]
    assert project.items["REQ-PWR-002"].backlinks["satisfied_by"] == ["DEC-PWR-001"]


def test_coverage_separates_addressed_satisfied_and_verified():
    project = _project()
    cov = project.coverage

    # Worked on and decided, but no test proves it yet.
    assert cov["REQ-PWR-003"].stage == "satisfied"
    assert cov["REQ-PWR-003"].satisfied_by == ["DEC-PWR-001"]
    assert cov["REQ-PWR-003"].verified_by == []

    # Linked to a test, but that test is only 'planned', not 'passing' -- the
    # standard's test.verifying_statuses: [passing] means a merely-linked test
    # doesn't count as having verified anything yet.
    assert cov["REQ-PWR-002"].stage == "satisfied"
    assert cov["REQ-PWR-002"].verified_by == []

    # requirement.coverable_statuses: [active] excludes draft items from
    # coverage entirely -- REQ-PWR-004 (draft) isn't tracked at all.
    assert "REQ-PWR-004" not in cov

    # Written down and never touched again.
    assert cov["BND-THM-002"].stage == "open"

    # A log entry alone counts as addressed, not satisfied.
    assert cov["BND-THM-001"].stage == "addressed"
    assert "LOG-A-005" in cov["BND-THM-001"].addressed_by


def test_outstanding_work_is_aggregated_into_summary_lines():
    """The real project's own coverage gaps (issue #3, finding 8) roll up into
    two summary lines instead of one warning per requirement."""
    project = _project()

    open_count = sum(1 for c in project.coverage.values() if c.stage == "open")
    unverified_count = sum(
        1
        for item_id, c in project.coverage.items()
        if c.stage != "open"
        and c.stage != "claimed"
        and not c.verified_by
        and project.items[item_id].type == "requirement"
    )
    assert open_count > 0 and unverified_count > 0  # otherwise this proves nothing

    aggregate_messages = {d.message for d in project.warnings if d.item_id is None}
    assert f"{open_count} item(s) with no coverage — see coverage.html" in aggregate_messages
    assert (
        f"{unverified_count} requirement(s) satisfied but not verified — see coverage.html"
        in aggregate_messages
    )

    # Neither routine class leaves a per-item warning behind.
    assert not any(d.item_id == "REQ-PWR-003" for d in project.warnings)
    assert not any(d.item_id == "REQ-PWR-004" for d in project.warnings)
    assert not any(d.item_id == "REQ-PWR-001" for d in project.warnings)  # verified


def test_log_entries_are_sealed_and_edits_are_caught():
    project = _project()
    entry = project.items["LOG-A-003"]
    # This repo's committed seal file predates the hash-format change
    # (docs/design/keys.md §5, link targets hashed as resolved keys), and
    # _project() never mints keys, so the seal's stored hash and
    # entry.content_hash are no longer expected to be byte-identical
    # strings -- verify()'s hash-format-aware comparison (seal.py's
    # _matches_sealed_hash) is what actually answers "is this unedited",
    # which is what this assertion means to check.
    seal.verify(project, write=False, reseal=False)
    assert "LOG-A-003" not in project.seal_violations

    entry.fields["summary"] = "edited after the fact"
    build_mod.compute_hashes(project)
    seal.verify(project, write=False, reseal=False)
    assert "LOG-A-003" in project.seal_violations


def test_log_amendments_are_links_not_edits():
    """A correction appends a new entry rather than rewriting the old one."""
    project = _project()
    # resolved_links, not links: this repo's own items/ has been through
    # links.expand_missing() (docs/design/keys.md §3), so the raw stored
    # target is now a frozen `LOG-A-003@<key>` composite -- item.links is
    # documented (model.py) as "nothing that merely traverses the graph
    # should read it directly". resolved_links is the always-bare form
    # every other graph-walking consumer reads, and what this assertion
    # actually means to check: that the link resolves to LOG-A-003.
    assert project.items["LOG-A-006"].resolved_links["amends"] == ["LOG-A-003"]
    assert project.items["LOG-A-003"].backlinks["amended_by"] == ["LOG-A-006"]
