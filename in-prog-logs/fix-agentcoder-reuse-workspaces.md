# Fix AgentCoder driver to reuse workspaces (one per role)

Task: the driver spawned every agent with `paseo run --new-workspace
worktree ...`, so every turn — respawns, review rounds — created a new
Paseo workspace. A real pilot ended with 130+ abandoned workspaces. Fix:
at most ONE workspace per role (coder/designer/reviewer) per job, reused
via `paseo run --workspace <id>`; the driver never passes
`--new-workspace`.

## What was verified live (probe, then archived)

Against the real CLI (probe output kept in `.scratch/wsprobe/`):
- `paseo workspace create --isolation worktree --mode branch-off
  --new-branch probe/ac-reuse-1 --base main --title probe --json` →
  JSON `{workspaceId, project, name, isolation, cwd}` (NO `id` key;
  cwd under `~/.paseo/worktrees/<daemon>/`).
- `paseo run --workspace <id> ... --json` prints a plain
  `Using workspace wks_...` banner line BEFORE the JSON
  `{agentId, status, provider, cwd, title}`; the driver's
  last-json-of-stdout parsing tolerates the banner. Two runs on one id
  both land in that workspace's recorded cwd; `workspace ls` shows no
  new workspace.
- `paseo workspace ls --json` lists ACTIVE workspaces only, keyed
  `workspaceId`.
- `paseo workspace archive <id> --json` → `{workspaceId, status:
  "archived", archivedAt}`; gone from `ls`. Probe workspace archived
  after the run.

## Design decisions

- Lazy per-role creation, ordered: id recorded in job.json → spec
  `workspaces[role]` → `workspace create` (recorded BEFORE launching).
- Spec `workspaces` validation: must be an object over roles
  coder/designer/reviewer; ids must be non-empty strings AND present in
  `paseo workspace ls --json`; coder==designer rejected (blindness).
- `job.json` keys `coder_workspace`/`designer_workspace`/
  `reviewer_workspace` survive pause/resume.
- Before every spawn, `prepare_tree` resets the workspace tree:
  `git checkout -B <branch> <sha>` (reviewer base = frozen test SHA);
  a dirty tree (`status --porcelain -uno` non-empty) PAUSES — "refusing
  to reset uncommitted work". No silent reset.
- Reviewer rounds share one workspace (`review*` roles map to the
  `reviewer` key); each round's agent gets its own branch in it.
- The driver NEVER archives/deletes workspaces — README documents the
  human's post-landing `paseo workspace archive` cleanup.

## Tests

New file `tests/test_agentcoder_workspaces.py` (11 tests / 13 params),
driven through the fake-paseo end-to-end suite (fake updated: `workspace
ls/create/archive` commands, `run --workspace` with the
`Using workspace <id>` banner). First run against the OLD driver:
13 failed (full log `.scratch/wsprobe/old-code-failures.txt`), e.g.
`assert '--new-workspace' not in ['run', '--new-workspace', ...]`,
`KeyError: 'coder_workspace'`. Against the new driver: 13 passed
(66.65s). Full agentcoder set (tool + land_push + workspaces):
142 passed in ~216s.

Fake-paseo gotcha found en route: workspace `create` must NOT consume
the agent-id `seq` counter (3 resume tests that hardcode `a1` broke
when it did; workspaces got their own counter).

## Mutation checks (disposable copies in `.scratch/mut1..4`)

Each mutation breaks exactly the behavior one test should catch; all
four are caught:
1. reviewer spawn back to `--new-workspace` →
   `test_review_rounds_share_one_reviewer_workspace` FAILED.
2. parallel spawn back to `--new-workspace` →
   `test_every_spawn_uses_one_workspace_per_role` FAILED.
3. dirty-tree check removed →
   `test_dirty_workspace_tree_pauses_respawn` FAILED. First run of
   this mutation ESCAPED: the test asserted `"dirty" in reason` and
   passed on the git-refusal message because the pytest tmp path
   literally contains "dirty" (test function name). Test hardened to
   assert the driver's own phrase "refusing to reset"; mutation then
   caught.
4. coder==designer validation removed →
   `test_spec_coder_designer_same_workspace_rejected` FAILED.

## Docs

- `tools/agentcoder/README.md`: 883 → 955 non-blank/non-comment lines
  (recounted); new "Workspaces" section (reuse model, lazy creation,
  dirty-tree pause, human archive step); spec `workspaces` key;
  spawn/test_review/idempotency/Limits bullets rewritten for reuse
  semantics; workspace CLI facts added to "Verified against the real
  CLI" (probe runs).
- `changelog.d/agentcoder-reuse-workspaces.fixed.md` added.

Status: COMPLETE. Landed on branch `fix/agentcoder-reuse-workspaces`
with PR (see repo); not merged.
