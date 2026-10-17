"""R10-X1: a `---` line inside a fenced code block does not split the item.

The splitter (parse.md_front_matter_blocks) treats every `---` at a line start
as a front-matter candidate, so pasting a front-matter example into an item's
body inside a ```yaml fence creates a live phantom item: duplicate ids, inert
examples that check as real fields, and a `refdes ls` listing the phantom.
The rule fixed here: a `---` inside an *open* fenced code block (``` or ~~~,
closing fence same char and length >= the opener, opener indented at most 3
spaces) is literal body text and never splits. A `---` outside any fence
splits exactly as before; an unclosed fence opener protects nothing from
splitting, so the rest of the file behaves as it does today.

The second rule, from the PR #331 review: protection must never swallow an
item silently. A `---`+key pair that only stopped being a front-matter
candidate because a fence protects it reports one warning at that line --
a pasted example costs one warning, and an item hidden behind an unclosed
earlier fence can never vanish without a word.

The third rule, finding R11-F1: an opener the file never closes is itself
warned at its line (the split is unchanged; only the silence is). When the
file ends with a line that looks like a closer carrying an info string --
the ```yaml-...-```yaml typo, which no closing fence may do -- that line is
named as the likely cause.
"""

from __future__ import annotations

import os
import shutil

from helpers import REPO

from refdes import cli as cli_mod
from refdes import parse
from refdes.schema import load_project

HEAD = "---\nid: DEC-FENCE-001\ntype: decision\ntitle: Solo\n---\n"
LOG_HEAD = "---\nid: LOG-FENCE-001\ntype: log\nsummary: Host\n---\n"


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
    body text -- one block (and one warning, see the swallow tests)."""
    text = HEAD + "\nHere is the config I meant to add:\n\n```yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n```\n\nEnd.\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    assert blocks[0][2]["id"] == "DEC-FENCE-001"
    assert len(warnings) == 1  # the paste is announced, never silent


def test_fenced_dashes_in_tilde_fence_do_not_split():
    text = HEAD + "\n~~~yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n~~~\n"
    blocks, errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
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
    blocks, _errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


def test_indented_fence_still_protects_its_dashes():
    """A fence opener indented up to 3 spaces is a fence (CommonMark); the
    column-0 `---` inside it does not split."""
    text = HEAD + "\n   ```yaml\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n   ```\n"
    blocks, _errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 1


def test_four_space_indent_is_not_a_fence_opener():
    """4+ spaces of indentation is an indented code block, not a fence, so the
    `---` after it splits exactly as it does today."""
    text = (
        HEAD
        + "\n    ```yaml\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


def test_dash_outside_any_fence_still_splits():
    """The no-regression pin: fences live in the bodies, and the `---` between
    the two items splits exactly as today -- and no warning is fired for a
    fence that protects no front-matter candidate."""
    text = (
        HEAD
        + "\n```calc\nx = 1\n```\n\n---\nid: DEC-FENCE-002\ntitle: Second\n---\n"
        + "\n```calc\ny = 2\n```\n"
    )
    blocks, _errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert [blocks[k][2]["id"] for k in (0, 1)] == ["DEC-FENCE-001", "DEC-FENCE-002"]
    assert warnings == []


def test_unclosed_fence_opener_protects_nothing():
    """Least-surprising rule for an unclosed fence with nothing to pair with:
    the file from the opener on behaves as it does today, so the key-shaped
    `---` after it splits. The split is silent-nothing: R11-F1 added a
    warning at the opener's line (the split itself is unchanged)."""
    text = (
        HEAD
        + "\n```yaml\nsome yaml with no closing fence\n\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"
    fence = [w for w in warnings if "unclosed fenced code block" in w[0]]
    assert [w[1] for w in fence] == [7]  # the opener's line


def test_fence_body_line_with_info_string_does_not_close_the_fence():
    """```python inside the fence is body text (a closing fence carries no
    info string), so the `---` after it is still inside the fence."""
    text = (
        HEAD
        + "\n```markdown\n```python\n---\nid: DEC-FENCE-002\ntitle: Phantom\n---\n```\n"
    )
    blocks, _errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 1


def test_backtick_in_info_string_is_not_a_fence_opener():
    """A fence opener's info string may not contain a backtick, so that line
    opens nothing and the `---` after it splits as today."""
    text = (
        HEAD
        + "\n``` use `x` inline\n---\nid: DEC-FENCE-002\ntitle: Second\n---\nbody\n"
    )
    blocks, _errors, _dups, _warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert len(blocks) == 2
    assert blocks[1][2]["id"] == "DEC-FENCE-002"


# ------------------------------------------------------------------- swallowing


SWALLOW = (
    "---\nid: A-1\ntype: log\n---\n"
    "Body of A with an UNCLOSED fence by mistake:\n"
    "```python\n"
    "x = 1\n"
    "\n"
    "---\nid: B-1\ntype: log\n---\n"
    "Body of B with a normal fence:\n"
    "```text\n"
    "hello\n"
    "```\n"
)


def test_unclosed_fence_swallowing_a_later_item_warns():
    """The PR #331 review repro: A's unclosed ``` pairs with the closer of
    B's body fence, protecting B's front matter -- B is suppressed, and that
    must be LOUD: one warning naming B's opening `---` line, saying fenced
    front matter is example text and an earlier fence is probably unclosed.
    (A phantom item is loud today via duplicate-id errors; a vanished item
    must not be silent.)"""
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(SWALLOW.split("\n"))
    assert errors == []
    assert [b[2]["id"] for b in blocks] == ["A-1"]
    assert len(warnings) == 1
    message, line = warnings[0]
    assert line == 9  # B's opening `---`
    assert "fenced code block" in message
    assert "unclosed" in message


def test_unclosed_fence_then_item_with_no_fence_loads_with_a_warning():
    """Variant: B carries no fence at all, so A's opener has no closer,
    protects nothing, and B splits -- exactly as on main (the split is
    unchanged), and since R11-F1 the opener is named by a warning."""
    text = (
        "---\nid: A-1\ntype: log\n---\n"
        "Body of A with an UNCLOSED fence:\n"
        "```python\n"
        "x = 1\n"
        "\n"
        "---\nid: B-1\ntype: log\n---\n"
        "Plain body, no fence.\n"
    )
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert [b[2]["id"] for b in blocks] == ["A-1", "B-1"]
    fence = [w for w in warnings if "unclosed fenced code block" in w[0]]
    assert [w[1] for w in fence] == [6]  # the ```python opener's line


def test_unclosed_fence_with_two_later_items_warns_once_and_keeps_the_third():
    """Variant: A's unclosed fence swallows B (which has a body fence, the
    closer), and C behind it splits. B's suppression is warned once; C is
    untouched -- nothing beyond the swallowed block changes."""
    text = SWALLOW + "\n---\nid: C-1\ntype: log\n---\nPlain body C.\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert [b[2]["id"] for b in blocks] == ["A-1", "C-1"]
    assert len(warnings) == 1
    assert warnings[0][1] == 9  # B's opening `---`


def test_unclosed_fence_swallowing_reports_through_the_loader(tmp_path):
    """End to end: the swallowed item surfaces the warning on the normal
    diagnostic channel (file:line), so `refdes check` says it out loud."""
    project, _path = _project(
        tmp_path,
        "swallow",
        "---\nid: DEC-FENCE-001\ntype: decision\ntitle: Solo\n---\n"
        "Body of A with an UNCLOSED fence by mistake:\n"
        "```python\nx = 1\n\n"
        "---\nid: DEC-FENCE-002\ntype: decision\ntitle: Second\n---\n"
        "Body of B with a normal fence:\n```text\nhello\n```\n",
    )
    assert [d.message for d in project.errors] == []
    assert [item.id for item in project.items.values()] == ["DEC-FENCE-001"]
    msgs = [d.message for d in project.warnings]
    assert any("fenced code block" in m and "unclosed" in m for m in msgs), msgs
    locs = [d.line for d in project.warnings if "fenced code block" in d.message]
    assert locs == [10]  # the `---` opening the swallowed item's front matter


# --------------------------------------------------------------------- end to end


def test_r10_x1_repro_pasted_front_matter_example_stays_inert(tmp_path):
    """The exact R10-X1 repro: pasting the docs/checks.md front-matter example
    as a ```yaml fence in an item body must not mint a phantom item -- no
    duplicate id, no fenced `checks:` read as a live field -- and the paste
    is announced with one warning."""
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
    msgs = [d.message for d in project.warnings]
    assert sum("fenced code block" in m for m in msgs) == 1


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
    example) parses exactly as today: one item, body verbatim, no warning
    (the list parser never runs the Markdown splitter)."""
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
    assert [d.message for d in project.warnings] == []


# ---------------------------------------------------- fences inside front matter (review round 2)

FM_SCALAR_FENCE = (
    "---\nid: DEC-FENCE-001\ntype: decision\ntitle: First\n---\nBody A plain.\n\n"
    "---\nid: DEC-FENCE-002\ntype: decision\ntitle: Second\nnote: |\n"
    "  ```\n  a fence marker inside a block scalar is YAML string content\n"
    "---\nBody B plain.\n\n"
    "---\nid: DEC-FENCE-003\ntype: decision\ntitle: Third\n---\n"
    "Body C with a closed fence:\n```text\nfence\n```\n"
)


def test_fence_opened_in_front_matter_is_yaml_text_not_a_fence():
    """PR #331 review round 2: the protection scan must not read a ``` line
    inside an item's FRONT MATTER (a block scalar can carry one) as a fence
    opener -- it is YAML string content. Reading it as a fence lets it
    protect that item's own closing `---`, and the item vanishes with no
    warning (main loads all three items)."""
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(FM_SCALAR_FENCE.split("\n"))
    assert errors == []
    assert [parsed.get("id") for _, _, parsed in blocks] == [
        "DEC-FENCE-001",
        "DEC-FENCE-002",
        "DEC-FENCE-003",
    ]
    assert warnings == []


def test_front_matter_fence_opened_at_its_end_still_loads_every_item():
    """The reviewer's exact shape: the block-scalar ``` is unclosed inside
    the front matter and pairs with a *closed* fence in a later item's body;
    front matter is opaque to fence tracking, so nothing protects anything
    and all items load exactly as they do today."""
    text = FM_SCALAR_FENCE.replace(
        "  a fence marker inside a block scalar is YAML string content\n",
        "  fence marker unclosed inside the block scalar\n",
    )
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert [parsed.get("id") for _, _, parsed in blocks] == [
        "DEC-FENCE-001",
        "DEC-FENCE-002",
        "DEC-FENCE-003",
    ]
    assert warnings == []


def test_front_matter_fence_loads_all_items_through_the_loader(tmp_path):
    """End to end: the reviewer's file loads as it does on main -- all three
    items, no errors, no warnings."""
    project, _path = _project(tmp_path, "fence_fm", FM_SCALAR_FENCE)
    assert [d.message for d in project.errors] == []
    assert [item.id for item in project.items.values()] == [
        "DEC-FENCE-001",
        "DEC-FENCE-002",
        "DEC-FENCE-003",
    ]
    assert [d.message for d in project.warnings if "fenced code block" in d.message] == []


# -------------------------------------------- unclosed fences (R11-F1: loud, not silent)

# The R11-F1 repro: a fenced example whose *closing* fence line carries an
# info string. By CommonMark a closing fence cannot carry one, so the fence
# is unclosed -- the rest of the file renders as code, and (an unclosed
# opener protecting nothing, per #331) the inner `---`+keys split as a live
# phantom item. The split stays exactly as on main; what was missing is the
# noise: one warning at the opener's line, naming the trailing closer-with-
# info-string line as the likely cause.
R11_F1 = (
    "---\n"                                              # 1
    "id: LOG-FENCE-001\ntype: log\nsummary: Host\n---\n"  # 2-5
    "The example:\n"                                     # 6
    "```yaml\n"                                          # 7  opener
    "---\nid: LOG-FENCE-002\ntype: log\nsummary: Phantom\n---\n"  # 8-12
    "prose under the example\n"                          # 13
    "```yaml\n"                                          # 14  intended closer, carries an info string
)


def _fence_warnings(warnings):
    return [w for w in warnings if "unclosed fenced code block" in w[0]]


def test_unclosed_fence_warns_at_its_opener():
    """Single item, body opens a fence that the file never closes: the split
    is what it is today (one item), the silence is not -- one warning at the
    opener's line."""
    text = LOG_HEAD + "body\n\n```yaml\nsome yaml\nno closer\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert [parsed.get("id") for _, _, parsed in blocks] == ["LOG-FENCE-001"]
    fence = _fence_warnings(warnings)
    assert [w[1] for w in fence] == [8]  # the `​```yaml` opener line
    assert "info string" not in fence[0][0]  # no closer to blame: no cause clause


def test_unclosed_fence_keeps_later_items_splitting_unchanged():
    """The unclosed opener protects nothing (the #331 rule, unchanged): the
    item after it splits exactly as on main, and the opener is named."""
    text = (
        LOG_HEAD
        + "body\n\n```yaml\nsome yaml\n\n"
        "---\nid: LOG-FENCE-002\ntype: log\nsummary: Second\n---\nplain body\n"
    )
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert [parsed.get("id") for _, _, parsed in blocks] == ["LOG-FENCE-001", "LOG-FENCE-002"]
    fence = _fence_warnings(warnings)
    assert [w[1] for w in fence] == [8]
    assert "info string" not in fence[0][0]


def test_closer_carrying_an_info_string_is_named_as_the_cause():
    """The R11-F1 repro: ```yaml ... ```yaml. The split is main's split
    (the phantom item lives -- this changes nothing about what parses); the
    warning names the opener's line AND the trailing closer line as the
    likely cause, quoting it."""
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(R11_F1.split("\n"))
    assert errors == []
    assert [parsed.get("id") for _, _, parsed in blocks] == ["LOG-FENCE-001", "LOG-FENCE-002"]
    fence = _fence_warnings(warnings)
    assert len(fence) == 1
    message, line = fence[0]
    assert line == 7  # the opener
    assert "```yaml" in message  # the closer, quoted
    assert "14" in message  # the closer's line
    assert "info string" in message  # why it cannot close


def test_unclosed_tilde_fence_containing_backticks_warns_at_the_tilde():
    """A ~~~ fence containing a ``` line: the backtick line is fence content,
    not a closer and not a second opener -- one warning, at the ~~~ line."""
    text = LOG_HEAD + "~~~markdown\n```yaml\nplain text\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    fence = _fence_warnings(warnings)
    assert [w[1] for w in fence] == [6]  # the ~~~ opener, not the ``` line


def test_unclosed_backtick_fence_containing_tildes_warns_at_the_backtick():
    """Mirror shape: a ``` fence containing a ~~~ line -- the tilde line
    cannot close a backtick fence, so the warning is at the backtick opener."""
    text = LOG_HEAD + "```md\n~~~\nplain text\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    fence = _fence_warnings(warnings)
    assert [w[1] for w in fence] == [6]


def test_closed_fence_pair_is_silent():
    """The no-regression pins for the new warning: a properly closed fence
    (trailing spaces on the closer included, per #331) warns about nothing."""
    closed = LOG_HEAD + "```text\nx = 1\n```\ndone\n"
    _b, _e, _d, warnings = parse.md_front_matter_blocks(closed.split("\n"))
    assert warnings == []
    trailing_space = LOG_HEAD + "```text\nx = 1\n``` \n"
    _b, _e, _d, warnings = parse.md_front_matter_blocks(trailing_space.split("\n"))
    assert warnings == []


def test_closed_tilde_fence_containing_backticks_is_silent():
    """A ~~~ fence legitimately containing ``` lines (the docs example of a
    fenced example) closes at the ~~~ line and warns about nothing."""
    text = LOG_HEAD + "~~~markdown\n```yaml\nplain text\n~~~\nafter\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    assert warnings == []


def test_unclosed_fence_in_a_list_item_warns_at_the_opener():
    """A fence opener indented 3 spaces inside a bullet is a fence (the
    #331 indent rule); unclosed, its line is what the warning names."""
    text = LOG_HEAD + "- step one\n   ```yaml\n   key: v\n"
    blocks, errors, _dups, warnings = parse.md_front_matter_blocks(text.split("\n"))
    assert errors == []
    assert len(blocks) == 1
    fence = _fence_warnings(warnings)
    assert [w[1] for w in fence] == [7]


def test_unclosed_fence_reports_through_the_loader(tmp_path):
    """End to end: the warning reaches the normal diagnostic channel with
    the file and the opener's line, so `refdes check` says it out loud."""
    project, _path = _project(
        tmp_path, "unclosed", LOG_HEAD + "body\n\n```yaml\nsome yaml\nno closer\n"
    )
    assert [d.message for d in project.errors] == []
    assert [item.id for item in project.items.values()] == ["LOG-FENCE-001"]
    fence = [d for d in project.warnings if "unclosed fenced code block" in d.message]
    assert len(fence) == 1
    assert fence[0].line == 8
    assert fence[0].file == "items/decisions/unclosed.md"


def test_closer_with_info_string_end_to_end(tmp_path):
    """The R11-F1 file through the loader: the phantom split is main's
    behavior (2 items -- this changes nothing about what parses), the noise
    is the new part, and the front-matter-with-info-string closer is quoted
    with its line."""
    project, _path = _project(tmp_path, "closer", R11_F1)
    assert [d.message for d in project.errors] == []
    assert sorted(item.id for item in project.items.values()) == ["LOG-FENCE-001", "LOG-FENCE-002"]
    fence = [d for d in project.warnings if "unclosed fenced code block" in d.message]
    assert len(fence) == 1
    assert fence[0].line == 7
    assert "```yaml" in fence[0].message
    assert "14" in fence[0].message


def test_unclosed_fence_check_and_build_parity(tmp_path, capsys):
    """`refdes check` and `refdes build` load through the same splitter, so
    both must print the identical warning (same file:line) for the R11-F1
    file -- and both stay at 0 errors (the split, and so the items, are
    main's). --no-write on both so no key minting rewrites the file out
    from under the line numbers."""
    shutil.copy(os.path.join(REPO, "refdes-project.yaml"), tmp_path / "refdes-project.yaml")
    shutil.copy(os.path.join(REPO, "refdes-schema.yaml"), tmp_path / "refdes-schema.yaml")
    # items/board-a/ like the repo's own layout: the log type declares its own
    # `board` field, so a path-scoped board is the spelling that keeps the
    # repo config's board registry from adding a warning of its own.
    items = tmp_path / "items" / "board-a"
    items.mkdir(parents=True)
    text = (
        "---\n"                                                     # 1
        "id: LOG-FENCE-001\ntype: log\nsummary: Host\n---\n"        # 2-5
        "The example:\n"                                            # 6
        "```yaml\n"                                                 # 7  opener
        "---\nid: LOG-FENCE-002\ntype: log\nsummary: Phantom\n---\n"  # 8-12
        "prose under the example\n"                                 # 13
        "```yaml\n"                                                 # 14  closer with an info string
    )
    (items / "unclosed.md").write_text(text, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")

    code = cli_mod.main(["--no-write", "-c", config, "check"])
    captured = capsys.readouterr()
    check_out = captured.out + captured.err
    assert code == 0
    assert "items/board-a/unclosed.md:7" in check_out
    assert "unclosed fenced code block" in check_out
    assert "line 14" in check_out
    assert "0 errors, 1 warnings" in check_out

    code = cli_mod.main(["--no-write", "-c", config, "build", "--dry-run"])
    captured = capsys.readouterr()
    build_out = captured.out + captured.err
    assert code == 0
    assert "items/board-a/unclosed.md:7" in build_out
    assert "unclosed fenced code block" in build_out
    assert "0 errors, 1 warnings" in build_out
