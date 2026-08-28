"""lifecycle -- and: gate rules, stamp.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

from helpers import LIFECYCLE_ITEMS, _check_severity_project, _lc_build, _pin_lifecycle_citation

from refdes import build as build_mod
from refdes import lifecycle, parse
from refdes.schema import load_project

# --------------------------------------------------------------- gate rules


def test_draft_items_rule_flags_only_the_draft_status_field(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["draft_items"].offenders == ["REQ-002"]


def test_uncovered_requirements_excludes_draft_items(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # REQ-001 is open and active -> offender. REQ-002 is open too, but draft
    # -> exempt, same problem as draft_items, not counted twice.
    assert results["uncovered_requirements"].offenders == ["REQ-001"]


def test_unverified_requirements_disabled_by_default_for_release(lifecycle_project):
    """Settled by the user: unverified requirements never block a release by
    default -- boards go to fab in order to get tested."""
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unverified_requirements"].enabled is False
    assert results["unverified_requirements"].status == "skipped"


def test_unverified_requirements_when_explicitly_enabled_excludes_draft(lifecycle_project):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "release_gate:\n  unverified_requirements: { release: true }\n",
        encoding="utf-8",
    )
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unverified_requirements"].offenders == ["REQ-001"]


def test_unpinned_citations_rule(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unpinned_citations"].offenders == ["CMP-001"]


def test_missing_vendored_copies_rule(lifecycle_project, tmp_path):
    root = lifecycle_project
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: deadbeef\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    vendored: true\n",
        encoding="utf-8",
    )
    project = _lc_build(root)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["missing_vendored_copies"].offenders == ["CMP-001"]
    # not simultaneously flagged as unpinned -- it IS pinned, just missing the blob
    assert results["unpinned_citations"].offenders == []


def test_unaccepted_board_moves_rule_reads_project_board_moves(lifecycle_project):
    """Drift detection itself is boards.py's own, extensively tested job --
    this only checks the gate rule reads project.board_moves correctly."""
    project = _lc_build(lifecycle_project)
    project.board_moves.append(("REQ-001", "board-a", "board-b"))
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unaccepted_board_moves"].offenders == ["REQ-001"]


def test_unaccepted_workspace_moves_rule_reads_project_workspace_moves(lifecycle_project):
    """Same shape as unaccepted_board_moves, reading project.workspace_moves
    instead -- a file silently changing workspace used to pass release
    unnoticed even though the same drift on board: already blocked it."""
    project = _lc_build(lifecycle_project)
    project.workspace_moves.append(("REQ-001", "alpha", "beta"))
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unaccepted_workspace_moves"].offenders == ["REQ-001"]
    assert results["unaccepted_workspace_moves"].status == "FAIL"
    # Same default posture as unaccepted_board_moves: on for release, off
    # for revision.
    revision_results = {r.name: r for r in lifecycle.evaluate_gate(project, "revision")}
    assert revision_results["unaccepted_workspace_moves"].status == "skipped"


def test_unaccepted_workspace_moves_blocks_a_release(lifecycle_project):
    project = _lc_build(lifecycle_project)
    project.workspace_moves.append(("REQ-001", "alpha", "beta"))
    outcome = lifecycle.stamp(project, kind="release", name="rev-a")
    assert outcome.status == "gate_failed"
    assert any(
        r.name == "unaccepted_workspace_moves" and r.status == "FAIL"
        for r in outcome.gate_results
    )


def test_info_check_failures_rule(tmp_path):
    project = _check_severity_project(
        tmp_path, item_type="option", item_id="OPT-001", prefix="opt"
    )
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "revision")}
    # off by default for revision too -- explicitly enable to see it fire.
    assert results["info_check_failures"].enabled is False
    project.release_gate["info_check_failures"]["release"] = True
    results2 = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results2["info_check_failures"].offenders == ["OPT-001"]


def test_nothing_defaults_on_for_revision(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = lifecycle.evaluate_gate(project, "revision")
    assert all(r.status == "skipped" for r in results)


# --------------------------------------------------------------------- stamp


def test_revision_stamps_unconditionally_despite_draft_and_uncovered_items(lifecycle_project):
    project = _lc_build(lifecycle_project)
    assert not project.errors
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    assert outcome.item_count == 3
    assert os.path.isfile(outcome.path)


def test_stamp_records_the_pinned_standard_version(tmp_path):
    """A baseline records `refdes_version` (the tool) but nothing said which
    *vocabulary* version produced its hashes -- revise.py needs this to know
    where to start migrating an existing baseline from."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 2, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n  - id: REQ-001\n    type: requirement\n    text: A requirement.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert project.standard_base == "hardware"
    assert project.standard_version == 2

    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.standard == {"base": "hardware", "version": 2}


def test_stamp_omits_standard_for_a_hand_rolled_schema(lifecycle_project):
    """`standard: none` (or no standard: key at all, as LIFECYCLE_SCHEMA has)
    must not fabricate a {base, version} -- there is no bundled vocabulary
    version to record."""
    project = _lc_build(lifecycle_project)
    assert project.standard_base == ""
    assert project.standard_version is None
    lifecycle.stamp(project, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.standard is None


def test_baseline_written_before_this_field_existed_loads_as_none(tmp_path):
    """Backward compatibility: an old baseline file with no `standard:` key
    at all must load with `.standard is None`, not raise or default to
    something that looks like an answer."""
    (tmp_path / ".refdes" / "baselines").mkdir(parents=True)
    (tmp_path / ".refdes" / "baselines" / "old.yaml").write_text(
        "kind: revision\n"
        "name: old\n"
        "stamped_at: '2026-01-01T00:00:00Z'\n"
        "stamped_by: someone\n"
        "refdes_version: 0.3.0\n"
        "items: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes.yaml").write_text(
        "site: {title: t, out: _site}\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    baseline = lifecycle.load_baseline(project, "old")
    assert baseline.standard is None


def test_release_blocked_then_passes_once_resolved(lifecycle_project):
    project = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    failing = {r.name for r in outcome.gate_results if r.enabled and r.offenders}
    assert failing == {"draft_items", "uncovered_requirements", "unpinned_citations"}
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))

    # Resolve all three: promote REQ-002 out of draft, cover REQ-001, pin CMP-001's citation.
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Uncovered active requirement.\n    status: active\n"
        "  - id: REQ-002\n    text: No longer a draft.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n    title: Covers both requirements.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    project2 = _lc_build(lifecycle_project)
    outcome2 = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert outcome2.status == "stamped"
    baseline = lifecycle.load_baseline(project2, "rel-a")
    assert baseline.kind == "release"
    assert baseline.gate["draft_items"] == "pass"
    assert baseline.gate["unverified_requirements"] == "skipped"
    assert set(baseline.items) == {"REQ-001", "REQ-002", "DEC-001", "CMP-001"}


def test_rerun_same_name_identical_content_is_a_noop(lifecycle_project):
    project = _lc_build(lifecycle_project)
    first = lifecycle.stamp(project, kind="revision", name="rev-a")
    mtime_before = os.path.getmtime(first.path)

    project2 = _lc_build(lifecycle_project)
    second = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert second.status == "unchanged"
    assert second.stamped_at == first.stamped_at
    assert os.path.getmtime(first.path) == mtime_before  # file untouched


def test_rerun_same_name_different_content_is_a_conflict(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        LIFECYCLE_ITEMS.replace("Uncovered active requirement.", "Edited text."),
        encoding="utf-8",
    )
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert outcome.status == "conflict"
    assert "different content" in outcome.conflict_detail
    assert "rev-a" in outcome.conflict_detail


def test_release_and_revision_are_peers_no_special_handling(lifecycle_project):
    """No lineage: a release does not need to follow or supersede the latest
    revision. Stamping rel-a after rev-a (a newer revision) is unremarkable."""
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Now covered.\n    status: active\n"
        "  - id: REQ-002\n    text: No longer draft.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert outcome.status == "stamped"


def test_kind_mismatch_under_the_same_name_is_a_conflict(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="shared-name")
    project2 = _lc_build(lifecycle_project)
    outcome = lifecycle.stamp(project2, kind="release", name="shared-name")
    # Same items, but kind differs (revision vs release) -- not a silent
    # kind upgrade; gate wasn't even satisfied here anyway (draft/uncovered).
    assert outcome.status in ("conflict", "gate_failed")
