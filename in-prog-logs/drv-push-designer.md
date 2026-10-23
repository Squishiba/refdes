# drv-push — blind test designer

Task: write acceptance tests for the DRV-PUSH defect — `do_land` in
`tools/agentcoder/agentcoder.py` pushed the coder branch BY NAME
(`git push -u origin <branch_name(job,'coder')>`), which pushes the LOCAL
branch of that name. After a `resume` respawn put the coder in a deduped
worktree checked out on a dash-named branch (`ac-<task>-coder`), the
slash-named local branch is a stale ref left at base by the abandoned
original worktree, so the push lands base, not the just-landed commit.
Contract fix: push HEAD explicitly
(`git push -u origin HEAD:refs/heads/<branch_name(job,'coder')>`), FF only.

I am blind to the implementation; I only wrote tests under the allowed
paths. No product code touched.

## Files written
- `tests/test_agentcoder_land_push.py` (NEW): two tests driving the real
  land phase against a real local bare `origin`, reusing `build_env` /
  `gitat` / `agentcoder` / the fake-gh+fake-paseo fixtures by loading
  `tests/test_agentcoder_tool.py` as a module (no edit to that file).
  - `test_land_pushes_head_when_coder_branch_is_deduped_renamed` (RED on
    base): wraps `HANDLERS["land"]`; before the real land it renames the
    coder worktree's checked-out branch to `ac-t1-coder` and forces the
    slash branch `ac/t1/coder` back to `base_sha` (the dedup scenario).
    Runs the whole flow to done. Asserts `refs/heads/ac/t1/coder` in the
    bare origin equals the worktree HEAD, and `pushed_sha` equals it.
  - `test_land_pushes_expected_branch_when_names_already_match` (control,
    GREEN on base): plain happy path; worktree stays on `ac/t1/coder`;
    origin ref == worktree HEAD == pushed_sha.
- `tests/drv-push.cases.json`: maps both node ids (dedup = `fail`,
  control = `pass`).

## Verification
`PYTHONPATH=src ...pytest -q tests/test_agentcoder_land_push.py`
against the BASE (unmodified) driver: **1 failed, 1 passed**.
- FAILED: `test_land_pushes_head_when_coder_branch_is_deduped_renamed`
- PASSED: `test_land_pushes_expected_branch_when_names_already_match`

Probe (`.scratch/drv-push-probe.py`) confirmed the mechanism on base code:
after land the worktree HEAD is the land test-commit on `ac-t1-coder`,
`pushed_sha` == that HEAD, but `refs/heads/ac/t1/coder` on origin ==
`base_sha` (the stale branch) — landed work never pushed. A scratch git
sim (`.scratch/fix_sim.py`) showed the `HEAD:refs/heads/...` refspec pushes
HEAD, flipping origin == HEAD (the sim needed `-f` only because the scratch
base had diverged; the real fix is FF-only, which holds in the land flow).

## Notes
- Fake gh default returns `pr list -> []` then a PR URL on create, so the
  land phase runs `gh pr create` (no real PR); the push is real git and is
  what the assertions read.
- The autouse git-identity fixture is module-scoped in the source test file
  and not auto-discovered cross-module; commits in the land phase supply
  `-c user.*` explicitly, so the flow is identity-independent (probe set the
  env directly).
- Status: finished — red/green split as required.
