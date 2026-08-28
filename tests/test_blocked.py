"""blocked_by.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import COVERAGE_SCHEMA, _build_at

from refdes import cli as cli_mod
from refdes import render

# --------------------------------------------------------------------- blocked_by

BLOCKED_SCHEMA = """\
site: {title: "Blocked Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies:  { inverse: satisfied_by, label: "Satisfies" }
  blocked_by: { inverse: blocks,       label: "Blocked by" }
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
      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
    satisfying_statuses: [accepted]
    links:
      satisfies:  [requirement]
      blocked_by: []
    body: { on_change: invalidate }
"""


BLOCKED_ITEMS = {
    "req-001.md": """\
---
id: REQ-001
type: requirement
text: Connector pin allocation must be final.
---
""",
    "dec-001.md": """\
---
id: DEC-001
type: decision
title: Root open question.
status: on_hold
---
""",
    "dec-002.md": """\
---
id: DEC-002
type: decision
title: Depends on DEC-001.
status: proposed
blocked_by: [DEC-001]
---
""",
    "dec-003.md": """\
---
id: DEC-003
type: decision
title: Satisfies REQ-001, depends on DEC-002.
status: proposed
satisfies: [REQ-001]
blocked_by: [DEC-002]
---
""",
}


@pytest.fixture
def blocked_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(BLOCKED_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in BLOCKED_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_blocked_by_resolves_the_transitive_root(blocked_project):
    project = _build_at(blocked_project)
    assert not project.errors
    chains = {c.item_id: c for c in project.blocked_chains}
    assert chains["DEC-002"].path == ["DEC-002", "DEC-001"]
    assert chains["DEC-002"].root_id == "DEC-001"
    assert chains["DEC-002"].root_status == "on_hold"
    # The declared edge is direct, but this one resolves through DEC-002 to
    # the same structural root -- the path is shown, not collapsed.
    assert chains["DEC-003"].path == ["DEC-003", "DEC-002", "DEC-001"]
    assert chains["DEC-003"].root_id == "DEC-001"


def test_blocked_by_target_of_any_type_no_status_restriction(blocked_project):
    """blocked_by may point at any item type, in any status, with nothing
    checked at declaration time."""
    (blocked_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: Blocked on a requirement.\n"
        "status: proposed\nblocked_by: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not project.errors
    chain = next(c for c in project.blocked_chains if c.item_id == "DEC-004")
    assert chain.root_id == "REQ-001"


def test_blocked_by_cycle_is_a_hard_error_naming_the_full_path(blocked_project):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: on_hold\nblocked_by: [DEC-003]")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")

    project = _build_at(blocked_project)
    errors = [d.message for d in project.errors if "blocked_by cycle" in d.message]
    assert len(errors) == 1  # reported once, not once per node in the cycle
    assert "DEC-001 -> DEC-003 -> DEC-002 -> DEC-001" in errors[0]
    # The graph is broken -- nothing downstream should trust partial chains.
    assert project.blocked_chains == []


def test_blocked_by_self_loop_is_a_cycle(blocked_project):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: on_hold\nblocked_by: [DEC-001]")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")
    project = _build_at(blocked_project)
    assert any("blocked_by cycle: DEC-001 -> DEC-001" in d.message for d in project.errors)


def test_stale_blocker_is_an_info_diagnostic(blocked_project):
    """Settled per satisfying_statuses, edge still declared -- info, not a
    warning or error, and default-hidden like every other info finding."""
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: accepted")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")

    project = _build_at(blocked_project)
    assert not project.errors
    infos = [d.message for d in project.infos if "blocked_by DEC-001" in d.message]
    assert len(infos) == 1
    assert "which is now 'accepted'" in infos[0]
    assert "is it still blocked?" in infos[0]
    # Never counted as a warning/error -- only visible via project.infos.
    assert not any("blocked_by DEC-001" in d.message for d in project.warnings)


def test_no_stale_diagnostic_for_a_type_with_no_settled_notion(blocked_project):
    """A blocker of a type that declares neither satisfying_statuses nor
    verifying_statuses never triggers the stale check -- 'unconfigured means
    nothing special happens', same default used throughout the schema
    engine."""
    (blocked_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: Blocked on a requirement.\n"
        "status: proposed\nblocked_by: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not any("blocked_by REQ-001" in d.message for d in project.infos)


def test_coverage_claimed_warning_includes_the_blocker_chain(blocked_project):
    project = _build_at(blocked_project)
    msg = next(
        d.message for d in project.warnings
        if d.item_id == "REQ-001" and "claimed but not verified" in d.message
    )
    assert "claimed by DEC-003, which is blocked_by DEC-002 <- DEC-001 (on_hold)" in msg


def test_coverage_aggregate_line_for_a_single_unambiguous_root(blocked_project):
    project = _build_at(blocked_project)
    assert any(
        "1 requirement(s) unsettled because DEC-001 is on_hold" in d.message
        for d in project.warnings
    )


def test_coverage_aggregate_line_excluded_when_claimers_trace_different_roots(blocked_project):
    """Deliberately conservative: a requirement whose several claimers trace
    to *different* root blockers is left out of the aggregate grouping --
    the per-item warning still names both chains in full."""
    (blocked_project / "items" / "dec-005.md").write_text(
        "---\nid: DEC-005\ntype: decision\ntitle: A second, independent root.\n"
        "status: on_hold\n---\n",
        encoding="utf-8",
    )
    (blocked_project / "items" / "dec-006.md").write_text(
        "---\nid: DEC-006\ntype: decision\ntitle: Also satisfies REQ-001.\n"
        "status: proposed\nsatisfies: [REQ-001]\nblocked_by: [DEC-005]\n---\n",
        encoding="utf-8",
    )
    project = _build_at(blocked_project)
    assert not any("unsettled because" in d.message for d in project.warnings)
    msg = next(
        d.message for d in project.warnings
        if d.item_id == "REQ-001" and "claimed but not verified" in d.message
    )
    assert "DEC-003, which is blocked_by DEC-002 <- DEC-001 (on_hold)" in msg
    assert "DEC-006, which is blocked_by DEC-005 (on_hold)" in msg


def test_audit_reports_blocked_chains(blocked_project):
    status = cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    assert status == 0


def test_audit_blocked_chains_section(blocked_project, capsys):
    cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Blocked chains:" in out
    assert "DEC-002 <- DEC-001 (on_hold, root)" in out
    assert "DEC-003 <- DEC-002 <- DEC-001 (on_hold, root)" in out


def test_audit_blocked_chains_section_is_none_with_no_edges(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "req-a.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: t.\n---\n", encoding="utf-8"
    )
    cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "Blocked chains:\n  (none)" in out


def test_audit_marks_a_stale_chain(blocked_project, capsys):
    text = (blocked_project / "items" / "dec-001.md").read_text(encoding="utf-8")
    text = text.replace("status: on_hold", "status: accepted")
    (blocked_project / "items" / "dec-001.md").write_text(text, encoding="utf-8")
    cli_mod.main(["-c", str(blocked_project / "refdes.yaml"), "audit"])
    out = capsys.readouterr().out
    assert "stale: edge still declared, blocker settled" in out


def test_item_page_shows_the_blocked_panel_with_resolved_root(blocked_project):
    project = _build_at(blocked_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "dec-003.html"), encoding="utf-8").read()
    assert "Blocked" in html
    assert '<a class="ref" href="dec-002.html" data-ref="DEC-002">DEC-002</a>' in html
    assert '<a class="ref" href="dec-001.html" data-ref="DEC-001">DEC-001</a>' in html
    assert "on_hold, root" in html


def test_coverage_html_shows_the_inline_blocker_chain(blocked_project):
    project = _build_at(blocked_project)
    out = render.render_site(project)
    html = open(os.path.join(out, "coverage.html"), encoding="utf-8").read()
    assert 'blocked-note">← DEC-002 ← DEC-001 (on_hold)' in html
