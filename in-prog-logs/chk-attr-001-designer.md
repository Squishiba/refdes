# chk-attr-001 — blind test designer

Task: page `{{...}}` block diagnostics report a body-relative line, not the
file line, for pages with front matter. I am the blind test designer: tests
only, no product code.

## What I verified first (not memory — the tree)

- `src/refdes/pages.py::_read_page` stores `Page.body` with front matter
  stripped via `parse.FRONTMATTER_RE` (`^---\s*\n(.*?)\n---\s*\n?(.*)$`), so
  a 4-line front matter makes body line 1 == file line 5.
- `src/refdes/build.py` `render_pages` passes that stripped body to
  `blocks_mod.extract_blocks(project, page.body, page.source_file)` — the
  single call site all registered block types share.
- `src/refdes/blocks.py::extract_blocks` computes
  `line_no = source.count("\n", 0, match.start()) + 1` — body-relative.
- `_REGISTRY` (blocks.py ~902) has five names in this tree: `calcblock`,
  `compare`, `index`, `cascade`, `tree`. The task text names `parts`, but
  there is no `parts` block directive in this registry (parts is a generated
  report page, not a `{{...}}` block) — so I covered the five real registry
  names, cascade included.
- Diagnostics land as `project.error(..., file=where_file, line=line_no)`
  (`Diagnostic` in model.py carries `.file`/`.line`); `refdes check` runs
  `build_mod.build`, and the block tests' usual helper `_build_at`
  (helpers.py) runs that same pipeline, so asserting on
  `project.errors[].line` is the real check path — matching how
  tests/test_blocks.py asserts.

## Tests written — tests/test_page_block_lines.py

Six tests, `blocks_project` fixture (conftest) + `_build_at`:

- Five "front matter" tests (one per block type): page `pages/overview.md`
  = 4 front-matter lines (1-4) + prose (5-7) + a bad directive on file line
  8. Directive chosen to fail `_validate_params` (so no renderer/item data
  is needed): `{{index type="decision"}}` (missing 'by'), `{{compare}}`
  (missing 'type'), `{{cascade}}` (missing 'from'), `{{tree bogus="x"}}`
  (unknown parameter), `{{calcblock}}` (missing 'item'). Assert the
  matching diagnostic's `.file`/`.line` == file line 8.
- One control: `pages/control.md`, no front matter, directive on file line
  5, asserts `.line == 5` (true today, must stay true).

The written file line is counted from the text the helper writes, and each
test pins it (`assert line == 8`), so the layout can't silently drift.

## Result on base (unfixed) code

`PYTHONPATH=src ...pytest -q tests/test_page_block_lines.py` →
5 failed (each reports line 3 == body-relative, must be 8), 1 passed (the
control). Matches the expected_on_base values in
tests/chk-attr-001.cases.json.

## Status

Finished. Deliverables: tests/test_page_block_lines.py,
tests/chk-attr-001.cases.json, this log. No product code touched.
