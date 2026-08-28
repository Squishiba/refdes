"""misspelled link keys.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import pytest
from helpers import COVERAGE_SCHEMA

from refdes import build as build_mod
from refdes import parse
from refdes.schema import load_project

# --------------------------------------------------------- misspelled link keys


TYPO_LINK_ITEMS = {
    "req-a.md": """\
---
id: REQ-A-001
type: requirement
text: Needs a decision.
---
""",
    "dec-a.md": """\
---
id: DEC-A-001
type: decision
title: Typo'd the link name.
status: accepted
sattisfies: [REQ-A-001]
---
""",
}


@pytest.fixture
def typo_link_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    for name, text in TYPO_LINK_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_misspelled_link_key_errors_instead_of_silently_dropping(typo_link_project):
    """`sattisfies:` must fail the build, not warn while quietly losing the edge (#1 P1-3)."""
    project = load_project(config_path=str(typo_link_project / "refdes.yaml"))
    parse.load_items(project)

    assert any(
        "sattisfies" in d.message and "satisfies" in d.message for d in project.errors
    )
    assert not any("sattisfies" in d.message for d in project.warnings)
    # The edge really is dropped -- that's exactly why this must be an error.
    assert project.items["DEC-A-001"].links == {}


def test_constraint_title_renamed_to_text_gives_a_specific_diagnostic(tmp_path):
    """Finding 4: an item declaring `constraint.title` where the schema wants
    `constraint.text` gets one diagnostic naming the rename -- not the generic
    unknown-field warning plus an unrelated-looking missing-required error a
    plain rename would otherwise produce.

    Against a hand-rolled schema, deliberately. The bundled standard reached
    this shape at the old v2 and left it again at the old v3, which renamed
    the type itself; now that those are collapsed into one version, no pinned
    standard has a `constraint` type wanting `text`, and a standard project
    that hasn't migrated gets the *type* rename diagnostic instead (below).
    The field table stays, because a hand-rolled schema in this shape is
    exactly the other case its docstring says it covers."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  constraint:\n"
        "    prefix: CON\n"
        "    fields:\n"
        "      text:  { type: text, required: true }\n"
        "      limit: { type: limit, required: true }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n    type: constraint\n    title: Old-style constraint.\n"
        '    limit: "<= 1 W"\n',
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    rename_errors = [
        d for d in project.errors
        if "constraint.title" in d.message and "constraint.text" in d.message
    ]
    assert len(rename_errors) == 1
    assert rename_errors[0].item_id == "CON-001"

    # Exactly this one diagnostic -- not the generic pair a plain rename would
    # otherwise produce.
    assert not any("unknown field 'title'" in d.message for d in project.warnings)
    assert not any("missing required field 'text'" in d.message for d in project.errors)

    # The old value is used for the new field, so nothing downstream cascades
    # into a confusing secondary failure.
    assert project.items["CON-001"].fields["text"] == "Old-style constraint."


def test_constraint_title_on_hardware_v1_is_unaffected(tmp_path):
    """v1 is untouched: title: is still constraint's real field there, so the
    rename diagnostic must not fire -- confirming it's scoped to schemas
    where the rename actually applies, not fired unconditionally by type
    name alone."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 1, presets: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - id: CON-001\n    type: constraint\n    title: A constraint.\n"
        '    limit: "<= 1 W"\n',
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["CON-001"].fields["title"] == "A constraint."


def test_unrecognized_field_far_from_any_link_still_only_warns(tmp_path):
    """A genuine unknown field with no close link name must keep warning, not error."""
    (tmp_path / "refdes.yaml").write_text(COVERAGE_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-a.md").write_text(
        """\
---
id: DEC-A-001
type: decision
title: Has a genuinely unrelated field.
status: accepted
completely_unrelated_nonsense: yes
---
""",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)

    assert any("completely_unrelated_nonsense" in d.message for d in project.warnings)
    assert not any("completely_unrelated_nonsense" in d.message for d in project.errors)
