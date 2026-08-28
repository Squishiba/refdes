"""multi-item markdown -- and: sections.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil
import textwrap

import pytest
import yaml
from helpers import REPO

from refdes import ids, parse
from refdes.schema import load_project

FLOW_STYLE_LIST_FILE = """\
defaults:
  type: requirement
  prefix: REQ-TMP
items:
  - id: REQ-TMP-001
    text: First.
  - {text: flow style entry}
"""


# -------------------------------------------------------------- multi-item markdown

MULTI_ITEM_DECISION_MD = """\
---
defaults:
  type: decision
  prefix: DEC-X
  status: accepted
---
id: DEC-X-001
title: First decision
---

Body of the first decision. Has some prose.

---
id: DEC-X-002
title: Second decision
---

Body of the second decision.
"""


@pytest.fixture
def flow_style_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "tmp.yaml").write_text(FLOW_STYLE_LIST_FILE, encoding="utf-8")
    return tmp_path


def test_allocation_into_flow_style_entry_stays_valid_yaml(flow_style_project):
    """`- {text: ...}` must gain an id without breaking the flow mapping (#1 P1-13)."""
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    text = path.read_text(encoding="utf-8")

    # The rewritten file must still be parseable YAML with the id + text intact.
    reparsed = yaml.safe_load(text)
    entries = reparsed["items"]
    assert entries[1] == {"id": "REQ-TMP-002", "text": "flow style entry"}


def test_unclosed_flow_entry_is_refused_not_corrupted(flow_style_project):
    """A flow mapping that doesn't close on its own line must be refused, not guessed at."""
    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - id: REQ-TMP-001
                text: First.
              - {text: "spans
                multiple lines"}
            """
        ),
        encoding="utf-8",
    )
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    before = path.read_text(encoding="utf-8")
    ids.allocate(project)
    after = path.read_text(encoding="utf-8")

    assert after == before  # refused write must leave the source file untouched
    assert any("could not write id" in d.message for d in project.errors)


def test_a_refused_write_back_is_not_reported_as_allocated(flow_style_project):
    """The refusal used to sit one line above "allocated REQ-TMP-002" and
    "allocated 1 id(s)", for an id that was never written anywhere -- and the
    ledger recorded it as allocated and burned its number, so the next run
    handed the same item a different id and REQ-TMP-002 was gone for nothing.
    Nothing was written, so nothing is claimed."""
    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - id: REQ-TMP-001
                text: First.
              - {text: "spans
                multiple lines"}
            """
        ),
        encoding="utf-8",
    )
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)

    assert assignments == []
    ledger = ids.load_ledger(project)
    assert "REQ-TMP-002" not in (ledger.get("allocated") or [])
    assert int((ledger.get("burned") or {}).get("REQ-TMP", 0)) == 1
    # Still pending, so a later run retries it rather than skipping it.
    assert len(project.pending) == 1


def test_one_refused_write_back_does_not_block_its_neighbours(flow_style_project):
    """Per-item, not per-file: an entry that can be written still is, and is
    still reported and burned normally."""
    path = flow_style_project / "items" / "requirements" / "tmp.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - id: REQ-TMP-001
                text: First.
              - {text: "spans
                multiple lines"}
              - text: A writable one.
            """
        ),
        encoding="utf-8",
    )
    project = load_project(config_path=str(flow_style_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)

    assert [new_id for _item, new_id in assignments] == ["REQ-TMP-003"]
    assert "id: REQ-TMP-003" in path.read_text(encoding="utf-8")
    ledger = ids.load_ledger(project)
    assert ledger["allocated"] == ["REQ-TMP-003"]
    assert any("could not write id" in d.message for d in project.errors)


@pytest.fixture
def multi_item_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "multi.md").write_text(MULTI_ITEM_DECISION_MD, encoding="utf-8")
    return tmp_path


def test_multi_item_markdown_file_parses_each_item_separately(multi_item_project):
    project = load_project(config_path=str(multi_item_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors

    one = project.items["DEC-X-001"]
    two = project.items["DEC-X-002"]
    assert one.fields["title"] == "First decision"
    assert two.fields["title"] == "Second decision"
    # `defaults:` applied to both, and each keeps its own body -- no leakage
    # between items sharing one file.
    assert one.fields["status"] == "accepted"
    assert two.fields["status"] == "accepted"
    assert "first decision" in one.body.lower()
    assert "second decision" in two.body.lower()
    assert "Body of the first decision" not in two.body
    assert "Body of the second decision" not in one.body


def test_multi_item_source_lines_point_at_each_items_own_fence(multi_item_project):
    project = load_project(config_path=str(multi_item_project / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    text = (
        (multi_item_project / "items" / "decisions" / "multi.md")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    one = project.items["DEC-X-001"]
    two = project.items["DEC-X-002"]
    assert text[one.source_line - 1].strip() == "id: DEC-X-001"
    assert text[two.source_line - 1].strip() == "id: DEC-X-002"


def test_today_style_single_item_file_is_unaffected(tmp_path):
    """A one-document file, unchanged, must parse identically to before."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    text = open(
        os.path.join(REPO, "items", "decisions", "dec-pwr-001-regulator-topology.md"),
        encoding="utf-8",
    ).read()
    (items / "dec.md").write_text(text, encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-PWR-001"]
    assert item.source_line == 2
    assert item.body.startswith("\nThe 3V3 rail draws")


def test_literal_horizontal_rule_stays_in_the_body(tmp_path):
    """A `---` not followed by a YAML key is prose, not a second item."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "one.md").write_text(
        "---\n"
        "id: DEC-HR-001\n"
        "type: decision\n"
        "title: Solo\n"
        "---\n\n"
        "Some intro text.\n\n"
        "---\n\n"
        "More text after a horizontal rule.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-HR-001"]
    assert "More text after a horizontal rule." in item.body
    assert "---" in item.body


def test_horizontal_rule_with_no_closing_fence_stays_literal(tmp_path):
    """Key-shaped text after a `---` with nothing later to close it stays prose."""
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "one.md").write_text(
        "---\n"
        "id: DEC-HR-002\n"
        "type: decision\n"
        "title: Solo\n"
        "---\n\n"
        "Some intro text.\n\n"
        "---\n"
        "Note: this looks like a key but there is no closing fence.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert not project.errors
    assert len(project.items) == 1
    item = project.items["DEC-HR-002"]
    assert "Note: this looks like a key" in item.body


def test_defaults_block_alone_with_no_items_is_an_error(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    (items / "empty.md").write_text(
        "---\ndefaults:\n  type: decision\n---\n\nJust prose, no item.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert any("no items" in d.message for d in project.errors)


def test_refdes_id_writes_back_into_each_items_own_fence(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    path = items / "multi.md"
    path.write_text(
        "---\ndefaults:\n  type: decision\n  prefix: DEC-MULTI\n---\n"
        "title: First, no id yet\n---\n\nBody one.\n\n"
        "---\ntitle: Second, no id yet\n---\n\nBody two.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert [new_id for _item, new_id in assignments] == [
        "DEC-MULTI-001",
        "DEC-MULTI-002",
    ]

    # Re-parse from disk: both ids landed at the right fence, and each item still
    # has its own distinct body.
    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert "Body one." in project2.items["DEC-MULTI-001"].body
    assert "Body two." in project2.items["DEC-MULTI-002"].body
    assert "Body two." not in project2.items["DEC-MULTI-001"].body


# ------------------------------------------------------------------- sections

SECTIONS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
    "  decision: { prefix: DEC, fields: { title: { type: text, required: true } }, body: {} }\n"
)


def test_section_elides_type_in_a_yaml_list_file(tmp_path):
    """Finding 6, built instead of the type-keyed items: mapping. A `section:`
    entry asserts the type for everything after it, so items no longer need
    to restate `type:` even though the file mixes two of them."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section: requirement\n"
        "  - id: REQ-001\n    text: Elided via section.\n"
        "  - id: REQ-002\n    text: Also elided.\n"
        "  - section: decision\n"
        "  - id: DEC-001\n    title: Elided via a second section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["REQ-001"].type == "requirement"
    assert project.items["REQ-002"].type == "requirement"
    assert project.items["DEC-001"].type == "decision"


def test_section_elides_type_in_multi_item_markdown(tmp_path):
    """The Markdown spelling of the same marker: a fenced block whose only
    key is `section:`, as close to the list-file spelling as the format
    allows."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "section: decision\n"
        "---\n"
        "---\n"
        "id: DEC-101\n"
        "title: First, elided type via section.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "section: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-101\n"
        "text: Second, elided type via a new section.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    assert not project.warnings
    assert project.items["DEC-101"].type == "decision"
    assert "Body one." in project.items["DEC-101"].body
    assert project.items["REQ-101"].type == "requirement"


def test_item_contradicting_its_section_is_an_error_not_a_silent_override(tmp_path):
    """The crux of why a section isn't just a second spelling of `defaults:`:
    under `defaults: {type: X}` an item may legally declare a different
    type -- a default is a fallback. Under a section, the container has
    already asserted what its items are, so a contradicting item is an
    error naming the conflict."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section: requirement\n"
        "  - id: DEC-201\n    type: decision\n    title: Contradicts the active section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "declares type 'decision'" in d.message and "section: requirement" in d.message
        for d in project.errors
    )
    assert "DEC-201" not in project.items


def test_file_defaults_type_conflicting_with_a_section_is_an_error(tmp_path):
    """Composition rule: if a file-level `defaults:` names a type and a
    section asserts a different one, that's the file contradicting itself --
    an error naming both, not a silent pick-a-winner."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: requirement\n"
        "items:\n"
        "  - section: decision\n"
        "  - id: DEC-301\n    title: Never legitimately typed.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "section: decision" in d.message and "defaults: {type: requirement}" in d.message
        for d in project.errors
    )


def test_section_composes_with_defaults_for_non_type_fields(tmp_path):
    """A file-level `defaults:` still supplies every other field exactly as
    today; a section only ever asserts `type:`, nothing else."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      text:   { type: text, required: true }\n"
        "      status: { type: enum, choices: [draft, active], default: draft }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  status: active\n"
        "items:\n"
        "  - section: requirement\n"
        "  - id: REQ-401\n    text: Gets status from file defaults, type from the section.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert not project.errors
    item = project.items["REQ-401"]
    assert item.type == "requirement"
    assert item.fields["status"] == "active"


def test_later_defaults_block_in_markdown_is_now_an_error_not_silent(tmp_path):
    """The bug the investigation turned up: only the very first block in a
    multi-item Markdown file was ever read as file-wide defaults. A second
    `defaults:`-shaped block used to be silently misparsed as a malformed
    item, and everything after it silently kept the *original* file-wide
    type -- reproduced here exactly as found: an intended requirement lands
    as a decision, with nothing louder than an 'unknown field' warning to
    notice by. Must error now, independent of the section feature."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: decision\n"
        "---\n"
        "---\n"
        "id: DEC-401\n"
        "title: First decision.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-401\n"
        "text: A requirement after a second defaults block.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "'defaults:' only applies as the very first block" in d.message
        for d in project.errors
    )
    # The first block's type is unaffected; the real fix (turn this into a
    # 'section: requirement' marker) is left to the author -- this test only
    # needs to confirm the mistake is no longer silent.
    assert project.items["DEC-401"].type == "decision"


def test_malformed_later_markdown_block_is_reported_not_silently_dropped(tmp_path):
    """The same silent-drop shape as the `defaults:` bug above, one step
    quieter: a later `---`-fenced block that opens with a `key:` line -- so it
    was plainly meant as an item -- but whose YAML doesn't parse used to be
    skipped with no diagnostic at all. The item vanished from the project, its
    body text was folded into the *previous* item's, and the build exited 0
    with zero errors. The very first block in the same file has always
    reported this; every later one now reports it identically."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-601\n"
        "text: The first requirement.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "id: REQ-602\n"
        'text: "unclosed quote\n'
        "---\n"
        "Body two.\n"
        "\n"
        "---\n"
        "id: REQ-603\n"
        "text: The third requirement.\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    bad = [d for d in project.errors if "invalid YAML front-matter" in d.message]
    assert bad, [str(d) for d in project.errors]
    # Reported inside the offending block, not blamed on line 1 of the file.
    assert bad[0].line >= 12
    assert "REQ-602" not in project.items
    # Everything around it still parses -- one bad block is not a parse abort.
    assert "REQ-601" in project.items
    assert "REQ-603" in project.items


def test_later_markdown_block_that_is_not_a_mapping_is_reported(tmp_path):
    """A block that parses cleanly but isn't a mapping is the other half of
    the same gap -- also silently skipped before, also already reported when
    it happens to be the file's own head block."""
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.md").write_text(
        "---\n"
        "defaults:\n"
        "  type: requirement\n"
        "---\n"
        "---\n"
        "id: REQ-611\n"
        "text: The first requirement.\n"
        "---\n"
        "Body one.\n"
        "\n"
        "---\n"
        "key: value\n"
        "- a stray sequence entry\n"
        "---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any(
        "front-matter" in d.message and d.line > 1 for d in project.errors
    ), [str(d) for d in project.errors]


def test_section_marker_must_name_a_real_string(tmp_path):
    (tmp_path / "refdes.yaml").write_text(SECTIONS_SCHEMA, encoding="utf-8")
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "items:\n"
        "  - section:\n"
        "  - id: REQ-501\n    type: requirement\n    text: Unaffected by the bad marker.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project)
    assert any("'section:' must name a type" in d.message for d in project.errors)
    assert project.items["REQ-501"].type == "requirement"
