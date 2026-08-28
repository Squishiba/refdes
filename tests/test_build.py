"""coverage -- and: coverage warning aggregation, build --dry-run (finding 5), check --board, summary view.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from helpers import COVERAGE_SCHEMA, _build_at, _project

from refdes import build as build_mod
from refdes import calc, parse, render
from refdes import cli as cli_mod
from refdes.schema import SchemaError, load_project


def test_settled_decision_satisfies_but_unsettled_only_claims(coverage_project):
    """A requirement's only satisfier being `on_hold` must not read as satisfied (#1 P1-1)."""
    project = load_project(config_path=str(coverage_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    settled = project.coverage["REQ-A-001"]
    assert settled.stage == "satisfied"
    assert settled.satisfied_by == ["DEC-A-001"]
    assert settled.claimed_by == []

    unsettled = project.coverage["REQ-B-001"]
    assert unsettled.stage == "claimed"
    assert unsettled.claimed_by == ["DEC-B-001"]
    assert unsettled.satisfied_by == []


def test_satisfying_statuses_absent_keeps_old_behavior(coverage_project):
    """A type with no satisfying_statuses: configured still counts every link (back-compat)."""
    schema = COVERAGE_SCHEMA.replace("    satisfying_statuses: [accepted]\n", "")
    (coverage_project / "refdes.yaml").write_text(schema, encoding="utf-8")

    project = load_project(config_path=str(coverage_project / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)

    unsettled = project.coverage["REQ-B-001"]
    assert unsettled.stage == "satisfied"
    assert unsettled.satisfied_by == ["DEC-B-001"]
    assert unsettled.claimed_by == []


NO_STATUS_FIELD_SCHEMA = """\
site: {title: "Bad Schema", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]
    body: { on_change: invalidate }
"""


def test_satisfying_statuses_requires_a_status_field(tmp_path):
    path = tmp_path / "refdes.yaml"
    path.write_text(NO_STATUS_FIELD_SCHEMA, encoding="utf-8")
    with pytest.raises(SchemaError, match="satisfying_statuses"):
        load_project(config_path=str(path))


# ---------------------------------------------------- coverage warning aggregation

COVERAGE_AGGREGATION_SCHEMA = """\
site: {title: "Coverage Aggregation Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
  verifies:  { inverse: verified_by, label: "Verifies" }
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  decision:
    prefix: DEC
    label: Decision
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }
    links:
      satisfies: [requirement]
    satisfying_statuses: [accepted]
    body: { on_change: invalidate }
  test:
    prefix: TST
    label: Test
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      verifies: [requirement]
    body: { on_change: invalidate }
"""


COVERAGE_AGGREGATION_ITEMS = {
    "req-open.md": "---\nid: REQ-OPEN-001\ntype: requirement\ntext: Untouched.\n---\n",
    "req-sat.md": "---\nid: REQ-SAT-001\ntype: requirement\ntext: Settled, unverified.\n---\n",
    "dec-sat.md": (
        "---\nid: DEC-SAT-001\ntype: decision\ntitle: t\nstatus: accepted\n"
        "satisfies: [REQ-SAT-001]\n---\n"
    ),
    "req-claim.md": "---\nid: REQ-CLAIM-001\ntype: requirement\ntext: Not settled.\n---\n",
    "dec-claim.md": (
        "---\nid: DEC-CLAIM-001\ntype: decision\ntitle: t\nstatus: on_hold\n"
        "satisfies: [REQ-CLAIM-001]\n---\n"
    ),
    "req-verified.md": "---\nid: REQ-VERIFIED-001\ntype: requirement\ntext: Fully covered.\n---\n",
    "dec-verified.md": (
        "---\nid: DEC-VERIFIED-001\ntype: decision\ntitle: t\nstatus: accepted\n"
        "satisfies: [REQ-VERIFIED-001]\n---\n"
    ),
    "tst.md": (
        "---\nid: TST-VERIFIED-001\ntype: test\ntitle: t\n"
        "verifies: [REQ-VERIFIED-001]\n---\n"
    ),
}


@pytest.fixture
def coverage_aggregation_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_AGGREGATION_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in COVERAGE_AGGREGATION_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _build_coverage_project(path):
    project = load_project(config_path=str(path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def test_open_and_unverified_coverage_warnings_are_aggregated(coverage_aggregation_project):
    """Per-item noise for the two routine coverage classes collapses into one
    summary line each, with `coverage.html` carrying the detail (issue #3, finding 8)."""
    project = _build_coverage_project(coverage_aggregation_project)

    messages = {d.message for d in project.warnings if d.item_id is None}
    assert "1 item(s) with no coverage — see coverage.html" in messages
    assert "1 requirement(s) satisfied but not verified — see coverage.html" in messages

    # No per-item duplicate for either aggregated class.
    assert not any(d.item_id == "REQ-OPEN-001" for d in project.warnings)
    assert not any(d.item_id == "REQ-SAT-001" for d in project.warnings)
    # Fully verified requirement contributes to neither bucket.
    assert not any(d.item_id == "REQ-VERIFIED-001" for d in project.warnings)


def test_claimed_but_not_verified_stays_per_item(coverage_aggregation_project):
    """The one coverage warning that names something actionable -- an unsettled
    decision -- must not be swallowed into the aggregate."""
    project = _build_coverage_project(coverage_aggregation_project)

    claimed = [d for d in project.warnings if d.item_id == "REQ-CLAIM-001"]
    assert len(claimed) == 1
    assert "claimed but not verified" in claimed[0].message


def test_satisfied_without_any_test_items_is_silent(coverage_project):
    """`coverage_project` declares no `test` type at all, so "not verified" is
    noise by construction -- suppressed entirely, per item and aggregated."""
    project = _build_coverage_project(coverage_project)

    assert not any(d.item_id == "REQ-A-001" for d in project.warnings)
    assert not any("satisfied but not verified" in d.message for d in project.warnings)


def test_first_test_item_makes_unverified_warnings_reappear(coverage_project):
    """The suppression only holds while zero `test` items exist -- adding the
    first one is meant to bring the warning right back (confirmed intended
    behaviour, not a surprise to design around)."""
    # Verifier-type detection is link-based now (docs/design/standard-library.md
    # §2), so this fixture's `test` type needs an actual `verifies:` link to
    # count -- a bare type named "test" with no such link no longer implies one.
    schema = COVERAGE_SCHEMA.replace(
        '  satisfies: { inverse: satisfied_by, label: "Satisfies" }\n',
        '  satisfies: { inverse: satisfied_by, label: "Satisfies" }\n'
        '  verifies: { inverse: verified_by, label: "Verifies" }\n',
    ) + (
        "  test:\n"
        "    prefix: TST\n"
        "    label: Test\n"
        "    fields:\n"
        "      title: { type: text, required: true, on_change: invalidate }\n"
        "    links:\n"
        "      verifies: [requirement]\n"
        "    body: { on_change: invalidate }\n"
    )
    (coverage_project / "refdes.yaml").write_text(schema, encoding="utf-8")
    (coverage_project / "items" / "tst.md").write_text(
        "---\nid: TST-UNRELATED-001\ntype: test\ntitle: An unrelated test.\n---\n",
        encoding="utf-8",
    )

    project = _build_coverage_project(coverage_project)

    assert any(
        d.message == "1 requirement(s) satisfied but not verified — see coverage.html"
        for d in project.warnings
    )


# ------------------------------------------------------- build --dry-run (finding 5)

DRY_RUN_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n  log: { prefix: LOG, append_only: true, "
    "fields: { summary: { type: text, required: true } } }\n"
)


@pytest.fixture
def dry_run_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(DRY_RUN_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(
        "defaults: { type: log, prefix: LOG }\n"
        "items:\n  - id: LOG-001\n    summary: first entry\n",
        encoding="utf-8",
    )
    return tmp_path


def test_cli_build_dry_run_writes_html_but_no_seal(dry_run_project):
    status = cli_mod.main(["-c", str(dry_run_project / "refdes.yaml"), "build", "--dry-run"])
    assert status == 0
    assert not (dry_run_project / ".refdes" / "log-seal.yaml").exists()

    html = (dry_run_project / "_site" / "index.html").read_text(encoding="utf-8")
    assert "draft-banner" in html


def test_cli_build_without_dry_run_seals_and_has_no_watermark(dry_run_project):
    status = cli_mod.main(["-c", str(dry_run_project / "refdes.yaml"), "build"])
    assert status == 0
    assert (dry_run_project / ".refdes" / "log-seal.yaml").is_file()

    html = (dry_run_project / "_site" / "index.html").read_text(encoding="utf-8")
    assert "draft-banner" not in html


def test_cli_reseal_rejects_unknown_board(sealed_board_project, capsys):
    status = cli_mod.main(
        ["-c", str(sealed_board_project / "refdes.yaml"), "build", "--reseal", "nonexistent"]
    )
    assert status != 0
    captured = capsys.readouterr()
    assert "not a board declared" in captured.err


def test_cli_build_reseal_scoped_to_board(sealed_board_project, capsys):
    assert cli_mod.main(["-c", str(sealed_board_project / "refdes.yaml"), "build"]) == 0

    log_a = sealed_board_project / "items" / "board-a" / "log.yaml"
    log_a.write_text(
        log_a.read_text(encoding="utf-8").replace("first entry", "edited entry"),
        encoding="utf-8",
    )

    status = cli_mod.main(
        ["-c", str(sealed_board_project / "refdes.yaml"), "build", "--reseal", "board-a"]
    )
    assert status == 0


# ------------------------------------------------------------------- check --board

CROSS_BOARD_CONFIG = """\
site: { title: "Cross-board Test", out: _site }
id: { width: 3 }
boards:
  board-a: { label: "Board A" }
  board-b: { label: "Board B" }
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
"""


@pytest.fixture
def cross_board_project(tmp_path):
    """A decision on board-b that satisfies a requirement on board-a -- the case
    that breaks if `check --board` ever scopes the file walk instead of just the
    report: board-b's own folder never mentions REQ-A-001 at all.
    """
    (tmp_path / "refdes.yaml").write_text(CROSS_BOARD_CONFIG, encoding="utf-8")
    a = tmp_path / "items" / "board-a"
    a.mkdir(parents=True)
    (a / "req.md").write_text(
        "---\nid: REQ-A-001\ntype: requirement\ntext: Owned by board A.\n---\n",
        encoding="utf-8",
    )
    b = tmp_path / "items" / "board-b"
    b.mkdir(parents=True)
    (b / "dec.md").write_text(
        "---\nid: DEC-B-001\ntype: decision\ntitle: Board B decision.\n"
        "satisfies: [REQ-A-001]\n---\n",
        encoding="utf-8",
    )
    return tmp_path


def test_check_board_scope_does_not_affect_link_resolution(cross_board_project):
    project = _build_at(cross_board_project)
    assert not project.errors
    assert project.items["DEC-B-001"].links["satisfies"] == ["REQ-A-001"]
    assert "DEC-B-001" in project.items["REQ-A-001"].backlinks.get("satisfied_by", [])


def test_cli_check_board_scopes_the_report_not_the_link_walk(cross_board_project, capsys):
    """`--board board-b` must still resolve REQ-A-001 -- it just doesn't get
    reported, since board-b's own item count is 1 (DEC-B-001 only)."""
    status = cli_mod.main(
        ["-c", str(cross_board_project / "refdes.yaml"), "check", "--board", "board-b"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "1 items, 0 errors" in out


def test_check_board_filters_diagnostics_to_that_board(board_project, capsys):
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "board-b"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "REQ-WRONG-001" in out  # board-b's own token-mismatch warning
    assert "REQ-S-001" not in out  # unboarded item's warning, filtered out
    # +1 over the item-scoped warnings: the project-level, once-per-type
    # 'coverable:' fallback nudge (this fixture's schema predates that flag).
    assert "2 items, 0 errors, 3 warnings" in out


def test_check_board_always_shows_project_level_diagnostics(board_project, capsys):
    """A diagnostic with no item_id isn't attributable to any one board, so
    --board must never hide it -- here, the project-wide 'no coverage' summary
    warning that `check` always emits for this fixture's uncovered items."""
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "board-a"]
    )
    out = capsys.readouterr().out
    assert status == 0
    assert "no coverage" in out


def test_check_without_board_flag_is_unaffected_by_the_feature(board_project, capsys):
    assert cli_mod.main(["-c", str(board_project / "refdes.yaml"), "check"]) == 0
    out = capsys.readouterr().out
    assert "REQ-WRONG-001" in out
    assert "REQ-S-001" in out
    # +1 over the item-scoped warnings: the project-level, once-per-type
    # 'coverable:' fallback nudge (this fixture's schema predates that flag).
    assert "5 items, 0 errors, 5 warnings" in out


def test_cli_check_board_rejects_unknown_board(board_project, capsys):
    status = cli_mod.main(
        ["-c", str(board_project / "refdes.yaml"), "check", "--board", "bord-a"]
    )
    assert status == 1
    err = capsys.readouterr().err
    assert "not a board declared" in err
    assert "board-a" in err  # difflib suggestion


# ----------------------------------------------------------------- summary view


@pytest.mark.parametrize(
    "limit_text, value, expected",
    [
        ("<= 0.15 W/in^2", "0.10 W/in^2", 1 / 3),    # a third of the limit spare
        ("<= 0.15 W/in^2", "0.2366 W/in^2", -0.577), # over, so negative
        ("<= 0.15 W/in^2", "0.15 W/in^2", 0.0),      # exactly on the limit
        (">= 3.0 V", "3.3 V", 0.1),
        (">= 3.0 V", "2.7 V", -0.1),
        ("9 V .. 36 V", "12 V", 1 / 9),              # nearer edge decides
        ("9 V .. 36 V", "40 V", -4 / 27),
    ],
)
def test_margin_reports_fractional_slack(limit_text, value, expected):
    env = {}
    calc.evaluate_block(f"x = {value}", env)
    margin = calc.parse_limit(limit_text).margin(env["x"])
    assert margin == pytest.approx(expected, abs=1e-3)


def test_margin_sign_always_agrees_with_pass_fail():
    """A positive margin that failed, or negative that passed, would be a lie."""
    for limit_text, value in [
        ("<= 5 V", "4 V"), ("<= 5 V", "6 V"),
        (">= 5 V", "6 V"), (">= 5 V", "4 V"),
        ("1 V .. 5 V", "3 V"), ("1 V .. 5 V", "7 V"),
    ]:
        env = {}
        calc.evaluate_block(f"x = {value}", env)
        limit = calc.parse_limit(limit_text)
        ok, _ = limit.check(env["x"])
        assert (limit.margin(env["x"]) >= 0) is ok, (limit_text, value)


def test_margin_is_unit_aware_not_magnitude_aware():
    """150 mW and 0.1 W differ by 33%, not by a factor of 1500."""
    env = {}
    calc.evaluate_block("x = 0.1 W", env)
    assert calc.parse_limit("<= 150 mW").margin(env["x"]) == pytest.approx(1 / 3, abs=1e-3)


def test_margin_is_undefined_where_it_would_be_meaningless():
    env = {}
    calc.evaluate_block("x = 5 V", env)
    assert calc.parse_limit("== 5 V").margin(env["x"]) is None  # met or not, no "close"
    env2 = {}
    calc.evaluate_block("y = 0 V", env2)
    assert calc.parse_limit("<= 0 V").margin(env2["y"]) is None  # no dividing by zero


def test_summary_orders_checks_by_tightest_margin():
    payload = render.summary_payload(_project())
    margins = [c.margin for _i, c in payload["margin_rows"] if c.margin is not None]
    assert margins == sorted(margins)
    assert margins[0] < 0  # the thermal violation sorts to the top


def test_a_constraint_that_is_checked_against_is_not_orphaned():
    """`checks:` is a real dependency even though it creates no link edge.

    Listing a checked-against constraint as untraced would contradict the margins
    table on the very same page.
    """
    project = _project()
    payload = render.summary_payload(project)
    orphan_ids = {i.id for i in payload["orphans"]}
    checked = {c.against for i in project.local_items for c in i.checks if c.against}
    assert checked
    assert not (orphan_ids & checked)


def test_summary_reports_every_computed_value():
    project = _project()
    payload = render.summary_payload(project)
    assert len(payload["calc_rows"]) == sum(len(i.calcs) for i in project.local_items)


def test_log_entries_have_a_readable_title_not_their_own_id():
    """A log entry names its description `summary`, so `title` must find it.

    Without this every table that shows a title -- coverage, the full record, hover
    previews -- renders a column of bare IDs for log entries.
    """
    project = _project()
    entries = [i for i in project.local_items if i.type == "log"]
    assert entries
    for entry in entries:
        assert entry.title != entry.id
        assert entry.title == entry.fields["summary"]


def test_page_named_summary_collides_with_the_report(paged_project):
    (paged_project / "pages" / "summary.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(paged_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)
    out = os.path.join(paged_project, "_site", "summary.html")
    assert "Nope" not in open(out, encoding="utf-8").read()
