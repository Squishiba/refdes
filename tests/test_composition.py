"""Composition: a set is a type-spec fragment carrying fields, links and body.

docs/design/composition.md. The merge rule (§2): sets merge in include-list
order, later wins; the type's own declaration merges last and wins; every
merge is by-name with whole-spec replacement. Two *sets* fighting is loud
(§6.1); the type outvoting a set it names is documented behavior, not an
error -- except when a set contributes nothing that survives, which warns
(§6.3).

The two tests §6.3 tied to `extends:` (`test_extends_naming_a_set_is_an_error`,
`test_extends_and_include_together_own_declaration_wins`) ride the extends
engine and sit at the end of this file.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import standards
from refdes.schema import SchemaError, load_project

BASE_TYPE = (
    "types:\n"
    "  note:\n"
    "    prefix: NTE\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
)


def _load(tmp_path, schema: str):
    write_project_config(tmp_path, "site: { title: T, out: _site }\n" + schema)
    return load_project(config_path=str(tmp_path / "refdes-project.yaml"))


# ------------------------------------------------------- include carries more


def test_include_carries_links(tmp_path):
    project = _load(
        tmp_path,
        "link_types:\n"
        "  refines: { inverse: refined_by }\n"
        "sets:\n"
        "  tracked:\n"
        "    links:\n"
        "      refines: [note]\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [tracked]\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n",
    )
    assert project.types["note"].links["refines"] == ["note"]


def test_include_carries_body(tmp_path):
    project = _load(
        tmp_path,
        "sets:\n"
        "  strict:\n"
        "    body: { required: true, on_change: invalidate }\n"
        + BASE_TYPE.replace(
            "prefix: NTE\n", "prefix: NTE\n    include: [strict]\n"
        ),
    )
    note = project.types["note"]
    assert note.body_required is True
    assert note.body_on_change == "invalidate"


def test_type_own_body_beats_included_body_wholesale(tmp_path):
    """Whole-spec replacement, not a key merge: the type's `body:` drops the
    set's `required: true` even though it only mentions `on_change:`."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  strict:\n"
        "    body: { required: true, on_change: invalidate }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [strict]\n"
        "    body: { on_change: log }\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n",
    )
    note = project.types["note"]
    assert note.body_on_change == "log"
    assert note.body_required is False


def test_two_sets_same_verb_identical_targets_is_fine(tmp_path):
    project = _load(
        tmp_path,
        "link_types:\n"
        "  refines: { inverse: refined_by }\n"
        "sets:\n"
        "  a:\n"
        "    links: { refines: [note] }\n"
        "  b:\n"
        "    links: { refines: [note] }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [a, b]\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n",
    )
    assert project.types["note"].links["refines"] == ["note"]


# ------------------------------------------------------- sets fighting is loud


def test_two_sets_same_verb_different_targets_is_an_error(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "link_types:\n"
            "  refines: { inverse: refined_by }\n"
            "sets:\n"
            "  a:\n"
            "    links: { refines: [note] }\n"
            "  b:\n"
            "    links: { refines: [other] }\n"
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    include: [a, b]\n"
            "    fields:\n"
            "      title: { type: text, required: true }\n"
            "  other:\n"
            "    prefix: OTH\n"
            "    fields:\n"
            "      title: { type: text, required: true }\n",
        )
    message = str(exc.value)
    assert "both declare link 'refines' with different targets" in message
    assert "declare 'refines' once, on the type" in message


def test_two_sets_different_body_is_an_error(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  a:\n"
            "    body: { required: true }\n"
            "  b:\n"
            "    body: { required: false }\n"
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    include: [a, b]\n"
            "    fields:\n"
            "      title: { type: text, required: true }\n",
        )
    message = str(exc.value)
    assert "both declare body with different specs" in message
    assert "declare body on the type instead" in message


# --------------------------------------------------- doc-only field patches


def test_doc_only_field_patch_inherits_the_rest(tmp_path):
    """A spec whose only key is `doc:` patches the included definition's doc
    and inherits everything else (docs/design/composition.md §3)."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      title: { type: text, required: true, on_change: log, default: t }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields:\n"
        '      title: { doc: "Type-specific wording." }\n',
    )
    title = project.types["note"].fields["title"]
    assert title.doc == "Type-specific wording."
    assert title.type == "text"
    assert title.required is True
    assert title.on_change == "log"
    assert title.default == "t"


def test_field_patch_with_semantic_key_is_an_error(tmp_path):
    """Some semantic keys but no `type:` is neither a patch nor a full
    definition -- it must be named, not defaulted to text."""
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  common:\n"
            "    fields:\n"
            "      title: { type: text, required: true }\n"
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    include: [common]\n"
            "    fields:\n"
            "      title: { required: false }\n",
        )
    message = str(exc.value)
    assert "overrides an included field but is neither a full definition" in message
    assert "nor a doc-only patch" in message
    assert "keys given: required" in message


def test_doc_only_patch_does_not_make_the_set_shadowed(tmp_path):
    """A set whose only field is doc-patched still contributed -- the patch
    inherits its type and policy -- so the total-shadow warning stays quiet."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      title: { type: text }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields:\n"
        '      title: { doc: "Type-specific wording." }\n',
    )
    assert not any(
        "contributes nothing" in d.message for d in project.warnings
    )


# ------------------------------------------------- a set is not a type


def test_set_declaring_include_is_an_error(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  a:\n"
            "    include: [b]\n"
            "    fields: { title: { type: text } }\n"
            "  b:\n"
            "    fields: { body: { type: text } }\n"
            + BASE_TYPE,
        )
    assert "sets.a may not declare 'include'" in str(exc.value)
    assert "a set carries fields, links and body only" in str(exc.value)


@pytest.mark.parametrize("key", ["coverable", "prefix"])
def test_set_declaring_type_identity_is_an_error(tmp_path, key):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  a:\n"
            f"    {key}: true\n"
            "    fields: { title: { type: text } }\n"
            + BASE_TYPE,
        )
    assert f"sets.a may not declare {key!r}" in str(exc.value)


def test_set_name_colliding_with_type_name_is_an_error(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  note:\n"
            "    fields: { extra: { type: text } }\n"
            + BASE_TYPE,
        )
    assert "sets.note collides with types.note" in str(exc.value)
    assert "a name may be a type or a set, not both" in str(exc.value)


# ------------------------------------------- sets confer no substitutability


def test_including_a_set_confers_no_substitutability(tmp_path):
    """Two types sharing a set are no more interchangeable than two types
    that happen to have the same fields: a link target list naming one still
    rejects the other (docs/design/composition.md §6.3)."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "link_types:\n"
        "  refines: { inverse: refined_by }\n"
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    links:\n"
        "      refines: [note]\n"
        "  other:\n"
        "    prefix: OTH\n"
        "    include: [common]\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: note, prefix: NTE }\n"
        "items:\n"
        "  - id: NTE-001\n"
        "    title: A note\n"
        "    refines: [OTH-001]\n",
        encoding="utf-8",
    )
    (items / "o.yaml").write_text(
        "defaults: { type: other, prefix: OTH }\n"
        "items:\n"
        "  - id: OTH-001\n"
        "    title: An other\n",
        encoding="utf-8",
    )
    project = _build_at(tmp_path)
    assert any(
        "may point at" in d.message and "OTH-001" in d.message
        for d in project.errors
    ), [d.message for d in project.errors]


# ------------------------------------------------------- the shadow warning


def test_include_contributing_nothing_warns(tmp_path):
    """The type redeclares the set's only field with a different spec: the
    include is dead weight, and the build says so without stopping."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      title: { type: text }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n",
    )
    messages = [d.message for d in project.warnings]
    assert any(
        "set 'common' contributes nothing that survives the merge" in m
        for m in messages
    ), messages


def test_partial_shadow_does_not_warn(tmp_path):
    """One field shadowed, one surviving: the include still earns its place."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      title: { type: text }\n"
        "      extra: { type: text }\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n",
    )
    assert "extra" in project.types["note"].fields
    assert not any(
        "contributes nothing" in d.message for d in project.warnings
    )


# ------------------------------------------------------- with `extends:`


def test_extends_naming_a_set_is_an_error(tmp_path):
    """A set is a shareable fragment, not a type: `extends:` names a type
    (composition.md §5, §6.1 item 5)."""
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  common:\n"
            "    fields:\n"
            "      title: { type: text }\n"
            "types:\n"
            "  note:\n"
            "    extends: common\n"
            "    prefix: NTE\n"
            "    label: Note\n"
            "    plural: Notes\n",
        )
    assert (
        "types.note.extends names 'common', which is a set, not a type; "
        "sets are shareable fragments -- extends names a type"
    ) in str(exc.value)


def test_extends_and_include_together_own_declaration_wins(tmp_path, monkeypatch):
    """The four layers of composition.md §4, weakest to strongest -- the
    parent, the included sets, the type's own declaration, and an overlay edit
    to the parent (which lands in the parent's layer for its children, not as a
    fifth voice) -- each with its winner asserted on one child."""
    root = tmp_path / "std" / "hardware" / "v1"
    root.mkdir(parents=True)
    (root / "base.yaml").write_text(
        "link_types:\n"
        "  refines: { inverse: refined_by }\n"
        "sets:\n"
        "  s:\n"
        "    fields:\n"
        "      b: { type: text, doc: from the set }\n"
        "      c: { type: text, doc: from the set }\n"
        "types:\n"
        "  p:\n"
        "    prefix: PAR\n"
        "    label: Parent\n"
        "    plural: Parents\n"
        "    fields:\n"
        "      a: { type: text, doc: from the parent }\n"
        "      b: { type: text, doc: from the parent }\n"
        "      c: { type: text, doc: from the parent }\n"
        "      e: { type: text, doc: from the parent }\n"
        "    links:\n"
        "      refines: [p]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(standards, "_STANDARDS_ROOT", str(tmp_path / "std"))
    project = _load(
        tmp_path,
        "standard: { base: hardware, version: 1 }\n"
        "types:\n"
        "  p:\n"
        "    fields:\n"
        "      d: { type: text, doc: added to the parent by the overlay }\n"
        "      e: { type: text, doc: the overlay edited the parent }\n"
        "  k:\n"
        "    extends: p\n"
        "    include: [s]\n"
        "    prefix: KID\n"
        "    label: Kid\n"
        "    plural: Kids\n"
        "    fields:\n"
        "      c: { type: text, doc: the type's own }\n",
    )
    fields = project.types["k"].fields
    assert fields["a"].doc == "from the parent"  # only the parent speaks
    assert fields["b"].doc == "from the set"  # a set beats the parent
    assert fields["c"].doc == "the type's own"  # the type beats set and parent
    assert fields["d"].doc == "added to the parent by the overlay"  # parent layer
    assert fields["e"].doc == "the overlay edited the parent"  # overlay edit reaches the child
    assert project.types["k"].links["refines"] == ["p"]
    # The parent's own resolved spec is untouched by its child.
    assert project.types["p"].fields["b"].doc == "from the parent"
