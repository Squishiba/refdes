"""diff -- and: identity, naming, CLI.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import _lc_build, _pin_lifecycle_citation

from refdes import cli as cli_mod
from refdes import lifecycle
from refdes.schema import SchemaError

# --------------------------------------------------------------------- diff


def test_diff_against_reports_changed_added_removed(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Edited.\n    status: active\n"
        "  - id: REQ-003\n    text: Brand new.\n    status: draft\n",
        encoding="utf-8",
    )
    project2 = _lc_build(lifecycle_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["REQ-001"]
    assert diff.added == ["REQ-003"]
    assert [r[0] for r in diff.removed] == ["REQ-002"]
    assert diff.removed[0][1] == "requirement"
    assert diff.unchanged_count == 1  # CMP-001


def test_latest_self_heals_after_a_baseline_is_deleted(lifecycle_project):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    # Resolve the release gate so the second stamp actually writes.
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Covered.\n    status: active\n"
        "  - id: REQ-002\n    text: Active now.\n    status: active\n",
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
    result = lifecycle.stamp(project2, kind="release", name="rel-a")
    assert result.status == "stamped"

    baselines = lifecycle.list_baselines(project)
    assert lifecycle.latest(baselines, kind="release").name == "rel-a"

    os.remove(lifecycle.baseline_path(project, "rel-a"))
    baselines2 = lifecycle.list_baselines(project)
    assert lifecycle.latest(baselines2, kind="release") is None
    assert lifecycle.latest(baselines2) is not None  # rev-a still there


# ----------------------------------------------------------------- identity


def test_stamped_by_defaults_to_os_username(lifecycle_project):
    project = _lc_build(lifecycle_project)
    assert project.baseline_identity == "os_user"
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    import getpass

    assert outcome.stamped_by == getpass.getuser()
    assert not any("baseline_identity" in d.message for d in project.warnings)


def test_git_identity_success(lifecycle_project, monkeypatch):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "baseline_identity: git_identity\n", encoding="utf-8"
    )
    project = _lc_build(lifecycle_project)

    class _FakeResult:
        returncode = 0
        stdout = "J. Bin\n"

    monkeypatch.setattr(lifecycle.subprocess, "run", lambda *a, **k: _FakeResult())
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.stamped_by == "J. Bin"
    assert not any("baseline_identity" in d.message for d in project.warnings)


def test_git_identity_failure_falls_back_and_warns(lifecycle_project, monkeypatch):
    (lifecycle_project / "refdes-project.yaml").write_text(
        "baseline_identity: git_identity\n", encoding="utf-8"
    )
    project = _lc_build(lifecycle_project)

    def _boom(*a, **k):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(lifecycle.subprocess, "run", _boom)
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    import getpass

    assert outcome.stamped_by == getpass.getuser()
    assert any(
        "baseline_identity: git_identity" in d.message and "falls back" in d.message
        for d in project.warnings
    )


# ---------------------------------------------------------------- naming


@pytest.mark.parametrize("bad_name", ["../evil", "..", ".", "a/b", "a\\b", ""])
def test_invalid_baseline_names_are_rejected(bad_name):
    with pytest.raises(SchemaError):
        lifecycle.validate_name(bad_name)


def test_valid_baseline_names_are_accepted():
    for name in ("rev-b", "rev_c", "sent-to-fab-2026.08", "a"):
        lifecycle.validate_name(name)  # must not raise


# --------------------------------------------------------------------- CLI


def test_cli_revision_stamps_and_reports(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "revision", "rev-a"])
    out = capsys.readouterr().out
    assert status == 0
    assert "revision 'rev-a' stamped: 3 items." in out
    assert os.path.isfile(lifecycle_project / ".refdes" / "baselines" / "rev-a.yaml")


def test_cli_release_blocked_prints_gate_table(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    captured = capsys.readouterr()
    assert status == 1
    assert "blocked -- not stamped" in captured.err
    assert "FAIL" in captured.err
    assert "draft_items" in captured.err
    assert not os.path.isfile(lifecycle_project / ".refdes" / "baselines" / "rel-a.yaml")


def test_the_whole_gate_table_lands_on_one_stream(lifecycle_project, capsys):
    """Rows used to pick their stream individually -- FAIL to stderr, pass and
    skipped to stdout -- so under any redirection the table arrived split
    across two files with its ordering destroyed. That is CI, which is the
    one place this report has to stay readable. The block is a failure report,
    so all of it goes to stderr, and none of it leaks into stdout."""
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    captured = capsys.readouterr()
    assert status == 1

    assert "FAIL" in captured.err
    # Every row, not just the failing ones.
    for name in ("draft_items", "unpinned_citations", "uncovered_requirements",
                 "unverified_requirements", "info_check_failures",
                 "unaccepted_board_moves"):
        assert name in captured.err, name

    # No gate row on stdout: a row there is one that split off from the table.
    gate_rows = [
        line for line in captured.out.splitlines()
        if line.startswith(("  pass ", "  FAIL ", "  skipped "))
    ]
    assert gate_rows == [], gate_rows


def test_cli_release_success_prints_log_nudge(lifecycle_project, capsys):
    (lifecycle_project / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Covered.\n    status: active\n"
        "  - id: REQ-002\n    text: Active now.\n    status: active\n",
        encoding="utf-8",
    )
    (lifecycle_project / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(lifecycle_project)
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "release", "rel-a"])
    out = capsys.readouterr().out
    assert status == 0
    assert "all gates passed" in out
    assert "Consider recording this in the design log" in out


def test_cli_invalid_name_exits_2(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "revision", ".."])
    err = capsys.readouterr().err
    assert status == 2
    assert "not a valid revision/release name" in err


def test_cli_floor_violation_blocks_both_commands(tmp_path):
    """The unconditional error floor -- the same one `check` already has."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n",  # missing required text
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "revision", "rev-a"])
    assert status == 1
    assert not os.path.isdir(tmp_path / ".refdes" / "baselines")


def test_draft_project_is_the_regression_case(lifecycle_project, capsys):
    """A project that never stamps anything behaves exactly as today: check/
    build are unaffected, and audit reports the draft state rather than
    erroring on the absence of any baseline."""
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "check"])
    assert status == 0  # no build errors from lifecycle machinery existing

    status2 = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status2 == 0
    assert "(none stamped yet -- project is in draft)" in out
    assert "(no revision stamped yet)" in out
    assert "(no release stamped yet)" in out


def test_audit_reports_both_diffs(lifecycle_project, capsys):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    status = cli_mod.main(["-c", str(lifecycle_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status == 0
    assert "Since last revision (rev-a" in out
    assert "Since last release: (no release stamped yet)" in out
    assert "(3 unchanged)" in out
