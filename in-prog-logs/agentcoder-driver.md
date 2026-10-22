# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py` (657 non-blank non-comment
lines, under the 700 goal), `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py` (29 tests, all passing on Linux; the module
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
- Review round 2 fixes: false-green closed -- the outcome regex now also
  captures SKIPPED/XFAIL/XPASS, `compare_cases` requires 'fail' ids to be
  FAILED on base (not PASSED-only-checked before), and the candidate gate
  (`gate_failures`) demands EVERY cases.json id show PASSED; missing ids
  report NOT-COLLECTED (skip summary lines carry file:line, not the id),
  exit 5 is red. `ensure_worktree` resets a reused worktree
  (`checkout --force --detach <sha>` + `clean -fdq`) so a kill between
  `worktree add` and cleanup can't test a stale tree. Preflight runs AFTER
  the first save (preflight pause leaves job.json + report.md), sets
  base_sha before its checks, re-runs on resume when unverified, and pauses
  when `prlimit` is missing unless `allow_no_prlimit: true`. Collection is
  side-effect free (kill-every-save test counts save points at run time).
  README branch names / max_rounds / prlimit / PR-body claims corrected.
- Full-suite numbers (measured in this worktree, default basetemp): 4291
  passed, 2 skipped, 0 failed. An earlier run with `--basetemp` under
  `.scratch/` showed 15 scaffold/sealing failures -- those tests are
  sensitive to their temp dir living *inside* a git repo; that run was the
  artifact, the clean numbers are the truth. `ruff check
  tools/agentcoder/agentcoder.py tests/test_agentcoder_tool.py --select
  E9,F` is clean.

## Round 3 (reviewers: driver + README, on the round-2 head)

- Preflight was escapable: a pause inside it left `base_sha` set, and resume
  keyed re-verification off `base_sha is None`, so the prlimit/capacity
  gates were skipped on the next resume. Fixed with an explicit
  `preflight_ok` flag set only after ALL checks pass, re-checked by every
  resume via one `ensure_preflight` helper (also de-duplicated the two
  call sites); tests prove resume re-pauses for prlimit-missing and a full
  Qwen cap until the condition clears, then proceeds.
- `run_tests` swallowed its own timeout (empty outcomes -> the run got
  blamed/judged); now a timeout, and any exit outside {0,1,5} with no
  per-test outcomes, PAUSEs with the real reason. `git()` gained a 120s
  default timeout (300s for push) + `GIT_TERMINAL_PROMPT=0` -> Pause.
- Land now refuses a moved coder HEAD (only land's own test commit on a
  resume is accepted) and a dirty tracked tree (escalate, before checkout,
  so `git add`ed garbage can't be swept into the test commit).
- PR adoption: adopt only OPEN PRs, or MERGED with head == gated coder SHA;
  CLOSED unmerged -> escalate; failing `gh pr list` -> pause (no blind
  create). Designer feedback uses `cases_file` from the spec, not a
  hardcoded path; `check_permits` rc!=0 and an unreadable contract no
  longer report "all clear"/empty text silently.
- README: exit-path list (no-args prints usage, not JSON; `status` exits
  0), pause-vs-escalate classification (dropped the stale-SHA claim),
  reviewer branch placement, PR-body contents, candidate green = exit 0
  AND all ids PASSED, `agent_timeout`/`test_timeout` documented, fnmatch
  scope-matching + raw `{tests}` noted in Limits.
- 36 driver tests (7 new); full suite 4298 passed, 2 skipped, 0 failed;
  ruff (E9,F on the two files) clean; driver at 696 non-blank/non-comment
  lines (cap 700 -- it is nearly full; future work on this file should
  expect to delete code to add any).

## Status

Finished. PR #356: "feat(tools): agentcoder -- a small driver for coder /
blind test designer / executor loops" (not merged, human gate).
