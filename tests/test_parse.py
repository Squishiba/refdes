"""YAML error diagnostics -- and: defaults: leaking across type: (finding 6), lint_own_tags (finding 11), reserved prefix key.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil

from conftest import write_project_config
from helpers import COVERAGE_SCHEMA, REPO

from refdes import build as build_mod
from refdes import docs_url, ids, parse
from refdes.schema import load_project

# --------------------------------------------------------- YAML error diagnostics


def test_invalid_yaml_in_a_list_file_reports_the_real_line_not_always_1(tmp_path):
    """Finding 13's actual point: line=1 was hardcoded, not a fallback -- wrong
    for any malformed YAML past the first couple of lines, not just the '>'
    gotcha this finding is nominally about. A literal tab in indentation is a
    clean repro: YAML disallows it outright, and PyYAML's own mark lands
    exactly on the offending line."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
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
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
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
    write_project_config(tmp_path, COVERAGE_SCHEMA)
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
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML front-matter" in d.message]
    assert len(yaml_errors) == 1
    assert yaml_errors[0].line != 1
    assert yaml_errors[0].line == 5  # the tabbed line itself


def test_bare_gte_limit_gets_a_quoting_hint(tmp_path):
    """A bare '>=' value is read by YAML as a folded-block-scalar indicator,
    not a comparison -- the resulting scanner error should carry a targeted
    hint saying so, not just PyYAML's raw internals message."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n"
        "    title: t\n"
        "    limit: >= 9 V\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
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
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: > shall be greater than something\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)

    yaml_errors = [d for d in project.errors if "invalid YAML" in d.message]
    assert len(yaml_errors) == 1
    assert "needs quotes" in yaml_errors[0].message


def test_other_yaml_errors_get_no_quoting_hint(tmp_path):
    """The hint must not fire on an unrelated malformed-YAML failure -- an
    unterminated flow sequence has nothing to do with the '>' gotcha."""
    write_project_config(tmp_path, COVERAGE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text(
        "items:\n"
        "  - id: REQ-A-001\n"
        "    text: [ unterminated\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
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
    write_project_config(tmp_path, DEFAULTS_LEAK_SCHEMA)
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)

    error = next(d for d in project.errors if d.item_id == "REQ-003")
    assert "inherited from this file's defaults:" not in error.message
    assert error.line == 5  # REQ-003's own line, not the defaults: block's


def test_defaults_leak_is_caught_the_same_way_in_markdown_files(tmp_path):
    """parse_markdown_file's file-wide defaults: block (the first front-matter
    block, when it's shaped as nothing but 'defaults:') merges the same way
    parse_list_file's does -- same bug, same fix, same test shape."""
    write_project_config(tmp_path, DEFAULTS_LEAK_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "mixed.md").write_text(
        "---\ndefaults:\n  type: requirement\n  status: active\n---\n"
        "id: REQ-001\ntext: A normal requirement.\n---\n"
        "id: CMP-001\ntype: component\ntitle: Some part\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
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
    write_project_config(tmp_path, LINT_TAGS_SCHEMA)
    if enabled:
        # refdes-project.yaml is the settings file itself now, so this appends
        # the one setting instead of replacing what was just written.
        with open(tmp_path / "refdes-project.yaml", "a", encoding="utf-8") as fh:
            fh.write("lint_own_tags: true\n")
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert _tags_lint_warnings(project) == []


def test_lint_own_tags_flags_inherited_only_and_fully_empty(tmp_path):
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not any(d.item_id == "REQ-002" for d in project.warnings)


def test_lint_own_tags_skips_a_type_with_no_tags_field(tmp_path):
    """component has no tags: field declared at all -- must never be flagged
    as if it were an item that failed to tag itself."""
    root = _lint_tags_project(tmp_path, LINT_TAGS_ITEMS)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not any(d.item_id == "CMP-001" for d in project.warnings)


# ------------------------------------------------------------- reserved prefix key


def _copy_repo_config(tmp_path):
    """Copy this repo's own two config files into `tmp_path`."""
    for name in ("refdes-project.yaml", "refdes-schema.yaml"):
        shutil.copy(os.path.join(REPO, name), tmp_path / name)


def test_per_item_prefix_overrides_file_defaults_in_a_list_file(tmp_path):
    _copy_repo_config(tmp_path)
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
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.body: new_id for item, new_id in assignments}
    assert got["Uses the file default prefix."] == "REQ-DEFAULT-001"
    assert got["Uses its own prefix."] == "REQ-OVERRIDE-001"
    # `prefix:` is consumed, never stored as a field.
    assert "prefix" not in project.item_by_id("REQ-OVERRIDE-001").fields


def test_per_item_prefix_overrides_file_defaults_in_markdown(tmp_path):
    _copy_repo_config(tmp_path)
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "multi.md").write_text(
        "---\ndefaults:\n  type: decision\n  prefix: DEC-DEFAULT\n---\n"
        "title: Uses the file default\n---\n\nBody.\n\n"
        "---\nprefix: DEC-OWN\ntitle: Uses its own prefix\n---\n\nBody.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    got = {item.fields["title"]: new_id for item, new_id in assignments}
    assert got["Uses the file default"] == "DEC-DEFAULT-001"
    assert got["Uses its own prefix"] == "DEC-OWN-001"


def test_front_matter_defaults_block_reads_only_the_first_and_only_a_defaults_block():
    """The block `parse_markdown_file` merges under every item, exposed for a
    caller that needs a Markdown file's defaults without its items -- the
    editor planning an id for an item it is about to append. Reading it any
    more loosely would number that item from a series the loader never
    applies."""
    def defaults_of(text):
        blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
        return parse.front_matter_defaults_block(blocks)

    assert defaults_of(
        "---\ndefaults:\n  type: requirement\n  prefix: REQ-SYS\n---\n\nbody\n"
    ) == {"type": "requirement", "prefix": "REQ-SYS"}
    # a first block that is an item, not a defaults block
    assert defaults_of("---\nid: REQ-001\nbody: x\n---\n") is None
    # no front matter at all
    assert defaults_of("just prose\n") is None
    # a defaults block that is not first is an error the loader reports, not
    # a second application point -- and never the file's defaults
    assert defaults_of(
        "---\nid: REQ-001\nbody: x\n---\n---\ndefaults:\n  prefix: NOPE\n---\n"
    ) is None
    # an empty defaults mapping is still a block: the loader consumes block
    # zero and merges nothing under the items
    assert defaults_of("---\ndefaults: {}\n---\n---\nbody: x\n---\n") == {}


# ------------------------------------------------- duplicate keys in a mapping

DUP_SCHEMA = (
    "site: {title: \"Dup Keys\", out: _site}\n"
    "id: {width: 3, ledger: .refdes/ids.yaml}\n"
    "on_change: {default: invalidate}\n"
    "units: {preferred: []}\n"
    "link_types:\n"
    "  satisfies: { inverse: satisfied_by, label: \"Satisfies\" }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    label: Requirement\n"
    "    fields:\n"
    "      text: { type: text, required: true, on_change: invalidate }\n"
    "      owner: { type: text, on_change: invalidate }\n"
    "    links: {}\n"
    "    body: { on_change: invalidate }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    label: Decision\n"
    "    fields:\n"
    "      title:  { type: text, required: true, on_change: invalidate }\n"
    "      status: { type: enum, choices: [proposed, accepted, on_hold], default: proposed, on_change: invalidate }\n"
    "    links:\n"
    "      satisfies: [requirement]\n"
    "    satisfying_statuses: [accepted]\n"
    "    body: { on_change: invalidate }\n"
)


def _dup_project(tmp_path, items: dict[str, str]):
    """A project whose only item files are `items`, loaded and parsed."""
    write_project_config(tmp_path, DUP_SCHEMA)
    (tmp_path / "items").mkdir(exist_ok=True)
    for name, text in items.items():
        (tmp_path / "items" / name).write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return project


def _dup_errors(project):
    return [d for d in project.errors if "duplicate key" in d.message]


def _item(project, item_id):
    """`project.items` is keyed by handle, never by display id."""
    return project.items[project.items_by_id[item_id]]


def test_two_id_lines_in_one_entry_error_and_name_both_lines(tmp_path):
    """YAML keeps the last of two `id:` keys and says nothing. The item the
    first one named is simply not in the model, so the repeat has to be an
    error that names the file, the line of *each* occurrence, the key, and the
    id the entry ended up with."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "defaults:\n"
            "  type: requirement\n"
            "  prefix: REQ\n"
            "items:\n"
            "  - id: REQ-001\n"
            "    text: prose\n"
            "    id: REQ-002\n"
            "    owner: someone else\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    error = errors[0]
    assert error.file == "items/r.yaml"
    assert error.level == "error"
    # Reported at the repeat, the way `duplicate id` reports at the second
    # definition and names the first; both line numbers are in the message.
    assert error.line == 7  # the repeat; the first is on line 5
    assert "duplicate key 'id'" in error.message
    assert "lines 5 and 7" in error.message
    assert "'REQ-001' is dropped for 'REQ-002'" in error.message
    # The entry itself is the surviving item, so that is the id the rest of
    # the run's diagnostics hang off.
    assert error.item_id == "REQ-002"
    # The published docs page for the family, never a repo-relative path
    # (docs_url.py's rule: the wheel ships no docs/*.md).
    assert docs_url.ITEMS_FIELDS_DOCS in error.message
    assert "docs/troubleshooting.md" not in error.message
    assert set(project.items_by_id) == {"REQ-002"}
    # And the file is off-limits to the rest of the load (see
    # test_load_time_writes.py).
    assert project.duplicate_key_files == {"items/r.yaml"}


def test_two_body_lines_in_one_entry_error_and_name_both_lines(tmp_path):
    """The same repeat on a key that is not an id: no item disappears, but the
    first body is gone from the model and from every rendered page, which is
    just as silent. Reported the same way, and without claiming an id was
    lost."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "defaults:\n"
            "  type: requirement\n"
            "  prefix: REQ\n"
            "items:\n"
            "  - id: REQ-001\n"
            "    text: prose\n"
            "    body: The first body.\n"
            "    body: The second body.\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    message = errors[0].message
    assert "duplicate key 'body'" in message
    assert "lines 7 and 8" in message
    assert errors[0].line == 8
    assert errors[0].item_id == "REQ-001"
    # The remedy names the shape that causes this most often: a list entry
    # that lost its `- ` marker and merged into the entry above it.
    assert "'- key:'" in message and "'- ' back on its own line" in message
    # The surviving body is the one in the model -- the loss is the point, and
    # the diagnostic must not paper over it.
    assert _item(project, "REQ-001").body == "The second body."


def test_a_clean_file_reports_no_duplicate_key_error(tmp_path):
    """The control: a list file and a Markdown file with no repeat in any
    mapping load exactly as they did, and no file is marked un-writable."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "defaults:\n"
            "  type: requirement\n"
            "  prefix: REQ\n"
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
            "    owner: a\n"
            "  - id: REQ-002\n"
            "    text: two\n"
            "    refines: [REQ-001]\n"
        ),
        "d.md": (
            "---\n"
            "id: DEC-001\n"
            "type: decision\n"
            "title: A decision\n"
            "satisfies: [REQ-001]\n"
            "---\n\nBody prose with a --- inside it.\n"
        ),
    })

    assert _dup_errors(project) == []
    assert project.duplicate_key_files == set()
    assert sorted(project.items_by_id) == ["DEC-001", "REQ-001", "REQ-002"]


def test_a_merged_entry_names_the_item_it_ate(tmp_path):
    """The shape from the report: deleting a list entry's opening `- key:`
    line takes the `- ` marker with it, so the entry's remaining fields merge
    into the entry above. Both repeats are reported, the vanished id is named
    as dropped, and the only other trace -- the reference the vanished id left
    dangling -- is still reported on top."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "defaults:\n"
            "  type: requirement\n"
            "  prefix: REQ\n"
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
            "  - id: REQ-002\n"
            "    text: two\n"
            "    id: REQ-003\n"
            "    text: three\n"
        ),
        "d.md": (
            "---\n"
            "id: DEC-001\n"
            "type: decision\n"
            "title: Points at the middle one\n"
            "satisfies: [REQ-002]\n"
            "status: accepted\n"
            "---\n"
        ),
    })

    errors = _dup_errors(project)
    assert [e.message.split(" in one mapping")[0] for e in errors] == [
        "duplicate key 'id'",
        "duplicate key 'text'",
    ]
    assert "REQ-002' is dropped for 'REQ-003'" in errors[0].message
    assert "an 'id:' lost this way is a whole item" in errors[0].message
    # The item that vanished is gone from the model -- which is exactly why
    # this is an error and not a warning.
    assert sorted(project.items_by_id) == ["DEC-001", "REQ-001", "REQ-003"]
    # ...and the dangling reference it leaves behind is still reported, so the
    # diagnostic that explains the cause is not the only one the author sees.
    build_mod.build(project, seal_write=False, reseal=False)
    dangling = [d for d in project.errors if "does not exist" in d.message]
    assert len(dangling) == 1
    assert dangling[0].item_id == "DEC-001"


def test_every_repeat_is_reported_not_just_the_first(tmp_path):
    """A file can lose more than one `- `: two entries merged into one leave
    three `id:` lines, and the author needs to see all of them, not the first
    pair found."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
            "    id: REQ-002\n"
            "    text: two\n"
            "    id: REQ-003\n"
            "    text: three\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 4
    assert [e.line for e in errors] == [4, 5, 6, 7]
    assert "lines 2 and 4" in errors[0].message
    assert "lines 4 and 6" in errors[2].message


def test_a_repeat_inside_a_nested_mapping_is_an_error_too(tmp_path):
    """Not only an item's own top-level keys: any mapping in the file counts,
    including one nested inside a field value. The line numbers are the file's
    own, and the item is still named."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
            "    on_change:\n"
            "      fields:\n"
            "        owner: ignore\n"
            "        owner: log\n"
            "      reason: rotates weekly\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    assert "duplicate key 'owner'" in errors[0].message
    assert "lines 6 and 7" in errors[0].message
    assert errors[0].line == 7
    assert errors[0].item_id == "REQ-001"


def test_a_repeat_in_a_defaults_block_is_reported_as_such(tmp_path):
    """A lost value in `defaults:` is inherited by every item in the file, so
    the message has to say which block it is in rather than leave the author
    hunting for an item that owns it."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "defaults:\n"
            "  type: requirement\n"
            "  prefix: REQ\n"
            "  owner: J. Bin\n"
            "  owner: A. Rivera\n"
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    assert "duplicate key 'owner'" in errors[0].message
    assert "in this file's defaults:" in errors[0].message
    assert "lines 4 and 5" in errors[0].message
    # No item owns it, so nothing is named in the diagnostic's `[...]` slot.
    assert errors[0].item_id is None
    assert _item(project, "REQ-001").fields["owner"] == "A. Rivera"


def test_a_repeat_in_a_flow_mapping_is_reported_as_one_line(tmp_path):
    """A single-line flow mapping puts both occurrences on one line, and
    "(lines 3 and 3)" reads like a bug in the diagnostic rather than in the
    file."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "items:\n"
            "  - {id: REQ-001, text: one, owner: a, owner: b}\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    assert "twice on line 2" in errors[0].message
    assert "'a' is dropped for 'b'" in errors[0].message
    assert errors[0].line == 2


def test_a_repeat_that_says_the_same_thing_twice_is_still_an_error(tmp_path):
    """Nothing is lost when both lines are identical, so the message must not
    claim a loss -- but one of the two lines was not meant to be there, and the
    usual cause (a lost `- `) is still worth naming."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "items:\n"
            "  - id: REQ-001\n"
            "    text: same\n"
            "    text: same\n"
        ),
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    assert "both lines read 'same', so nothing is lost" in errors[0].message


def test_a_repeat_in_markdown_front_matter_is_an_error(tmp_path):
    """The Markdown half of the same rule, with the block's own line numbers:
    a front-matter block is parsed as text of its own, so a mark inside it is
    relative to the block and has to be shifted back onto the file."""
    project = _dup_project(tmp_path, {
        "d.md": (
            "---\n"
            "id: DEC-001\n"
            "type: decision\n"
            "title: First title\n"
            "title: Second title\n"
            "status: accepted\n"
            "satisfies: [REQ-001]\n"
            "---\n\nBody.\n"
        ),
        "r.yaml": "items:\n  - id: REQ-001\n    text: one\n",
    })

    errors = _dup_errors(project)
    assert len(errors) == 1
    assert "duplicate key 'title'" in errors[0].message
    assert "lines 4 and 5" in errors[0].message
    assert errors[0].file == "items/d.md"
    assert errors[0].line == 5
    assert errors[0].item_id == "DEC-001"
    # The Markdown remedy is the Markdown one: there is no `- ` marker to lose.
    assert "'- key:'" not in errors[0].message
    assert "front matter" in errors[0].message
    assert project.duplicate_key_files == {"items/d.md"}


def test_a_repeat_in_a_merge_key_is_not_a_repeat(tmp_path):
    """`<<:` merges an anchor into the mapping and is not itself one of the
    mapping's keys; checking after PyYAML flattened it would call the
    anchored keys duplicates of the explicit ones. Anchors are undocumented
    for item files, so this is a guard against a false positive, not a
    feature."""
    project = _dup_project(tmp_path, {
        "r.yaml": (
            "items:\n"
            "  - id: REQ-001\n"
            "    text: one\n"
            "    on_change: &h\n"
            "      mode: invalidate\n"
            "  - id: REQ-002\n"
            "    text: two\n"
            "    on_change:\n"
            "      <<: *h\n"
            "      mode: log\n"
        ),
    })

    assert _dup_errors(project) == []
    assert project.duplicate_key_files == set()
