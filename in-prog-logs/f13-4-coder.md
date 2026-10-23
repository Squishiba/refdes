# f13-4 — invalid page front-matter warning printed twice, no line

## Root cause
`refdes check`/`refdes build` print the warning twice because a writable
run loads the pages twice, both loads intentional and both needed:
1. `loader.load_tree` -> `image_freeze.freeze_images` (src/refdes/image_freeze.py:130)
   calls `pages.load_pages` to scan page bodies for image references,
2. `build()` (src/refdes/build.py:3960) calls it again to pick up freeze's
   disk rewrites.

Verified with a stack trace of `load_pages` on a scratch project in
`.scratch/f13-4/proj` (reproduced the double print first).

## Fix (src/refdes/pages.py)
- Per-page dedupe guard on the project (`_front_matter_warned` set keyed by
  the project-relative path), the same pattern `citations.read_lockfile`
  uses for a multi-reader message. Chose this over removing a load: neither
  load is removable (freeze needs page bodies, build needs the rewritten
  text).
- File line computed in `_front_matter_file_line`:
  `text.count("\n", 0, match.start(1)) + 1 + exc.problem_mark.line`
  (mark is 0-based in the front-matter text; group 1 starts on file line 2
  for a plain file, later if `\s*` swallowed a blank line after the fence).
  Falls back to the opening fence line (`count("\n",0,match.start(0))+1`)
  when no mark.
- `_front_matter_detail` composes `context; problem` from the MarkedYAMLError
  so the message keeps YAML's wording without the front-matter-relative
  "line N, column M" position part.

## Verification
- Scratch project: top-of-file bad line -> `pages/badyaml.md:2`, later line
  -> `:3`, blank line after fence -> `:3`; one warning each through
  `refdes check` and `refdes build` (real CLI).
- Full suite: 4427 passed, 2 skipped (the 4417 first reported was the pre-designer
  count; re-run on the PR head after the review fixes: 4427).
- Finished.

## PR #369 review round (2026-10-23)

Three findings, all fixed in one follow-up commit:
1. No-mark fallback (`ReaderError`, e.g. a NUL byte) leaked
   `in "<unicode string>", position 7` via `str(exc)` -- the exact
   front-matter-relative position the ticket removes.
   `_front_matter_detail` now strips the `in "...", position N` /
   `line N, column M` tail with `_YAML_POSITION_TAIL_RE`, keeping the
   cause. Extended `test_no_mark_falls_back_to_fence_line` with the
   absence assertions (authorized one test edit; no existing assertion
   weakened).
2. `_front_matter_warned` getattr/setattr -> declared as a real field
   `front_matter_warned: set[str] = field(default_factory=set)` on
   `Project` (model.py, next to `pages`), plain like neighbouring fields
   (no repr/compare exclusions exist on this dataclass), used directly.
3. This log's stale 4417 count (above) and the designer log's mention of
   `tests/f13-4.cases.json`, which is not in this PR -- both corrected.

Verified: NUL page through the real CLI prints
`pages/nul.md:1 -- invalid page front-matter: unacceptable character
#x0000: special characters are not allowed` (no position tail, fence
line). Targeted tests 26 passed; `ruff check --select E9,F,I001` clean on
the touched files; full suite above.
