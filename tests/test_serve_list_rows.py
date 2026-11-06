"""Source-level pins on the item list's rows (src/refdes/serve/static/list.js).

The list pane's own header comment states the contract: rows "link to the item
view while keeping the current filter query in the URL." app.js routes
`#/items/<handle>[?filters]` to the item view (app.js:28-30), and style.css
styles a block-level `.item-link { display: block }` sized to fill a row -- so
the row is meant to be an anchor.

The repo has no Node/DOM/browser harness for the served shell (see
tests/test_serve_static.py's "No Node here"; nothing under tests/ imports
node/jsdom/playwright/puppeteer), so these are text checks over the served
module -- the established style. They assert that `row()` wires the anchor it
creates into the row, so a `link` that is created, given an href, and dropped
fails the pins.

Browser verification the implementer must do (Chromium + Firefox, `refdes
serve`, /edit/#/items): the count of `li.item-row a.item-link` anchors equals
the item count; clicking a row navigates the detail pane to that item
(`location.hash` moves to `#/items/<handle>`); and with a filter active the
row's href preserves the current filter query (e.g. `#/items/<handle>?board=x`).
"""

from __future__ import annotations

import os
import re

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)
LIST = os.path.join(STATIC, "list.js")


def list_source():
    with open(LIST, encoding="utf-8") as fh:
        return fh.read()


def row_function(source):
    """The body of the row() builder, up to the next top-level export. The row
    is the only thing between `function row(` and `export function renderList`,
    so this slice is the row's construction in isolation."""
    start = source.index("function row(")
    end = source.index("export function renderList", start)
    return source[start:end]


def test_row_attaches_the_link_it_creates():
    """row() builds `const link = el('a', 'item-link')` and must put it in the
    row, wrapping the visible content: the anchor is appended to the li, and the
    head/title/meta are appended to the anchor (style.css's `.item-link { display:
    block }` is the block that fills the row). A `link` that is created, given an
    href, and never appended renders rows as inert divs -- the bug on main."""
    body = row_function(list_source())
    assert "li.appendChild(link)" in body, "the row never attaches the anchor it builds"
    assert "link.appendChild(head)" in body
    assert "link.appendChild(meta)" in body
    assert "link.appendChild(el('div', 'item-title', item.title))" in body
    # the visible content lives inside the link, not directly in the li
    assert "li.appendChild(head)" not in body
    assert "li.appendChild(meta)" not in body
    assert "li.appendChild(el('div', 'item-title'" not in body


def test_the_row_link_routes_to_the_item_view_with_the_filter_query():
    """The anchor's href is `#/items/<handle>` (app.js decodes it back to the item
    route) built from encodeURIComponent(item.handle), with filterQuery(filters)
    appended so the current filters ride along in the deep link. An href on an
    anchor that is never attached is unreachable, so this pins the href on the
    link the row actually attaches to the li."""
    body = row_function(list_source())
    match = re.search(r"link\.href\s*=\s*`([^`]*)`", body)
    assert match, "row() sets no href on the item link"
    href = match.group(1)
    assert href.startswith("#/items/")
    assert "encodeURIComponent(item.handle)" in href
    assert "filterQuery(filters)" in href
    # the anchor carrying the route is the one appended into the row
    assert "li.appendChild(link)" in body


def test_rows_render_text_through_el_never_innerhtml():
    """Rows render untrusted item text (title, source file, ids) read from project
    files, so every string is assigned through el()/textContent, never innerHTML.
    This is the constraint the link-wrapping fix must preserve: wiring the anchor
    by rewriting the row's markup through innerHTML would reopen the injection
    hole el() exists to close (see dom.js). The pin is red on main because the
    row does not yet attach its anchor -- the fix has to keep the text on el()."""
    source = list_source()
    assert "innerHTML" not in source, "list.js must not write markup through innerHTML"
    body = row_function(source)
    assert "li.appendChild(link)" in body
