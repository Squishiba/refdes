"""Navis slice 1 (in-prog-logs/navis-design-20261025.md §13 slice 1).

Grammar (design §4), body scan producing `Item.navis`, malformed-marker
diagnostics (`model.Diagnostic`), site-consumption of markers, the hash
invariants (§7), and the `index` payload's `navis` key (absent-key
convention). Slice 1 is read-only: nothing mints keys, no archive store.

The binding invariants tested here:
* a marker is one closed `<!--navi:…-->` comment on one line, outside
  fenced code, indented code, inline code spans and open HTML comments;
* a malformed marker is a warning diagnostic at its line, never swallowed
  (the codebase's stated policy, build.py:66-68);
* adding the scan changes no content hash / calc_hash / seal input: the
  scan never mutates `Item.body`, and a build with the scan step disabled
  hashes byte-identically (proved by monkeypatching the step to a no-op);
* the marker bytes are consumed from published HTML (design §4: the
  comment is inert text to the renderer, so the scan strips it before
  `md.render`, the way calc fences are placeholder-swapped);
* `navis` in the `index` payload follows the "absent key, not null"
  convention, so a Navi-free project's payload stays byte-identical.
"""

from __future__ import annotations

import json

from conftest import write_project_config

from refdes import build as build_mod
from refdes import loader, navis, render
from refdes.model import Project

SCHEMA = """\
site: { title: Navis Test, out: _site }
on_change: { default: invalidate }
types:
  note:
    prefix: NOTE
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: invalidate }
  memo:
    prefix: MEMO
    fields:
      title: { type: text, required: true, on_change: invalidate }
    body: { on_change: ignore }
"""


def _md(id_: str, type_: str, title: str, body: str) -> str:
    return f"---\nid: {id_}\ntype: {type_}\ntitle: {title}\n---\n{body}"


def _project(tmp_path, files: dict[str, str]) -> Project:
    config = write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    project, _stale = loader.load_tree(str(config), write=False)
    build_mod.build(project, seal_write=False)
    return project


# ---------------------------------------------------------------- scan grammar


def test_scan_keyless_marker():
    found, bad = navis.scan_body("before\n<!--navi: remember the copper thing-->\nafter")
    assert bad == []
    assert len(found) == 1
    assert found[0].key == ""
    assert found[0].text == "remember the copper thing"
    assert found[0].line_offset == 1


def test_scan_two_markers_on_one_line():
    # The design's "One line, always" rule (§4) binds each marker to one
    # line (CRLF safety, exact line reporting, panel row a sentence); it
    # does not bind a line to one marker. The first `-->` closes the first
    # marker, and a second closed marker on the same line is its own Navi.
    found, bad = navis.scan_body("<!--navi: first--><!--navi: second-->")
    assert bad == []
    assert [(n.text, n.line_offset) for n in found] == [("first", 0), ("second", 0)]
    assert navis.strip_markers("<!--navi: first--><!--navi: second--> tail") == "tail"


def test_scan_keyed_marker():
    found, bad = navis.scan_body("<!--navi:k7f3q2x8d0m Model worst-case copper temperature.-->")
    assert bad == []
    assert found[0].key == "k7f3q2x8d0m"
    assert found[0].text == "Model worst-case copper temperature."
    assert found[0].line_offset == 0


def test_scan_multiple_markers_line_offsets():
    body = "a\n<!--navi: one-->\nb\n<!--navi: two-->\n<!--navi: three-->"
    found, bad = navis.scan_body(body)
    assert bad == []
    assert [n.text for n in found] == ["one", "two", "three"]
    assert [n.line_offset for n in found] == [1, 3, 4]


def test_marker_is_one_line_only():
    # Grammar §4: one line, always. A marker that *closes* on a later
    # line was never a marker: it is a warning naming the opening line.
    # A `<!--navi:` that never closes is the existing unclosed-comment
    # machinery's territory (build.py), not this one.
    found, bad = navis.scan_body("<!--navi: spans\ntwo lines-->\n")
    assert found == []
    assert bad == [(0, ("navi marker spans lines; a marker is one line: "
                        "`<!--navi: the reminder-->`"))]


def test_malformed_empty_text_is_a_warning():
    found, bad = navis.scan_body("text\n<!--navi:  -->\nmore")
    assert found == []
    assert len(bad) == 1
    assert bad[0][0] == 1
    assert "no text" in bad[0][1]


def test_malformed_key_alphabet_is_a_warning():
    # An 11-character key-shaped head in the wrong alphabet is reported,
    # never silently read as text (report-on-typo posture).
    found, bad = navis.scan_body("<!--navi:K7F3Q2X8D0M text-->")
    assert found == []
    assert len(bad) == 1
    assert "key alphabet" in bad[0][1]


def test_malformed_key_with_empty_text():
    found, bad = navis.scan_body("<!--navi:k7f3q2x8d0m-->")
    assert found == []
    assert len(bad) == 1
    assert "no text" in bad[0][1]


def test_short_token_is_text_not_a_key():
    # 10 characters is not key-shaped; the whole thing is a keyless Navi.
    found, bad = navis.scan_body("<!--navi:k7f3q2x8d0 Model the thing-->")
    assert bad == []
    assert found[0].key == ""
    assert found[0].text == "k7f3q2x8d0 Model the thing"


def test_marker_text_keeps_grammar_edges():
    # Text may contain colons, references, braces, arrows-as-bytes; only
    # `-->` terminates the marker.
    found, bad = navis.scan_body("<!--navi: see REQ-001 {{temp}} a:b [x] < b-->")
    assert bad == []
    assert found[0].text == "see REQ-001 {{temp}} a:b [x] < b"


def test_nested_marker_first_close_wins():
    # Comments do not nest; the first `-->` terminates (same rule as the
    # inline-calc comment tracking).
    found, bad = navis.scan_body("<!--navi: a <!--navi: b--> tail")
    assert bad == []
    assert len(found) == 1
    assert found[0].text == "a <!--navi: b"


def test_marker_inside_fenced_code_is_inert():
    body = "text\n```\n<!--navi: in a fence-->\n```\n"
    found, bad = navis.scan_body(body)
    assert found == []
    assert bad == []


def test_marker_inside_tilde_fence_is_inert():
    body = "~~~\n<!--navi: in a fence-->\n~~~\n"
    found, bad = navis.scan_body(body)
    assert found == []
    assert bad == []


def test_marker_inside_inline_code_is_inert():
    # Code spans are literal text (design §4 inertness inventory): the
    # marker in a code span is prose about markers, not a Navi.
    found, bad = navis.scan_body("write `<!--navi: text-->` to add a Navi")
    assert found == []
    assert bad == []


def test_marker_inside_html_comment_is_inert():
    found, bad = navis.scan_body("<!-- a comment <!--navi: x--> more -->")
    assert found == []
    assert bad == []


def test_marker_line_with_span_after_closed_comment():
    # An inert comment that closes mid-line does not shield a later
    # marker on the same line.
    found, bad = navis.scan_body("<!-- plain --> <!--navi: real-->")
    assert len(found) == 1
    assert found[0].text == "real"
    assert bad == []


def test_marker_in_indented_code_is_inert():
    body = "para\n\n    <!--navi: indented code-->\n"
    found, bad = navis.scan_body(body)
    assert found == []
    assert bad == []


def test_scan_handles_unicode_and_long_lines():
    long_text = "x" * 5000
    body = f"<!--navi: Ω µ ± {long_text}-->\n"
    found, bad = navis.scan_body(body)
    assert bad == []
    assert found[0].text.startswith("Ω µ ±")
    assert len(found[0].text) == len(long_text) + 6


# ------------------------------------------------------------------- stripping


def test_strip_markers_noop_is_the_same_string():
    body = "no markers\njust text\n"
    assert navis.strip_markers(body) is body


def test_title_projection_carries_no_marker_bytes(tmp_path):
    # F14-4: the title of a marker-bearing item (when the title is the body
    # fallback, i.e. no title field) is a projection of the body, so it must
    # not carry marker bytes -- the list page's summary column, the tree,
    # the hover preview and the item page's <h1> all read it.
    project = _project(
        tmp_path,
        {
            "note-001.md": (
                "---\nid: NOTE-001\ntype: note\n---\n\n"
                "<!--navi: check the copper temperature-->\n"
                "The stage power is 0.30 W and this is a long enough body to project.\n"
            )
        },
    )
    item = project.item_by_id("NOTE-001")
    assert "navi" not in item.title
    assert item.title.startswith("The stage power")


def test_title_projection_unchanged_for_a_no_marker_item(tmp_path):
    # Byte-identity: an item with no markers titles exactly as before.
    project = _project(
        tmp_path,
        {
            "note-001.md": (
                "---\nid: NOTE-001\ntype: note\n---\n\n"
                "The stage power is 0.30 W and this is a long enough body to project.\n"
            )
        },
    )
    item = project.item_by_id("NOTE-001")
    assert item.title.startswith("The stage power")


def test_strip_markers_removes_only_the_marker():
    body = "before <!--navi: gone--> after\nsecond line\n"
    out = navis.strip_markers(body)
    assert "navi" not in out
    assert "before after" in out  # surrounding whitespace collapses to one space
    assert "second line" in out


def test_strip_markers_keeps_inert_occurrences():
    body = "```\n<!--navi: fence-->\n```\nsee `<!--navi: code-->`\n"
    out = navis.strip_markers(body)
    assert "<!--navi: fence-->" in out
    assert "`<!--navi: code-->`" in out


def test_strip_markers_preserves_bytes_outside_markers():
    body = "Ωµ\r\nunicode ok\n<!--navi: x-->\nend"
    out = navis.strip_markers(body)
    assert out == "Ωµ\r\nunicode ok\nend"


def test_strip_marker_only_line_joins_the_paragraph():
    # The exact reviewed repro: a marker alone on its own line inside a
    # paragraph must not leave a blank line behind (a blank line is a
    # paragraph break); markers sharing a line with text are removed with
    # their surrounding whitespace, collapsed to a single space.
    body = (
        "Three things drive the power architecture: a 9-36 V input range, a 3V3 rail at\n"
        "<!--navi: remember to check the thermal pad-->\n"
        "<!--navi: second--> text <!--navi: third-->"
    )
    assert navis.strip_markers(body) == (
        "Three things drive the power architecture: a 9-36 V input range, a 3V3 rail at\n"
        "text"
    )


def test_strip_marker_only_line_between_paragraphs_leaves_one_break():
    out = navis.strip_markers("para one\n\n<!--navi: x-->\n\npara two\n")
    assert out == "para one\n\n\npara two\n"


def test_strip_marker_only_line_at_body_start_and_end():
    assert navis.strip_markers("<!--navi: x-->\ntext\n") == "text\n"
    assert navis.strip_markers("text\n<!--navi: x-->\n") == "text\n"
    assert navis.strip_markers("<!--navi: x-->") == ""


def test_strip_marker_only_line_is_crlf_safe():
    out = navis.strip_markers("a\r\n<!--navi: x-->\r\nb\r\n")
    assert out == "a\r\nb\r\n"
    assert navis.strip_markers("a\r\ntext <!--navi: x--> tail\r\n") == "a\r\ntext tail\r\n"
    # A marker-only line ending in CRLF is a marker-only line.
    assert navis.strip_markers("a\r\n<!--navi: x-->\r\n") == "a\r\n"


def test_strip_marker_only_line_in_list_item():
    assert navis.strip_markers("- one\n  <!--navi: x-->\n- two\n") == "- one\n- two\n"


def test_strip_marker_in_table_row_collapses_to_clean_row():
    assert navis.strip_markers("| a | <!--navi: x--> b |\n") == "| a | b |\n"


def test_strip_marker_only_line_in_blockquote():
    # A `> ` line whose content is only markers is a structural line
    # (the `>` is a container prefix, not text): the whole line goes, so
    # the quoted paragraph stays ONE paragraph (a bare `>` line is a
    # blockquote paragraph break -- the reviewed defect).
    assert navis.strip_markers("> quoted\n> <!--navi: x-->\n> more\n") == (
        "> quoted\n> more\n"
    )


def test_scan_marker_spanning_lines_warns():
    found, bad = navis.scan_body("text <!--navi: spans\ntwo lines--> more\n")
    assert found == []
    assert len(bad) == 1
    assert bad[0][0] == 0  # reported at the line the marker opened on
    assert "one line" in bad[0][1]
    # the bytes are left for the page (an HTML comment, escaped, visible)
    assert "<!--navi: spans" in navis.strip_markers("text <!--navi: spans\ntwo lines--> more\n")


def test_scan_marker_spanning_lines_never_closes_stays_quiet():
    # An unclosed `<!--navi:` is the existing unclosed-comment warning's
    # territory (design §4) -- no second diagnostic for it.
    found, bad = navis.scan_body("text <!--navi: spans\nand stays open forever\n")
    assert found == [] and bad == []


def test_multiline_inline_code_span_is_inert():
    # CommonMark code spans close on LATER lines; the marker inside is
    # literal code text, not a Navi, and strip must not delete code.
    body = "`alpha\n<!--navi: inside span--> beta`\n"
    found, bad = navis.scan_body(body)
    assert found == [] and bad == []
    assert navis.strip_markers(body) is body


def test_fence_inside_blockquote_is_inert():
    body = "> q1\n> ```\n> <!--navi: x-->\n> ```\n> q2\n"
    found, bad = navis.scan_body(body)
    assert found == [] and bad == []
    assert navis.strip_markers(body) is body


def test_scan_is_inert_after_fence_on_crlf_body():
    # The functions advertise CRLF; every marker after a fence used to
    # vanish on a CRLF body because the close regex lacked a CR.
    body = "a\r\n```\r\n<!--navi: x-->\r\n```\r\nb\r\n"
    found, bad = navis.scan_body(body)
    assert found == [] and bad == []
    assert navis.strip_markers(body) is body
    # and a live marker on a CRLF body still lives
    live = navis.scan_body("a\r\n<!--navi: x-->\r\nb\r\n")
    assert [n.text for n in live[0]] == ["x"]


def test_render_marker_only_line_does_not_split_paragraph(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "Three things drive the power architecture: a 9-36 V input range, a 3V3 rail at\n"
                "<!--navi: remember to check the thermal pad-->\n"
                "<!--navi: second--> text <!--navi: third-->\n",
            )
        },
    )
    html = project.item_by_id("NOTE-001").body_html
    assert "navi" not in html
    assert html.count("<p>") == 1
    assert "a 3V3 rail at\ntext" in html


def test_render_escaped_pipe_in_table_row_keeps_the_table(tmp_path):
    # `table.py`'s escapedSplit treats `\|` as cell content, not a cell
    # delimiter -- counting it as a delimiter rebuilt the blank row with
    # an extra column and the stripped page rendered a paragraph.
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "| <!--navi: a \\| b--> |\n|---|\n",
            )
        },
    )
    html = project.item_by_id("NOTE-001").body_html
    assert "<table>" in html and "<p>" not in html
    assert "navi" not in html


def test_render_marker_only_line_does_not_split_blockquote(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "> quoted one\n> <!--navi: middle-->\n> quoted two\n",
            )
        },
    )
    html = project.item_by_id("NOTE-001").body_html
    assert "navi" not in html
    assert html.count("<p>") == 1
    assert "quoted one\nquoted two" in html


def test_payload_lines_name_the_original_body_lines(tmp_path):
    # Stripping markers for render must not shift reported line numbers:
    # the scan runs on the ORIGINAL body, render strips a local copy.
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "intro\n<!--navi: one-->\nmid <!--navi: two--> mid\n",
            )
        },
    )
    assert [navi.line_offset for navi in project.item_by_id("NOTE-001").navis] == [1, 2]


# ------------------------------------------------- build integration: Item.navis


def test_build_populates_item_navis(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md("NOTE-001", "note", "Power", "intro\n<!--navi: remember X-->\noutro\n"),
            "list.yaml": (
                "defaults: { type: memo }\n"
                "items:\n"
                "  - id: MEMO-001\n"
                "    title: List file\n"
                "    body: |\n"
                "      list body\n"
                "      <!--navi:k7f3q2x8d0m text-->\n"
            ),
        },
    )
    note = project.item_by_id("NOTE-001")
    assert [n.text for n in note.navis] == ["remember X"]
    memo = project.item_by_id("MEMO-001")
    assert [n.key for n in memo.navis] == ["k7f3q2x8d0m"]
    assert [n.text for n in memo.navis] == ["text"]


def test_malformed_marker_diagnostic_at_line(tmp_path):
    project = _project(
        tmp_path,
        {"note.md": _md("NOTE-001", "note", "Power", "intro\n<!--navi:-->\noutro\n")},
    )
    diags = [d for d in project.diagnostics if "navi" in d.message]
    assert len(diags) == 1
    assert diags[0].level == "warning"
    assert diags[0].file == "items/note.md"
    # body_line 6 (front matter is 5 lines) + offset 1.
    assert diags[0].line == 7
    assert diags[0].item_id == "NOTE-001"


def test_valid_markers_add_no_diagnostics(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_markers = _project(
        tmp_path / "a",
        {"note.md": _md("NOTE-001", "note", "Power", "<!--navi: a Navi-->\n")},
    )
    plain = _project(
        tmp_path / "b",
        {"note.md": _md("NOTE-001", "note", "Power", "not a Navi\n")},
    )
    assert [d.message for d in with_markers.warnings] == [d.message for d in plain.warnings]
    assert with_markers.errors == plain.errors


# -------------------------------------------------------------------- hashing


def test_scan_changes_no_hash(tmp_path, monkeypatch):
    """The scan itself must not enter any hash: body bytes are the hash
    input (build._hash_payload), the scan must not mutate `Item.body`, and
    a build whose very first build runs with the scan step stubbed produces
    byte-identical hashes. The stub goes in *before* the first build: a
    build never resets `Item.navis`, so stubbing a project that was already
    scanned compares a scanned item's (stale) populated navis against
    nothing and pins nothing."""
    files = {
        "note.md": _md(
            "NOTE-001", "note", "Power",
            "intro `P_diss := 2 W = 2 W` prose <!--navi: remember X-->\n"
            "<!--navi: second-->\n",
        ),
        "memo.md": _md("MEMO-001", "memo", "Log", "<!--navi: in a log-->\n"),
    }

    def hashes(root, *, scanned: bool):
        if not scanned:
            monkeypatch.setattr(navis, "scan", lambda _project: [])
        project = _project(root, files)
        return {i.id: i.content_hash for i in project.local_items}

    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    (tmp_path / "probe").mkdir()
    # Direct pin (the scan runs after compute_hashes, so the on/off build
    # comparison below is insensitive to the payload *reading* navis at its
    # current position -- this catches that regression at the payload):
    # nothing the scan produces is hash input, on an item whose navis ARE
    # populated. Runs first: monkeypatch is in force for the rest of the
    # test, so the probe project must be built before the scan is stubbed.
    probe = _project(tmp_path / "probe", files)
    assert any(item.navis for item in probe.local_items)
    builder = build_mod.hash_payload_builder(probe, build_mod.HASH_FORMAT)
    for item in probe.local_items:
        assert "navis" not in builder(item, probe.types[item.type])
    with_scan = hashes(tmp_path / "with", scanned=True)
    without = hashes(tmp_path / "without", scanned=False)
    assert with_scan == without
    assert all(hash_ for hash_ in with_scan.values())


def test_marker_in_hash_free_body_is_hash_neutral(tmp_path):
    """§7.1: a `ignore`-mode body's bytes are not hash input, so adding a
    marker there leaves the content hash byte-identical."""
    with_marker = _project(
        tmp_path,
        {
            "memo-a.md": _md("MEMO-001", "memo", "A", "text <!--navi: added-->\n"),
        },
    )
    plain = _project(
        tmp_path,
        {
            "memo-a.md": _md("MEMO-001", "memo", "A", "text \n"),
        },
    )
    # Same tree, second build in the same dir would mix; load each in its
    # own directory for a clean comparison.
    assert with_marker.item_by_id("MEMO-001").content_hash == plain.item_by_id("MEMO-001").content_hash


def test_marker_never_mutates_body(tmp_path):
    text = "intro\n<!--navi: remember X-->\noutro\n"
    project = _project(tmp_path, {"note.md": _md("NOTE-001", "note", "Power", text)})
    item = project.item_by_id("NOTE-001")
    assert item.body == text
    assert item.navis  # scanned
    assert item.body == text  # scan left it alone


# --------------------------------------------------------- inline-calc coexist


def test_inline_calc_span_on_marker_line_unaffected(tmp_path):
    """§4 collision inventory: the marker must not disturb the inline-calc
    scan. Same body minus the marker must produce the same calc."""
    with_marker = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "`P_diss := 12 V * 2 A = 24 W` <!--navi: check the thermal-->\n",
            )
        },
    )
    plain = _project(
        tmp_path,
        {"note.md": _md("NOTE-001", "note", "Power", "`P_diss := 12 V * 2 A = 24 W`\n")},
    )
    a = with_marker.item_by_id("NOTE-001")
    b = plain.item_by_id("NOTE-001")
    assert a.calc_values == b.calc_values
    assert [d.message for d in a and with_marker.warnings] == [
        d.message for d in plain.warnings
    ]


# ----------------------------------------------------------------- rendering


def test_render_consumes_markers(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "before <!--navi: consumed-->\nkeep this text\n",
            )
        },
    )
    html = project.item_by_id("NOTE-001").body_html
    assert "navi" not in html
    assert "before" in html
    assert "keep this text" in html
    # The marker must not survive as escaped comment text (html:false
    # escapes comments to visible text -- the scan consumes them first).
    assert "&lt;!--" not in html


def test_render_keeps_inert_marker_occurrences(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "```\n<!--navi: in fence-->\n```\nuse `<!--navi: text-->` here\n",
            )
        },
    )
    html = project.item_by_id("NOTE-001").body_html
    assert "&lt;!--navi: in fence--&gt;" in html
    assert "&lt;!--navi: text--&gt;" in html


def test_render_of_marker_free_body_is_untouched(tmp_path):
    body = "plain prose with [a link](x.md) and `code`\n"
    project = _project(tmp_path, {"note.md": _md("NOTE-001", "note", "P", body)})
    assert "plain prose" in project.item_by_id("NOTE-001").body_html


def test_pages_are_not_scanned(tmp_path):
    # Slice 1 is items-only (design §14.1): a marker in a narrative page
    # is not a Navi and pages render exactly as before (escaped visible
    # text, consumed by real renderers, not by us).
    config = write_project_config(tmp_path, SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "intro.md").write_text(
        "# Intro\n\n<!--navi: page marker-->\n", encoding="utf-8"
    )
    project, _stale = loader.load_tree(str(config), write=False)
    build_mod.build(project, seal_write=False)
    page = project.pages[0]
    assert _page_navis_text(project) == ""
    assert "&lt;!--navi: page marker--&gt;" in page.body_html


def _page_navis_text(project) -> str:
    return "".join(n.text for item in project.local_items for n in item.navis)


# ------------------------------------------------------------- index payload


def _payload(tmp_path, files):
    project = _project(tmp_path, files)
    return render.items_json(project)


def test_projection_keeps_document_order_on_one_line(tmp_path):
    # Design §11: (file, line) order -- a line with two markers must
    # keep document order, not text-alphabetical order, so `ls` numbers
    # and `show <n>` address the markers the way the page reads them.
    payload = _payload(
        tmp_path,
        {"note.md": _md("NOTE-001", "note", "P", "<!--navi: zebra--><!--navi: apple-->\n")},
    )
    assert [row["text"] for row in payload["navis"]] == ["zebra", "apple"]


def test_projection_source_names_the_item_key(tmp_path):
    # Design §10: identity resolves by key, never by display id (renames
    # move display ids); a panel/archive consumer must be able to resolve
    # the row from the row itself.
    project = _project(
        tmp_path,
        {
            "note.md": (
                "---\nid: NOTE-001\ntype: note\ntitle: P\nkey: k7f3q2x8d0m\n---\n"
                "<!--navi: resolve me-->\n"
            )
        },
    )
    row = navis.projection(project)[0]
    assert row["source"]["key"] == "k7f3q2x8d0m"


def test_index_payload_omits_navis_key_when_none(tmp_path):
    payload = _payload(
        tmp_path, {"note.md": _md("NOTE-001", "note", "Power", "plain body\n")}
    )
    assert "navis" not in payload


def test_index_payload_navis_key_rows(tmp_path):
    payload = _payload(
        tmp_path,
        {
            "note.md": _md(
                "NOTE-001", "note", "Power",
                "intro\n<!--navi:k7f3q2x8d0m Model the copper thing-->\n",
            ),
            "memo.md": _md("MEMO-001", "memo", "Log", "<!--navi: plain-->\n"),
        },
    )
    rows = payload["navis"]
    assert json.dumps(rows)  # rows are plain JSON data
    assert len(rows) == 2
    # (file, line) order: memo.md's keyless row sorts before note.md's.
    keyless, keyed = rows[0], rows[1]
    assert keyed["key"] == "k7f3q2x8d0m"
    assert keyed["text"] == "Model the copper thing"
    assert keyed["source"] == {
        "item": "NOTE-001",
        "key": None,  # the *item* has no key; the row key is the marker's
        "file": "items/note.md",
        "line": 7,
    }
    assert keyless["key"] is None
    assert keyless["text"] == "plain"
    assert keyless["source"]["item"] == "MEMO-001"
    assert keyless["source"]["line"] == 6


def test_index_payload_round_trips(tmp_path):
    payload = _payload(
        tmp_path, {"note.md": _md("NOTE-001", "note", "Power", "<!--navi: x Ω-->\n")}
    )
    round_tripped = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    assert round_tripped["navis"][0]["text"] == "x Ω"


def test_strip_removes_the_live_marker_not_its_inert_twin():
    # Round-5 review A3: an inert code-span twin of the marker's text on
    # the same line. A strip that locates markers by TEXT removes the
    # FIRST occurrence -- the authored code span -- and leaves the live
    # marker visible. The scan records absolute raw spans, so only the
    # live marker's bytes go.
    body = "> `<!--navi: x-->` then <!--navi: x--> real\n"
    out = navis.strip_markers(body)
    assert out == "> `<!--navi: x-->` then real\n"
    assert [n.text for n in navis.scan_body(body)[0]] == ["x"]


def test_strip_honours_escaped_backtick():
    # Round-5 review B: `\`` is a literal backtick, not a code-span
    # opener; the marker after it is live.
    body = "write \\` here <!--navi: live--> and `code` later\n"
    assert [n.text for n in navis.scan_body(body)[0]] == ["live"]
    assert navis.strip_markers(body) == "write \\` here and `code` later\n"


def test_escaped_lt_is_not_a_marker():
    # Round-5 review C: `\<` is a literal `<`; a marker-shaped run behind
    # it is authored text, kept byte-identical, and must not become a
    # Navi (the old strip ate it and left a stray backslash).
    body = "text \\<!--navi: esc--> tail\n"
    assert navis.scan_body(body) == ([], [])
    assert navis.strip_markers(body) == body


def test_markers_in_one_table_row_scan_in_document_order():
    # Round-5 review D2: the row's cells carry two markers; document
    # order is left to right, not the order the tokenizer's per-cell
    # offsets sort to.
    body = "| a | b |\n|---|---|\n| xxxx <!--navi: second--> | <!--navi: first--> y |\n"
    assert [(n.text, n.line_offset) for n in navis.scan_body(body)[0]] == [
        ("second", 2),
        ("first", 2),
    ]


def test_strip_fails_closed_on_an_unmappable_span(monkeypatch):
    # The mapping layer's guarantee is exact spans; a body whose spans
    # cannot be located exactly is an internal bug, and strip refuses to
    # guess (a guessed strip corrupts authored text -- the reviewed A3):
    # the bytes stay intact, the diagnostic is reported, nothing raises.
    def boom(norm_lines, token_ranges):
        raise navis.NavisMappingError("test-injected mapping failure")

    monkeypatch.setattr(navis, "_machine", boom)
    body = "text <!--navi: x--> tail\n"
    assert navis.strip_markers(body) == body
    analysis = navis.analyze_navis(body)
    assert analysis.navis == ()
    (msg,) = [m for _, m in analysis.diagnostics]
    assert msg.startswith(navis.MAPPING_MESSAGE)
    # the warning names the failure so a bug report is actionable
    assert "NavisMappingError" in msg and "test-injected mapping failure" in msg
    found, bad = navis.scan_body(body)
    assert found == []
    assert len(bad) == 1 and bad[0][1].startswith(navis.MAPPING_MESSAGE)


def test_strip_drops_a_line_left_bare_of_list_bullets():
    # A marker alone in a list item must not leave an empty bullet
    # behind: a bare `-` is an empty item, visible authored structure
    # the marker's removal should not create.
    body = "- one\n- <!--navi: x-->\n- two\n"
    assert navis.strip_markers(body) == "- one\n- two\n"
    html = build_mod._markdown_parser().render(navis.strip_markers(body))
    assert html.count("<li>") == 2


def test_strip_never_inserts_a_space_before_punctuation():
    assert navis.strip_markers("Use <!--navi: n-->, as noted.") == "Use, as noted."
    assert navis.strip_markers("Use <!--navi: n--> notes") == "Use notes"
    assert navis.strip_markers("text<!--navi: n-->.") == "text."


# --------- regression family from the deep-analysis report (round 6) ---------


def test_lone_cr_marker_offsets_and_strip():
    body = "a\r<!--navi: x-->\rb"
    found, bad = navis.scan_body(body)
    assert bad == []
    assert [n.line_offset for n in found] == [1]
    assert navis.strip_markers(body) == "a\rb"


def test_nul_and_separators_before_marker_preserve_raw_body():
    for body in ("a\x00b <!--navi: x-->\n", "a\x0cb <!--navi: x-->\n",
                 "a\u2028b <!--navi: x-->\n", "a\u2029b <!--navi: x-->\n",
                 "\ufeffa <!--navi: x-->\n"):
        found, bad = navis.scan_body(body)
        assert bad == [] and len(found) == 1, body
        stripped = navis.strip_markers(body)
        assert stripped == body.split(" <!--navi: x-->")[0] + "\n", body


def test_table_escaped_pipe_raw_span():
    body = "| a\\|b | <!--navi: x--> |\n|---|---|\n| c | d |\n"
    found, bad = navis.scan_body(body)
    assert bad == [] and len(found) == 1
    stripped = navis.strip_markers(body)
    assert stripped == "| a\\|b |  |\n|---|---|\n| c | d |\n"
    assert "\\|" in stripped  # the escape is authored text, byte-untouched


def test_table_duplicate_cells_without_final_pipe():
    body = "|a|b|\n|-|-|\n| <!--navi: x--> | <!--navi: y-->\n"
    found, bad = navis.scan_body(body)
    assert bad == []
    assert [n.text for n in found] == ["x", "y"]
    assert navis.strip_markers(body) == "|a|b|\n|-|-|\n| |\n"


def test_comment_state_across_blank_and_heading():
    for body in ("<!-- outer\n\n<!--navi: x-->\ntail -->\n",
                 "<!-- outer\n# <!--navi: x-->\ntail -->\n"):
        found, bad = navis.scan_body(body)
        assert found == [] and bad == [], body
        assert navis.strip_markers(body) == body


def test_residue_thematic_breaks_and_plus_text():
    for residue in ("---", "***", "- - -", "___", "+++"):
        body = f"{residue} <!--navi: x-->\n"
        found, bad = navis.scan_body(body)
        assert bad == [] and len(found) == 1
        assert navis.strip_markers(body) == f"{residue}\n"
    for residue in ("1.", ">", "-", "*", "+", ">>", "1. -"):
        body = f"{residue} <!--navi: x-->\n"
        assert navis.strip_markers(body) == "", residue


def test_marker_in_link_attributes_is_inert():
    for body in ('[t](u "<!--navi: x-->") tail\n',
                 ("[a]: /url\n"
                  "text <!--navi: x-->\n")):
        found, bad = navis.scan_body(body)
        assert bad == []
        title = body.startswith("[t](")
        assert (len(found) == 0) == title, body


def test_image_alt_marker_is_inline():
    body = "![a <!--navi: x--> b](u.png) tail\n"
    found, bad = navis.scan_body(body)
    assert bad == [] and len(found) == 1
    assert navis.strip_markers(body) == "![a b](u.png) tail\n"


def test_five_thousand_markers_strip_correctly():
    # Scale, not speed (no wall-clock assertion -- CI flakes): the
    # linear passes (bisected line lookup, single-join strip) must keep a
    # many-marker body exact.
    body = "".join(f"thing {i} <!--navi: note {i}-->\n" for i in range(5000))
    analysis = navis.analyze_navis(body)
    assert [n.text for n in analysis.navis] == [f"note {i}" for i in range(5000)]
    assert analysis.stripped == "".join(f"thing {i}\n" for i in range(5000))


def test_no_marker_scan_skips_parser(monkeypatch):
    def boom():
        raise AssertionError("the parser factory must not run")

    monkeypatch.setattr(navis, "_marker_parser", boom)
    body = "plain text with no markers and no <!-- at all\n"
    found, bad = navis.scan_body(body)
    assert found == [] and bad == []
    assert navis.strip_markers(body) is body
    analysis = navis.analyze_navis(body)
    assert analysis.stripped is body


def test_analysis_reused_for_scan_and_render():
    body = "a <!--navi: x--> b\n"
    first = navis.analyze_navis(body)
    assert navis.analyze_navis(body) is first
    assert navis.strip_markers(body) is first.stripped
    found, _ = navis.scan_body(body)
    assert [n.text for n in found] == [n.text for n in first.navis]


def test_hardbreak_adjacent_to_marker(tmp_path):
    # The agreed C1 policy: a run of 2+ spaces ending the line after a
    # marker is a hard break -- the marker's left run collapses to a
    # single space, the break's own spaces stay verbatim.
    assert navis.strip_markers("a <!--navi: x-->  \nb\n") == "a   \nb\n"
    assert navis.strip_markers("a <!--navi: x-->\\\nb\n") == "a\\\nb\n"
    html = build_mod._markdown_parser().render(
        navis.strip_markers("a <!--navi: x-->  \nb\n")
    )
    assert "<br" in html and "navi" not in html


def test_marker_payload_syntax_is_never_evaluated(tmp_path):
    body = "text <!--navi: {{missing}} [[x]] `a := b`-->\n"
    found, bad = navis.scan_body(body)
    assert bad == [] and len(found) == 1
    project = _project(
        tmp_path, {"note.md": _md("NOTE-001", "note", "P", body)}
    )
    assert not project.errors and not project.warnings
    assert "navi" not in project.item_by_id("NOTE-001").body_html
    assert "{{missing}}" not in project.item_by_id("NOTE-001").body_html


def test_original_line_mapping_after_mixed_terminators():
    body = "a\r\n<!--navi: x-->\rb\n<!--navi: y-->\n"
    found, bad = navis.scan_body(body)
    assert bad == []
    assert [n.line_offset for n in found] == [1, 3]
    assert [n.text for n in found] == ["x", "y"]
    assert navis.strip_markers(body) == "a\r\nb\n"


def test_normalization_build_diagnostics_never_traceback(tmp_path):
    project = _project(
        tmp_path,
        {
            "note.md": _md("NOTE-001", "note", "CR", "a\r<!--navi: x-->\rb\n"),
            "note-b.md": _md(
                "NOTE-002", "note", "NUL", "a\x00b <!--navi: y-->\n"
            ),
            "note-c.md": _md(
                "NOTE-003", "note", "pipe",
                "| a\\|b | <!--navi: z--> |\n|---|---|\n| c | d |\n",
            ),
        },
    )
    assert not project.errors and not project.warnings
    for id_ in ("NOTE-001", "NOTE-002", "NOTE-003"):
        assert "navi" not in project.item_by_id(id_).body_html
