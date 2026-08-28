"""project settings (refdes-project.yaml).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os

import pytest
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
    (tmp_path / "refdes.yaml").write_text(MINIMAL_PROJECT_SCHEMA, encoding="utf-8")
    if settings_yaml is not None:
        (tmp_path / "refdes-project.yaml").write_text(settings_yaml, encoding="utf-8")
    return tmp_path / "refdes.yaml"


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
        "missing_vendored_copies":    {"release": True,  "revision": False},
        "uncovered_requirements":     {"release": True,  "revision": False},
        "unverified_requirements":    {"release": False, "revision": False},
        "info_check_failures":        {"release": False, "revision": False},
        "unaccepted_board_moves":     {"release": True,  "revision": False},
        "unaccepted_workspace_moves": {"release": True,  "revision": False},
    }


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
    config = _write_minimal_project(tmp_path, "- not\n- a\n- mapping\n")
    with pytest.raises(SchemaError, match="must be a mapping"):
        load_project(config_path=str(config))


def test_sigfigs_flows_through_calc_formatting(tmp_path):
    """Project.sigfigs, resolved once at load, reaches calc.format_value via
    build.run_calcs without every caller threading a digits= parameter."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes-project.yaml").write_text("sigfigs: 2\n", encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nP = 3.3 V * 1.2 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert project.items["DEC-001"].calcs[0].result == "4 W"  # 2 sigfigs, not "3.96 W"


def test_sigfigs_flows_through_check_messages(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  constraint: { prefix: CON, fields: { limit: { type: limit, required: true } } }\n"
        "  decision: { prefix: DEC, fields: {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "refdes-project.yaml").write_text("sigfigs: 2\n", encoding="utf-8")
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
        "```calc\nx : A = 0.6061 A\n```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    check = project.items["DEC-001"].checks[0]
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
