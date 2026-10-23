# f13-4 designer — invalid page front-matter warning: once, with a file line

Role: blind test designer. Wrote no product code. Tests only in
`tests/test_page_front_matter_warning.py` and `tests/f13-4.cases.json`,
plus this log.

## What I found (all verified by running, blind to the fix)

- The double print is a double **load**, on a **writable** run only:
  `cli._load` -> `loader.load_tree` -> (`write=True`) `image_freeze.freeze_images`
  -> `pages.load_pages` warns once; then `cmd_check`/`cmd_build` ->
  `build()` (build.py:3960) -> `pages.load_pages` warns again. So `check` and
  `build` (writable) printed the warning **2x**; `check --no-write` printed it
  **1x** (freeze_images gated off). Confirmed by running the CLI on a scratch
  pages-only project.
- `_build_at` (helpers) does NOT reproduce the double load — it skips
  `load_tree`/`freeze_images` and loads pages once. So every test here drives
  the real CLI entry `cli.main([...])` + `capsys`, as the contract requires.
- The missing line: `pages._read_page` warns `file=rel_to_root` with no `line`,
  so the diagnostic prints `pages/badyaml.md` with no `:N`, unlike every other
  page diagnostic. The embedded YAML excerpt ("line 1, column 8") is
  front-matter-relative.

## Line math (verified in a probe against the installed PyYAML)

`FRONTMATTER_RE = ^---\s*\n(.*?)\n---\s*\n?(.*)$` (DOTALL). Opening `---` fence
is file line 1; the front-matter text is group(1), whose first line is file
line 2. The `\s*` after `---` swallows blank line(s) after the fence, pushing
group(1) down. `problem_mark.line` is 0-based within group(1). File line =
`<group(1) start file line>` + `problem_mark.line`. Cases + hand-computed
expected lines:
- `title: [unclosed` first line (mark 0) -> 2
- bad on 2nd front-matter line (mark 1) -> 3
- one blank line after the fence, mark 0 -> 3 (regex allows the blank)
- bad on 3rd front-matter line (mark 2) -> 4
- NUL byte in front matter -> `ReaderError` (a `YAMLError` with NO
  `problem_mark`) -> fall back to opening fence -> 1
- blank line BEFORE the fence -> `FRONTMATTER_RE.match` (anchored at pos 0)
  does NOT match -> no front matter -> no warning (regex does not allow it).

## Test outcomes on base (this branch, pre-fix)

`pytest tests/test_page_front_matter_warning.py` -> 7 failed, 3 passed.
- Fail (new behavior): top/later/blank-after-fence/deep line cases (no `:N`
  on base), no-mark fallback, count==1 on check, count==1 on build.
- Pass (controls): valid front matter, no front matter, blank-before-fence.
Each line/count assertion fails on base for the intended reason (verified by
reading base stdout: 2 warnings, `pages/badyaml.md` with no line).

Assertions are implementation-agnostic: count once in CLI output; the printed
`where` contains `pages/badyaml.md:<file line>`; message keeps the
`invalid page front-matter:` prefix; the front-matter-relative "line R,
column" wording is gone (file line > R always, so a fix that *replaces* the
excerpt position with the file line also satisfies it).

Ruff clean on the new test file. cases.json node ids match `--collect-only`
1:1.
