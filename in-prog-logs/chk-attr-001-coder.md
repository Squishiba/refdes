# chk-attr-001 — page block diagnostics report file line

Task: `refdes check` diagnostics for page blocks counted lines inside
`Page.body` (front matter stripped), so pages with front matter reported a
line a few lines early.

## What I did

- `src/refdes/pages.py` (`_read_page`): compute `front_matter_lines` = the
  number of newlines the matched front matter occupies in the file
  (`text.count("\n", 0, match.start(2))`) and set it on the returned `Page`
  as `page.front_matter_lines`. On the YAML-error path `body` stays the whole
  file, so the offset stays 0 and body-relative lines are already file lines.
- `src/refdes/blocks.py` (`extract_blocks`): new `line_offset: int = 0`
  parameter; `line_no` adds it. Diagnostic text unchanged. Default 0 keeps
  every other caller behavior identical.
- `src/refdes/build.py` (`render_pages`): pass
  `getattr(page, "front_matter_lines", 0)` at the single call site shared by
  all five block types.
- Changelog fragment `changelog.d/page-block-diagnostic-file-line.fixed.md`.
  Note: the task text lists `{{parts}}` as a block type; the registry
  (`blocks.py` `_REGISTRY`) has index, tree, compare, calcblock, cascade —
  no `parts` block exists, so the fragment names the real five.

## Verification

Scratch project in `.scratch/chk-attr-001` (repo config copied, one page with
4 front-matter lines + bad directive, control page without front matter, plus
a page exercising compare/tree/calcblock/cascade errors). Ran
`python -m refdes.cli main --no-write check` (PYTHONPATH=src):

- With fix: `pages/overview.md:8` (directive on file line 8, front matter
  lines 1-4), control `pages/control.md:5` unchanged; compare/tree/calcblock/
  cascade all report their true file lines (8/10/12/14).
- Baseline (git archive of HEAD src into `.scratch/headsrc`): reproduced the
  symptom exactly — `pages/overview.md:3`.

`tests/test_pages.py tests/test_blocks.py tests/test_calcblock.py
tests/test_compare_block.py` → 83 passed.

Finished.
