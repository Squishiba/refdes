"""The `{{compare}}` block (docs/design/candidate-parts.md §3, tests §9).

The fixture is §7's worked example: two bounds, four components (one with
nothing written about it at all), and the calc values that produce the
margins in the spec's rendered table.
"""

from __future__ import annotations

import html
import json
import re

import pytest
from conftest import write_project_config
from helpers import _build_at

from refdes import blocks as blocks_mod

# `component` declares exactly the six fields §3.7's error message lists, in
# that sorted order, and its status choices in the order that message lists.
COMPARE_SCHEMA = """\
site: {title: "Compare Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
types:
  bound:
    prefix: BND
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      limit:  { type: limit, required: true, on_change: invalidate }
      status: { type: enum, choices: [draft, active, retired], default: draft, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  component:
    prefix: CMP
    check_severity:
      candidate: info
      selected: error
      rejected: info
      obsolete: info
    fields:
      title:       { type: text, required: true, on_change: invalidate }
      part_number: { type: text, on_change: invalidate }
      refdes:      { type: list, on_change: ignore }
      rationale:   { type: text, on_change: invalidate }
      status:      { type: enum, choices: [candidate, selected, rejected, obsolete], default: candidate, on_change: invalidate }
      checks:      { type: checks, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true, on_change: invalidate }
    links: {}
    body: { on_change: invalidate }
"""

BOUNDS = """\
defaults: { type: bound, status: active }
items:
  - id: BND-PWR-011
    title: Output current at 3V3
    limit: ">= 3 A"
  - id: BND-PWR-012
    title: Standby quiescent budget
    limit: "<= 500 uA"
"""

REQUIREMENT = """\
---
id: REQ-PWR-004
type: requirement
text: The rail must source its rated current at temperature.
---
"""


def _component(item_id, *, status, part_number=None, rationale=None, calc="", checks=()):
    front = [
        "---",
        f"id: {item_id}",
        "type: component",
        f"title: Candidate {item_id.rsplit('-', 1)[-1]}.",
    ]
    if part_number:
        front.append(f"part_number: {part_number}")
    front.append(f"status: {status}")
    if rationale:
        front.append(f"rationale: {rationale}")
    if checks:
        front.append("checks:")
        front.extend(checks)
    front.append("---")
    body = f"\n```calc\n{calc}\n```\n" if calc else "\n"
    return "\n".join(front) + body


_CHECKS_BOTH = [
    "  - value: I_out",
    "    against: BND-PWR-011",
    "  - value: I_q",
    "    against: BND-PWR-012",
]

# File names sort so that load order (016, 014, 015, 017) differs from ID
# order, which `test_compare_rows_sorted_by_id` pins.
COMPARE_ITEMS = {
    "m-cmp-pwr-016.md": _component(
        "CMP-PWR-016",
        status="rejected",
        part_number="LM2596S-ADJ",
        calc="I_out = 3 A | A\nI_q = 5 mA | mA",
        checks=_CHECKS_BOTH,
    ),
    "a-cmp-pwr-014.md": _component(
        "CMP-PWR-014",
        status="selected",
        part_number="MP1584EN-LF-Z",
        calc="I_out = 3 A | A\nI_q = 60 uA | uA",
        checks=_CHECKS_BOTH,
    ),
    "z-cmp-pwr-015.md": _component(
        "CMP-PWR-015",
        status="rejected",
        part_number="TPS562200DDCR",
        rationale="Cheaper, but cannot meet the current bound.",
        calc="I_out = 2 A | A\nI_q = 17 uA | uA",
        checks=_CHECKS_BOTH,
    ),
    "b-cmp-pwr-017.md": _component("CMP-PWR-017", status="candidate"),
}

FULL_DIRECTIVE = (
    '{{compare type="component"'
    ' columns="part_number, status, calc:I_out, calc:I_q"'
    ' against="BND-PWR-011, BND-PWR-012"}}'
)


@pytest.fixture
def compare_project(tmp_path):
    write_project_config(tmp_path, COMPARE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bounds.yaml").write_text(BOUNDS, encoding="utf-8")
    (items / "req-004.md").write_text(REQUIREMENT, encoding="utf-8")
    for name, text in COMPARE_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "pages").mkdir()
    return tmp_path


def _page_with_block(root, directive):
    (root / "pages" / "index.md").write_text(f"# Overview\n\n{directive}\n", encoding="utf-8")


def _compare_page(root):
    project = _build_at(root)
    page = next(p for p in project.pages if p.slug == "index")
    return project, page


def _cell_text(cell_html: str) -> str:
    """A cell as an author would read it: tags gone, entities resolved."""
    return html.unescape(re.sub(r"<[^>]+>", "", cell_html)).strip()


def _table_rows(body_html: str) -> list[list[str]]:
    table = re.search(r'<table class="compare-table">.*?</table>', body_html, re.DOTALL)
    assert table, "no compare table in the rendered page"
    rows = re.findall(r"<tr>(.*?)</tr>", table.group(0), re.DOTALL)
    return [[_cell_text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.DOTALL)] for r in rows]


# ------------------------------------------------------------------ rendering


def test_compare_renders_pass_and_fail_columns(compare_project):
    """The §7 table, cell for cell.

    The bound headers carry the limit as authored (`>= 3 A`), not a
    typographic re-spelling: §3.2 makes "the block never parses a limit" the
    load-bearing rule, so the header is the only place the author's own text
    survives unchanged.
    """
    _page_with_block(compare_project, FULL_DIRECTIVE)
    project, page = _compare_page(compare_project)
    assert not project.errors

    assert _table_rows(page.body_html) == [
        ["ID", "part_number", "status", "I_out", "I_q",
         "BND-PWR-011 >= 3 A", "BND-PWR-012 <= 500 uA", "Checks"],
        ["CMP-PWR-014", "MP1584EN-LF-Z", "selected", "3 A", "60 \u00b5A",
         "pass 0%", "pass +88%", "2/2"],
        ["CMP-PWR-015", "TPS562200DDCR", "rejected", "2 A", "17 \u00b5A",
         "fail \u221233%", "pass +97%", "1/2"],
        ["CMP-PWR-016", "LM2596S-ADJ", "rejected", "3 A", "5 mA",
         "pass 0%", "fail \u2212900%", "1/2"],
        ["CMP-PWR-017", "\u2014", "candidate", "\u2014", "\u2014",
         "\u2014", "\u2014", "\u2014"],
    ]


def test_compare_missing_values_are_em_dash(compare_project):
    """Unset field, undefined calc, and undeclared check all render `\u2014`.

    Never blank, never `0`, never `None`: an empty cell reads as "no", and
    "nobody wrote it down" is a different finding (\u00a73.5)."""
    _page_with_block(compare_project, FULL_DIRECTIVE)
    project, page = _compare_page(compare_project)
    assert not project.errors

    row = next(r for r in _table_rows(page.body_html) if r[0] == "CMP-PWR-017")
    assert row == ["CMP-PWR-017", "\u2014", "candidate"] + ["\u2014"] * 5
    assert '<td class="compare-missing">\u2014</td>' in page.body_html
    for not_allowed in ("None", "<td></td>", "<td>0</td>"):
        assert not_allowed not in page.body_html


def test_compare_never_evaluates(compare_project):
    """A calc value that exists but was never checked shows `\u2014`, not a verdict.

    The value is in the row (`I_out` renders), and it would pass the bound if
    the block evaluated it -- but `run_checks` produced no result, so the
    block has no verdict to print (\u00a73.2). The code-object check is the pin
    that prose cannot make: the renderer never reads an item's raw calc
    environment and never parses a limit.
    """
    (compare_project / "items" / "c-cmp-pwr-018.md").write_text(
        _component("CMP-PWR-018", status="candidate", part_number="TPS563200",
                   calc="I_out = 3 A | A"),
        encoding="utf-8",
    )
    _page_with_block(compare_project, FULL_DIRECTIVE)
    project, page = _compare_page(compare_project)
    assert not project.errors

    row = next(r for r in _table_rows(page.body_html) if r[0] == "CMP-PWR-018")
    assert row[3] == "3 A"  # the calc value is there...
    assert row[5] == "\u2014"  # ...and the bound column is not
    assert row[7] == "\u2014"  # no checks at all, so no score either

    from refdes import calc as calc_mod

    code = blocks_mod._render_compare.__code__
    assert "_env" not in code.co_names
    assert hasattr(calc_mod, "parse_limit")  # the parser exists...
    assert "parse_limit" not in code.co_names  # ...and this block does not use it
    assert "calc_values" in code.co_names  # formatted results are the only source


def test_compare_rows_sorted_by_id(compare_project):
    """File order, status order, and margin order all differ from ID order."""
    _page_with_block(compare_project, FULL_DIRECTIVE)
    project, page = _compare_page(compare_project)
    assert not project.errors

    loaded = [i.id for i in project.local_items if i.type == "component"]
    assert loaded != sorted(loaded)  # the fixture really is scrambled

    ids = [r[0] for r in _table_rows(page.body_html)][1:]
    assert ids == ["CMP-PWR-014", "CMP-PWR-015", "CMP-PWR-016", "CMP-PWR-017"]


def test_compare_no_sort_parameter(compare_project):
    """`sort=` is refused by name, with the accepted set spelled out (\u00a73.3)."""
    _page_with_block(compare_project, '{{compare type="component" sort="margin"}}')
    project, page = _compare_page(compare_project)

    assert len(project.errors) == 1
    assert "unknown parameter 'sort'" in project.errors[0].message
    assert "compare accepts: against, board, columns, status, subtypes, tag, type." in (
        project.errors[0].message
    )
    assert "compare-table" not in page.body_html


# -------------------------------------------------------------------- errors


def test_compare_unknown_type_field_status_and_bound(compare_project):
    """The four \u00a73.7 errors, message for message."""
    _page_with_block(
        compare_project,
        "\n\n".join(
            [
                '{{compare type="compnent"}}',
                '{{compare type="component" columns="Iout"}}',
                '{{compare type="component" against="REQ-PWR-004"}}',
                '{{compare type="component" status="maybe"}}',
            ]
        ),
    )
    project, _page = _compare_page(compare_project)

    messages = [d.message for d in project.errors]
    assert len(messages) == 4
    assert any("unknown type 'compnent'. Did you mean 'component'?" in m for m in messages)
    # \u00a73.4 pins this to "the same message shape {{index}} produces", and
    # {{index}} lists declared fields sorted (`blocks.py`); the spec's own
    # example happens to write refdes before rationale, which is not a sort.
    assert any(
        "type 'component' has no field 'Iout'. Declared fields: checks, part_number, "
        "rationale, refdes, status, title.\nFor a calc value, write calc:Iout." in m
        for m in messages
    )
    assert any(
        "'REQ-PWR-004' declares no limit. compare's against= needs a bound "
        "(a type with a 'limit' field)." in m
        for m in messages
    )
    assert any(
        "type 'component' has no status 'maybe'. Declared choices: candidate, "
        "selected, rejected, obsolete." in m
        for m in messages
    )


def test_compare_type_without_checks_field_errors(compare_project):
    """A type with no `checks:` field cannot be compared -- an empty column
    set is not a result (\u00a73.7)."""
    _page_with_block(compare_project, '{{compare type="requirement" against="BND-PWR-011"}}')
    project, page = _compare_page(compare_project)

    assert len(project.errors) == 1
    assert project.errors[0].message.endswith(
        "type 'requirement' declares no 'checks' field, so there is nothing to "
        "compare against BND-PWR-011. Drop against=, or compare a type that "
        "declares checks."
    )
    assert "compare-table" not in page.body_html


def test_compare_warns_on_unchecked_bound(compare_project):
    """A bound no row checks against is a warning naming the bound and the
    page -- not an error, and not silence (\u00a73.7)."""
    (compare_project / "items" / "bnd-013.md").write_text(
        "---\nid: BND-PWR-013\ntype: bound\nstatus: active\n"
        'title: Switching frequency ceiling\nlimit: "<= 2 MHz"\n---\n',
        encoding="utf-8",
    )
    _page_with_block(
        compare_project,
        '{{compare type="component" against="BND-PWR-011, BND-PWR-013"}}',
    )
    project, _page = _compare_page(compare_project)

    assert not project.errors
    warnings = [d for d in project.warnings if "checks: entry against" in d.message]
    assert len(warnings) == 1
    assert warnings[0].message == (
        "no component in this selection has a checks: entry against BND-PWR-013. "
        "Its column will be empty."
    )
    assert warnings[0].file and warnings[0].file.endswith("index.md")


# -------------------------------------------------------------- block plumbing


def test_compare_unknown_block_name_untouched(compare_project):
    """`{{comparex}}` is not a block and must survive as literal text."""
    _page_with_block(compare_project, '{{comparex type="component"}}')
    project, page = _compare_page(compare_project)
    assert not project.errors
    assert '{{comparex type=' in page.body_html
    assert "compare-table" not in page.body_html


def test_compare_empty_selection_is_a_paragraph(compare_project):
    """No matching rows is a paragraph, not an empty table, and not a failure."""
    from refdes import cli as cli_mod

    _page_with_block(compare_project, '{{compare type="component" status="obsolete"}}')
    status = cli_mod.main(["-c", str(compare_project / "refdes-project.yaml"), "build"])

    assert status == 0
    project = next(
        p for p in [_build_at(compare_project)] if p is not None
    )
    page = next(p for p in project.pages if p.slug == "index")
    assert '<p class="compare-empty">No component items.</p>' in page.body_html
    assert "compare-table" not in page.body_html


def test_compare_no_write_identical(compare_project):
    """`--no-write` renders the same bytes and leaves the source tree alone."""
    import hashlib

    from refdes import cli as cli_mod

    config = str(compare_project / "refdes-project.yaml")
    _page_with_block(compare_project, FULL_DIRECTIVE)

    def snapshot() -> dict[str, str]:
        hashes = {}
        for path in sorted(compare_project.rglob("*")):
            if not path.is_file() or "_site" in path.parts:
                continue
            rel = path.relative_to(compare_project).as_posix()
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def rendered_page() -> bytes:
        out = compare_project / "_site" / "index.html"
        return out.read_bytes() if out.exists() else b""

    before = snapshot()
    assert cli_mod.main(["-c", config, "--no-write", "build"]) == 0
    dry_page = rendered_page()
    assert b"compare-table" in dry_page
    assert snapshot() == before  # nothing in the source tree changed

    assert cli_mod.main(["-c", config, "build"]) == 0
    wet_page = rendered_page()
    assert dry_page == wet_page


def test_compare_local_rows_only(compare_project):
    """An imported component is not a row; an imported bound is a column."""
    upstream = {
        "title": "Upstream",
        "version": "1",
        "items": [
            {
                "id": "CMP-X-001",
                "type": "component",
                "title": "Foreign candidate.",
                "fields": {
                    "title": "Foreign candidate.",
                    "part_number": "MP1584EN-LF-Z",
                    "status": "selected",
                },
                "links": {},
                "content_hash": "upstreamhash01",
            },
            {
                "id": "BND-X-009",
                "type": "bound",
                "title": "Foreign bound.",
                "fields": {"title": "Foreign bound.", "limit": "<= 12 V", "status": "active"},
                "links": {},
                "content_hash": "upstreamhash02",
            },
        ],
    }
    (compare_project / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    write_project_config(
        compare_project,
        COMPARE_SCHEMA
        + '\nimports:\n  - name: platform\n    items: upstream.json\n    version: "1"\n',
    )
    _page_with_block(
        compare_project,
        '{{compare type="component" columns="part_number" against="BND-PWR-011, BND-X-009"}}',
    )
    project, page = _compare_page(compare_project)
    assert not project.errors

    rows = _table_rows(page.body_html)
    assert [r[0] for r in rows][1:] == [
        "CMP-PWR-014",
        "CMP-PWR-015",
        "CMP-PWR-016",
        "CMP-PWR-017",
    ]
    assert "CMP-X-001" not in page.body_html
    assert rows[0][-2] == "BND-X-009 <= 12 V"  # imported bound is still a column
