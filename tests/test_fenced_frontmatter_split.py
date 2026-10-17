"""R10-X1: a `---` line inside a fenced code block does not split the item.

The splitter (parse.md_front_matter_blocks) treats every `---` at a line start
as a front-matter candidate, so pasting a front-matter example into an item's
body inside a ```yaml fence creates a live phantom item: duplicate ids, inert
examples that check as real fields, and a `refdes ls` listing the phantom.
The rule fixed here: a `---` inside an *open* fenced code block (``` or ~~~,
closing fence same char and length >= the opener, opener indented at most 3
spaces) is literal body text and never splits. A `---` outside any fence
splits exactly as before; an unclosed fence opener protects nothing, so the
rest of the file behaves as it does today.
"""

from __future__ import annotations

import os
import shutil

from helpers import REPO

from refdes import parse
from refdes.schema import load_project

HEAD = "---\nid: DEC-FENCE-001\ntype: decision\ntitle: Solo\n---\n"


def _project(tmp_path, name: str, text: str):
    shutil.copy(os.path.join(REPO, "refdes-project.yaml"), tmp_path / "refdes-project.yaml")
    shutil.copy(os.path.join(REPO, "refdes-schema.yaml"), tmp_path / "refdes-schema.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    path = items / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return project, path


# ------------------------------------------------------------------ splitter unit


def test_fenced_dashes_in_backtick_fence_do_not_split():
    """The R10-X1 shape: a front-matter example pasted as a ```yaml fence stays
    body text -- one block, no phantom item."""
    text = HEAD + "\nHere is the config I meant to add:\n\n```yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n```\n\nEnd.\n"
    blocks, errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    assert blocks[0][2]["id"] == "DEC-FENCE-001"


def test_fenced_dashes_in_tilde_fence_do_not_split():
    text = HEAD + "\n~~~yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n~~~\n"
    blocks, errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1


def test_longer_closing_fence_closes_and_inner_shorter_fence_is_literal():
    """```` opens; a ``` line inside does not close it; the `---` stays
    literal until the ```` closer, and a `---` after that splits as usual."""
    text = (
        HEAD
        + "\n````markdown\n---\nid: PHANTOM\ntitle: no\n```\n---\n````\n"
        + "---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


def test_indented_fence_still_protects_its_dashes():
    """A fence opener indented up to 3 spaces is a fence (CommonMark); the
    column-0 `---` inside it does not split."""
    text = HEAD + "\n   ```yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n   ```\n"
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 1


def test_four_space_indent_is_not_a_fence_opener():
    """4+ spaces of indentation is an indented code block, not a fence, so the
    `---` after it splits exactly as it does today."""
    text = (
        HEAD
        + "\n    ```yaml\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


def test_dash_outside_any_fence_still_splits():
    """The no-regression pin: fences live in the bodies, and the `---` between
    the two items splits exactly as today."""
    text = (
        HEAD
        + "\n```calc\nx = 1\n```\n\n---\nid: DEC-FENCE-002\ntitle: Second\n---\n"
        + "\n```calc\ny = 2\n```\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert [blocks[k][2]["id"] for k in (0, 1)] == ["DEC-FENCE-001", "DEC-FENCE-002"]


def test_unclosed_fence_opener_protects_nothing():
    """Least-surprising rule for an unclosed fence: the file from the opener
    on behaves as it does today, so the key-shaped `---` after it splits."""
    text = (
        HEAD
        + "\n```yaml\nsome yaml with no closing fence\n\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


def test_fence_body_line_with_info_string_does_not_close_the_fence():
    """```python inside the fence is body text (a closing fence carries no
    info string), so the `---` after it is still inside the fence."""
    text = (
        HEAD
        + "\n```markdown\n```python\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n```\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 1


def test_backtick_in_info_string_is_not_a_fence_opener():
    """A fence opener's info string may not contain a backtick, so that line
    opens nothing and the `---` after it splits as today."""
    text = (
        HEAD
        + "\n``` use `x` inline\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


# --------------------------------------------------------------------- end to end


def test_r10_x1_repro_pasted_front_matter_example_stays_inert(tmp_path):
    """The exact R10-X1 repro: pasting the docs/checks.md front-matter example
    as a ```yaml fence in an item body must not mint a phantom item -- no
    duplicate id, no fenced `checks:` read as a live field."""
    project, _path = _project(
        tmp_path,
        "fenced",
        "---\nid: DEC-FENCE-001\ntype: decision\ntitle: Solo\nsummary: One.\n"
        "status: accepted\n---\n\n"
        "The config I meant to add:\n\n"
        "```yaml\n---\nid: DEC-FENCE-001\nchecks:\n  - value: eff\n    against: BND-THM-002\n---\n```\n\n"
        "End of the example.\n",
    )
    assert [d.message for d in project.errors] == []
    assert [item.id for item in project.items.values()] == ["DEC-FENCE-001"]
    body = project.item_by_id("DEC-FENCE-001").body
    assert "id: DEC-FENCE-001" in body  # the fenced text is verbatim body prose
    assert project.item_by_id("DEC-FENCE-001").fields.get("checks") is None


def test_only_the_later_section_has_a_fenced_example(tmp_path):
    """Two items, the second one's body carries a fenced front-matter example:
    both items survive, the fence stays in the second item's body."""
    project, _path = _project(
        tmp_path,
        "twosec",
        HEAD
        + "\nFirst body.\n\n---\nid: DEC-FENCE-002\ntype: decision\ntitle: Second\n---\n\n"
        "```yaml\n---\nid: PHANTOM-999\ntitle: never an item\n---\n```\n",
    )
    assert [d.message for d in project.errors] == []
    assert sorted(item.id for item in project.items.values()) == ["DEC-FENCE-001", "DEC-FENCE-002"]
    assert "id: PHANTOM-999" in project.item_by_id("DEC-FENCE-002").body


def test_load_does_not_rewrite_the_file(tmp_path):
    """Round trip: loading the file (what `refdes ls` does) leaves every byte,
    fenced content included, untouched."""
    text = (
        HEAD
        + "\n```yaml\n---\nid: PHANTOM-999\nchecks: []\n---\n```\n"
    )
    project, path = _project(tmp_path, "roundtrip", text)
    assert [d.message for d in project.errors] == []
    assert path.read_text(encoding="utf-8") == text
    assert "```yaml" in project.item_by_id("DEC-FENCE-001").body


def test_list_file_body_is_unaffected(tmp_path):
    """The list-file spelling (`body: |` carrying a fenced front-matter
    example) parses exactly as today: one item, body verbatim."""
    shutil.copy(os.path.join(REPO, "refdes-project.yaml"), tmp_path / "refdes-project.yaml")
    shutil.copy(os.path.join(REPO, "refdes-schema.yaml"), tmp_path / "refdes-schema.yaml")
    items = tmp_path / "items" / "decisions"
    items.mkdir(parents=True)
    path = items / "entries.yaml"
    path.write_text(
        "defaults:\n  type: decision\n  prefix: DEC-LIST\nitems:\n"
        "  - id: DEC-LIST-001\n    title: Solo\n    body: |\n"
        "      Example:\n\n"
        "      ```yaml\n      ---\n      id: DEC-LIST-001\n      ---\n      ```\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assert [d.message for d in project.errors] == []
    assert [item.id for item in project.items.values()] == ["DEC-LIST-001"]
    assert "---" in project.item_by_id("DEC-LIST-001").body
