"""lifecycle -- and: gate rules, stamp.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest

from conftest import write_project_config
from helpers import LIFECYCLE_ITEMS, _check_severity_project, _lc_build, _pin_lifecycle_citation

from refdes import adopt
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


def test_rerun_same_name_identical_content_after_keys_adopt_is_a_noop(lifecycle_project):
    project = _lc_build(lifecycle_project)
    first = lifecycle.stamp(project, kind="revision", name="rev-a")

    adoption = adopt.apply(str(lifecycle_project))
    assert adoption.ok, adoption.errors
    mtime_after_adoption = os.path.getmtime(first.path)

    project2 = _lc_build(lifecycle_project)
    second = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert second.status == "unchanged"
    assert second.stamped_at == first.stamped_at
    assert os.path.getmtime(first.path) == mtime_after_adoption  # file untouched


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
    # Loading minted surrogate keys and rewrote the item files -- rebuild once
    # so the parsed source lines in the returned project name the CURRENT
    # files, which is what the gate's file:line offenders must match.
    _h8_rebuild(tmp_path, extra_config)
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
        "inline_calc_results": "pass",
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


def _line_of(root, needle):
    """1-indexed line of the task row in the file on disk (after the
    key-minting rewrite), so tests assert the real source location instead
    of a magic number that drifts with the fixture."""
    text = (root / "items" / "log.yaml").read_text(encoding="utf-8")
    return next(i for i, line in enumerate(text.splitlines(), start=1) if needle in line)


def test_cli_gate_table_offender_names_the_rows_line(tmp_path, capsys):
    """The clickable line where the owner asked for it: the printed table
    row carries the task row's file:line."""
    from refdes import cli as cli_mod

    _h8_project(tmp_path, H8_OPEN_TASK_THREAD, H8_GATE_RULES_ON)
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "release", "rel-a"]) == 1
    err = capsys.readouterr().err
    line = _line_of(tmp_path, "id: T-thermal-model")
    assert f"FAIL     open_tasks  LOG-002: open task T-thermal-model (items/log.yaml:{line})" in err
    real = (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8").splitlines()
    assert "id: T-thermal-model" in real[line - 1]


def test_open_tasks_enabled_blocks_with_named_offender(tmp_path):
    project = _h8_project(tmp_path, H8_OPEN_TASK_THREAD, H8_GATE_RULES_ON)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    # the offender names the tip it sits at and the task id to go tick --
    # the open row folds down from LOG-001 to the LOG-002 tip -- and carries
    # the row's own file:line
    assert results["open_tasks"].status == "FAIL"
    line = _line_of(tmp_path, "id: T-thermal-model")
    assert results["open_tasks"].offenders == [
        f"LOG-002: open task T-thermal-model (items/log.yaml:{line})"
    ]
    # the location really names the task row, not a nearby line
    real = (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8").splitlines()
    assert "id: T-thermal-model" in real[line - 1]

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


def test_open_tasks_ignores_a_derived_row_reached_through_a_link(tmp_path):
    """§5 rules 1-2 at the gate, one hop out: the tip's `addresses:` link puts
    the requirement's coverage gap INTO the thread's derived block
    (`threads._scope` follows each member's own links one hop), so a gate
    implementation that read derived rows instead of only the authored fold
    would trip here. It must not: the gap stays its own rule's business and
    `open_tasks` stays clean."""
    from refdes import threads

    items = H8_OPEN_TASK_THREAD.replace(
        "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n",
        "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: dropped}\n",
    ).replace(
        "    follows: LOG-001\n",
        "    follows: LOG-001\n    addresses: REQ-001\n",
    )
    write_project_config(tmp_path, H8_CONFIG + H8_GATE_RULES_ON)
    items_dir = tmp_path / "items"
    items_dir.mkdir(exist_ok=True)
    (items_dir / "log.yaml").write_text(items, encoding="utf-8")
    (items_dir / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    title: Idle current budget\n    status: active\n"
        "    body: The idle rail must stay under 10 uA.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    # the one-hop reach is real: the derived row for a non-member, reached
    # through the tip's own link, shows in the thread's derived block (§6's
    # decided example). `addresses` makes the gap `unverified`, not `open`.
    (view,) = threads.threads_projection(project)
    assert [(row["kind"], row["problem"], row["ref"]) for row in view["derived"]] == [
        ("coverage", "unverified", "REQ-001")
    ]
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["open_tasks"].status == "pass"
    assert results["open_tasks"].offenders == []


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
        f"LOG-002: open task T-thermal-model (items/log.yaml:{_line_of(tmp_path, 'id: T-thermal-model')})",
        f"LOG-003: open task T-decoupling (items/log.yaml:{_line_of(tmp_path, 'id: T-decoupling')})",
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
    # the tip declares no list of its own (that is the ambiguity), so the
    # location is the tip entry's own line -- the file position to open to
    # resolve the conflict
    assert results["open_tasks"].offenders == [
        "LOG-009: conflicting task list (task reconciliation required) "
        f"(items/log.yaml:{_line_of(tmp_path, 'id: LOG-009')})"
    ]


def test_open_tasks_names_a_lone_thread_head(tmp_path):
    """Owner decision (PR #193): a lone entry with no `follows:` at all is
    fold_tasks' own "thread of one -- the ordinary log head the first task
    list is written on", so its open task blocks."""
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
    assert results["open_tasks"].offenders == [
        f"LOG-001: open task t1 (items/log.yaml:{_line_of(tmp_path, 'id: t1')})"
    ]


def test_revision_half_can_be_enabled_for_both_rules_through_the_overlay(tmp_path):
    """Owner decision (PR #193): both rules' revision half is
    overlay-enable-able like every other rule's; nothing special-cases them
    out of it."""
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


# ------------------------------------------------- inline_calc_results

IC_CONFIG = (
    "site: { title: IC, out: _site }\n"
    "types: { decision: { prefix: DEC, fields: {} } }\n"
)

# Stored 4.52 V, computes 4.436 V: outside the stored literal's half-place
# window (docs/math.md "Inline calc") -- the canonical stale span.
IC_STALE_BODY = "The divider gives `Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.52 V`.\n"
IC_FRESH_BODY = "The divider gives `Vout := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 4.436 V`.\n"


def _ic_rebuild(tmp_path):
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    return project


def _ic_project(tmp_path, body, extra_config=""):
    write_project_config(tmp_path, IC_CONFIG + extra_config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        f"---\nid: DEC-001\ntype: decision\n---\n\n{body}", encoding="utf-8"
    )
    _ic_rebuild(tmp_path)  # key-minting rewrite: line numbers must match disk
    return _ic_rebuild(tmp_path)


def test_inline_calc_results_stale_editable_span_blocks_release(tmp_path):
    project = _ic_project(tmp_path, IC_STALE_BODY)
    assert any("stored result says" in d.message for d in project.warnings)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].enabled is True
    assert results["inline_calc_results"].status == "FAIL"
    # the span's own line on disk (after the key-minting rewrite), not a
    # magic number -- same contract as open_tasks' clickable offender
    text = (tmp_path / "items" / "dec.md").read_text(encoding="utf-8").splitlines()
    line = next(i for i, ln in enumerate(text, start=1) if "Vout :=" in ln)
    assert results["inline_calc_results"].offenders == [
        f"DEC-001: inline calc Vout (items/dec.md:{line})"
    ]
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))
    # the revision half defaults off: the revision stamps through it
    revision = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert revision.status == "stamped"


def test_inline_calc_results_off_passes(tmp_path):
    project = _ic_project(
        tmp_path, IC_STALE_BODY, "release_gate:\n  inline_calc_results: { release: false }\n"
    )
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].enabled is False
    assert results["inline_calc_results"].status == "skipped"
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "stamped"


def test_inline_calc_results_fresh_span_passes(tmp_path):
    project = _ic_project(tmp_path, IC_FRESH_BODY)
    assert not project.warnings
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "pass"
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"


def test_inline_calc_results_exempt_captured_history(tmp_path):
    """A captured log entry with a stale span keeps its warning and passes
    the gate: the design exempts frozen text (docs/design/inline-calc.md §2)."""
    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(
        "items:\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    date: 2026-10-19\n"
        "    summary: Divider settled.\n"
        "    body: |\n"
        "      Settled at `Vfb := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 9.9 V`.\n",
        encoding="utf-8",
    )
    project = _ic_rebuild(tmp_path)
    history.capture(str(tmp_path), project.item_by_id("LOG-001"))
    project = _ic_rebuild(tmp_path)
    assert any("stored result says" in d.message for d in project.warnings)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "pass"
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"


def test_inline_calc_results_id_less_continuation_span_blocks_release(tmp_path):
    """An id-less continuation is editable prose like any other item. Its
    diagnostic has an empty display id, so the gate must resolve it from the
    warning's source location as well as by display id."""
    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(
        "items:\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    date: 2026-10-19\n"
        "    summary: First.\n"
        "  - type: log\n"
        "    date: 2026-10-19\n"
        "    summary: Continuation.\n"
        "    follows: LOG-001\n"
        "    body: |\n"
        "      Settled at `Vfb := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 9.9 V`.\n",
        encoding="utf-8",
    )
    _ic_rebuild(tmp_path)  # mint the continuation's key and rewrite follows
    project = _ic_rebuild(tmp_path)
    stale = next(d for d in project.warnings if "stored result says" in d.message)
    assert stale.item_id == ""
    continuation = next(
        item for item in project.local_items
        if item.id == "" and item.source_file == stale.file
    )
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "FAIL"
    assert results["inline_calc_results"].offenders == [
        f"{continuation.key}: inline calc Vfb ({stale.file}:{stale.line})"
    ]
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_inline_calc_results_id_less_markdown_continuation_span_blocks_release(
    tmp_path,
):
    """The id-less lookup must cover a Markdown continuation's whole body,
    not only its first body line: the diagnostic is the span's absolute line,
    while the item is located by its front-matter/body start."""
    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(
        "items:\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    date: 2026-10-18\n"
        "    summary: First.\n",
        encoding="utf-8",
    )
    (items / "notes.md").write_text(
        "---\n"
        "type: log\n"
        "date: 2026-10-19\n"
        "summary: Continuation.\n"
        "follows: LOG-001\n"
        "---\n"
        "\n"
        "Settled.\n"
        "`Vfb := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 9.9 V`.\n",
        encoding="utf-8",
    )
    _ic_rebuild(tmp_path)  # mint the continuation's key and rewrite follows
    project = _ic_rebuild(tmp_path)
    stale = next(d for d in project.warnings if "stored result says" in d.message)
    continuation = next(
        item
        for item in project.local_items
        if item.id == "" and item.source_file == stale.file
    )
    assert stale.item_id == ""
    assert stale.file == "items/notes.md"
    text = (tmp_path / "items" / "notes.md").read_text(encoding="utf-8").splitlines()
    span_line = next(i for i, ln in enumerate(text, start=1) if "Vfb :=" in ln)
    assert stale.line == span_line
    assert continuation.source_line < continuation.body_line < stale.line
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "FAIL"
    assert results["inline_calc_results"].offenders == [
        f"{continuation.key}: inline calc Vfb ({stale.file}:{stale.line})"
    ]
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_inline_calc_results_captured_then_edited_span_blocks_release(tmp_path):
    """Capturing an entry freezes the captured snapshot, not every future
    edit. A post-capture edit leaves the live item editable, so a stale span
    in the edited text must block release (captured_edits' default-off rule
    is not a substitute for this gate)."""
    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    log = items / "log.yaml"
    log.write_text(
        "items:\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    date: 2026-10-19\n"
        "    summary: Divider settled.\n"
        "    body: |\n"
        "      Settled at `Vfb := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 9.9 V`.\n",
        encoding="utf-8",
    )
    project = _ic_rebuild(tmp_path)
    history.capture(str(tmp_path), project.item_by_id("LOG-001"))
    log.write_text(
        log.read_text(encoding="utf-8").replace(
            "summary: Divider settled.",
            "summary: Divider settled, post-capture edit.",
        ),
        encoding="utf-8",
    )
    project = _ic_rebuild(tmp_path)
    assert any("stored result says" in d.message for d in project.warnings)
    assert any("edited after captured" in d.message for d in project.warnings)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    stale = next(d for d in project.warnings if "stored result says" in d.message)
    assert results["inline_calc_results"].status == "FAIL"
    assert results["inline_calc_results"].offenders == [
        f"LOG-001: inline calc Vfb ({stale.file}:{stale.line})"
    ]
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_inline_calc_results_unreadable_history_store_fails_closed(tmp_path):
    """The inline-calc gate cannot use a broken store to prove that captured
    history is exempt. With a stale editable span present, an unreadable
    store is a release failure, not a silent exemption."""
    project = _ic_project(tmp_path, IC_STALE_BODY)
    events = tmp_path / ".refdes" / "history" / "events"
    events.mkdir(parents=True)
    (events / "bad.yaml").write_text("kind: [unclosed\n", encoding="utf-8")
    project = _ic_rebuild(tmp_path)
    with pytest.raises(history.HistoryError):
        history.capture_index(project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "FAIL"
    assert len(results["inline_calc_results"].offenders) == 1
    offender = results["inline_calc_results"].offenders[0]
    assert offender.startswith("history: inline calc freshness cannot be checked")
    assert "history store unreadable" in offender
    assert "\n" not in offender
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isfile(lifecycle.baseline_path(project, "rel-a"))


def test_inline_calc_results_unreadable_history_store_fails_closed_captured(
    tmp_path,
):
    """A capture cannot prove itself unedited after the store that holds its
    snapshot becomes unreadable; a stale span in that item fails closed."""
    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "standard: { base: hardware, version: 3 }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(
        "items:\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    date: 2026-10-19\n"
        "    summary: Divider settled.\n"
        "    body: |\n"
        "      Settled at `Vfb := 0.8 V * (1 + 10 kohm/2.2 kohm) | V = 9.9 V`.\n",
        encoding="utf-8",
    )
    project = _ic_rebuild(tmp_path)
    history.capture(str(tmp_path), project.item_by_id("LOG-001"))
    events = tmp_path / ".refdes" / "history" / "events"
    (events / "bad.yaml").write_text("kind: [unclosed\n", encoding="utf-8")
    project = _ic_rebuild(tmp_path)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "FAIL"
    assert "history store unreadable" in results["inline_calc_results"].offenders[0]
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "gate_failed"


def test_inline_calc_results_unreadable_history_store_keeps_seal_exempt(tmp_path):
    """Corrupting the history store must not widen the gate past what it
    checks: a build-sealed item remains exempt by the seal alone."""
    from refdes import seal as seal_mod

    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "types:\n"
        "  decision: { prefix: DEC, append_only: true, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n" + IC_STALE_BODY, encoding="utf-8"
    )
    project = _ic_rebuild(tmp_path)
    seal_mod.verify(project, write=True)
    events = tmp_path / ".refdes" / "history" / "events"
    events.mkdir(parents=True)
    (events / "bad.yaml").write_text("kind: [unclosed\n", encoding="utf-8")
    project = _ic_rebuild(tmp_path)
    with pytest.raises(history.HistoryError):
        history.capture_index(project)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "pass"
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"


def test_inline_calc_results_unreadable_history_store_without_stale_span_passes(
    tmp_path,
):
    """A broken history store is not a global release gate; the inline-calc
    rule fails closed only when its own stale-span check is in play."""
    project = _ic_project(tmp_path, IC_FRESH_BODY)
    events = tmp_path / ".refdes" / "history" / "events"
    events.mkdir(parents=True)
    (events / "bad.yaml").write_text("kind: [unclosed\n", encoding="utf-8")
    project = _ic_rebuild(tmp_path)
    assert not any(d.code == "inline_calc_stale" for d in project.warnings)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "pass"
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"


def test_inline_calc_results_exempt_build_seal(tmp_path):
    """A sealed (build-locked) entry keeps its stale warning and passes the
    gate: the body is locked text, not editable prose (the exemption mirrors
    the captured-history one -- docs/design/inline-calc.md §2)."""
    from refdes import seal as seal_mod

    write_project_config(
        tmp_path,
        "site: { title: IC, out: _site }\n"
        "types:\n"
        "  decision: { prefix: DEC, append_only: true, fields: {} }\n",
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n" + IC_STALE_BODY, encoding="utf-8"
    )
    project = _ic_rebuild(tmp_path)
    seal_mod.verify(project, write=True)
    project = _ic_rebuild(tmp_path)
    assert seal_mod.is_sealed(project, project.item_by_id("DEC-001"))
    assert any("stored result says" in d.message for d in project.warnings)
    results = {r.name: r for r in lifecycle.evaluate_gate(project, "release")}
    assert results["inline_calc_results"].status == "pass"
    assert lifecycle.stamp(project, kind="release", name="rel-a").status == "stamped"
