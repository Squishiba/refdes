# drv-push: land phase pushes coder HEAD by refspec

Task: the driver's `do_land` pushed the coder branch *by name*
(`git push -u origin ac/<task>/coder`), so a respawned coder living on a
differently named local branch (e.g. `ac-f13-4-coder` in a deduped
worktree, job f13-4) pushed a stale local branch of the expected name
instead of the landed HEAD — `gh pr create` then failed with "no commits
between main and <branch>".

Change (tools/agentcoder/agentcoder.py, one line in `do_land`):
`git push -u origin HEAD:refs/heads/<branch_name(job,'coder')>` — fast-forward
only, no `--force`. `job["pushed_sha"]` is still read back as the worktree
HEAD after the push, unchanged. Grep for `"push"`: line 885 was the only
push site in the driver; `pushed_sha` reads elsewhere are unaffected.
Added the matching sentence to tools/agentcoder/README.md at the land-phase
push description.

Verification (`.scratch/drv-push/check.py`, direct `do_land` against a real
bare origin, `pr_number` preset to skip gh):
- control (local branch already named `ac/x/coder`): origin ref == landed
  HEAD — passes on old and new code.
- mismatch (local branch `ac-x-coder`, stale `ac/x/coder` at base in the
  shared repo): OLD code pushes the stale base commit (origin ref == base,
  reproducing f13-4 — the acceptance test fails on current code as
  required); NEW code pushes the landed HEAD — passes.
- `tests/test_agentcoder_tool.py`: 114 passed after the change.
The acceptance test file itself is the designer's deliverable (not written
here, per task rules).

Status: finished.
