# scratch-dir — gitignored .scratch/ for agent temporary files

Task: add a gitignored per-worktree scratch directory (`.scratch/`) and point
agents at it in AGENTS.md; also drop a stale `refdes.yaml` mention from a
.gitignore comment.

## Progress

- Synced first: `git merge --ff-only main` -> "Already up to date."
- `.gitignore`: added `.scratch/` with a comment in the same style as the
  existing blocks (per-worktree scratch area, never committed, nothing in it
  needs cleaning up). Updated the `**/.refdes/schema.json` comment so it no
  longer names `refdes.yaml` (retired — project config is now
  `refdes-project.yaml` plus optional `refdes-schema.yaml`); changed nothing
  else in that comment.
- `AGENTS.md`: added a short "Temporary files go in .scratch/" section right
  after the "When working on a task, document your changes" section covering:
  where to put temporary files, not deleting/moving them, never writing
  outside the working directory, and explicit staging by path.
- Verification to run: `git check-ignore -v .scratch/anything.txt`,
  `grep -n "refdes.yaml" .gitignore` (expect nothing), full test suite
  (expect 702 passed), `git status --short` (expect only the three files).
- Then commit (no push).

## Verification & result

- `git check-ignore -v .scratch/anything.txt` ->
  `.gitignore:44:.scratch/	.scratch/anything.txt` (ignored by the new line).
- `grep "refdes.yaml" .gitignore` -> no matches. Note: the `ornith-docs/`
  comment also named `refdes.yaml`; since the DONE gate requires zero
  matches, that mention was reworded to "its own project config" too
  (ornith-docs is not on disk here, so the config name couldn't be
  verified). Only the schema.json comment was explicitly required by the
  task text, but the grep gate forced this second one.
- `python -m pytest tests/ -q` -> 702 passed, 0 failed (26.23s).
- `git status --short` before commit -> exactly `.gitignore`, `AGENTS.md`,
  `in-prog-logs/scratch-dir.md`.
- Committed (not pushed): 3f18bd0.

FINISHED.