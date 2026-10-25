- AgentCoder workspaces: every agent a job spawns now runs in a **reused**
  workspace (`paseo run --workspace <id>`) instead of `paseo run
  --new-workspace` per agent. The job keeps at most one workspace per role —
  coder, designer, reviewer — recorded in `job.json` as `coder_workspace`,
  `designer_workspace`, `reviewer_workspace`; respawn, feedback rounds, and
  review round N all reuse the role's workspace. The old per-agent
  `--new-workspace` is what left a real pilot with 130+ abandoned workspaces.
  A spec can now pin existing active workspaces via a `workspaces` map (the
  coder and designer must be two different ids — the designer stays blind to
  the coder's tree); a role with no pinned id gets one created lazily at
  first spawn. Before each spawn the driver resets the workspace tree to the
  branch that agent needs, and a **dirty** tree **pauses** the job rather
  than silently resetting uncommitted work. The driver never archives or
  deletes a workspace: after the PR lands, `paseo workspace archive <id>`
  for the job's one-to-three ids is the human's cleanup step.
