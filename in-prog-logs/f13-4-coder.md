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
- Full suite: 4417 passed, 2 skipped.
- Finished.
