"""lifecycle -- and: gate rules, stamp.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest

from conftest import write_project_config
from helpers import LIFECYCLE_ITEMS, _check_severity_project, _lc_build, _pin_lifecycle_citation

from refdes import build as build_mod
from refdes import history, keys, lifecycle, parse
from refdes.schema import SchemaError, load_project

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
    # Append: `refdes-project.yaml` is the marker holding site:/standard:/types:,
    # so overwriting it would silently test a different project.
    with (lifecycle_project / "refdes-project.yaml").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write("release_gate:\n  unverified_requirements: { release: true }\n")
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unverified_requirements"].offenders == ["REQ-001"]


def test_unpinned_citations_rule(lifecycle_project):
    project = _lc_build(lifecycle_project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["unpinned_citations"].offenders == ["CMP-001"]


def _pin_kept_copy_without_blob(root) -> None:
    """The state the `audit` pin-column fix must not disturb: a lockfile that
    says `kept_copy: true` with no bytes behind it."""
    (root / ".refdes").mkdir(exist_ok=True)
    (root / ".refdes" / "citations.yaml").write_text(
        "citations:\n"
        "  https://example.com/datasheet.pdf:\n"
        "    sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: true\n",
        encoding="utf-8",
    )


def test_missing_kept_copies_rule(lifecycle_project, tmp_path):
    root = lifecycle_project
    _pin_kept_copy_without_blob(root)
    project = _lc_build(root)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["missing_kept_copies"].offenders == ["CMP-001"]
    # not simultaneously flagged as unpinned -- it IS pinned, just missing the blob
    assert results["unpinned_citations"].offenders == []


def test_missing_kept_copies_still_reads_the_state_word_not_the_pin_word(lifecycle_project):
    """Pinned so a reworded `audit` citation row can't quietly stop blocking a
    release. The rule filters on `status.state == "cache_missing"`
    (lifecycle.py:577-585) and never looks at the pin column, which `audit`
    now renders as `no copy` for exactly this state -- so the gate must still
    FAIL, and still name the item. See tests/test_citations.py's
    `test_cli_audit_never_calls_a_missing_kept_copy_kept` for the other half.
    """
    root = lifecycle_project
    _pin_kept_copy_without_blob(root)
    project = _lc_build(root)
    status = project.item_by_id("CMP-001").citations[0]
    assert status.state == "cache_missing"
    assert status.kept_copy is True  # the lockfile flag the rule must ignore
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    rule = next(r for r in outcome.gate_results if r.name == "missing_kept_copies")
    assert rule.status == "FAIL"
    assert rule.offenders == ["CMP-001"]


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
    project = load_project(
        config_path=str(
            write_project_config(
                tmp_path,
                "site: { title: T, out: _site }\n"
                "standard: { base: hardware, version: 2, presets: [] }\n",
            )
        )
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n  - id: REQ-001\n    type: requirement\n    text: A requirement.\n",
        encoding="utf-8",
    )
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
    project = load_project(
        config_path=str(
            write_project_config(
                tmp_path,
                "site: {title: t, out: _site}\n"
                "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n",
            )
        )
    )
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


# ------------------------------------------------- H8: open_tasks / captured_edits
#
# Both rules are off by default (living-notes plan §H8): the gate reads the
# thread fold and the H3 diagnostic, and an opt-in `release_gate:` overlay is
# the only way to make either one block. The fold is read through
# `chains.fold_tasks` (the same per-tip walk `threads.threads_projection`
# uses), never re-implemented.

H8_CONFIG = (
    "site: { title: H8, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

# One tip: LOG-001 declares the list, LOG-002's tip folds it. One open row,
# one done row -- the done row is §5 rule 2's ticked task and never blocks.
H8_OPEN_TASK_THREAD = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "      - {id: T-thermal-done, text: Read the datasheet., state: done}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling started.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
)

H8_GATE_RULES_ON = "release_gate:\n  open_tasks: { release: true }\n"


def _h8_project(tmp_path, items_yaml, extra_config=""):
    write_project_config(tmp_path, H8_CONFIG + extra_config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    return _h8_rebuild(tmp_path, extra_config)


def _h8_rebuild(tmp_path, extra_config=""):
    """Reload/rebuild WITHOUT rewriting items/ -- the rebuild after an edit
    or a capture must see the edited files, not the fixture's text."""
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    return project


def _capture_then_edit(tmp_path, root_project, item_id, new_summary):
    """H3's state for real: capture through the history store's own API, then
    edit the item file so the live digest differs from the snapshot."""
    history.capture(str(tmp_path), root_project.item_by_id(item_id))
    log = tmp_path / "items" / "log.yaml"
    text = log.read_text(encoding="utf-8").replace(
        "summary: Power work list.", f"summary: {new_summary}"
    )
    log.write_text(text, encoding="utf-8")


def test_both_new_rules_are_off_for_both_kinds_by_default(tmp_path):
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD)
    for kind in ("release", "revision"):
        results = {r.name: r for r in lifecycle.evaluate_gate(project, kind)}
        assert results["open_tasks"].enabled is False
        assert results["open_tasks"].status == "skipped"
        assert results["captured_edits"].enabled is False
        assert results["captured_edits"].status == "skipped"


def test_default_off_a_dirty_project_stamps_exactly_the_main_shape(tmp_path):
    """The phase's strongest nothing-changed test: with an open task at the
    tip AND an edited-after-captured item, `refdes release` still stamps --
    and the stamped baseline is compared, not just the exit code. The
    baseline `gate:` block records every rule including skipped ones (main's
    own posture, see test_release_blocked_then_passes_once_resolved), so
    this pins the whole block: every main rule keeps its main status and the
    two new rules appear as `skipped`, nothing else."""
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD)
    _capture_then_edit(tmp_path, project, "LOG-001", "Rewritten after capture.")
    project = _h8_rebuild(tmp_path)
    # the edited-after-captured diagnostic is a warning, never an error
    assert not project.errors
    assert any("edited after captured" in d.message for d in project.warnings)

    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "stamped"
    baseline = lifecycle.load_baseline(project, "rel-a")
    assert baseline.gate == {
        "draft_items": "pass",
        "unpinned_citations": "pass",
        "missing_kept_copies": "pass",
        "uncovered_requirements": "pass",
        "unverified_requirements": "skipped",
        "info_check_failures": "skipped",
        "unaccepted_board_moves": "pass",
        "unaccepted_workspace_moves": "pass",
        "open_tasks": "skipped",
        "captured_edits": "skipped",
    }
    # stamped output: the stamped items are exactly the project's items,
    # unchanged in shape by the new rules
    assert set(baseline.items) == {"LOG-001", "LOG-002"}


def test_default_off_cli_release_stdout_unchanged(tmp_path, capsys):
    """CLI half of the default-off proof: stdout is the ordinary stamped
    report -- no new lines, exit 0 -- on a project the new rules would
    block if they were on."""
    _h8_project(tmp_path, H8_OPEN_TASK_THREAD)
    cfg = str(tmp_path / "refdes-project.yaml")
    from refdes import cli as cli_mod

    assert cli_mod.main(["-c", cfg, "release", "rel-a"]) == 0
    out = capsys.readouterr().out
    assert "release 'rel-a' stamped" in out
    assert "all gates passed" in out


def test_open_tasks_enabled_blocks_with_named_offender(tmp_path):
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD, H8_GATE_RULES_ON)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # the offender names the tip it sits at and the task id to go tick --
    # the open row folds down from LOG-001 to the LOG-002 tip
    assert results["open_tasks"].status == "FAIL"
    assert results["open_tasks"].offenders == ["LOG-002: open task T-thermal-model"]

    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))
    # revision stays false while release is true: the revision still stamps
    revision = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert revision.status == "stamped"


def test_captured_edits_enabled_blocks_naming_the_item(tmp_path):
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD)
    _capture_then_edit(tmp_path, project, "LOG-001", "Rewritten after capture.")
    write_project_config(
        tmp_path, H8_CONFIG + "release_gate:\n  captured_edits: { release: true }\n"
    )
    project = _h8_rebuild(tmp_path)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["captured_edits"].status == "FAIL"
    assert results["captured_edits"].offenders == ["LOG-001"]
    # open_tasks off here: the open task alone does not block
    assert results["open_tasks"].status == "skipped"

    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    rule = next(r for r in outcome.gate_results if r.name == "captured_edits")
    assert rule.offenders == ["LOG-001"]
    revision = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert revision.status == "stamped"


def test_captured_edits_quiet_while_the_digest_still_matches(tmp_path):
    """The rule reads the diagnostic, not a file mtime: revert the edit and
    the current digest matches the snapshot again, and the rule passes."""
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD)
    _capture_then_edit(tmp_path, project, "LOG-001", "Rewritten after capture.")
    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace(
            "summary: Rewritten after capture.", "summary: Power work list."
        ),
        encoding="utf-8",
    )
    write_project_config(
        tmp_path, H8_CONFIG + "release_gate:\n  captured_edits: { release: true }\n"
    )
    project = _h8_rebuild(tmp_path)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["captured_edits"].status == "pass"


def test_unknown_rule_name_still_rejected_with_the_existing_message(tmp_path):
    from refdes.schema import load_project as lp

    cfg = write_project_config(tmp_path, H8_CONFIG + "release_gate:\n  open_task: { release: true }\n")
    with pytest.raises(SchemaError) as excinfo:
        lp(config_path=str(cfg))
    assert "release_gate.open_task is not a known rule" in str(excinfo.value)
    # the new names are part of the known set the suggestion runs against
    assert "open_tasks" in str(excinfo.value)


def test_open_tasks_counts_author_rows_only_never_derived(tmp_path):
    """§5 rules 1-2 enforced at the gate: a thread whose only open work is
    derived rows (an uncovered requirement) must not trip open_tasks."""
    items = H8_OPEN_TASK_THREAD.replace(
        "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n",
        "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: dropped}\n",
    )
    write_project_config(tmp_path, H8_CONFIG + H8_GATE_RULES_ON)
    items_dir = tmp_path / "items"
    items_dir.mkdir(exist_ok=True)
    (items_dir / "log.yaml").write_text(items, encoding="utf-8")
    (items_dir / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Nobody has covered this yet.\n    status: active\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # the derived problem is real (the default-on coverage rule sees it)...
    assert results["uncovered_requirements"].offenders == ["REQ-001"]
    # ...and open_tasks stays clean: dropped is not open, and a derived row
    # is not a task
    assert results["open_tasks"].status == "pass"


def test_open_tasks_counts_every_open_tip_of_a_fork(tmp_path):
    fork = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Head., date: 2026-08-30}\n"
        "  - id: LOG-002\n"
        "    summary: Thermal branch.\n"
        "    date: 2026-09-02\n"
        "    follows: LOG-001\n"
        "    tasks:\n"
        "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
        "  - id: LOG-003\n"
        "    summary: Decoupling branch.\n"
        "    date: 2026-09-03\n"
        "    follows: LOG-001\n"
        "    tasks:\n"
        "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
    )
    project = _h8_project(tmp_path, fork, H8_GATE_RULES_ON)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["open_tasks"].offenders == [
        "LOG-002: open task T-thermal-model",
        "LOG-003: open task T-decoupling",
    ]
    # done/dropped tasks don't trip it: the same fork with both lists done
    done = fork.replace("state: open", "state: done")
    alt = tmp_path / "done-variant"
    alt.mkdir()
    write_project_config(alt, H8_CONFIG + H8_GATE_RULES_ON)
    alt_items = alt / "items"
    alt_items.mkdir()
    (alt_items / "log.yaml").write_text(done, encoding="utf-8")
    project2 = load_project(config_path=str(alt / "refdes-project.yaml"))
    parse.load_items(project2)
    keys.mint_missing(project2)
    build_mod.build(project2)
    results2 = {r.name: r for r in lifecycle.evaluate_gate(project2, "release")}
    assert results2["open_tasks"].status == "pass"


def test_conflicting_fold_at_a_tip_blocks(tmp_path):
    """A task fold that refused between differing equal-distance
    declarations blocks: the gate must not pass a list it couldn't read.
    The offender says the list is conflicting, in the fold's own words."""
    merge = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-007, summary: Merge parent left., date: 2026-08-07, tasks: [{id: a, text: Left., state: done}]}\n"
        "  - {id: LOG-008, summary: Merge parent right., date: 2026-08-08, tasks: [{id: b, text: Right., state: done}]}\n"
        "  - {id: LOG-009, summary: Silent merge., date: 2026-08-09, follows: [LOG-007, LOG-008]}\n"
    )
    project = _h8_project(tmp_path, merge, H8_GATE_RULES_ON)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["open_tasks"].offenders == [
        "LOG-009: conflicting task list (task reconciliation required)"
    ]


def test_open_tasks_names_a_lone_thread_head_provisionally(tmp_path):
    """Provisional design decision (plan doesn't settle it): a lone entry
    with no `follows:` at all is fold_tasks' own "thread of one -- the
    ordinary log head the first task list is written on", so its open task
    blocks. If the owner decides only edge-bearing threads count, this test
    flips."""
    lone = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: First list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        "      - {id: t1, text: One., state: open}\n"
    )
    project = _h8_project(tmp_path, lone, H8_GATE_RULES_ON)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["open_tasks"].offenders == ["LOG-001: open task t1"]


def test_revision_half_can_be_enabled_for_both_rules_through_the_overlay(tmp_path):
    """Design posture (open question in the PR): both rules' revision half
    is overlay-enable-able like every other rule's; nothing special-cases
    them out of it."""
    project = _h8_project(
        tmp_path,
        H8_OPEN_TASK_THREAD,
        "release_gate:\n  open_tasks: { revision: true }\n  captured_edits: { revision: true }\n",
    )
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "revision")}
    assert results["open_tasks"].status == "FAIL"
    assert results["captured_edits"].status == "pass"
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "gate_failed"
