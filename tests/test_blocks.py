"""generated blocks -- and: ls (finding 9).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json

import pytest
from helpers import BLOCKS_SCHEMA, _build_at, _numeric_hint_project

from refdes import cli as cli_mod


def _page_with_block(project_root, directive):
    (project_root / "pages" / "index.md").write_text(
        f"# Overview\n\n{directive}\n", encoding="utf-8"
    )


def _index_page(blocks_project):
    project = _build_at(blocks_project)
    page = next(p for p in project.pages if p.slug == "index")
    return project, page


def test_index_groups_by_enum_in_declared_choices_order(blocks_project):
    """Heading order follows `choices:` (proposed, accepted, on_hold), not
    alphabetical (accepted, on_hold, proposed) -- a distinguishing case."""
    _page_with_block(blocks_project, '{{index by="status" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    headings = [h for h in ["proposed", "accepted", "on_hold"] if f"<h4>{h}</h4>" in page.body_html]
    positions = [page.body_html.index(f"<h4>{h}</h4>") for h in headings]
    assert positions == sorted(positions)
    assert headings == ["proposed", "accepted", "on_hold"]
    assert "DEC-002" in page.body_html  # proposed
    assert "DEC-001" in page.body_html  # accepted
    assert "DEC-003" in page.body_html  # on_hold


def test_index_groups_by_text_field_lexicographically_with_unset_last(blocks_project):
    """`schematic_page` is text, not a number: "12" < "7" lexicographically.
    A decision with no schematic_page value groups under (unset), sorted last."""
    (blocks_project / "items" / "dec-004.md").write_text(
        "---\nid: DEC-004\ntype: decision\ntitle: No page yet.\n---\n", encoding="utf-8"
    )
    _page_with_block(blocks_project, '{{index by="schematic_page" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    order = [h for h in ["12", "7", "(unset)"] if f"<h4>{h}</h4>" in page.body_html]
    assert order == ["12", "7", "(unset)"]


def test_index_list_valued_field_files_item_under_every_value(blocks_project):
    _page_with_block(blocks_project, '{{index by="tags" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "<h4>layout</h4>" in page.body_html
    assert "<h4>review</h4>" in page.body_html
    # DEC-001 (tags: [layout, review]) appears under both headings -- the ID
    # cell's text is picked up by the page's own _linkify pass for free, so
    # each appearance is both an href and the link text: 2 headings x 2.
    assert page.body_html.count("DEC-001") == 4
    assert page.body_html.count('href="dec-001.html"') == 2


def test_index_board_scoping(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" board="thermal"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-003" in page.body_html
    assert "DEC-001" not in page.body_html
    assert "DEC-002" not in page.body_html


def test_index_empty_result_is_not_an_error(blocks_project):
    # TST-001 has no board, so board="thermal" matches zero test items.
    _page_with_block(blocks_project, '{{index by="title" type="test" board="thermal"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "No test items." in page.body_html


def test_index_unknown_type_suggests_a_correction(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decisoin"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown type 'decisoin'" in d.message and "Did you mean 'decision'?" in d.message
        for d in project.errors
    )


def test_index_unknown_field_names_declared_fields(blocks_project):
    _page_with_block(blocks_project, '{{index by="pageno" type="decision"}}')
    project, _page = _index_page(blocks_project)
    msg = next(d.message for d in project.errors if "has no field" in d.message)
    assert "no field 'pageno'" in msg
    assert "schematic_page" in msg


def test_index_non_groupable_field_type_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{index by="checks" type="decision"}}')
    project, _page = _index_page(blocks_project)
    assert any("not a groupable field" in d.message for d in project.errors)


def test_index_unknown_board_suggests_a_correction(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" board="powr"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown board 'powr'" in d.message and "Did you mean 'power'?" in d.message
        for d in project.errors
    )


def test_index_unknown_parameter_names_accepted_ones(blocks_project):
    _page_with_block(blocks_project, '{{index by="status" type="decision" sortt="asc"}}')
    project, _page = _index_page(blocks_project)
    msg = next(d.message for d in project.errors if "unknown parameter" in d.message)
    assert "'sortt'" in msg
    assert "by, type, board" in msg


def test_index_missing_required_parameter_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{index type="decision"}}')
    project, _page = _index_page(blocks_project)
    assert any("missing required parameter 'by'" in d.message for d in project.errors)


def test_block_directive_inside_a_fenced_code_example_is_not_executed(blocks_project):
    """A doc showing "here's how you write {{index ...}}" inside a fenced
    example must render that line as literal example text, not run it as a
    live directive -- the trap docs/blocks.md's own examples originally fell
    into (extraction happens on raw markdown before md.render, so it has no
    idea a fence is present unless it looks for one itself)."""
    _page_with_block(
        blocks_project,
        '```markdown\n{{index by="status" type="decision"}}\n```',
    )
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "index-table" not in page.body_html
    assert "{{index by=" in page.body_html  # survives, HTML-escaped, inside <pre><code>


def test_unrecognized_block_name_passes_through_as_literal_text(blocks_project):
    _page_with_block(blocks_project, '{{TBD some note to self}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "{{TBD some note to self}}" in page.body_html


def test_index_only_local_items_not_imports(blocks_project):
    """An imported item must never appear in a project-generated index --
    that is what makes the block trustworthy as *this* project's own view."""

    upstream = {
        "title": "Upstream",
        "version": "1",
        "items": [
            {
                "id": "DEC-X-001",
                "type": "decision",
                "title": "Foreign.",
                "fields": {"title": "Foreign.", "status": "accepted"},
                "links": {},
                "content_hash": "upstreamhash01",
            }
        ],
    }
    (blocks_project / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
    schema = BLOCKS_SCHEMA + (
        '\nimports:\n  - name: platform\n    items: upstream.json\n    version: "1"\n'
    )
    (blocks_project / "refdes.yaml").write_text(schema, encoding="utf-8")
    _page_with_block(blocks_project, '{{index by="status" type="decision"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-X-001" in project.items  # imported, resolvable...
    assert "DEC-X-001" not in page.body_html  # ...but never in a generated index


# --------------------------------------------------------------- ls (finding 9)


def test_ls_lists_every_local_item(blocks_project, capsys):
    status = cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls"])
    assert status == 0
    out = capsys.readouterr().out
    for item_id in ("DEC-001", "DEC-002", "DEC-003", "REQ-001", "CMP-001", "TST-001"):
        assert item_id in out


def test_ls_filters_by_type(blocks_project, capsys):
    cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls", "--type", "decision"])
    out = capsys.readouterr().out
    assert "DEC-001" in out and "DEC-002" in out and "DEC-003" in out
    assert "REQ-001" not in out and "CMP-001" not in out


def test_ls_filters_by_board(blocks_project, capsys):
    cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls", "--board", "power"])
    out = capsys.readouterr().out
    assert "DEC-001" in out and "DEC-002" in out
    assert "DEC-003" not in out  # on the thermal board, not power


def test_ls_filters_by_tag(blocks_project, capsys):
    """DEC-001 (tags: [layout, review]) and DEC-002 (tags: [review]) both
    carry the review tag; DEC-003 has no tags: of its own at all."""
    cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls", "--tag", "review"])
    out = capsys.readouterr().out
    assert "DEC-001" in out and "DEC-002" in out
    assert "DEC-003" not in out


def test_ls_free_text_matches_tags_not_just_title(blocks_project, capsys):
    """'layout' appears in DEC-001's tags:, not in its title -- free text
    has to reach tags: for this to mean anything (finding 9's whole point)."""
    cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls", "layout"])
    out = capsys.readouterr().out
    assert "DEC-001" in out
    assert "DEC-002" not in out
    assert "DEC-003" not in out


def test_ls_filters_by_source_file(blocks_project, capsys):
    cli_mod.main(["-c", str(blocks_project / "refdes.yaml"), "ls", "--file", "items/dec-001.md"])
    out = capsys.readouterr().out
    assert "DEC-001" in out
    assert "DEC-002" not in out


def test_ls_no_match_reports_cleanly_and_exits_zero(blocks_project, capsys):
    status = cli_mod.main(
        ["-c", str(blocks_project / "refdes.yaml"), "ls", "no-such-thing-anywhere"]
    )
    assert status == 0
    assert "no items match" in capsys.readouterr().out


def test_ls_omits_the_board_column_when_the_project_has_no_boards(tmp_path, capsys):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-001\n    text: A plain requirement.\n",
    )
    cli_mod.main(["-c", str(root / "refdes.yaml"), "ls"])
    out = capsys.readouterr().out
    assert "CAN-001" in out
    assert "requirement" in out


def test_cascade_up_follows_declared_links_within_trace_true_default(blocks_project):
    """`selects` is `trace: false` in this schema, so it's excluded from the
    default `via=` set -- CMP-001 must not appear."""
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "REQ-001" in page.body_html
    assert "CON-001" in page.body_html
    assert "CMP-001" not in page.body_html


def test_cascade_explicit_via_can_include_a_non_traced_link(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up" via="selects"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "CMP-001" in page.body_html
    assert "REQ-001" not in page.body_html


def test_cascade_down_follows_backlinks(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-001" direction="down"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "DEC-001" in page.body_html  # satisfied_by
    assert "TST-001" in page.body_html  # verified_by


def test_cascade_both_renders_two_labeled_branches(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-001" direction="both"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert ">Upward<" in page.body_html
    assert ">Downward<" in page.body_html
    assert "DEC-001" in page.body_html


def test_cascade_depth_limits_the_walk(blocks_project):
    # DEC-002 has no outgoing links, so depth=1 from it should show nothing.
    _page_with_block(blocks_project, '{{cascade from="DEC-002" direction="up" depth="1"}}')
    project, page = _index_page(blocks_project)
    assert not project.errors
    assert "nothing found" in page.body_html


def test_cascade_unknown_root_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="REQ-999" direction="up"}}')
    project, _page = _index_page(blocks_project)
    assert any("REQ-999 does not exist" in d.message for d in project.errors)


def test_cascade_unknown_direction_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="sideways"}}')
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown direction 'sideways'" in d.message and "down, up, both" in d.message
        for d in project.errors
    )


def test_cascade_missing_required_parameter_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001"}}')
    project, _page = _index_page(blocks_project)
    assert any("missing required parameter 'direction'" in d.message for d in project.errors)


def test_cascade_unknown_via_link_type_suggests_a_correction(blocks_project):
    _page_with_block(
        blocks_project, '{{cascade from="DEC-001" direction="up" via="satisfyes"}}'
    )
    project, _page = _index_page(blocks_project)
    assert any(
        "unknown link type 'satisfyes'" in d.message and "Did you mean 'satisfies'?" in d.message
        for d in project.errors
    )


def test_cascade_non_positive_depth_is_an_error(blocks_project):
    _page_with_block(blocks_project, '{{cascade from="DEC-001" direction="up" depth="0"}}')
    project, _page = _index_page(blocks_project)
    assert any("depth must be a positive integer" in d.message for d in project.errors)


DIAMOND_SCHEMA = """\
site: {title: "Diamond Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
link_types:
  next: { inverse: prev, label: "Next" }
types:
  node:
    prefix: NODE
    fields:
      title: { type: text, required: true }
    links:
      next: [node]
"""


@pytest.fixture
def diamond_project(tmp_path):
    (tmp_path / "refdes.yaml").write_text(DIAMOND_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    # NODE-001 -> NODE-002 -> NODE-004, NODE-001 -> NODE-003 -> NODE-004:
    # two paths reconverge on NODE-004.
    graph = {
        "NODE-001": ("Root", ["NODE-002", "NODE-003"]),
        "NODE-002": ("Left", ["NODE-004"]),
        "NODE-003": ("Right", ["NODE-004"]),
        "NODE-004": ("Sink", []),
    }
    for node_id, (title, targets) in graph.items():
        next_yaml = f"next: [{', '.join(targets)}]\n" if targets else ""
        (items / f"{node_id.lower()}.md").write_text(
            f"---\nid: {node_id}\ntype: node\ntitle: {title}\n{next_yaml}---\n",
            encoding="utf-8",
        )
    (tmp_path / "pages").mkdir()
    return tmp_path


def test_cascade_marks_a_reconverged_node_already_shown(diamond_project):
    _page_with_block(diamond_project, '{{cascade from="NODE-001" direction="up"}}')
    project, page = _index_page(diamond_project)
    assert not project.errors
    # Rendered twice (once fully, once as the reconverged leaf) -- the page's
    # own _linkify pass also bare-links each occurrence's plain-text id, so
    # 'data-ref="NODE-004"' is the reliable count, not the raw substring.
    assert page.body_html.count('data-ref="NODE-004"') == 2
    assert page.body_html.count("already shown above") == 1
