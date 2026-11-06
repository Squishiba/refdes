# listrow-links — test author slice (LISTROW-tests)

Slice: write ONLY `tests/test_serve_list_rows.py` pinning the browser-editor
item-list row-links bug. No source or existing-test edits.

## The bug (confirmed on main, 1b9efa14)

`src/refdes/serve/static/list.js` `row()` creates the anchor and sets its href
(lines 14-15) then drops it: `const link = el('a', 'item-link');
link.href = \`#/items/${encodeURIComponent(item.handle)}${filterQuery(filters)}\`;`
— `link` is never appended. The row's visible content (`head`, the title div,
`meta`) is appended straight to `li` (lines 24, 26, 32), so `li.item-row`
holds only plain divs. The file's own header comment says rows "link to the
item view while keeping the current filter query in the URL".

Intent is corroborated by the surrounding code, not just the comment:
- `style.css:29` `.item-link { color: inherit; text-decoration: none; display:
  block; }` — a block anchor sized to fill a row.
- `app.js:28-30` routes `#/items/<handle>[?filters]` to the item view
  (`decodeURIComponent(m[1])`).
- `filters.js` `filterQuery` yields `?a=b&...` (empty string when no filters).
- `navis-panel.js:46` builds the same shape `#/items/${encodeURIComponent(...)}`.

## Test style decision

No browser/Node harness for the served shell. Confirmed: nothing under
`tests/` imports node/jsdom/playwright/puppeteer (grep);
`tests/test_serve_static.py` opens with "No Node here" and asserts on served
JS as text. So these are source-level assertions over `list.js` — the
established style. Sliced the `row()` body out via
`function row(` .. `export function renderList` and asserted structure, so a
created-and-dropped `link` fails.

## The three pins (all RED on main)

1. `test_row_attaches_the_link_it_creates` — the anchor is appended to the li
   (`li.appendChild(link)`) and the visible content is appended to the anchor
   (`link.appendChild(head|meta|title div)`), not directly to the li. On main
   `li.appendChild(head|meta|title)` is present and no `link.appendChild` /
   `li.appendChild(link)` exists.
2. `test_the_row_link_routes_to_the_item_view_with_the_filter_query` — href is
   `#/items/` + `encodeURIComponent(item.handle)` + `filterQuery(filters)`,
   pinned on the link the row actually attaches (the `li.appendChild(link)`
   half is what is red on main; the href text itself already exists).
3. `test_rows_render_text_through_el_never_innerhtml` — `innerHTML` absent from
   `list.js` (guard the fix must preserve), plus the row attaches its anchor.

## Red/green evidence

Ran on main: all 3 FAIL on `assert 'li.appendChild(link)' in body`
(the dropped anchor). Verified GREEN against a scratch-patched copy of
`list.js` (content appended to `link`, then `li.appendChild(link)`): all
assertions pass, so the pins are not over-specified. `ruff check` on the new
file: clean.

Windows/Linux: reads use `open(..., encoding="utf-8")` (no `newline=`), no
path-separator asserts, no browser calls.

## Browser verification the implementer MUST do (Chromium + Firefox, `refdes
serve`, /edit/#/items):
- anchor count == item count: `document.querySelectorAll('li.item-row
  a.item-link').length` equals `li.item-row` count (main: 20 rows, 0 anchors).
- click navigation: clicking a row moves `location.hash` to `#/items/<handle>`
  and the detail pane renders that item (main: hash stays `#/items`).
- filter query preserved: with a filter active (e.g. `?board=x`) the row href
  and post-click hash keep the query (e.g. `#/items/<handle>?board=x`).

## Status

Done. Test file only; branch pushed; NO PR (per instructions).
