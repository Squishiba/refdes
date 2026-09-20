"""project settings (refdes-project.yaml).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import build as build_mod
from refdes import parse, render
from refdes.schema import SchemaError, load_project

# --------------------------------------------------- project settings (refdes-project.yaml)

MINIMAL_PROJECT_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
)


def _write_minimal_project(tmp_path, settings_yaml: str | None = None):
    """The two real files, from one combined schema constant plus settings text
    appended to the marker. Returns the marker's path, what load_project reads."""
    config = write_project_config(tmp_path, MINIMAL_PROJECT_SCHEMA)
    if settings_yaml is not None:
        with config.open("a", encoding="utf-8") as fh:
            fh.write(settings_yaml)
    return config


DATE_PROJECT_SCHEMA = """\
site: { title: Date test, out: _site }
types:
  log:
    prefix: LOG
    fields:
      date: { type: date, required: true }
      summary: { type: text, required: true }
"""


def _write_date_project(tmp_path, entries, date_format: str | None = None):
    format_setting = f"date_format: {date_format}\n" if date_format else ""
    write_project_config(tmp_path, format_setting + DATE_PROJECT_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    item_lines = ["items:"]
    for item_id, value in entries:
        item_lines.extend(
            [
                f"  - id: {item_id}",
                "    type: log",
                f'    date: "{value}"',
                f"    summary: Entry {item_id}",
            ]
        )
    (items / "log.yaml").write_text("\n".join(item_lines) + "\n", encoding="utf-8")
    return tmp_path


def _date_errors(project):
    return [d for d in project.errors if "expected " in d.message]


def test_project_settings_absent_file_matches_pre_config_defaults(tmp_path):
    """A project with no refdes-project.yaml behaves exactly as today -- except
    publish_datasheets, whose default is a deliberate change (see its own
    docstring on Project)."""
    config = _write_minimal_project(tmp_path)
    project = load_project(config_path=str(config))
    assert project.sigfigs == 4
    assert project.item_layout == "flat"
    assert project.baseline_identity == "os_user"
    assert project.require_rejection_rationale is True
    assert project.publish_datasheets is False
    assert project.lint_own_tags is False
    assert project.release_gate == {
        "draft_items":                {"release": True,  "revision": False},
        "unpinned_citations":         {"release": True,  "revision": False},
        "missing_kept_copies":    {"release": True,  "revision": False},
        "uncovered_requirements":     {"release": True,  "revision": False},
        "unverified_requirements":    {"release": False, "revision": False},
        "info_check_failures":        {"release": False, "revision": False},
        "unaccepted_board_moves":     {"release": True,  "revision": False},
        "unaccepted_workspace_moves": {"release": True,  "revision": False},
    }


def test_date_format_defaults_to_strict_iso(tmp_path):
    root = _write_date_project(
        tmp_path,
        [("LOG-001", "2026-01-25"), ("LOG-002", "01/25/2026")],
    )
    project = _build_at(root)

    assert project.date_format == "YYYY-MM-DD"
    errors = _date_errors(project)
    assert [(d.item_id, d.message) for d in errors] == [
        (
            "LOG-002",
            "date: '01/25/2026' is not a valid date; expected YYYY-MM-DD",
        )
    ]


def test_custom_date_format_accepts_interchangeable_separators(tmp_path):
    root = _write_date_project(
        tmp_path,
        [
            ("LOG-001", "01/25/2026"),
            ("LOG-002", "01-25-2026"),
            ("LOG-003", "01.25.2026"),
            ("LOG-004", "2026-01-25"),
        ],
        date_format="MM/DD/YYYY",
    )
    project = _build_at(root)

    assert project.date_format == "MM/DD/YYYY"
    errors = _date_errors(project)
    assert [(d.item_id, d.message) for d in errors] == [
        (
            "LOG-004",
            "date: '2026-01-25' is not a valid date; expected MM/DD/YYYY",
        )
    ]


def test_impossible_date_is_a_hard_error_naming_expected_format(tmp_path):
    root = _write_date_project(
        tmp_path,
        [("LOG-001", "13/32/2026")],
        date_format="MM/DD/YYYY",
    )
    project = _build_at(root)

    assert [(d.item_id, d.message) for d in _date_errors(project)] == [
        (
            "LOG-001",
            "date: '13/32/2026' is not a valid date; expected MM/DD/YYYY",
        )
    ]


def test_date_format_setting_rejects_invalid_placeholder_shape(tmp_path):
    config = _write_minimal_project(tmp_path, "date_format: YYYY/DD\n")
    with pytest.raises(
        SchemaError,
        match="date_format must use YYYY, MM, and DD exactly once",
    ):
        load_project(config_path=str(config))


def test_non_iso_log_dates_render_in_chronological_order(tmp_path):
    root = _write_date_project(
        tmp_path,
        [
            ("LOG-001", "12/31/2025"),
            ("LOG-002", "01/15/2026"),
            ("LOG-003", "02/01/2025"),
        ],
        date_format="MM/DD/YYYY",
    )
    project = _build_at(root)
    assert not project.errors

    out = render.render_site(project)
    log_html = (tmp_path / out / "log.html").read_text(encoding="utf-8")
    document_html = (tmp_path / out / "document.html").read_text(encoding="utf-8")
    summary_html = (tmp_path / out / "summary.html").read_text(encoding="utf-8")

    oldest_first = ["LOG-003", "LOG-001", "LOG-002"]
    assert [
        log_html.index(f'data-ref="{item_id}"')
        for item_id in oldest_first
    ] == sorted(log_html.index(f'data-ref="{item_id}"') for item_id in oldest_first)
    assert [
        document_html.index(f'<section class="doc-item" id="{item_id.lower()}">')
        for item_id in oldest_first
    ] == sorted(
        document_html.index(f'<section class="doc-item" id="{item_id.lower()}">')
        for item_id in oldest_first
    )

    newest_first = list(reversed(oldest_first))
    recent_log_html = summary_html[summary_html.index("<h2>Recent design log</h2>") :]
    assert [
        recent_log_html.index(f'data-ref="{item_id}"')
        for item_id in newest_first
    ] == sorted(
        recent_log_html.index(f'data-ref="{item_id}"')
        for item_id in newest_first
    )


def test_project_settings_sigfigs_overrides_the_default(tmp_path):
    config = _write_minimal_project(tmp_path, "sigfigs: 6\n")
    project = load_project(config_path=str(config))
    assert project.sigfigs == 6


@pytest.mark.parametrize(
    "settings_yaml",
    ["sigfigs: 0\n", "sigfigs: 16\n", "sigfigs: 1.5\n", 'sigfigs: "4"\n', "sigfigs: true\n"],
)
def test_project_settings_sigfigs_out_of_range_or_wrong_type_is_a_schema_error(tmp_path, settings_yaml):
    config = _write_minimal_project(tmp_path, settings_yaml)
    with pytest.raises(SchemaError, match="sigfigs must be an integer between 1 and 15"):
        load_project(config_path=str(config))


def test_project_settings_item_layout_accepts_workspace(tmp_path):
    config = _write_minimal_project(tmp_path, "item_layout: workspace\n")
    project = load_project(config_path=str(config))
    assert project.item_layout == "workspace"


def test_project_settings_item_layout_rejects_a_free_form_pattern(tmp_path):
    """The user explicitly rejected general pattern syntax -- only the two
    fixed shapes are valid, not e.g. "<workspace>/<board>"."""
    config = _write_minimal_project(tmp_path, 'item_layout: "<workspace>/<board>"\n')
    with pytest.raises(SchemaError, match=r"item_layout must be one of \['flat', 'workspace'\]"):
        load_project(config_path=str(config))


def test_project_settings_baseline_identity_accepts_git_identity(tmp_path):
    config = _write_minimal_project(tmp_path, "baseline_identity: git_identity\n")
    project = load_project(config_path=str(config))
    assert project.baseline_identity == "git_identity"


def test_project_settings_baseline_identity_rejects_unknown_value(tmp_path):
    config = _write_minimal_project(tmp_path, "baseline_identity: ldap\n")
    with pytest.raises(SchemaError, match="baseline_identity must be one of"):
        load_project(config_path=str(config))


def test_project_settings_require_rejection_rationale_must_be_boolean(tmp_path):
    config = _write_minimal_project(tmp_path, "require_rejection_rationale: maybe\n")
    with pytest.raises(SchemaError, match="require_rejection_rationale must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_publish_datasheets_must_be_boolean(tmp_path):
    config = _write_minimal_project(tmp_path, "publish_datasheets: on-request\n")
    with pytest.raises(SchemaError, match="publish_datasheets must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_lint_own_tags_must_be_boolean(tmp_path):
    config = _write_minimal_project(tmp_path, "lint_own_tags: sometimes\n")
    with pytest.raises(SchemaError, match="lint_own_tags must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_overlay_only_touches_named_rules(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  unverified_requirements: { release: true }\n",
    )
    project = load_project(config_path=str(config))
    assert project.release_gate["unverified_requirements"] == {"release": True, "revision": False}
    # everything else is untouched
    assert project.release_gate["draft_items"] == {"release": True, "revision": False}


def test_project_settings_release_gate_rejects_unknown_rule_with_a_suggestion(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_item: { release: true }\n",  # typo: missing 's'
    )
    with pytest.raises(SchemaError, match=r"draft_item.*Did you mean 'draft_items'"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_names_the_rule_rename(tmp_path):
    """S1 renamed the `missing_vendored_copies` rule to
    `missing_kept_copies`; a project still carrying the old key gets the
    rename spelled out, not a fuzzy suggestion that may not fire."""
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  missing_vendored_copies: { release: true }\n",
    )
    with pytest.raises(SchemaError, match=r"missing_vendored_copies was renamed to 'missing_kept_copies'"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_rejects_unknown_inner_key(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_items: { relase: true }\n",  # typo: missing 'e'
    )
    with pytest.raises(SchemaError, match="release_gate.draft_items.relase"):
        load_project(config_path=str(config))


def test_project_settings_release_gate_rejects_non_boolean_value(tmp_path):
    config = _write_minimal_project(
        tmp_path,
        "release_gate:\n  draft_items: { release: yes-please }\n",
    )
    with pytest.raises(SchemaError, match="release_gate.draft_items.release must be true or false"):
        load_project(config_path=str(config))


def test_project_settings_unknown_top_level_key_is_a_schema_error(tmp_path):
    config = _write_minimal_project(tmp_path, "sigffigs: 6\n")  # typo
    with pytest.raises(SchemaError, match=r"unknown setting 'sigffigs'.*Did you mean 'sigfigs'"):
        load_project(config_path=str(config))


def test_project_settings_file_must_be_a_mapping(tmp_path):
    write_project_config(tmp_path, MINIMAL_PROJECT_SCHEMA)
    config = tmp_path / "refdes-project.yaml"
    config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="must be a mapping"):
        load_project(config_path=str(config))


def test_sigfigs_flows_through_calc_formatting(tmp_path):
    """Project.sigfigs, resolved once at load, reaches calc.format_value via
    build.run_calcs without every caller threading a digits= parameter."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
    )
    (tmp_path / "refdes-project.yaml").write_text(
        "site: { title: T, out: _site }\nsigfigs: 2\n", encoding="utf-8"
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nP = 3.3 V * 1.2 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(start=str(tmp_path))
    parse.load_items(project)
    build_mod.build(project)
    assert project.item_by_id("DEC-001").calcs[0].result == "4 W"  # 2 sigfigs, not "3.96 W"


def test_sigfigs_flows_through_check_messages(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  constraint: { prefix: CON, fields: { limit: { type: limit, required: true } } }\n"
        "  decision: { prefix: DEC, fields: {} }\n",
    )
    (tmp_path / "refdes-project.yaml").write_text(
        "site: { title: T, out: _site }\nsigfigs: 2\n", encoding="utf-8"
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults: { type: constraint }\n"
        "items:\n  - id: CON-001\n    limit: \"<= 600 mA\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "checks:\n"
        "  - value: x\n"
        "    against: CON-001\n"
        "---\n\n"
        "```calc\nx = 0.6061 A | A\n```\n",
        encoding="utf-8",
    )
    project = load_project(start=str(tmp_path))
    parse.load_items(project)
    build_mod.build(project)
    check = project.item_by_id("DEC-001").checks[0]
    assert check.actual == "0.61 A"  # 2 sigfigs, not the default 4 (0.6061 A)


def test_per_board_pages_are_scoped_to_that_boards_items(board_project):
    project = _build_at(board_project)
    out = render.render_site(project)

    # previews_json embeds every item's data on every page for hover previews, so
    # scoping has to be checked against the actual rendered item section, not just
    # a bare substring search for the id anywhere on the page.
    doc_a = open(os.path.join(out, "document-board-a.html"), encoding="utf-8").read()
    doc_b = open(os.path.join(out, "document-board-b.html"), encoding="utf-8").read()
    assert 'id="req-a-001"' in doc_a
    assert 'id="req-b-001"' not in doc_a
    assert 'id="req-b-001"' in doc_b
    assert 'id="req-a-001"' not in doc_b

    cov_a = open(os.path.join(out, "coverage-board-a.html"), encoding="utf-8").read()
    assert 'data-ref="REQ-A-001"' in cov_a
    assert 'data-ref="REQ-B-001"' not in cov_a

    # The global pages are untouched -- every item still appears on them.
    doc_global = open(os.path.join(out, "document.html"), encoding="utf-8").read()
    assert 'id="req-a-001"' in doc_global and 'id="req-b-001"' in doc_global


def test_items_json_exports_board_registry_and_per_item_board(board_project):
    project = _build_at(board_project)
    payload = render.items_json(project)
    assert payload["boards"]["board-a"]["label"] == "Board A"
    assert payload["boards"]["board-a"]["token"] == "A"
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["REQ-A-001"]["board"] == "board-a"
    assert by_id["REQ-S-001"]["board"] == ""


def test_reserved_filename_guard_covers_per_board_report_names(board_project):
    pages = board_project / "pages"
    pages.mkdir()
    (pages / "document-board-a.md").write_text("# Nope\n", encoding="utf-8")
    project = _build_at(board_project)
    render.render_site(project)
    assert any("generated report" in d.message for d in project.errors)
