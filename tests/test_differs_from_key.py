"""The `differs_from:` disambiguation key (docs/design/vocabulary-review.md P20).

A vocabulary term -- a type, a field, a link verb -- can carry, next to its
`doc:`, one sentence per confusable neighbour saying how the two differ:

    types:
      note:
        prefix: NTE
        doc: A short prose note.
        differs_from:
          bound: a note states nothing numeric; a bound is a checkable number.

The shape is a non-empty mapping of term name to a non-empty sentence, in the
bundled standard and in a project's `refdes-schema.yaml` alike; anything else
is a configuration error naming the block path (the `doc:` posture). A named
term that does not resolve in the *resolved* standard -- to a type, a link
verb under its own or its inverse name, a set, or a field of the same type --
is a load-time error too, the established posture for dangling references in
standard definitions (`include:`, `extends:`, link targets, `required_when:`).

The generated vocabulary page renders each pair as a fact line, linking the
other term when it has an entry on the page; a field's line appears under its
definition in the type's fields table. A project that declares none is
byte-identical to before the key existed, in the page and in the exports.
"""

from __future__ import annotations

import json
import os

import pytest
from conftest import write_project_config
from helpers import REPO

from refdes import schema_json as schema_json_mod
from refdes import vocabulary
from refdes.model import SchemaError
from refdes.schema import load_project

BASE = """\
site: {title: T, out: _site}
id: {width: 3}
on_change: {default: invalidate}
units: {preferred: []}
"""


def _load(tmp_path, schema: str):
    write_project_config(tmp_path, BASE + schema)
    return load_project(start=str(tmp_path))


DEFAULT_NOTE_FIELDS = "    fields:\n      title: {type: text}\n    links: {}\n"


def _schema(
    note_extra: str = "",
    bound_extra: str = "",
    tracks_extra: str = "",
    note_fields: str = DEFAULT_NOTE_FIELDS,
) -> str:
    """Two plain types and a verb; each hook appends lines *inside* its own
    entry (one mapping per key -- a repeated key in one file is itself a
    configuration error now, so tests never write two `note:` blocks)."""
    return (
        "link_types:\n"
        "  tracks:\n"
        "    inverse: tracked_by\n"
        "    doc: Points at the entry recording this.\n"
        + tracks_extra
        + "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    doc: A short prose note.\n"
        + note_extra
        + note_fields
        + "  bound:\n"
        "    prefix: BND\n"
        "    doc: A checkable number.\n"
        + bound_extra
        + "    fields:\n      limit: {type: limit}\n"
        "    links: {}\n"
    )


def _load_vocab(tmp_path, schema: str):
    write_project_config(tmp_path, BASE + schema)
    return load_project(start=str(tmp_path))


# ------------------------------------------------------- accepted in an overlay


def test_differs_from_accepted_on_a_type(tmp_path):
    project = _load(
        tmp_path,
        _schema(note_extra="    differs_from:\n      bound: a note is prose; a bound is a checkable number.\n"),
    )
    assert project.types["note"].differs_from == {
        "bound": "a note is prose; a bound is a checkable number."
    }
    # Everything else about the type is untouched.
    assert project.types["note"].doc == "A short prose note."


def test_differs_from_accepted_on_a_field(tmp_path):
    project = _load(
        tmp_path,
        _schema(
            note_fields="    fields:\n"
            "      title:\n"
            "        type: text\n"
            "        differs_from:\n"
            "          bound: the title labels; a bound is an item.\n"
            "    links: {}\n",
        ),
    )
    assert project.types["note"].fields["title"].differs_from == {
        "bound": "the title labels; a bound is an item."
    }


def test_differs_from_accepted_on_a_link_verb(tmp_path):
    project = _load(
        tmp_path,
        _schema(
            tracks_extra="    differs_from:\n"
            "      tracked_by: the verb points out; the inverse names what points back.\n"
        ),
    )
    assert project.link_types["tracks"].differs_from == {
        "tracked_by": "the verb points out; the inverse names what points back."
    }


def test_differs_from_on_a_set_field_rides_into_the_includer(tmp_path):
    """A set's fields are field specs, so the note is written once and every
    including type carries it -- the `doc:` pattern."""
    project = _load(
        tmp_path,
        "sets:\n"
        "  common:\n"
        "    fields:\n"
        "      caption:\n"
        "        type: text\n"
        "        differs_from:\n"
        "          note: the caption labels; the item itself is the thing.\n"
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    include: [common]\n"
        "    fields: {title: {type: text}}\n"
        "    links: {}\n",
    )
    assert project.types["note"].fields["caption"].differs_from == {
        "note": "the caption labels; the item itself is the thing."
    }


def test_a_type_without_differs_from_is_unchanged(tmp_path):
    project = _load(tmp_path, _schema())
    assert project.types["note"].differs_from == {}
    assert project.types["bound"].fields["limit"].differs_from == {}
    assert project.link_types["tracks"].differs_from == {}


def test_a_subtype_never_inherits_its_parents_differs_from(tmp_path):
    """Like `doc:`, the note belongs to the term that wrote it -- inheriting
    it would put the parent's sentence on the subtype's page entry."""
    project = _load(
        tmp_path,
        "types:\n"
        "  note:\n"
        "    prefix: NTE\n"
        "    fields: {title: {type: text}}\n"
        "    differs_from:\n"
        "      other: the note's own sentence.\n"
        "  other:\n"
        "    prefix: OTH\n"
        "    fields: {title: {type: text}}\n"
        "  subnote:\n"
        "    extends: note\n"
        "    prefix: SUB\n"
        "    label: Subnote\n"
        "    plural: Subnotes\n"
        "    fields: {title: {type: text}}\n",
    )
    assert project.types["note"].differs_from == {"other": "the note's own sentence."}
    assert project.types["subnote"].differs_from == {}


# ------------------------------------------------------------- shape errors


@pytest.mark.parametrize(
    "value",
    ["42", "[a, b]", "{}", '"  "', "true"],
    ids=["int", "list", "empty", "whitespace", "bool"],
)
def test_differs_from_must_be_a_non_empty_mapping(tmp_path, value):
    with pytest.raises(SchemaError) as exc:
        _load(tmp_path, _schema(note_extra=f"    differs_from: {value}\n"))
    assert "types.note.differs_from" in str(exc.value)


def test_a_bad_sentence_names_the_pair(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            _schema(note_extra="    differs_from: {other: 42}\n"),
        )
    assert "types.note.differs_from.other" in str(exc.value)
    assert "non-empty sentence" in str(exc.value)
    # ... and a did-you-mean on the dangling neighbour name is the same
    # file's business, not this sentence's: `other` does not exist here.


def test_a_bad_differs_from_on_a_field_names_the_field(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    fields:\n"
            "      title: {type: text, differs_from: [a]}\n",
        )
    assert "types.note.fields.title.differs_from" in str(exc.value)


def test_a_bad_differs_from_on_a_link_verb_names_the_verb(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            _schema(tracks_extra="    differs_from: 42\n"),
        )
    assert "link_types.tracks.differs_from" in str(exc.value)


def test_a_bad_differs_from_on_a_set_field_names_the_set(tmp_path):
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            "sets:\n"
            "  common:\n"
            "    fields:\n"
            "      title: {type: text, differs_from: 42}\n"
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    include: [common]\n"
            "    fields: {title: {type: text}}\n"
            "    links: {}\n",
        )
    assert "sets.common.fields.title.differs_from" in str(exc.value)


# --------------------------------------------------- dangling terms are errors


def test_a_dangling_term_is_a_configuration_error(tmp_path):
    """Precedent: `include:`, `extends:`, link targets and `required_when:`
    all make a dangling reference in a resolved standard definition a load
    error naming both sides -- differs_from matches that posture, it does not
    merely warn."""
    with pytest.raises(SchemaError) as exc:
        _load(
            tmp_path,
            _schema(note_extra="    differs_from: {nogterm: nothing with this name exists}\n"),
        )
    message = str(exc.value)
    assert "types.note.differs_from" in message
    assert "nogterm" in message
    assert "not a declared" in message


def test_a_dangling_term_in_a_verb_and_in_a_field_is_caught(tmp_path):
    for schema, needle in (
        (_schema(tracks_extra="    differs_from: {nothere: x}\n"),
         "link_types.tracks.differs_from"),
        (
            "types:\n"
            "  note:\n"
            "    prefix: NTE\n"
            "    fields:\n"
            "      title: {type: text, differs_from: {nothere: x}}\n",
            "types.note.fields.title.differs_from",
        ),
    ):
        with pytest.raises(SchemaError) as exc:
            _load(tmp_path, schema)
        assert needle in str(exc.value)


def test_a_term_deleted_by_an_override_is_still_dangling(tmp_path):
    """Validation runs on the resolved schema, so a reference that resolves
    against the bundle is caught once the override deletes the term -- the
    same after-merge posture as `_validate_link_targets`. `test` is chosen
    because no bundle link list names it, so the load error here is this
    check's, not the link-target check's."""
    write_project_config(
        tmp_path,
        BASE
        + "standard: {base: hardware, version: 3}\n"
        "types:\n"
        "  test: null\n"
        "  note:\n"
        "    prefix: NOT\n"
        "    fields: {title: {type: text}}\n"
        "    differs_from:\n"
        "      test: prose, not a verification.\n",
    )
    with pytest.raises(SchemaError) as exc:
        load_project(start=str(tmp_path))
    assert "types.note.differs_from" in str(exc.value)
    assert "test" in str(exc.value)


def test_inverse_names_and_own_fields_resolve(tmp_path):
    """A verb may name its own inverse (it is how readers meet the edge from
    the other end); a type may name a field declared on itself -- the
    bound/limit case the bundled standard uses."""
    project = _load(
        tmp_path,
        _schema(
            tracks_extra="    differs_from: {tracked_by: \"same edge, seen from the other end\"}\n",
            bound_extra="    differs_from:\n      limit: the bound is the item; the limit is the comparison on it.\n",
        ),
    )
    assert project.link_types["tracks"].differs_from == {
        "tracked_by": "same edge, seen from the other end"
    }
    assert "limit" in project.types["bound"].differs_from


# ------------------------------------------------------------- the page


def test_a_term_fact_line_links_the_other_term_in_html(tmp_path):
    project = _load_vocab(
        tmp_path,
        _schema(note_extra="    differs_from:\n      bound: a note is prose; a bound is a checkable number.\n"),
    )
    html = vocabulary.render_html(project)
    block = html[html.index('id="term-note"'):]
    assert "<dt>Differs from</dt>" in block
    assert '<a href="#term-bound"><code>bound</code></a>' in block
    assert "a note is prose; a bound is a checkable number." in block


def test_a_field_fact_line_links_the_page_term(tmp_path):
    project = _load_vocab(
        tmp_path,
        _schema(
            note_fields="    fields:\n"
            "      title:\n"
            "        type: text\n"
            "        differs_from:\n"
            "          bound: the title labels; the bound is an item.\n"
            "    links: {}\n"
        ),
    )
    html = vocabulary.render_html(project)
    block = html[html.index('id="term-note"'):]
    assert 'Differs from <a href="#term-bound"><code>bound</code></a>' in block


def test_a_type_may_name_its_own_field_without_an_anchor(tmp_path):
    """`limit` is a field, not a page entry: the fact line names it in code
    text and links nothing."""
    project = _load_vocab(
        tmp_path,
        _schema(
            bound_extra="    differs_from:\n"
            "      limit: the bound is the item; the limit is the comparison on it.\n"
        ),
    )
    html = vocabulary.render_html(project)
    block = html[html.index('id="term-bound"'):]
    assert "<dt>Differs from</dt>" in block
    assert "<code>limit</code>: the bound is the item" in block
    assert 'href="#term-limit"' not in block


def test_fact_lines_render_in_markdown(tmp_path):
    project = _load_vocab(
        tmp_path,
        _schema(
            note_extra="    differs_from:\n"
            "      bound: a note is prose; a bound is a checkable number.\n",
            note_fields="    fields:\n"
            "      title:\n"
            "        type: text\n"
            "        doc: The label.\n"
            "        differs_from:\n"
            "          bound: the title labels; the bound is an item.\n"
            "    links: {}\n",
        ),
    )
    md = vocabulary.render_markdown(project)
    assert (
        "- **Differs from `bound`:** a note is prose; a bound is a checkable number."
        in md
    )
    # the field's line lives inside its fields-table row, after its doc
    assert "| `title` | The label. Differs from `bound`: the title labels; the bound is an item. |" in md


def test_a_sentence_with_markup_stays_text(tmp_path):
    project = _load_vocab(
        tmp_path,
        _schema(note_extra="    differs_from:\n      bound: a note holds <script> nothing checkable.\n"),
    )
    html = vocabulary.render_html(project)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------- the bundled pairs


@pytest.fixture(scope="module")
def repo_project():
    return load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))


def test_the_bundled_pairs_are_on_both_generated_pages(repo_project):
    html = vocabulary.render_html(repo_project)
    md = vocabulary.render_markdown(repo_project)
    alt = html[html.index('id="term-alternate"'):]
    alt = alt[: alt.index('id="term-blocked_by"') if 'id="term-blocked_by"' in alt else len(alt)]
    assert '<a href="#term-drop_in"><code>drop_in</code></a>' in alt
    assert "needs checking before it goes in a design" in alt
    assert "<dt>Differs from</dt>" in html[html.index('id="term-bound"'):]
    assert "<code>limit</code>: the bound is the numeric" in html
    assert "**Differs from `drop_in`:**" in md
    assert "**Differs from `limit`:**" in md


def test_the_bundled_pairs_reach_the_schema_json(repo_project):
    doc = schema_json_mod.build_schema(repo_project)
    assert doc["$defs"]["bound__entry"]["differs_from"]["limit"]
    alt = doc["$defs"]["component__entry"]["properties"]["alternate"]
    assert alt["differs_from"]["drop_in"]
    # An unrelated verb is untouched: no annotation key where nothing was written.
    assert "differs_from" not in doc["$defs"]["requirement__entry"]["properties"]["refines"]


# --------------------------------------------------- the bundled-standard path


BUNDLE_BASE = """\
link_types:
  tracks: {inverse: tracked_by, doc: Points at the entry.}
types:
  note:
    prefix: NTE
    doc: A short prose note.
    fields: {title: {type: text}}
  bound:
    prefix: BND
    doc: A checkable number.
    fields: {limit: {type: limit}}
"""


def _bundle_project(tmp_path, monkeypatch, base_yaml: str):
    """A project pinned to a fake bundled standard written in `tmp_path`:
    the bundle path skips `configcheck` entirely (its docstring says so), so
    this is the only way to drive `schema.py`'s own shape check -- the same
    reason `test_schema_doc_key`'s `doc:` has `_doc_text` for this path."""
    root = tmp_path / "bundle" / "hardware" / "v7"
    root.mkdir(parents=True)
    (root / "base.yaml").write_text(base_yaml, encoding="utf-8")
    monkeypatch.setattr("refdes.standards._STANDARDS_ROOT", str(tmp_path / "bundle"))
    write_project_config(tmp_path, BASE + "standard: {base: hardware, version: 7}\n")
    return load_project(start=str(tmp_path))


def test_the_bundle_path_accepts_a_good_block(tmp_path, monkeypatch):
    project = _bundle_project(
        tmp_path,
        monkeypatch,
        BUNDLE_BASE.replace(
            "  note:\n    prefix: NTE",
            "  note:\n    prefix: NTE\n"
            "    differs_from:\n      bound: prose, not a number.",
        ),
    )
    assert project.types["note"].differs_from == {"bound": "prose, not a number."}


@pytest.mark.parametrize(
    "block",
    [
        "    differs_from: 42",
        "    differs_from: {}",
        "    differs_from: {bound: 42}",
        "    differs_from: {bound: '  '}",
    ],
    ids=["scalar", "empty", "scalar-sentence", "blank-sentence"],
)
def test_a_bad_shape_in_the_bundle_is_still_a_configuration_error(
    tmp_path, monkeypatch, block
):
    """configcheck never sees the bundle; the parse loop's own check does."""
    with pytest.raises(SchemaError) as exc:
        _bundle_project(
            tmp_path,
            monkeypatch,
            BUNDLE_BASE.replace("  note:\n    prefix: NTE", f"  note:\n    prefix: NTE\n{block}"),
        )
    assert "types.note.differs_from" in str(exc.value)


def test_a_dangling_term_in_the_bundle_is_a_configuration_error(tmp_path, monkeypatch):
    with pytest.raises(SchemaError) as exc:
        _bundle_project(
            tmp_path,
            monkeypatch,
            BUNDLE_BASE.replace(
                "  note:\n    prefix: NTE",
                "  note:\n    prefix: NTE\n"
                "    differs_from:\n      nogterm: not in this standard.",
            ),
        )
    assert "types.note.differs_from" in str(exc.value)
    assert "nogterm" in str(exc.value)


# ------------------------------------- no differs_from means no byte drift


def test_a_project_without_differs_from_keys_shows_nothing(tmp_path):
    project = _load_vocab(tmp_path, _schema())
    html = vocabulary.render_html(project)
    md = vocabulary.render_markdown(project)
    assert "Differs from" not in html
    assert "Differs from" not in md
    schema_json_text = json.dumps(schema_json_mod.build_schema(project), sort_keys=True)
    assert '"differs_from"' not in schema_json_text
