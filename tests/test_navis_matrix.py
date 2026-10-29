"""The Navis context matrix: every Markdown context x marker placement,
asserted against the project's own renderer.

The reviews of slice 1 kept finding one more hand-rolled-scan blind spot
after another (multi-line code spans, fences inside blockquotes, CRLF
after a fence, `>` prefixes, ...). The matrix pins the contract in one
place so "inert" is a property of the renderer (`build._markdown_parser`
-- the same parse the site renders with), not of a scanner that has to
re-derive it. A cell asserts (navi count, warning count, marker bytes
gone from the published page) for one (context, placement, line-ending)
cell: 27 x 5 x 2 = 270 cells.

Contexts: paragraph, list item, nested list, blockquote, nested
blockquote, indented code, backtick fence, tilde fence, fence in list,
fence in blockquote, inline code single-line / multi-line / double-
backtick, open HTML comment, raw HTML, table row, ATX heading, setext
heading, link text, emphasis, escaped backslash, escaped backtick, inert
code-span twin in blockquote / list / table cell, two markers in one
table row. Placements: alone on a line, leading text, trailing text, two
on a line, spanning two lines.
"""

from __future__ import annotations

import pytest

from refdes import navis
from refdes.build import _markdown_parser

MARKERS = {
    "alone": "<!--navi: mk1-->",
    "leading": "<!--navi: mk1--> tail",
    "trailing": "head <!--navi: mk1-->",
    "two": "<!--navi: mk1--> mid <!--navi: mk2-->",
    "span": "<!--navi: spans\ntwo lines-->",
}

# The marker slot, indented to the context's own container prefix.
def _slot(inner: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in inner.split("\n"))


def _inline(inner: str, before: str, after: str, multi_before: str, multi_after: str) -> str:
    """A context whose marker sits mid-line (single-line contexts): the
    spanning placement breaks onto its own lines inside the construct."""
    if "\n" in inner:
        return f"{multi_before}\n{inner}\n{multi_after}\n"
    return f"{before}{inner}{after}\n"


CONTEXTS = {
    "paragraph": lambda m: f"ctx one\n{m}\nctx two\n",
    "list_item": lambda m: f"- ctx one\n{_slot(m, '- ')}\n- ctx two\n",
    "nested_list": lambda m: f"- outer\n  - ctx one\n{_slot(m, '  - ')}\n  - ctx two\n",
    "blockquote": lambda m: f"> ctx one\n{_slot(m, '> ')}\n> ctx two\n",
    "nested_blockquote": lambda m: f"> > ctx one\n{_slot(m, '> > ')}\n> > ctx two\n",
    "indented_code": lambda m: f"ctx one\n\n{_slot(m, '    ')}\n\nctx two\n",
    "fence_backtick": lambda m: f"ctx one\n\n```\n{m}\n```\n\nctx two\n",
    "fence_tilde": lambda m: f"ctx one\n\n~~~\n{m}\n~~~\n\nctx two\n",
    "fence_in_list": lambda m: f"- ctx\n\n  ```\n{_slot(m, '  ')}\n  ```\n\n- ctx two\n",
    "fence_in_blockquote": lambda m: f"> ctx\n> ```\n{_slot(m, '> ')}\n> ```\n> ctx two\n",
    "inline_code_single": lambda m: _inline(
        m, "ctx `pre ", " post` ctx", "ctx `pre", "post` ctx"
    ),
    # `inline_code_multi` is the multi-line form of the construct: every
    # placement rides inside a span opened on the first line and closed
    # on the last.
    "inline_code_multi": lambda m: f"ctx `pre\n{m}\npost` ctx\n",
    "inline_code_double": lambda m: _inline(
        m, "ctx `` pre ", " post `` ctx", "ctx `` pre", "post `` ctx"
    ),
    "html_comment_open": lambda m: f"ctx <!-- open\n{m}\nclose --> ctx\n",
    "raw_html": lambda m: f"ctx <div>\n{m}\n</div> ctx\n",
    "table_row": lambda m: f"| a | b |\n|---|---|\n| x | {m} |\n",
    "heading_atx": lambda m: f"# Title {m}\nctx\n",
    "heading_setext": lambda m: f"Title {m}\n=====\n",
    "link_text": lambda m: _inline(m, "[pre ", " post](u) ctx", "[pre", "post](u) ctx"),
    "emphasis": lambda m: _inline(m, "ctx *pre ", " post* ctx", "ctx *pre", "post* ctx"),
    "escaped_backslash": lambda m: _inline(
        m, "ctx \\", " tail", "ctx \\", "tail"
    ),
    # The reviewed A3 family: an INERT code-span twin of the marker's own
    # text, on the same line as the live marker, in each container whose
    # raw line carries a prefix. A strip that searches for the marker's
    # text hits the inert twin first and eats authored text.
    "a3_in_blockquote": lambda m: f"> `<!--navi: inert-->` {_slot(m, '> ')} real\n",
    "a3_in_list": lambda m: f"- `<!--navi: inert-->` {_slot(m, '- ')} real\n",
    "a3_in_table": lambda m: f"| a | b |\n|---|---|\n| `<!--navi: inert-->` {m} | z |\n",
    # CommonMark backslash escapes: an escaped backtick cannot open a
    # code span (the marker after it is live); an escaped `<` cannot
    # start a comment (the marker is inert, its bytes authored text).
    "escaped_backtick": lambda m: f"write \\` {m} and `code` later\n",
    "escaped_lt": lambda m: f"text \\<!--navi: esc--> {m} tail\n",
    # The reviewed D2 family: markers in two cells of one table row --
    # document order is the row's left-to-right order, not the order the
    # row tokenizer visits the cells' inner offsets.
    "d2_table": lambda m: (
        f"| a | b |\n|---|---|\n| z <!--navi: cellA--> | <!--navi: cellB--> {m} y |\n"
    ),
}

INERT = {
    "indented_code",
    "fence_backtick",
    "fence_tilde",
    "fence_in_list",
    "fence_in_blockquote",
    "inline_code_single",
    "inline_code_multi",
    "inline_code_double",
    "html_comment_open",
}

# Contexts whose span cell cannot produce a warning: the construct closes
# at the end of the marker's first line (ATX heading, table row), the
# continuation rides a fresh container item (list bullet prefix), the
# marker sits in a table cell (the row ends at the line end) -- so the
# marker is an unclosed comment there, the existing unclosed-comment
# warning's territory (design §4), not a closed two-line one.
SPAN_SILENT = {
    "heading_atx",
    "table_row",
    "list_item",
    "nested_list",
    "a3_in_list",
    "a3_in_table",
    "d2_table",
}

# The open-comment context swallows up to the first `-->`, which is the
# first marker's own close -- so the second marker on the swallowed line
# is live text (what the renderer sees). In `escaped_backslash` the
# backslash escapes the slot's first character: a `<` (alone/leading/two
# slots) makes that marker inert -- inert bytes stay on the page; the
# trailing slot starts with a letter, so the backslash is literal text
# and its marker is live.
SPECIAL = {
    ("html_comment_open", "two"): (1, 0, False),
    ("escaped_backslash", "alone"): (0, 0, False),
    ("escaped_backslash", "leading"): (0, 0, False),
    ("escaped_backslash", "trailing"): (1, 0, True),
    ("escaped_backslash", "two"): (1, 0, False),
}
SPECIAL_TEXTS = {
    ("html_comment_open", "two"): ["mk2"],
    ("escaped_backslash", "alone"): [],
    ("escaped_backslash", "leading"): [],
    ("escaped_backslash", "trailing"): ["mk1"],
    ("escaped_backslash", "two"): ["mk2"],
}

# Contexts with a fixed live marker of its own, beside the placement's
# slot (document order: the extras' texts come first).
EXTRA_NAVIS = {"d2_table": 2}
EXTRA_TEXTS = {"d2_table": ["cellA", "cellB"]}

# Contexts whose page keeps marker bytes AFTER a correct strip: an inert
# occurrence of the marker text (code-span twin, escaped opening) stays
# authored text on the page.
INERT_TEXT = {"a3_in_blockquote", "a3_in_list", "a3_in_table", "escaped_lt"}

# Contexts whose SPAN cell leaves marker bytes on the page (a fixed live
# marker's line keeps a second, span-opened marker whose bytes render as
# the escaped comment the renderer shows).
SPAN_RESIDUE = {"d2_table"}

SLOT_COUNT = {"alone": 1, "leading": 1, "trailing": 1, "two": 2, "span": 0}
SLOT_TEXTS = {
    "alone": ["mk1"],
    "leading": ["mk1"],
    "trailing": ["mk1"],
    "two": ["mk1", "mk2"],
    "span": [],
}


def expected(context: str, placement: str) -> tuple[int, int, bool]:
    """(navi count, warning count, marker bytes gone from the page)."""
    special = SPECIAL.get((context, placement))
    if special is not None:
        return special
    if context in INERT:
        return (0, 0, False)
    extra = EXTRA_NAVIS.get(context, 0)
    if placement == "span":
        if context in SPAN_SILENT:
            return (extra, 0, extra > 0 and context not in SPAN_RESIDUE)
        return (0, 1, False)
    return (extra + SLOT_COUNT[placement], 0, context not in INERT_TEXT)


def expected_texts(context: str, placement: str) -> list[str]:
    """The Navi texts in document order -- the scan's ordinals are the
    source's, not the tokenizer's (the reviewed D2 family)."""
    special = SPECIAL_TEXTS.get((context, placement))
    if special is not None:
        return special
    if context in INERT:
        return []
    if placement == "span":
        return list(EXTRA_TEXTS.get(context, [])) if context in SPAN_SILENT else []
    return list(EXTRA_TEXTS.get(context, [])) + SLOT_TEXTS[placement]


@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("context", list(CONTEXTS))
@pytest.mark.parametrize("placement", list(MARKERS))
def test_navis_context_matrix(context, placement, ending):
    body = CONTEXTS[context](MARKERS[placement]).replace("\n", ending)
    navis_found, warnings = navis.scan_body(body)
    want_navis, want_warnings, gone = expected(context, placement)
    assert [n.text for n in navis_found] == expected_texts(context, placement), (
        f"{context}/{placement}"
    )
    assert len(navis_found) == want_navis, f"{context}/{placement}: {[n.text for n in navis_found]}"
    assert len(warnings) == want_warnings, f"{context}/{placement}: {warnings}"

    html = _markdown_parser().render(navis.strip_markers(body))
    assert ("navi" not in html) is gone, f"{context}/{placement}: {html}"
