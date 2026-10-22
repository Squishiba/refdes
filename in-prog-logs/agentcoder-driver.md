# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py` (624 non-blank non-comment
lines, under the 700 goal), `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py` (31 tests, all passing on Linux; the module
is skipped on Windows). Committed on branch `feat-agentcoder-driver` off
main tip.

## Design (as shipped)

- `run <spec.json> [jobdir]` / `resume <jobdir>` / `status <jobdir>`; every
  exit path prints a JSON object (`status` + `reason` at minimum).
- Phases: spawn -> test_review -> execute -> candidate -> land -> report ->
  done. `job.json` rewritten atomically (temp + `os.replace`) at every
  transition, so resume is crash-safe. The kill/resume test computes the
  dry-run save count and parametrizes over every save point.
- Default jobdir `<repo>/.scratch/agentcoder/<task_id>` (`.scratch/` is
  gitignored here); keep job dirs out of tracked paths elsewhere.
- Tools resolved via `AGENTCODER_PASEO` / `AGENTCODER_GH` env vars; the
  tests use fake `paseo`/`gh` scripts this way.
- Executor runs `test_command` in a temp detached worktree of base (and of
  coder HEAD) with frozen test files checked out, scrubbed env, `prlimit`
  prefix when available, `-rA` appended for pytest; temp worktrees are
  removed (`worktree remove --force`) after each round, including on
  failure.
- Land: commit author `agentcoder <noreply@refdes.local>`, trailer
  `Co-authored-by: <last path segment of coder_model>
  <noreply@refdes.local>`; existing PR for the branch adopted before
  `gh pr create` (idempotent resume after a crash between create and save).
- Exit codes: 0 ready-for-human-gate, 2 escalated, 1 paused/error.

## Difficulties hit

- Parallel spawns raced on the fake paseo's state file; fixed with
  `fcntl.flock` in the fake (test-side only, driver unaffected).
- The outcome regex initially anchored `$`, which misses `-rA` summary
  lines of the form `FAILED <id> - reason`; un-anchored with `[ \t]+`
  separator.
- `dict(re.findall(...))` inverted the outcomes map (status as key) --
  every test looked NOT-RUN; now `{node: status}`.
- The test-filter step used raw `fnmatch(p, g)`, so a bare-directory glob
  like `tests` filtered every file out; `test_paths` became empty and
  `git checkout <sha> --` (empty pathspec) fully detached the candidate
  worktree at the *test* commit, making every candidate run red. Fixed to
  use the same `path_matches` (directory-prefix) rule as `scope_check`,
  plus an explicit escalation when the designer adds no test files.
- Review round 1 fixes (this pass): Windows skip + README note; reviewer
  pre-allocated None slot removed (resume retries the spawn); spec now
  requires a non-empty `title` and validates `task_id` with
  `git check-ref-format`; land adopts an existing PR via `gh pr list` and
  saves right after the number is parsed; repo validation accepts linked
  worktrees (`rev-parse --is-inside-work-tree`); a hung sibling spawn is
  killed with its peers; every blocking paseo/gh call has a timeout
  (TimeoutExpired -> Pause); spec gained `cases_file`; the Co-authored-by
  trailer is derived from `coder_model`; temp worktrees are removed after
  each round; every early-exit path prints JSON.
- Full-suite numbers (measured in this worktree, default basetemp): 4293
  passed, 2 skipped, 0 failed. An earlier run with `--basetemp` under
  `.scratch/` showed 15 scaffold/sealing failures -- those tests are
  sensitive to their temp dir living *inside* a git repo; that run was the
  artifact, the clean numbers are the truth. `ruff check
  tools/agentcoder/agentcoder.py tests/test_agentcoder_tool.py --select
  E9,F` is clean.

## Status

Finished. PR #356: "feat(tools): agentcoder -- a small driver for coder /
blind test designer / executor loops" (not merged, human gate).
