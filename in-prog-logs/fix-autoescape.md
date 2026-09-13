# Fix autoescaping — Jinja autoescape was silently disabled

`autoescape=select_autoescape(["html"])` in src/refdes/render.py matched on the
template name's suffix; every template is named `*.html.j2`, which ends in
`.j2`, so it returned False for every template and nothing was ever escaped.

## What I did

1. Verified the bug before touching anything:
   `select_autoescape(["html"])("item.html.j2")` → False (run directly against
   the installed jinja2).
2. `src/refdes/render.py`: replaced
   `autoescape=select_autoescape(["html"])` with `autoescape=True` and a
   comment explaining why `select_autoescape(["html"])` doesn't work here
   (suffix matching vs `.html.j2` names), so nobody reintroduces it. Dropped
   the now-unused `select_autoescape` from the jinja2 import.
3. `tests/test_citations.py`: new `test_citation_page_value_is_html_escaped`,
   in the rendering section, next to the other `#page=` href tests. Builds the
   `citation_project` fixture with `page: '14" onmouseover="alert(1)'`, renders,
   and asserts:
   - `'onmouseover="' not in html` — the unescaped breakout is gone, and
   - `"onmouseover=&#34;" in html` — the escaped form (quote → `&#34;`
     entity, markupsafe's escaping) appears in the href and the page cell.

## Difficulties

- Verified the exact entity form with a scratch script: markupsafe escapes `"`
  as `&#34;`, not `&quot;` — the task description said "the quote rendered as
  an entity", and `&#34;` is that entity. A first quick `python -c` check got
  mangled by PowerShell quote handling (the `\"` in the one-liner), so I
  verified via a file-based check instead.
- No template needed a new `| safe`: the full suite passes with escaping on,
  confirming the 5 existing markers (item/document/log/page body_html,
  previews_json) cover every intentional raw-markup site.

## Verification

- `python -m pytest tests/ -q` → 662 passed, 0 failed (661 baseline + 1 new).
- Revert gate: with render.py restored to the committed
  `select_autoescape(["html"])` version, the new test FAILS, showing the raw
  breakout `#page=14" onmouseover="alert(1)" target="_blank"` in the rendered
  HTML; with the fix back in place it passes again.
- `git status --short` → exactly src/refdes/render.py, tests/test_citations.py,
  in-prog-logs/fix-autoescape.md.

Committed locally as `render: actually enable Jinja autoescaping`. Not pushed,
no PR.

## Status

Finished.