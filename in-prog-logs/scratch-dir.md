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

Status at this point: edits made; verification + commit pending.