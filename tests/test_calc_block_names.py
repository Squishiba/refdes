"""Named calc blocks, Phase 1 (docs/design/named-calc-blocks.md §3, §10).

Sabotage-style: every claim is paired with the mutation that would falsify
it -- the unnamed test fails the moment a renderer starts decorating blocks
that were never named; each fence-error test fails if the grammar loosens,
tightens, or rewords; the scope test fails if naming quietly becomes a
scoping mechanism (§3.5, the single most important non-goal).
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import calc, calc_rewrite, cli as cli_mod, keys, links, parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _item(item_id: str, body: str) -> str:
    return f"---\nid: {item_id}\ntype: decision\n---\n\n{body}"


def _build(tmp_path, files: dict[str, str], write: bool = True):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    if keys.mint_missing(project, write=write):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=write)
    build_mod.build(project)
    return project


def _fence_lines(tmp_path, name: str, needle: str) -> list[int]:
    """Every 1-indexed line of `needle` in the item file as it is ON DISK
    after the build -- key minting rewrites front matter, so expected lines
    must come from the post-build text, not the authored one."""
    text = (tmp_path / "items" / name).read_text(encoding="utf-8")
    lines = [i + 1 for i, line in enumerate(text.splitlines()) if needle in line]
    assert lines, f"{needle!r} not in {name}"
    return lines


# --------------------------------------------------------------- parsing


def test_named_fence_parses(tmp_path):
    """```calc id="losses" evaluates its lines exactly as an unnamed fence
    does, and the name reaches CalcLine.block. Sabotage: a parser that eats
    the id into the block body, or drops it before CalcLine, fails here."""
    named = _item("DEC-001", '```calc id="losses"\nP_diss = 12 V * 0.5 A | W\n```\n')
    plain = _item("DEC-001", "```calc\nP_diss = 12 V * 0.5 A | W\n```\n")

    p1 = _build(tmp_path, {"a.md": named})
    assert not p1.errors, p1.errors
    p2 = _build(tmp_path, {"a.md": plain})
    assert not p2.errors, p2.errors

    assert p1.item_by_id("DEC-001").calc_values["P_diss"] == \
        p2.item_by_id("DEC-001").calc_values["P_diss"]
    assert p1.item_by_id("DEC-001").calcs[0].block == "losses"
    # Sabotage pair: the unnamed block's rows carry no block name.
    assert p2.item_by_id("DEC-001").calcs[0].block == ""


def test_parse_fence_attrs_grammar():
    """The §3.3 grammar owned by calc.parse_fence_attrs, unit-level.
    Sabotage: accepting `name=` or a bare word here fails the error tests;
    rejecting a legal lowercase-hyphen name fails this one."""
    assert calc.parse_fence_attrs("") is None
    assert calc.parse_fence_attrs(" ") is None
    assert calc.parse_fence_attrs(' id="losses"') == "losses"
    assert calc.parse_fence_attrs(' id="thermal_headroom"') == "thermal_headroom"
    assert calc.parse_fence_attrs(' id="a-b_9"') == "a-b_9"
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' name="losses"')
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(" losses")
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(" id=losses")
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' id="Losses"')
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' id="1losses"')
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' id="losses!"')
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' id=""')
    # 40 characters is the documented ceiling; 41 is not.
    assert calc.parse_fence_attrs(' id="' + "a" * 40 + '"') == "a" * 40
    with pytest.raises(calc.CalcFenceError):
        calc.parse_fence_attrs(' id="' + "a" * 41 + '"')


# --------------------------------------------------------------- rendering


def test_unnamed_block_html_unchanged(tmp_path):
    """§3.5: an unnamed block's HTML is byte-for-byte what it was before
    naming existed -- including an item with several unnamed blocks.
    Sabotage: any anchor or caption added to an unnamed table, or a changed
    table tag, fails the exact-substring comparisons below."""
    body = (
        "one\n\n```calc\nx = 1\n```\n\ntwo\n\n```calc\ny = 2\n```\n"
    )
    p = _build(tmp_path, {"a.md": _item("DEC-001", body)})
    assert not p.errors, p.errors
    item = p.item_by_id("DEC-001")
    html = item.body_html

    # The table tag itself, byte for byte: no id attribute on an unnamed table.
    assert html.count('<table class="calc">') == 2
    assert "<caption" not in html
    assert 'id="calc-' not in html

    # Each rendered table equals what the shared renderer produces with no
    # block name -- the whole table, not just the opening tag.
    counts = [build_mod._calc_line_count(b) for b in calc.extract_blocks(item.body)]
    cursor = 0
    for count in counts:
        chunk = item.calcs[cursor : cursor + count]
        cursor += count
        table = build_mod._calc_table_html(chunk)
        assert html.count(table) == 1
    assert cursor == len(item.calcs)


def test_named_block_renders_caption_and_anchor(tmp_path):
    """§3.5 / §11.10: id="calc-<name>" on the table and a caption carrying
    the name. Sabotage: an anchor without a caption (or vice versa), or the
    anchor spelled differently, fails here."""
    body = '```calc id="losses"\nP_diss = 1 W\n```\n'
    p = _build(tmp_path, {"a.md": _item("DEC-001", body)})
    assert not p.errors, p.errors
    html = p.item_by_id("DEC-001").body_html
    assert '<table class="calc" id="calc-losses">' in html
    assert "<caption class=\"calc-caption\">losses</caption>" in html


# --------------------------------------------------------------- fence errors


FENCE_ERROR_CASES = [
    (
        '```calc name="losses"',
        "calc fence: unknown attribute 'name' -- a calc fence accepts "
        'id="..."; write id="losses".',
    ),
    (
        "```calc losses",
        "calc fence: 'losses' is not an attribute -- attributes are "
        'key="value"; write id="losses".',
    ),
    (
        "```calc id=losses",
        "calc fence: 'losses' is not an attribute -- attributes are "
        'key="value"; write id="losses".',
    ),
    (
        '```calc id="Losses"',
        "calc fence: block name 'Losses' must match [a-z][a-z0-9_-]* -- "
        "write 'losses'.",
    ),
]


@pytest.mark.parametrize("fence,expected", FENCE_ERROR_CASES)
def test_fence_attribute_errors(tmp_path, fence, expected):
    """The four §7 fence messages, message for message, reported at the
    fence line. Sabotage: silently ignoring the bad fence (the old §2
    behaviour) yields zero errors and fails; so does any rewording."""
    text = _item("DEC-001", fence + "\nx = 1\n```\n")
    p = _build(tmp_path, {"a.md": text})
    errs = [d for d in p.errors if "calc fence:" in d.message]
    assert len(errs) == 1, p.errors
    assert errs[0].message == expected
    assert errs[0].line == _fence_lines(tmp_path, "a.md", fence)[0]


def test_duplicate_block_name_in_item_errors(tmp_path):
    """Two id="losses" in one item -> one error naming both lines and
    suggesting a rename (§7). Sabotage: permissive duplicates, a message
    missing either line number, or project-wide (not per-item) checking."""
    text = _item(
        "DEC-001",
        '```calc id="losses"\nx = 1\n```\n\nmid prose\n\n'
        '```calc id="losses"\ny = 2\n```\n',
    )
    p = _build(tmp_path, {"a.md": text})
    errs = [d for d in p.errors if "named twice" in d.message]
    assert len(errs) == 1, p.errors
    first, again = _fence_lines(tmp_path, "a.md", '```calc id="losses"')
    assert errs[0].message == (
        "calc block 'losses' is named twice in this item -- first at line "
        f"{first}, again at line {again}. A block name can only be used once "
        "per item (values already share one item-wide scope); rename one of "
        "them, e.g. 'losses' -> 'losses_2'."
    )
    assert errs[0].line == again


def test_same_block_name_in_two_items_is_fine(tmp_path):
    """§11.2 decided: uniqueness is per item, not per project. Sabotage: a
    project-wide registry would flag this pair."""
    p = _build(tmp_path, {
        "a.md": _item("DEC-001", '```calc id="losses"\nx = 1\n```\n'),
        "b.md": _item("DEC-002", '```calc id="losses"\ny = 2\n```\n'),
    })
    assert not p.errors, p.errors


# --------------------------------------------------------------- scope


def test_scope_unchanged_by_naming(tmp_path):
    """§3.5, the single most important non-goal: naming does not scope
    anything. A value assigned in block `supply` is visible to block
    `losses`; a name reused across the two blocks is still the existing
    assigned-twice error. Sabotage: block-scoped env would evaluate the
    first item clean of errors AND the second without the duplicate error."""
    split_ok = _item(
        "DEC-001",
        '```calc id="supply"\nV_out = 3.3 V\nI_load = 1.2 A\n```\n\n'
        '```calc id="losses"\nP_out = V_out * I_load | W\n```\n',
    )
    p = _build(tmp_path, {"a.md": split_ok})
    assert not p.errors, p.errors
    assert p.item_by_id("DEC-001").calc_values["P_out"]

    reused = _item(
        "DEC-001",
        '```calc id="supply"\nP_diss = 1 W\n```\n\n'
        '```calc id="losses"\nP_diss = 2 W\n```\n',
    )
    p2 = _build(tmp_path, {"a.md": reused})
    errs = [d for d in p2.errors if "assigned twice" in d.message]
    assert len(errs) == 1, p2.errors
    assert "'P_diss' is assigned twice in this item" in errs[0].message


def test_block_qualified_reference_errors(tmp_path):
    """§4.2/§7: DEC-001.losses.P_diss is an error naming the plain form;
    the plain form still resolves. Sabotage: resolving the qualified
    spelling (a second spelling of one reference) or rejecting both."""
    owner = _item("DEC-001", "```calc\nP_diss = 2 W\n```\n")
    qualified = _item(
        "DEC-002", "```calc\nP_copy = DEC-001.losses.P_diss\n```\n"
    )
    p = _build(tmp_path, {"a.md": owner, "b.md": qualified})
    errs = [d for d in p.errors if d.item_id == "DEC-002"]
    assert len(errs) == 1, p.errors
    assert errs[0].message == (
        "calc 'P_copy': cross-item reference 'DEC-001.losses.P_diss' names a "
        "block -- a calc value is named by ITEM.NAME, and DEC-001.P_diss "
        "already names it uniquely. Drop '.losses'."
    )

    plain = _item("DEC-002", "```calc\nP_copy = DEC-001.P_diss\n```\n")
    p2 = _build(tmp_path, {"a.md": owner, "b.md": plain})
    assert not p2.errors, p2.errors
    assert p2.item_by_id("DEC-002").calc_values["P_copy"]


# --------------------------------------------------------------- rewrite / no-write


def test_calc_rewrite_preserves_fence(tmp_path):
    """§3.6: calc-rewrite rewrites assignment lines and never touches the
    fence line -- a named fence survives byte-identical. Sabotage: a rewrite
    that normalises or strips the info string would rename the block."""
    write_project_config(tmp_path, (
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields: {}\n"
        "    body: {}\n"
    ))
    items = tmp_path / "items"
    items.mkdir()
    text = _item(
        "DEC-001",
        '```calc id="losses"\nV = 12 V\nI = 0.5 A\nP : W = V * I\n```\n',
    )
    (items / "dec.md").write_text(text, encoding="utf-8")

    result = calc_rewrite.apply(str(tmp_path))
    assert result.ok, result.errors
    after = (items / "dec.md").read_text(encoding="utf-8")
    assert '```calc id="losses"' in after  # fence byte-identical
    assert "P = V * I | W" in after        # the retired line inside did move
    assert "P : W = V * I" not in after


def test_no_write_identical(tmp_path):
    """§6.4: `build --no-write` renders named blocks identically to a
    writable build. Sabotage: a render path that mutates under --no-write
    (dropping captions, say) changes the site bytes and fails."""
    text = _item(
        "DEC-001",
        '```calc id="losses"\nP_diss = 12 V * 0.5 A | W\n```\n',
    )
    _build(tmp_path, {"a.md": text})  # writable: mints keys, expands refs
    config = str(tmp_path / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "build"]) == 0
    site = tmp_path / "_site"
    writable = {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*") if p.is_file()
    }
    assert writable

    assert cli_mod.main(["-c", config, "--no-write", "build"]) == 0
    no_write = {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*") if p.is_file()
    }
    assert no_write == writable
