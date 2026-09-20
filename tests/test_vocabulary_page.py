"""The generated vocabulary reference page (finding 38, chunk 3).

`vocabulary.html` in every built site, and the docs site's own generated
`docs/vocabulary.md`, both come from one generator: `vocabulary.entries()`
over the *resolved* schema. These tests are the contract:

- every term the resolved schema knows about has an entry, and nothing it
  does not know about gets one (a preset the build did not enable must
  not appear);
- a project's own overlay term appears with its own `doc:`, and one
  without a `doc:` says "no definition" plainly rather than vanishing;
- a link verb entry states its targets and its inverse, and "pointed at
  by" is computed from the schema -- including a verb declared under its
  inverse name;
- the page is static: no script of its own, no handler attributes.
"""

from __future__ import annotations

import importlib.util
import os

import pytest
from conftest import write_project_config
from helpers import REPO

from refdes import build as build_mod
from refdes import nav as nav_mod
from refdes import parse, render, vocabulary
from refdes.schema import load_project

GEN_PATH = os.path.join(REPO, "docs-site", "gen_examples.py")
DOC_PATH = os.path.join(REPO, "docs", "vocabulary.md")

VOCAB_SCHEMA = """\
site: { title: "Vocab Test", out: _site }
id: { width: 3 }
link_types:
  satisfies:   { inverse: satisfied_by,  label: Satisfies, doc: "A decision meets a requirement." }
  documents:   { inverse: documented_by, label: Documents }
  tracks:      { inverse: tracked_by,    label: Tracks }
sets:
  provenance:
    tags: { type: list, on_change: ignore, doc: "Free-form labels." }
types:
  requirement:
    prefix: REQ
    label: Requirement
    doc: "Something the design must achieve."
    fields:
      text: { type: text, required: true, doc: "The statement itself." }
    links: {}
  decision:
    prefix: DEC
    label: Decision
    doc: "A choice that was made."
    include: [provenance]
    fields:
      title: { type: text, required: true }
    links:
      satisfies: [requirement]
  note:
    prefix: NOT
    label: Note
    links:
      documented_by: [requirement]
      tracks: []
"""

ITEMS = "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A requirement.\n"


@pytest.fixture()
def vocab_root(tmp_path):
    write_project_config(tmp_path, VOCAB_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(ITEMS, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def vocab_project(vocab_root):
    return load_project(config_path=str(vocab_root / "refdes-project.yaml"))


def _group(vocab, kind):
    return {e.name: e for e in vocab.entries[kind]}


def _term_block(html, anchor):
    """One rendered term's own markup, for asserting what that entry says."""
    start = html.index(f'id="term-{anchor}"')
    rest = html[start:]
    end = rest.find('class="vocab-term"')
    return rest if end == -1 else rest[:end]


# ------------------------------------------------------- coverage of the schema


def test_every_resolved_term_has_an_entry(vocab_project):
    """Types, verbs, sets and the engine-reserved keys: nothing the
    resolved schema knows about is missing, and nothing extra appears."""
    vocab = vocabulary.entries(vocab_project)
    assert set(_group(vocab, "types")) == set(vocab_project.types)
    assert set(_group(vocab, "links")) == set(vocab_project.link_types)
    assert set(_group(vocab, "sets")) == set(vocab_project.sets)
    assert set(_group(vocab, "keys")) == set(vocabulary.RESERVED_KEYS)


def test_reserved_key_definitions_come_from_code():
    """Engine-reserved keys have no `doc:` in any YAML, so their definitions
    live in exactly one place: `vocabulary.RESERVED_KEYS`."""
    for name, text in vocabulary.RESERVED_KEYS.items():
        assert text.strip(), f"reserved key {name!r} has no definition"
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    vocab = vocabulary.entries(project)
    for name, entry in _group(vocab, "keys").items():
        assert entry.doc == vocabulary.RESERVED_KEYS[name]


# ------------------------------------------------------------------ definitions


def test_overlay_type_appears_with_its_own_definition(vocab_project):
    """A project's own type, defined by its own `doc:` in the overlay."""
    types = _group(vocabulary.entries(vocab_project), "types")
    assert types["decision"].doc == "A choice that was made."
    assert "A choice that was made." in vocabulary.render_html(vocab_project)


def test_undefined_overlay_term_shows_no_definition(vocab_project):
    """Project overlays are not required to define anything: the term is
    still there, and says so plainly."""
    types = _group(vocabulary.entries(vocab_project), "types")
    assert types["note"].doc == ""
    assert vocabulary.NO_DEFINITION in _term_block(
        vocabulary.render_html(vocab_project), "note"
    )


def test_undefined_field_shows_no_definition_while_a_defined_one_does(vocab_project):
    types = _group(vocabulary.entries(vocab_project), "types")
    fields = {f.name: f for f in types["decision"].fields}
    assert fields["title"].doc == ""
    assert fields["tags"].doc == "Free-form labels."
    assert vocabulary.NO_DEFINITION in _term_block(
        vocabulary.render_html(vocab_project), "decision"
    )
    req = {f.name: f for f in types["requirement"].fields}
    assert req["text"].doc == "The statement itself."


# ------------------------------------------------------------------ link verbs


def test_link_verb_entry_shows_targets_and_inverse(vocab_project):
    verbs = _group(vocabulary.entries(vocab_project), "links")
    satisfies = verbs["satisfies"]
    assert satisfies.inverse == "satisfied_by"
    assert satisfies.targets == ["requirement"]
    assert satisfies.targets_unrestricted is False
    assert satisfies.declared_on == ["decision"]
    html = vocabulary.render_html(vocab_project)
    block = _term_block(html, "satisfies")
    assert "satisfied_by" in block and "requirement" in block


def test_a_verb_with_an_empty_target_list_says_any_type(vocab_project):
    """`tracks: []` means any target type; an empty list rendered as nothing
    reads like a mistake."""
    verbs = _group(vocabulary.entries(vocab_project), "links")
    assert verbs["tracks"].targets_unrestricted is True
    assert vocabulary.ANY_TARGET in _term_block(
        vocabulary.render_html(vocab_project), "tracks"
    )


def test_pointed_at_by_is_computed_from_the_schema(vocab_project):
    types = _group(vocabulary.entries(vocab_project), "types")
    assert ("satisfies", ["decision"]) in types["requirement"].pointed_at_by


def test_pointed_at_by_resolves_a_verb_declared_by_its_inverse_name(vocab_project):
    """`note: {links: {documented_by: [requirement]}}` is the same edge as
    `requirement --documents--> note`: the note is pointed at, not pointing.
    """
    types = _group(vocabulary.entries(vocab_project), "types")
    assert ("documents", ["requirement"]) in types["note"].pointed_at_by
    verbs = _group(vocabulary.entries(vocab_project), "links")
    assert verbs["documents"].targets == ["note"]
    assert verbs["documents"].declared_on == ["note"]


def test_set_entry_lists_its_fields_and_includers(vocab_project):
    sets = _group(vocabulary.entries(vocab_project), "sets")
    assert [f.name for f in sets["provenance"].fields] == ["tags"]
    assert sets["provenance"].included_by == ["decision"]


# ---------------------------------------------------------------- examples


def test_every_term_has_a_worked_example(vocab_project):
    """No entry renders example-less: overlay terms fall back to a generated
    one built from their own resolved facts."""
    for e in vocabulary.entries(vocab_project).terms():
        assert e.example.strip(), f"{e.kind} term {e.name!r} has no example"


def test_examples_render_in_both_renderers(vocab_project):
    html = vocabulary.render_html(vocab_project)
    md = vocabulary.render_markdown(vocab_project)
    assert 'class="vocab-example"' in html
    assert "<pre><code>" in html
    assert "**Example:**" in md
    assert "```yaml" in md


def test_bundled_standard_terms_have_hand_written_examples():
    """Every hardware@3 term the pinned schema resolves is covered by the
    hand-written EXAMPLES table -- a standard term silently falling back to
    the generic generator (a preset verb, a renamed term) is a gap to close."""
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    for e in vocabulary.entries(project).terms():
        assert (e.kind, e.name) in vocabulary.EXAMPLES, (
            f"{e.kind} term {e.name!r} has no hand-written example"
        )
        assert e.example == vocabulary.EXAMPLES[(e.kind, e.name)]


def test_example_markup_is_escaped(vocab_project):
    """Examples are markup on the page like any other content: a `<` in one
    (a bound's `<= 0.15 W/in^2`) must not become markup."""
    project = load_project(config_path=os.path.join(REPO, "refdes-project.yaml"))
    html = vocabulary.render_html(project)
    assert "<= 0.15" not in html
    assert "&lt;= 0.15" in html


# ------------------------------------------------------------------- the page


def test_page_has_anchors_for_every_term(vocab_project):
    html = vocabulary.render_html(vocab_project)
    for entry in vocabulary.entries(vocab_project).terms():
        assert f'id="{entry.anchor}"' in html


def test_page_has_no_script_of_its_own(vocab_project):
    html = vocabulary.render_html(vocab_project)
    assert "<script" not in html.lower()
    assert "onclick" not in html.lower()
    assert "javascript:" not in html.lower()


def test_page_escapes_a_definition(vocab_project):
    """Definitions are author text: a `<` in one must not become markup."""
    vocab_project.types["requirement"].doc = "A <script> in a definition."
    html = vocabulary.render_html(vocab_project)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------- registration + build


def test_vocabulary_is_a_project_wide_report(vocab_root):
    # A scope with no items has no reports at all, so this asks the question
    # of a project that has been parsed.
    project = load_project(config_path=str(vocab_root / "refdes-project.yaml"))
    parse.load_items(project)
    assert nav_mod.REPORT_LABELS["vocabulary"] == "Vocabulary"
    assert "vocabulary" in nav_mod.scope_reports(project)
    assert "vocabulary" not in nav_mod.scope_reports(project, board="nope")


def test_built_site_writes_the_page_and_links_it(vocab_root):
    project = load_project(config_path=str(vocab_root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    render.render_site(project)
    out = os.path.join(str(vocab_root), "_site")
    with open(os.path.join(out, "vocabulary.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert 'id="term-requirement"' in page
    assert '<a href="vocabulary.html"' in page
    # base.html.j2 carries exactly two script tags of its own; this page's
    # content adds none.
    assert page.lower().count("<script") == 2


# ---------------------------------------------------------------- docs site


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_examples_vocab", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page_text():
    with open(DOC_PATH, encoding="utf-8") as fh:
        return fh.read()


def test_docs_site_vocabulary_page_is_current(gen):
    """docs/vocabulary.md is generated: the committed page must equal what
    the generator produces from the repo's own pin, byte for byte."""
    assert gen.extract_vocabulary_block(_page_text()) == gen.render_vocabulary_block()


def test_docs_site_check_accepts_the_committed_page(gen):
    assert gen.main(["--check"]) == 0


def test_docs_site_page_defines_a_bundled_term():
    """The docs-site page is the bundled standard's vocabulary: a term and a
    definition straight out of the pinned base.yaml."""
    page = _page_text()
    assert "### `requirement`" in page
    assert "Something the design must achieve" in page
