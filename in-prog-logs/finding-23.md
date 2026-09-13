# finding-23 — wire `page:` into citation hrefs (part 1)

## Task
Backlog finding 23, part 1 only: append `#page={{ c.spec.page }}` to the
remote and local-copy citation hrefs in `item.html.j2` when `page` is set.
Part 2 (outline-resolved `section:`, pypdf, fetch-time resolution) is
explicitly deferred — not built.

## Progress
- Synced branch: `git merge --ff-only main` succeeded (e2a04eb..3a2fced).
- Read docs/design/backlog.md "### 23" — confirms part 1 is a template-only
  change of the form "append `#page=...` to an existing href, only when page
  is set".
- Confirmed `CitationSpec.page` is `str` defaulting to `""` (model.py:261),
  coerced via `str(entry.get("page") or "")` (citations.py:117) — so
  `{% if c.spec.page %}` is the correct guard. No Python changes needed.
- Edited `src/refdes/templates/item.html.j2` lines 115-116: both the upstream
  link and the `local copy` link now append `#page={{ c.spec.page }}` when
  set. Visible link text unchanged (still the bare URL / "local copy").
- Did NOT touch `document.html.j2` (plain-text url, separate decision) or
  `references.html.j2` (grouped by URL across citers — page would be
  misattributed).

## Tests
Added two tests to the rendering section of `tests/test_citations.py`
(existing module, no new file):
- citation WITH `page:` → asserts the full `<a href="...#page=14"...>` markup
  (not a substring anywhere on the page), for both the upstream href and the
  published local-copy href.
- citation WITHOUT `page:` → asserts bare `href="https://example.com/ds.pdf"`
  and that no `#page=` fragment appears in the rendered item page.

## Verification
- `python -m pytest tests/ -q` all pass (658 + 2 added = 660).
- `git status --short` shows only the template, the test file, and this log.

## Status
Finished.