# Finding 12 — Fix the `body:`-in-list-files rationale

Docs and comment wording only; no behavior change.

## What I did

1. Grounded first: read backlog.md §12, then README.md "Authoring" (lines 51–95),
   which states the fact outright — a `.md` file is "not limited to one item: a
   further `---` starts a new item's front-matter, and an optional leading block
   whose only key is `defaults:` applies to every item that follows". docs/authoring.md's
   own "Several items in one file" section says the same. So the old rationale —
   that steering log entries into YAML lists avoids "one file per entry" — was
   defending against a constraint that never existed.
2. `docs/authoring.md`, "### Bodies in list files": replaced the two-sentence
   lead-in. It now says a `.md` file already holds many items sharing one
   `defaults:` block, so the tradeoff is not file count but whether an entry
   carries prose — a bare date-and-summary entry is fine as a list entry, one
   with a paragraph belongs in `.md`, and `body:` covers the middle. Same
   length (4 lines), same register as the surrounding prose.
3. `src/refdes/parse.py`, comment above `RESERVED`: same correction in the
   comment's own voice. `RESERVED` itself and every other line untouched — the
   diff is comment text only.

## Diff shape

- docs/authoring.md: 1 hunk, 4 lines replaced by 4.
- src/refdes/parse.py: 1 hunk, comment lines only (3 → 4).

## Difficulties

- The shell whitelist refuses `cd`, so everything ran with absolute paths and
  `git -C <worktree>`. pytest was pointed at the worktree's `tests/` directly;
  `import refdes` fails outside it, which confirms the run resolved the package
  from this worktree's `src/` and not from some other install.
- `in-prog-logs/` did not exist in this worktree; created it with this file.

## Verification

- `grep -rn "one file per entry" docs/authoring.md src/refdes/parse.py` → no matches.
- `grep -rn "one file per daily entry" docs/authoring.md src/refdes/parse.py` → no matches.
- `python -m pytest <worktree>/tests -q` → 650 passed, 0 failed.
- `git status --short` → exactly docs/authoring.md, src/refdes/parse.py,
  in-prog-logs/finding-12.md.

Committed locally as `docs: state the real body:-in-list-files tradeoff, not a
false one`. Not pushed, no PR.

## Status

Finished.
