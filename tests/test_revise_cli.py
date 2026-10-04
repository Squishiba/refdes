"""diff -- and: identity, naming, CLI.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import re

import pytest
from conftest import write_project_config
from helpers import REPO, _lc_build, _pin_lifecycle_citation

from refdes import cli as cli_mod
from refdes import ids as ids_mod
from refdes import lifecycle
from refdes.schema import SchemaError

STALE_SCHEMA = """\
site: { title: "Stale arithmetic test", out: _site }
types:
  decision:
    prefix: DEC
    fields:
      status: { type: enum, choices: [proposed, accepted, superseded], default: proposed }
  note:
    prefix: NOTE
    fields:
      tag: { type: text }
"""


@pytest.fixture
def stale_project(tmp_path):
    """DEC-001/DEC-002 both start `proposed` with the identical calc block;
    DEC-003 is `proposed` with no calc block at all; NOTE-001 has a calc
    block but its type declares no `status` field. Covers, in one fixture,
    every combination the signal's applicability rule needs to distinguish."""
    write_project_config(tmp_path, STALE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-002\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-003\n"
        "    status: proposed\n"
        "    body: No calc block here, just prose.\n",
        encoding="utf-8",
    )
    (items / "notes.yaml").write_text(
        "defaults: { type: note }\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    tag: v1\n"
        '    body: "```calc\\nx = 1 V * 1 A | W\\n```"\n',
        encoding="utf-8",
    )
    return tmp_path


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
    # Append: `refdes-project.yaml` is the marker holding site:/standard:/id:,
    # so overwriting it would silently test a different project.
    with (lifecycle_project / "refdes-project.yaml").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write("baseline_identity: git_identity\n")
    project = _lc_build(lifecycle_project)

    class _FakeResult:
        returncode = 0
        stdout = "J. Bin\n"

    monkeypatch.setattr(lifecycle.subprocess, "run", lambda *a, **k: _FakeResult())
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.stamped_by == "J. Bin"
    assert not any("baseline_identity" in d.message for d in project.warnings)


def test_git_identity_failure_falls_back_and_warns(lifecycle_project, monkeypatch):
    # Append, not overwrite: see test_git_identity_success.
    with (lifecycle_project / "refdes-project.yaml").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write("baseline_identity: git_identity\n")
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
    status = cli_mod.main(
        ["-c", str(lifecycle_project / "refdes-project.yaml"), "revision", "rev-a"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "revision 'rev-a' stamped: 3 items." in out
    assert os.path.isfile(lifecycle_project / ".refdes" / "baselines" / "rev-a.yaml")


def test_cli_release_blocked_prints_gate_table(lifecycle_project, capsys):
    status = cli_mod.main(
        ["-c", str(lifecycle_project / "refdes-project.yaml"), "release", "rel-a"]
    )
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
    status = cli_mod.main(
        ["-c", str(lifecycle_project / "refdes-project.yaml"), "release", "rel-a"]
    )
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
    status = cli_mod.main(
        ["-c", str(lifecycle_project / "refdes-project.yaml"), "release", "rel-a"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "all gates passed" in out
    assert "Consider recording this in the design log" in out


def _cover_both_requirements_and_release(project_dir, capsys) -> list[str]:
    """Make the release gate passable, release, and return the nudge block the
    command printed (header line included)."""
    (project_dir / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Covered.\n    status: active\n"
        "  - id: REQ-002\n    text: Active now.\n    status: active\n",
        encoding="utf-8",
    )
    (project_dir / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n  - id: DEC-001\n    title: Covers both.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    _pin_lifecycle_citation(project_dir)
    assert (
        cli_mod.main(
            ["-c", str(project_dir / "refdes-project.yaml"), "release", "rel-a"]
        )
        == 0
    )
    return _nudge_block(capsys.readouterr().out)


def _nudge_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Consider recording"))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith("```"):
            break
        block.append(line)
    return block


def _normalised_nudge(lines: list[str]) -> list[str]:
    """Blank out the two values that legitimately differ between a live run and
    a documentation sample: the stamp date and the release name."""
    out = []
    for line in lines:
        line = re.sub(r"^\s*date: \S+\s*$", "    date: <date>", line)
        line = re.sub(
            r"Released \S+ \u2014 sent to fab\.", "Released <name> \u2014 sent to fab.", line
        )
        out.append(line)
    return out


def test_cli_release_log_nudge_ids_are_marked_placeholders(lifecycle_project, capsys):
    """`  - id: LOG-...` pasted as a truncated-but-plausible id and then failed
    the PREFIX-NNN shape check, which reads like the tool minted something odd
    rather than like the author skipped a placeholder (user-sim run 2, "Lower
    severity" list). Both ids now stay invalid AND say they are placeholders.
    """
    block = _cover_both_requirements_and_release(lifecycle_project, capsys)
    text = "\n".join(block)

    id_line = next(line for line in block if "- id:" in line)
    placeholder = id_line.split("- id:", 1)[1].split("#", 1)[0].strip()
    assert placeholder, id_line
    assert ids_mod.split_id(placeholder) is None, f"{placeholder} is a real id shape"
    assert "#" in id_line, "the placeholder is not marked as one"
    assert "LOG-..." not in text

    citation_line = next(line for line in block if "- item:" in line)
    recorded = citation_line.split("- item:", 1)[1].split("#", 1)[0].strip()
    assert ids_mod.split_id(recorded) is None, f"{recorded} is a real id shape"
    assert "#" in citation_line, "the placeholder is not marked as one"


def test_release_nudge_citation_form_loads_under_the_shipped_schema(lifecycle_project, capsys):
    """The nudge's `- item:` placeholder must name an id the shipped schema
    can actually mint. It used to print `DEC-A-0NN` -- a prefix hardware@3
    never hands out after the decision merge -- so following the tool's own
    advice cited an item that cannot exist and failed the build (PR #176
    review). The placeholder must carry the same prefix as the nudge's own
    `- id:`, and the substituted form must survive the loader and a build.
    """
    block = _cover_both_requirements_and_release(lifecycle_project, capsys)
    id_line = next(line for line in block if "- id:" in line)
    citation_line = next(line for line in block if "- item:" in line)
    id_placeholder = id_line.split("- id:", 1)[1].split("#", 1)[0].strip()
    cited_placeholder = citation_line.split("- item:", 1)[1].split("#", 1)[0].strip()
    # The cited entry is an earlier log entry, so its placeholder carries
    # the log prefix the nudge's own new entry uses -- not a retired one.
    assert cited_placeholder.split("-")[0] == id_placeholder.split("-")[0]

    # Run the hint's citation form through the loader: substitute the
    # placeholder digits and build a hardware@3 project whose log entry
    # cites an id of exactly that shape.
    cited = re.sub(r"\d*NN$", "001", cited_placeholder)
    root = lifecycle_project / "v3-after"
    root.mkdir()
    write_project_config(
        root, "site: { title: v3 }\nstandard: { base: hardware, version: 3 }\n"
    )
    (root / "items").mkdir()
    (root / "items" / "log.yaml").write_text(
        "items:\n"
        f"  - id: {cited}\n    type: log\n    summary: Earlier entry\n"
        "  - id: LOG-900\n    type: log\n    summary: Released rev-a\n"
        f"    citations:\n      - item: {cited}\n",
        encoding="utf-8",
    )
    assert cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "--no-write", "check"]
    ) == 0


@pytest.mark.parametrize(
    "doc",
    ["docs/design-log.md", "docs/lifecycle.md", "docs/design/lifecycle.md"],
)
def test_docs_quote_the_log_nudge_the_cli_actually_prints(lifecycle_project, capsys, doc):
    """The nudge is documentation-as-UX, so the pages quoting it have to quote
    the real thing -- same gate `test_docs_examples.py` runs on the generated
    type examples and `test_scaffold.py` on the `yaml.schemas` path."""
    block = _cover_both_requirements_and_release(lifecycle_project, capsys)
    with open(os.path.join(REPO, doc), encoding="utf-8") as fh:
        doc_block = _nudge_block(fh.read())

    assert doc_block, f"{doc} no longer shows the release log nudge"
    assert _normalised_nudge(doc_block) == _normalised_nudge(block)


def test_cli_invalid_name_exits_2(lifecycle_project, capsys):
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes-project.yaml"), "revision", ".."])
    err = capsys.readouterr().err
    assert status == 2
    assert "not a valid revision/release name" in err


def test_cli_floor_violation_blocks_both_commands(tmp_path):
    """The unconditional error floor -- the same one `check` already has."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n",  # missing required text
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "revision", "rev-a"])
    assert status == 1
    assert not os.path.isdir(tmp_path / ".refdes" / "baselines")


def test_draft_project_is_the_regression_case(lifecycle_project, capsys):
    """A project that never stamps anything behaves exactly as today: check/
    build are unaffected, and audit reports the draft state rather than
    erroring on the absence of any baseline."""
    status = cli_mod.main(["-c", str(lifecycle_project / "refdes-project.yaml"), "check"])
    assert status == 0  # no build errors from lifecycle machinery existing

    status2 = cli_mod.main(["-c", str(lifecycle_project / "refdes-project.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status2 == 0
    assert "(none stamped yet -- project is in draft)" in out
    assert "(no revision stamped yet)" in out
    assert "(no release stamped yet)" in out


def test_audit_reports_both_diffs(lifecycle_project, capsys):
    project = _lc_build(lifecycle_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    status = cli_mod.main(["-c", str(lifecycle_project / "refdes-project.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status == 0
    assert "Since last revision (rev-a" in out
    assert "Since last release: (no release stamped yet)" in out


# ----------------------------------------------------- stale arithmetic signal


def test_stale_arithmetic_flags_status_moved_with_calc_unchanged(stale_project):
    project = _lc_build(stale_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (stale_project / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    status: accepted\n"  # moved, calc untouched
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-002\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-003\n"
        "    status: proposed\n"
        "    body: No calc block here, just prose.\n",
        encoding="utf-8",
    )
    project2 = _lc_build(stale_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["DEC-001"]
    assert diff.stale_arithmetic == ["DEC-001"]


def test_stale_arithmetic_not_flagged_when_calc_moves_too(stale_project):
    """The bug this signal exists to catch is verdict-without-arithmetic --
    a decision that also updated its own numbers isn't that bug, whatever
    else changed about it."""
    project = _lc_build(stale_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (stale_project / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-002\n"
        "    status: accepted\n"  # moved, and so did the calc block
        '    body: "```calc\\nP = 5 V * 1 A | W\\n```"\n'
        "  - id: DEC-003\n"
        "    status: proposed\n"
        "    body: No calc block here, just prose.\n",
        encoding="utf-8",
    )
    project2 = _lc_build(stale_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["DEC-002"]
    assert diff.stale_arithmetic == []


def test_stale_arithmetic_not_flagged_without_a_calc_block(stale_project):
    """Most items in most projects have no calc block at all -- that has to
    stay silent, not error or guess, even when its verdict genuinely moves."""
    project = _lc_build(stale_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (stale_project / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-002\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-003\n"
        "    status: accepted\n"  # moved, no calc block to be stale
        "    body: No calc block here, just prose.\n",
        encoding="utf-8",
    )
    project2 = _lc_build(stale_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["DEC-003"]
    assert diff.stale_arithmetic == []


def test_stale_arithmetic_not_flagged_without_a_status_field(stale_project):
    """NOTE-001 has a calc block but its type declares no `status` field --
    there's no verdict for this signal to compare, whatever else about the
    item changes."""
    project = _lc_build(stale_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (stale_project / "items" / "notes.yaml").write_text(
        "defaults: { type: note }\n"
        "items:\n"
        "  - id: NOTE-001\n"
        "    tag: v2\n"  # changed; calc block itself untouched
        '    body: "```calc\\nx = 1 V * 1 A | W\\n```"\n',
        encoding="utf-8",
    )
    project2 = _lc_build(stale_project)
    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.changed == ["NOTE-001"]
    assert diff.stale_arithmetic == []


def test_stale_arithmetic_silent_against_a_baseline_that_predates_the_signal(stale_project):
    """A baseline stamped before this feature existed has no `verdict`/
    `calc_hash` to compare against -- silence, not a guess. This entry is
    also format 2 with a stored hash that doesn't check out under that old
    definition, so it lands under `uncomparable` (can't tell), never
    `changed`."""
    (stale_project / ".refdes" / "baselines").mkdir(parents=True)
    (stale_project / ".refdes" / "baselines" / "old.yaml").write_text(
        "kind: revision\n"
        "name: old\n"
        "stamped_at: '2026-01-01T00:00:00Z'\n"
        "stamped_by: someone\n"
        "refdes_version: 0.3.0\n"
        "items:\n"
        "  DEC-001: { hash: 0000000000000000, type: decision, title: '', "
        "hash_format: 2 }\n",
        encoding="utf-8",
    )
    project = _lc_build(stale_project)  # DEC-001 is still `proposed` here
    baseline = lifecycle.load_baseline(project, "old")
    diff = lifecycle.diff_against(project, baseline)
    assert diff.changed == []  # the bogus stored hash proves nothing, either way
    assert diff.uncomparable == ["DEC-001"]
    assert diff.stale_arithmetic == []


def test_stale_arithmetic_silent_with_no_baseline_stamped_at_all(stale_project, capsys):
    """Extends test_draft_project_is_the_regression_case: a project that has
    never stamped anything has no prior point to have drifted from, so
    'stale' can't be asked yet -- audit must not mention it."""
    status = cli_mod.main(["-c", str(stale_project / "refdes-project.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status == 0
    assert "(no revision stamped yet)" in out
    assert "stale arithmetic" not in out


def test_audit_prints_the_stale_arithmetic_annotation(stale_project, capsys):
    project = _lc_build(stale_project)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (stale_project / "items" / "decisions.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n"
        "    status: accepted\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-002\n"
        "    status: proposed\n"
        '    body: "```calc\\nP = 3.3 V * 1.2 A | W\\n```"\n'
        "  - id: DEC-003\n"
        "    status: proposed\n"
        "    body: No calc block here, just prose.\n",
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(stale_project / "refdes-project.yaml"), "audit"])
    out = capsys.readouterr().out
    assert status == 0
    assert "DEC-001 -- stale arithmetic: status changed, calc block did not" in out
    assert "(3 unchanged)" in out
