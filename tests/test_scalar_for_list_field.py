"""A scalar written for a list-shaped field is a build error, not a value.

`in-prog-logs/user-sim-release-gate-run1.md` §2, finding F2. The exact repro:

    - id: CMP-010
      title: Part with SCALAR tags
      tags: "power, analog"     # meant to be two tags

`refdes check` reported `0 errors, 0 warnings`, exit 0, and the stored value
was the *single* tag `"power, analog"` -- confirmed through the API, which
returns `["power, analog"]` where the list form returns `["power", "analog"]`.
Nothing in the build could tell the two apart, and neither could a newcomer:
`refdes ls --tag analog` still found the item, because tag matching is a
substring test, so the wrong value looked right everywhere it could be looked
at.

The editor's create path already refused the same field on the same value
(`serve/edit.py::_creation_fields`); the loader had no equivalent, and that
disagreement was the bug. One constant, `model.NON_SCALAR_FIELD_TYPES`, is now
the single list of list-shaped field types both halves consult.

Refusing rather than splitting on a comma is the point, not a shortcut: a
delimiter guess is right for `"power, analog"` and silently wrong for a tag
that legitimately contains a comma. A scalar link target (`satisfies: REQ-001`)
is a *different* case and stays lenient -- one target is one edge, and nothing
is lost -- pinned by `test_scalar_link_target_still_creates_one_link` so a
future sweep at "scalars" can't take it with it.
"""

from __future__ import annotations

from conftest import write_project_config
from helpers import _build_at

from refdes import cli as cli_mod
from refdes import parse
from refdes.model import NON_SCALAR_FIELD_TYPES
from refdes.schema import load_project

# A hand-rolled schema, so the `tags` field's `type: list` is the fixture's own
# declaration rather than the bundled standard's -- the check reads
# `FieldSpec.type`, not the name, and this proves it.
SCHEMA = """\
site: { title: "Scalar tags", out: _site }
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title: { type: text, required: true }
      tags: { type: list, on_change: ignore }
      candidates: { type: list, on_change: ignore }
    links:
      satisfies: [requirement]
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: { type: text, required: true }
    links: {}
"""

SCALAR_TAGS = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: Part with SCALAR tags\n"
    '    tags: "power, analog"\n'
)

LIST_TAGS = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-011\n"
    "    title: Part with LIST tags\n"
    "    tags: [power, analog]\n"
)

SCALAR_CANDIDATES = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: A part\n"
    "    candidates: 3.3\n"
)

MAPPING_TAGS = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: A part\n"
    "    tags: {primary: power}\n"
)

BARE_NULL_TAGS = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: A part\n"
    "    tags:\n"
)

SCALAR_TAGS_IN_DEFAULTS = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    '  tags: "power, analog"\n'
    "\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: Inherits its tags\n"
    "  - id: CMP-011\n"
    "    title: Inherits them too\n"
)

LIST_TAGS_IN_DEFAULTS = (
    "defaults:\n"
    "  type: component\n"
    "  prefix: CMP\n"
    "  tags: [power]\n"
    "\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: Inherits a real list\n"
    "  - id: CMP-011\n"
    "    title: Brings its own\n"
    "    tags: [analog]\n"
)

SCALAR_TAGS_IN_MARKDOWN = (
    "---\n"
    "id: CMP-010\n"
    "type: component\n"
    "title: Part with SCALAR tags\n"
    'tags: "power, analog"\n'
    "---\n"
)

ONE_REQUIREMENT = (
    "defaults: { type: requirement, prefix: REQ }\n"
    "items:\n"
    "  - id: REQ-001\n"
    "    text: A requirement.\n"
)

SCALAR_LINK_TARGET = (
    "defaults: { type: component, prefix: CMP }\n"
    "items:\n"
    "  - id: CMP-010\n"
    "    title: A part\n"
    "    satisfies: REQ-001\n"
)


def _project(tmp_path, *files: tuple[str, str]):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in files:
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])


# ------------------------------------------------------------- the exact repro


def test_scalar_where_a_list_belongs_is_a_build_error(tmp_path, capsys):
    """F2 verbatim. Before the fix this printed `2 items, 0 errors, 0 warnings`
    and exited 0; the value silently became the one tag `"power, analog"`."""
    root = _project(tmp_path, ("cmp.yaml", SCALAR_TAGS))
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "items/cmp.yaml:3" in err
    assert "CMP-010" in err
    # Names the field, its declared type, and what was actually found.
    assert "field 'tags' is a list field" in err
    assert "a string 'power, analog'" in err


def test_the_stored_value_is_never_silently_split_or_wrapped(tmp_path):
    """The value is still loaded, unchanged, so downstream code has something
    to read while the build is red -- but nothing pretends the scalar was a
    list of two. What the check *forbids* is the silent part: the build
    reporting zero problems while holding the wrong value."""
    root = _project(tmp_path, ("cmp.yaml", SCALAR_TAGS))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    item = next(i for i in project.local_items if i.id == "CMP-010")
    assert item.fields["tags"] == "power, analog"  # not ["power", "analog"]
    assert [d for d in project.errors if "list field" in d.message]


def test_the_list_form_still_builds_green(tmp_path, capsys):
    """The other half of the pair, and the reason the error is a good one: the
    same project written the way the schema declares builds with no
    diagnostics at all."""
    root = _project(tmp_path, ("cmp.yaml", LIST_TAGS))
    assert _check(root) == 0
    assert "0 errors" in capsys.readouterr().out


# -------------------------------------------------------------- other shapes


def test_a_scalar_on_any_list_shaped_field_is_refused(tmp_path):
    """Not a `tags` special case: the check reads `FieldSpec.type`, so a second
    list-typed field on the same type is caught the same way."""
    root = _project(tmp_path, ("cmp.yaml", SCALAR_CANDIDATES))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    errors = [d for d in project.errors if "list field" in d.message]
    assert len(errors) == 1
    assert "field 'candidates' is a list field" in errors[0].message
    assert "a number 3.3" in errors[0].message


def test_a_mapping_written_for_a_list_field_is_refused_too(tmp_path):
    """`tags:` is not the only non-list YAML shape; a mapping is the other one
    a hand edit produces, and it is just as much a collection-shaped mistake."""
    root = _project(tmp_path, ("cmp.yaml", MAPPING_TAGS))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    assert [d for d in project.errors if "a mapping" in d.message]


def test_a_bare_null_is_still_the_existing_explicit_null_case(tmp_path):
    """A bare `tags:` is YAML null, and null is not a scalar the author typed
    a value into -- the existing explicit-null diagnostic owns it (it becomes
    the field's default, with a warning). Reporting the same keystroke twice
    would help nobody, so this check stays out of its way."""
    root = _project(tmp_path, ("cmp.yaml", BARE_NULL_TAGS))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    assert not [d for d in project.errors if "list field" in d.message]


# ------------------------------------------------------------------ defaults


def test_a_scalar_inherited_from_defaults_is_reported_at_the_defaults_block(tmp_path):
    """A `defaults:` entry is a value too, and the line the author has to edit
    is the defaults block's -- not whichever item happened to be diagnosed
    first, which is the item's own line."""
    root = _project(tmp_path, ("cmp.yaml", SCALAR_TAGS_IN_DEFAULTS))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    errors = [d for d in project.errors if "list field" in d.message]
    assert len(errors) == 2  # every item that inherits it is broken
    # The defaults: block's own first key line -- the same line the loader
    # reports for a dead defaults entry -- not either item's own line, since
    # the key the author has to edit is up there and not in the item.
    assert {d.line for d in errors} == {2}
    assert {d.item_id for d in errors} == {"CMP-010", "CMP-011"}


def test_an_item_may_override_a_list_valued_default_with_its_own_list(tmp_path):
    """The ordinary defaults: contract, still intact -- a per-item list is a
    list, and only the defaults entry is wrong."""
    root = _project(tmp_path, ("cmp.yaml", LIST_TAGS_IN_DEFAULTS))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    assert not project.errors


# ------------------------------------------------------------- markdown form


def test_the_markdown_form_is_checked_too(tmp_path):
    """Front-matter items reach the same merge, so the same value written in a
    .md file fails the same way -- this is one check in the loader, not one
    per serialization."""
    root = _project(tmp_path, ("cmp.md", SCALAR_TAGS_IN_MARKDOWN))
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    errors = [d for d in project.errors if "list field" in d.message]
    assert len(errors) == 1
    # Item-granular, like every other parse diagnostic: the front-matter
    # block's first line, not the `tags:` key's own line inside it.
    assert errors[0].line == 2
    assert errors[0].item_id == "CMP-010"


# ------------------------------------------------- links stay lenient (on purpose)


def test_scalar_link_target_still_creates_one_link(tmp_path):
    """`satisfies: REQ-001` as a bare scalar is *not* this bug. A link verb
    takes a list of targets, and a scalar names exactly one of them: one
    target in, one edge out, nothing lost and nothing misread. The report
    called this leniency intentional, and it stays -- this test exists so that
    widening the loader's scalar check to links would fail here rather than
    quietly ship."""
    root = _project(tmp_path, ("req.yaml", ONE_REQUIREMENT), ("cmp.yaml", SCALAR_LINK_TARGET))
    project = _build_at(root)
    assert not project.errors
    item = next(i for i in project.local_items if i.id == "CMP-010")
    # resolved_links, not raw links: what a graph consumer reads, and the one
    # thing here that proves the edge is a real resolved reference rather than
    # text that merely looks like one.
    assert item.resolved_links["satisfies"] == ["REQ-001"]


# ------------------------------------------------- one constant, two callers


def test_the_editor_and_the_loader_share_one_constant():
    """The bug was two halves of the tool disagreeing about the same set, so
    the set itself is asserted here rather than re-derived: `serve.edit` and
    `serve.api` both name this exact object, and it is the one the loader
    consults. A second, hand-maintained copy is what this test rules out."""
    from refdes.serve import api as api_mod
    from refdes.serve import edit as edit_mod

    assert edit_mod.NON_SCALAR_FIELD_TYPES is NON_SCALAR_FIELD_TYPES
    assert api_mod.NON_SCALAR_FIELD_TYPES is NON_SCALAR_FIELD_TYPES
    # An unknown type name in the set would make the loader's check dead code:
    # it compares `fspec.type` against exactly these.
    assert NON_SCALAR_FIELD_TYPES == {"list", "checks", "citations", "options"}
