"""`{{calcblock}}`, Phase 3 (docs/design/named-calc-blocks.md §5.4, §7, §10).

Sabotage-style: every claim is paired with the mutation that would falsify
it. The rendering test fails if the block ever assembles its own table;
the never-evaluates test fails if the renderer grows a second evaluator or
restates the owner's failure; each §7 error test fails on a rewording, a
silence, or a permissive fallback; the local-items-only test fails if an
imported item is ever rendered from upstream text; the `--no-write` test
fails if the block mints, expands, or writes anything.

The fixture is §8.1's item -- the constructed split of the repo's real
DEC-PWR-001 into `supply` and `losses` -- so §8.3's rendered table can be
pinned cell for cell.
"""

from __future__ import annotations

import html
import json
import re

DOTALL = re.DOTALL

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import blocks as blocks_mod
from refdes import build as build_mod
from refdes import calc as calc_mod
from refdes import cli as cli_mod

CALCBLOCK_SCHEMA = """\
site: { title: "Calcblock Test", out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
history: { default: invalidate }
units: { preferred: [] }
types:
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  component:
    prefix: CMP
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
"""

# §8.1 verbatim in its arithmetic: the two named blocks, supply assumptions
# first and the dissipation argument second, with the scope deliberately
# crossing the boundary (P_out in `losses` reads V_out from `supply`).
OWNER = """\
---
id: DEC-PWR-001
type: decision
title: 3V3 rail regulator topology
---

## Working

```calc id="supply"
V_in   = 12 V \u00b1 5%
V_out  = 3.3 V
I_load = 1.2 A
eff    = 0.93
```

```calc id="losses"
P_out  = V_out * I_load | W
P_diss = P_out * (1/eff - 1) | W
A_board = 1.4 inch * 0.9 inch
P_dens = P_diss / A_board | W/in^2
```
"""

NO_CALCS = """\
---
id: CMP-PWR-001
type: component
title: A part that computes nothing.
---
"""

UNNAMED_ONLY = """\
---
id: DEC-THM-009
type: decision
title: A calculation nobody named.
---

```calc
Q_diss = 0.5 W
```
"""

DIRECTIVE = '{{calcblock item="DEC-PWR-001" block="losses"}}'


@pytest.fixture
def calcblock_project(tmp_path):
    write_project_config(tmp_path, CALCBLOCK_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-pwr-001.md").write_text(OWNER, encoding="utf-8")
    (items / "cmp-pwr-001.md").write_text(NO_CALCS, encoding="utf-8")
    (items / "dec-thm-009.md").write_text(UNNAMED_ONLY, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    return tmp_path


def _page_with_block(root, directive):
    (root / "pages" / "index.md").write_text(f"# Overview\n\n{directive}\n", encoding="utf-8")


def _page(root, slug="index"):
    project = _build_at(root)
    return project, next(p for p in project.pages if p.slug == slug)


def _cell_text(cell_html: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell_html)).strip()


def _calc_tables(body_html: str) -> list[list[list[str]]]:
    """Every `​<table class="calc">` in the page as text rows, in page order."""
    tables = re.findall(r'<table class="calc"[^>]*>.*?</table>', body_html, DOTALL)
    out = []
    for table in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)
        out.append(
            [[_cell_text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.DOTALL)]
             for r in rows]
        )
    return out


# ------------------------------------------------------------------- rendering


def test_calcblock_renders_owner_rows(calcblock_project):
    """§8.3's table, cell for cell, from the fixture.

    Sabotage: a renderer that pulled the `supply` rows in too, reformatted a
    result, or dropped the unit assertion renders different cells and fails.
    """
    _page_with_block(calcblock_project, DIRECTIVE)
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors

    assert _calc_tables(page.body_html) == [
        [
            ["P_out| W", "V_out * I_load", "3.96 W", ""],
            ["P_diss| W", "P_out * (1/eff - 1)", "0.2981 W", ""],
            ["A_board", "1.4 inch * 0.9 inch", "1.26 in\u00b2", ""],
            ["P_dens| W/in^2", "P_diss / A_board", "0.2366 W/in\u00b2", ""],
        ]
    ]
    # The `supply` rows are not here -- one directive, one named block (§5.4).
    # They may appear inside an expression (P_out = V_out * I_load), so the
    # assertion is about row *names*, which only a row can contribute.
    names = [row[0] for row in _calc_tables(page.body_html)[0]]
    for supply in ("V_in", "V_out", "I_load", "eff"):
        assert supply not in names


def test_calcblock_caption_names_owner_and_block(calcblock_project):
    """§5.4/§8.3: a caption line naming the owning item (linked) and the block.

    Sabotage: a caption without the link, or naming only one of the two, or a
    caption that replaced the table's own `losses` caption instead of riding
    above it, fails here.
    """
    _page_with_block(calcblock_project, DIRECTIVE)
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors

    caption = re.search(r'<p class="calcblock-caption">.*?</p>', page.body_html, DOTALL)
    assert caption, page.body_html
    assert 'href="dec-pwr-001.html"' in caption.group(0)
    assert "DEC-PWR-001" in caption.group(0)
    assert "losses" in caption.group(0)
    # The table keeps the owner's own anchor and caption: same call, same HTML.
    assert '<table class="calc" id="calc-losses">' in page.body_html
    assert '<caption class="calc-caption">losses</caption>' in page.body_html


def test_calcblock_two_directives_render_two_blocks(calcblock_project):
    """Q7 decided: no render-all mode -- two blocks is two directives (§5.4).

    Sabotage: an `all=`-style default, or a second directive that re-rendered
    the first block, changes the table count or their contents.
    """
    _page_with_block(
        calcblock_project,
        '{{calcblock item="DEC-PWR-001" block="supply"}}\n\n'
        '{{calcblock item="DEC-PWR-001" block="losses"}}',
    )
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors

    tables = _calc_tables(page.body_html)
    assert len(tables) == 2
    assert [row[0] for row in tables[0]] == ["V_in", "V_out", "I_load", "eff"]
    assert [row[0] for row in tables[1]] == [
        "P_out| W", "P_diss| W", "A_board", "P_dens| W/in^2",
    ]
    assert page.body_html.count('class="calcblock-caption"') == 2


def test_calcblock_renders_a_composite_item_ref(calcblock_project):
    """§5.4: `item=` accepts the DISPLAY-ID@key composite, resolved by key.

    Sabotage: a lookup that only ever tried the display id renders nothing for
    a composite whose label is stale; one that ignored the key half could not
    tell a stale label from a live key.
    """
    _build_at(calcblock_project)  # mint the keys the composite needs
    config = str(calcblock_project / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "build"]) == 0
    project = _build_at(calcblock_project)
    key = project.item_by_id("DEC-PWR-001").key
    assert key

    _page_with_block(calcblock_project, '{{calcblock item="DEC-PWR-001@%s" block="losses"}}' % key)
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors
    assert '<table class="calc" id="calc-losses">' in page.body_html


# --------------------------------------------------------------- never evaluates


def test_calcblock_never_evaluates(calcblock_project):
    """§5.4's load-bearing rule, pinned three ways.

    (1) The code-object pin: the renderer reads `item.calcs` and never touches
    an evaluation environment or the evaluator -- the same shape
    `test_compare_never_evaluates` makes.
    (2) The rows are the only source: rewriting a stored row changes the page,
    which no re-evaluating renderer could do.
    (3) An owner whose calc *fails* still renders, error row included, and the
    block adds no diagnostic of its own -- the failure is the owner's and the
    build already reported it at the owner's line.
    """
    code = blocks_mod._render_calcblock.__code__
    for evaluator in ("_env", "evaluate_block", "evaluate", "parse_limit", "resolver"):
        assert evaluator not in code.co_names, evaluator
    assert hasattr(calc_mod, "evaluate_block")  # the evaluator exists...
    assert "calcs" in code.co_names  # ...and this block does not use it

    _page_with_block(calcblock_project, DIRECTIVE)
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors
    assert "0.2981 W" in page.body_html

    item = project.item_by_id("DEC-PWR-001")
    next(line for line in item.calcs if line.name == "P_diss").result = "9.99 W"
    build_mod.render_pages(project)
    rebuilt = next(p for p in project.pages if p.slug == "index")
    assert "9.99 W" in rebuilt.body_html  # stored rows, not fresh arithmetic
    assert "0.2981 W" not in rebuilt.body_html


def test_calcblock_renders_the_owner_error_row(calcblock_project):
    """An owner whose calc failed renders its error row here, unchanged.

    Sabotage: a block that re-evaluated would produce a second failure at the
    page's line, or swallow the owner's error row, or substitute a verdict.
    """
    (calcblock_project / "items" / "dec-pwr-002.md").write_text(
        "---\nid: DEC-PWR-002\ntype: decision\ntitle: A failed calculation.\n---\n\n"
        '```calc id="oops"\nbad = missing_name * 2 | W\n```\n',
        encoding="utf-8",
    )
    _page_with_block(calcblock_project, '{{calcblock item="DEC-PWR-002" block="oops"}}')
    project, page = _page(calcblock_project)

    owner_errors = [d for d in project.errors if d.item_id == "DEC-PWR-002"]
    assert len(owner_errors) == 1, project.errors  # the owner's, at the owner's line
    page_errors = [d for d in project.errors if (d.file or "").endswith("index.md")]
    assert page_errors == []  # the block restates nothing (§5.4)

    assert '<tr class="calc-row calc-error">' in page.body_html
    assert "missing_name" in page.body_html
    for verdict in ("pass", "fail"):
        assert verdict not in page.body_html


# --------------------------------------------------------------------- §7 errors


def test_calcblock_unknown_block_lists_names(calcblock_project):
    """§7 verbatim: the error lists the names the item does have.

    Sabotage: a permissive fallback (render the first block, render all of
    them) or a message that omits the available names fails here.
    """
    _page_with_block(calcblock_project, '{{calcblock item="DEC-PWR-001" block="loess"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="DEC-PWR-001" block="loess"}} — '
        "'DEC-PWR-001' has no calc block named 'loess'. It names: losses, supply."
    )
    assert '<p class="block-error">' in page.body_html
    assert '<table class="calc"' not in page.body_html


def test_calcblock_item_without_calcs(calcblock_project):
    """§7 verbatim: an item that computes nothing has nothing to render."""
    _page_with_block(calcblock_project, '{{calcblock item="CMP-PWR-001" block="losses"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="CMP-PWR-001" block="losses"}} — '
        "CMP-PWR-001 has no calc blocks. calcblock renders a named "
        "```calc block; this item computes nothing."
    )
    assert '<table class="calc"' not in page.body_html


def test_calcblock_missing_block_param(calcblock_project):
    """§7 verbatim: `block` is required, and the error names the accepted set."""
    _page_with_block(calcblock_project, '{{calcblock item="DEC-PWR-001"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="DEC-PWR-001"}} — '
        "missing required parameter 'block'. calcblock accepts: block, item."
    )
    assert '<table class="calc"' not in page.body_html


def test_calcblock_missing_item_param(calcblock_project):
    """The same error shape with the other required parameter missing.

    Sabotage: a renderer that indexed params["item"] directly would raise
    KeyError out of the dispatch instead of a named parameter error.
    """
    _page_with_block(calcblock_project, '{{calcblock block="losses"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock block="losses"}} — '
        "missing required parameter 'item'. calcblock accepts: block, item."
    )
    assert '<table class="calc"' not in page.body_html


def test_calcblock_unknown_param(calcblock_project):
    """§7 verbatim: `all=` is refused by name -- the no-wildcard rule (§5.1(b))."""
    _page_with_block(
        calcblock_project, '{{calcblock item="DEC-PWR-001" block="losses" all="true"}}'
    )
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="DEC-PWR-001" block="losses" all="true"}} — '
        "unknown parameter 'all'. calcblock accepts: block, item."
    )
    assert '<table class="calc"' not in page.body_html


def test_calcblock_no_board_or_tag_param(calcblock_project):
    """Q7 decided: no board=/tag= narrowing either (§5.4, §11.7).

    Sabotage: adding a filtering parameter later would silently accept these;
    the closed parameter set is what makes the block's answer enumerable.
    """
    _page_with_block(
        calcblock_project,
        '{{calcblock item="DEC-PWR-001" block="losses" board="board-a"}}',
    )
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert "unknown parameter 'board'" in project.errors[0].message
    assert "calcblock accepts: block, item." in project.errors[0].message
    assert '<table class="calc"' not in page.body_html


def test_calcblock_item_that_does_not_exist(calcblock_project):
    """An unknown item is an error naming what it suggests, not a shrug.

    Sabotage: falling through to "has no calc blocks" would tell the author
    the wrong thing about a typo'd id.
    """
    _page_with_block(calcblock_project, '{{calcblock item="DEC-PWR-01" block="losses"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message.endswith(
        "DEC-PWR-01 does not exist. Did you mean 'DEC-PWR-001'?"
    )
    assert "has no calc blocks" not in project.errors[0].message
    assert '<table class="calc"' not in page.body_html


def test_calcblock_unnamed_blocks_only(calcblock_project):
    """An item that computes but names nothing gets §7's `#calc:` wording.

    Sabotage: "It names: " with an empty list, or silently rendering the
    unnamed block, both fail here.
    """
    _page_with_block(calcblock_project, '{{calcblock item="DEC-THM-009" block="losses"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="DEC-THM-009" block="losses"}} — '
        "DEC-THM-009 has calc blocks but none is named -- add id=\"...\" to "
        "its fence to make this block work."
    )
    assert '<table class="calc"' not in page.body_html


# ------------------------------------------------------------- local items only


def _import_upstream(root):
    """One imported component, carried the way `imports._absorb` carries it:
    no body, no calc blocks."""
    upstream = {
        "title": "Upstream",
        "version": "1",
        "items": [
            {
                "id": "CMP-X-001",
                "type": "component",
                "title": "Foreign part with a calculation upstream.",
                "fields": {"title": "Foreign part with a calculation upstream."},
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    (root / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    write_project_config(
        root,
        CALCBLOCK_SCHEMA
        + '\nimports:\n  - name: platform\n    items: upstream.json\n    version: "1"\n',
    )


def test_calcblock_imported_item_errors(calcblock_project):
    """§7 verbatim: an imported item is refused, not rendered."""
    _import_upstream(calcblock_project)
    _page_with_block(calcblock_project, '{{calcblock item="CMP-X-001" block="losses"}}')
    project, page = _page(calcblock_project)

    assert len(project.errors) == 1
    assert project.errors[0].message == (
        '{{calcblock item="CMP-X-001" block="losses"}} — '
        "'CMP-X-001' is an imported item. Imported items carry no calc blocks "
        "in this project; render the upstream project's own page instead."
    )
    assert '<table class="calc"' not in page.body_html


def test_calcblock_local_items_only(calcblock_project):
    """The imported item is refused *as imported*, never as "no calc blocks".

    Sabotage: an implementation that checked `item.calcs` before `external`
    would report the missing-calcs error and imply the author's own item is
    the problem; the upstream text must never be rendered here.
    """
    _import_upstream(calcblock_project)
    _page_with_block(calcblock_project, '{{calcblock item="CMP-X-001" block="losses"}}')
    project, page = _page(calcblock_project)

    assert project.item_by_id("CMP-X-001").external is True
    assert "imported item" in project.errors[0].message
    assert "has no calc blocks" not in project.errors[0].message
    assert "Foreign part with a calculation upstream." not in page.body_html


# ------------------------------------------------------------- block plumbing


def test_calcblock_unknown_block_name_untouched(calcblock_project):
    """`{{calcblockx}}` is not a block and must survive as literal text."""
    _page_with_block(calcblock_project, '{{calcblockx item="DEC-PWR-001" block="losses"}}')
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors
    assert "{{calcblockx item=" in page.body_html
    assert '<table class="calc"' not in page.body_html


def test_calcblock_directive_in_a_fenced_example_is_not_executed(calcblock_project):
    """A doc showing the directive is showing an example, not running it."""
    _page_with_block(calcblock_project, "```markdown\n" + DIRECTIVE + "\n```")
    project, page = _page(calcblock_project)
    assert not project.errors, project.errors
    assert '<table class="calc"' not in page.body_html
    assert '{{calcblock item=' in page.body_html


def test_calcblock_no_write_identical(calcblock_project):
    """§6.4/§5.4: `--no-write` renders byte-identical pages and writes nothing.

    Sabotage: a render path that mints a key, expands a reference, or mutates
    a stored row under a writable build makes the two site snapshots differ.
    """
    _page_with_block(calcblock_project, DIRECTIVE)
    config = str(calcblock_project / "refdes-project.yaml")

    assert cli_mod.main(["-c", config, "build"]) == 0
    site = calcblock_project / "_site"
    writable = {
        p.relative_to(site): p.read_bytes() for p in site.rglob("*") if p.is_file()
    }
    assert writable
    assert any(b'id="calc-losses"' in blob for blob in writable.values())

    assert cli_mod.main(["-c", config, "--no-write", "build"]) == 0
    no_write = {
        p.relative_to(site): p.read_bytes() for p in site.rglob("*") if p.is_file()
    }
    assert no_write == writable
