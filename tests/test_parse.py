"""YAML error diagnostics -- and: defaults: leaking across type: (finding 6), lint_own_tags (finding 11), reserved prefix key.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil

from helpers import COVERAGE_SCHEMA, REPO

from refdes import build as build_mod
from refdes import ids, parse
from refdes.schema import load_project

# --------------------------------------------------------- YAML error diagnostics


def test_invalid_yaml_in_a_list_file_reports_the_real_line_not_always_1(tmp_path):
    """Finding 13's actual point: line=1 was hardcoded, not a fallback -- wrong
    for any malformed YAML past the first couple of lines, not just the '>'
    gotcha this finding is nominally about. A literal tab in indentation is a
    clean repro: YAML disallows it outright, and PyYAML's own mark lands
    exactly on the offending line."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: fine.\n"
        "  - id: REQ-A-002\n"
        "\ttext: tabbed\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert yaml_errors[0].line != 1
    assert yaml_errors[0].line == 5  # the tabbed line itself


def test_invalid_yaml_in_markdown_front_matter_reports_the_real_line(tmp_path):
    """Same fix, front-matter path -- the parsed text is a *slice* of the
    file starting after the opening fence, so the exception's own mark (which
    is relative to that slice) needs the slice's offset added back, or the
    reported line would be wrong in a new way instead of just defaulting to 1."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.md").write_text(
        "---\n"
        "id: DEC-A-001\n"
        "type: decision\n"
        "title: fine so far\n"
        "\tstatus: tabbed\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML front-matter" in d.message]
    assert len(yaml_errors) == 1
    assert yaml_errors[0].line != 1
    assert yaml_errors[0].line == 5  # the tabbed line itself


def test_bare_gte_limit_gets_a_quoting_hint(tmp_path):
    """A bare '>=' value is read by YAML as a folded-block-scalar indicator,
    not a comparison -- the resulting scanner error should carry a targeted
    hint saying so, not just PyYAML's raw internals message."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n"
        "    title: t\n"
        "    limit: >= 9 V\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" in yaml_errors[0].message
    assert '">= 9 V"' in yaml_errors[0].message
    assert yaml_errors[0].line == 4  # the `limit: >= 9 V` line itself


def test_bare_gt_hint_fires_on_any_field_not_just_limit(tmp_path):
    """The finding is explicit that this must be scoped to the line's actual
    content, not to a field literally named `limit` -- the same YAML gotcha
    hits any field."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: > shall be greater than something\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" in yaml_errors[0].message


def test_other_yaml_errors_get_no_quoting_hint(tmp_path):
    """The hint must not fire on an unrelated malformed-YAML failure -- an
    unterminated flow sequence has nothing to do with the '>' gotcha."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: [ unterminated\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" not in yaml_errors[0].message


# ---------------------------------------- defaults: leaking across type: (finding 6)

DEFAULTS_LEAK_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "      status: { type: enum, choices: [draft, active, retired] }\n"
    "  component:\n"
    "    prefix: CMP\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      status: { type: enum, choices: [candidate, selected, obsolete] }\n"
)


def _defaults_leak_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(DEFAULTS_LEAK_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "mixed.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def test_inherited_default_failing_the_overridden_types_own_enum_names_the_defaults_line(
    tmp_path,
):
    root = _defaults_leak_project(
        tmp_path,
        "defaults:\n  type: requirement\n  status: active\n"
        "items:\n"
        "  - id: REQ-001\n    text: A normal requirement.\n"
        "  - id: CMP-001\n    type: component\n    title: Some part\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    error = next(d for d in project.errors if d.item_id == "CMP-001")
    assert "inherited from this file's defaults:" in error.message
    assert "not set on CMP-001 itself" in error.message
    # The defaults: block's own first key ("type: requirement") is line 2 --
    # not CMP-001's own line further down, which never wrote status: at all.
    assert error.line == 2
    assert error.file == "items/mixed.yaml"


def test_a_value_the_item_actually_wrote_itself_is_reported_normally(tmp_path):
    """The inherited-value framing must not leak onto a value an item wrote
    on its own -- only a value it never stated should be called inherited."""
    root = _defaults_leak_project(
        tmp_path,
        "defaults:\n  type: requirement\n"
        "items:\n  - id: REQ-002\n    text: Something.\n    status: bogus\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    error = next(d for d in project.errors if d.item_id == "REQ-002")
    assert "inherited from this file's defaults:" not in error.message
    assert error.line == 4  # REQ-002's own line, not the defaults: block's


def test_overriding_the_defaults_value_is_not_treated_as_inherited(tmp_path):
    """An item that restates the same key defaults: also sets is not
    inheriting anything -- its own value won, so a failure there is its own,
    reported exactly as it always was."""
    root = _defaults_leak_project(
        tmp_path,
        "defaults:\n  type: requirement\n  status: active\n"
        "items:\n  - id: REQ-003\n    text: Overrides status itself.\n    status: bogus\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    error = next(d for d in project.errors if d.item_id == "REQ-003")
    assert "inherited from this file's defaults:" not in error.message
    assert error.line == 5  # REQ-003's own line, not the defaults: block's


def test_defaults_leak_is_caught_the_same_way_in_markdown_files(tmp_path):
    """parse_markdown_file's file-wide defaults: block (the first front-matter
    block, when it's shaped as nothing but 'defaults:') merges the same way
    parse_list_file's does -- same bug, same fix, same test shape."""
    (tmp_path / "refdes.yaml").write_text(DEFAULTS_LEAK_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "mixed.md").write_text(
        "---\ndefaults:\n  type: requirement\n  status: active\n---\n"
        "id: REQ-001\ntext: A normal requirement.\n---\n"
        "id: CMP-001\ntype: component\ntitle: Some part\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    error = next(d for d in project.errors if d.item_id == "CMP-001")
    assert "inherited from this file's defaults:" in error.message
    assert error.line == 2  # the defaults: block's own first key line


# --------------------------------------------------- lint_own_tags (finding 11)

LINT_TAGS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields:\n"
    "      text: { type: text, required: true }\n"
    "      tags: { type: list, on_change: ignore }\n"
    "  component:\n"
    "    prefix: CMP\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
)


def _lint_tags_project(tmp_path, items_yaml, enabled=True):
    (tmp_path / "refdes.yaml").write_text(LINT_TAGS_SCHEMA, encoding="utf-8")
    if enabled:
        (tmp_path / "refdes-project.yaml").write_text("lint_own_tags: true\n", encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "mixed.yaml").write_text(items_yaml, encoding="utf-8")
    # A separate file/defaults: block, deliberately never mentioning tags: at
    # all -- component doesn't declare the field, so merging a requirement
    # file's own tags: onto it would trip the unrelated "unknown field"
    # warning instead of exercising the type-with-no-tags-field skip this is
    # meant to isolate.
    (items / "untaggable.yaml").write_text(
        "defaults:\n  type: component\n"
        "items:\n  - id: CMP-001\n    title: A type with no tags field at all.\n",
        encoding="utf-8",
    )
    return tmp_path


LINT_TAGS_ITEMS = (
    "defaults:\n  type: requirement\n  tags: [power]\n"
    "items:\n"
    "  - id: REQ-001\n    text: Only the file default tag.\n"
    "  - id: REQ-002\n    text: Has its own tag too.\n    tags: [current limit]\n"
    "  - id: REQ-003\n    text: Explicitly empty tags.\n    tags: []\n"
)


def _tags_lint_warnings(project):
    """Isolate this lint's own warnings from unrelated ones (e.g. the
    coverable: fallback notice, which fires for any project using a custom
    requirement type without declaring it)."""
    return [d for d in project.warnings if "tags:" in d.message]


def test_lint_own_tags_is_off_by_default(tmp_path):
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS, enabled=False)
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert _tags_lint_warnings(project) == []


def test_lint_own_tags_flags_inherited_only_and_fully_empty(tmp_path):
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS)
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    warnings = _tags_lint_warnings(project)
    warned_ids = {d.item_id for d in warnings}
    assert warned_ids == {"REQ-001", "REQ-003"}

    inherited = next(d for d in warnings if d.item_id == "REQ-001")
    assert "entirely inherited from this file's defaults:" in inherited.message

    empty = next(d for d in warnings if d.item_id == "REQ-003")
    assert "no tags: at all" in empty.message


def test_lint_own_tags_is_silent_for_an_items_own_tags(tmp_path):
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS)
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not any(d.item_id == "REQ-002" for d in project.warnings)


def test_lint_own_tags_skips_a_type_with_no_tags_field(tmp_path):
    """component has no tags: field declared at all -- must never be flagged
    as if it were an item that failed to tag itself."""
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS)
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not any(d.item_id == "CMP-001" for d in project.warnings)


# ------------------------------------------------------------- reserved prefix key


def test_per_item_prefix_overrides_file_defaults_in_a_list_file(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "mixed.yaml").write_text(
        "defaults:\n  type: requirement\n  prefix: REQ-DEFAULT\n"
        "items:\n"
        "  - body: Uses the file default prefix.\n"
        "  - prefix: REQ-OVERRIDE\n"
        "    body: Uses its own prefix.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.body: new_id for item, new_id in assignments}
    assert got["Uses the file default prefix."] == "REQ-DEFAULT-001"
    assert got["Uses its own prefix."] == "REQ-OVERRIDE-001"
    # `prefix:` is consumed, never stored as a field.
    assert "prefix" not in project.items["REQ-OVERRIDE-001"].fields


def test_per_item_prefix_overrides_file_defaults_in_markdown(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "multi.md").write_text(
        "---\ndefaults:\n  type: decision\n  prefix: DEC-DEFAULT\n---\n"
        "title: Uses the file default\n---\n\nBody.\n\n"
        "---\nprefix: DEC-OWN\ntitle: Uses its own prefix\n---\n\nBody.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.fields["title"]: new_id for item, new_id in assignments}
    assert got["Uses the file default"] == "DEC-DEFAULT-001"
    assert got["Uses its own prefix"] == "DEC-OWN-001"
