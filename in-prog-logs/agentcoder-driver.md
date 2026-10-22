# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py`, `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py`. Committed on branch `feat-agentcoder-driver`
off main tip.

## Design (as shipped)

- Current size: driver 697 non-blank non-comment lines (under the 700 goal
  -- nearly full, future changes here should expect to delete code to add
  any); 37 tests, all passing on Linux, module skipped on Windows; full
  suite 4299 passed / 2 skipped / 0 failed; ruff (E9,F on the two files)
  clean. All measured with pytest's default basetemp: an earlier "15
  failures" claim was an artifact of running with `--basetemp` inside the
  repo tree (scaffold/sealing tests are sensitive to a temp dir inside a
  git repo).
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
  <noreply@refdes.local>`; existing OPEN PR for the branch (or MERGED at
  the gated coder sha) adopted before `gh pr create`; CLOSED unmerged
  escalates; failing `gh pr list` pauses.
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
- Reviewed over 4 rounds (headless reviewers, driver + tests + README
  legs). Main changes: round 1 added Windows skip, spec validation
  (`title`, `git check-ref-format`), idempotent-land PR adoption, linked
  -worktree repos, sibling-kill + timeouts on every blocking call,
  `cases_file`, model-derived trailer, JSON on every early exit; round 2
  closed the false-green (strict outcomes: every cases.json id must show
  PASSED, SKIPPED/XFAIL/XPASS/exit-5 red, worktree reset on reuse,
  preflight ordering, prlimit gate); round 3 made preflight un-skippable
  via a `preflight_ok` flag re-checked by every resume, turned swallowed
  test/git timeouts into honest pauses, added land guards (moved HEAD /
  dirty tree escalate) and PR-state rules (adopt OPEN, MERGED-at-gated-sha
  only; CLOSED escalates), and corrected the README; round 4 (docs) pinned
  `base_sha` at first resolution, documented idempotency precisely, said
  plainly that designer blindness is by instruction not enforcement,
  documented the exact timeout/exit-code behavior, and added the suite
  basetemp caveat.

## Status

Finished. PR #356: "feat(tools): agentcoder -- a small driver for coder /
blind test designer / executor loops" (not merged, human gate).
