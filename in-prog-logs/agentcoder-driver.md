# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py`, `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py`. Committed on branch `feat-agentcoder-driver`
off main tip.

## Design (as shipped)

- Current size: driver 700 non-blank non-comment lines (at the 700 goal
  -- future changes here must delete code to add any); 63 tests, all
  passing on Linux, module skipped on non-Linux (prlimit is Linux-only);
  full suite 4325 passed / 2 skipped / 0 failed; ruff (E9,F on the two
  files) clean. All measured with pytest's default basetemp: an earlier "15
  failures" claim was an artifact of running with `--basetemp` inside the
  repo tree (scaffold/sealing tests are sensitive to a temp dir inside a
  git repo).
- `run <spec.json> [jobdir]` / `resume <jobdir>` / `status <jobdir>`: every
  run/resume/status exit prints a JSON object (`status` + `reason` at
  minimum); a bare `main()` call prints usage and exits 1 (not JSON).
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
  prefix when available, `--junitxml` (job dir) + `--rootdir` pinned for
  pytest; temp worktrees are
  removed (`worktree remove --force`) after each round, including on
  failure.
- Land: commit author `agentcoder <noreply@refdes.local>`, trailer
  `Co-authored-by: <last path segment of coder_model>
  <noreply@refdes.local>`; a moved coder head bounces back to re-gate at
  candidate; existing OPEN PR for the branch (or MERGED at the
  driver-recorded pushed sha) adopted before `gh pr create`; CLOSED
  unmerged escalates; failing `gh pr list` pauses.
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
- Reviewed over 5 rounds (headless reviewers, driver + tests + README
  legs). Main changes: round 1 added Windows skip, spec validation
  (`title`, `git check-ref-format`), idempotent-land PR adoption, linked
  -worktree repos, sibling-kill + timeouts on every blocking call,
  `cases_file`, model-derived trailer, JSON on every early exit; round 2
  closed the false-green (strict outcomes: every cases.json id must show
  PASSED, SKIPPED/XFAIL/XPASS/exit-5 red, worktree reset on reuse,
  preflight ordering, prlimit gate); round 3 made preflight un-skippable
  via a `preflight_ok` flag re-checked by every resume, turned swallowed
  test/git timeouts into honest pauses, added land guards and PR-state
  rules, and corrected the README; round 4 (docs) pinned
  `base_sha` at first resolution, documented idempotency precisely, said
  plainly that designer blindness is by instruction not enforcement,
  documented the exact timeout/exit-code behavior, and added the suite
  basetemp caveat; round 5 made land's moved-head guard forge-proof (HEAD
  must equal the gated sha, the driver-recorded test-commit/pushed sha, or
  bounce to re-gate -- no commit-message string matching), made the
  test-review gate sha-scoped (designer commits after an APPROVE re-enter
  review, fresh reviewer per sha), made the MERGED-PR adoption compare the
  driver's recorded pushed sha, absolutized jobdir, gave
  `validate_spec`'s git calls the guarded timeout, persisted agent ids on
  every completed turn, and made the driver tests independent of the
  machine's git identity (a module fixture sets the identity and points
  git config at /dev/null; local `~/.gitconfig` had masked a CI-only
  failure in round 4).
## Rounds 7-9 (review passes)

Round 7 (numbered 5->7: round 6 was review-only, no code changes): outcomes
stopped trusting agent stdout (driver-owned `--junitxml`, `--rootdir` pinned;
forged `PASSED` lines can no longer satisfy the gate), `{tests}` expands
driver-side with a zero-match Pause, the kill-sweep stops job agents by title
and records `stopped_agents`; tests 43->47.

Round 8: junit node ids resolve class-based classnames to real files,
`expand_tests` keeps dirs + `.py`, the sweep spares recorded agents and
resume respawns recorded-dead ones, XPASS documented as PASSED, linux-only
skip; tests 47->54.

Round 9: every `paseo ls` consumer moved to the real, live-verified ls keys
(`id`/`name`/`provider`/`cwd` -- the fake had invented `agentId`/`title`/
`model`, silently disabling the Qwen cap and the sweep and making every
resume respawn recorded agents), the fake now emits the verified schema,
verdicts must be the final log line (thought-block text never counts),
`allow_no_prlimit` must be a real bool, deleted/renamed-away test files no
longer stall land, a failed land commit un-stages the driver's own staged
files, dead reviewers respawn, docs fixes; tests 54->63, driver at 700 lines.

## Status

Finished. PR #356:
"feat(tools): agentcoder -- a small driver for coder /
blind test designer / executor loops" (not merged, human gate). CI state is
per-head, not global: the round-3 head was green on all three legs
(ubuntu, ubuntu 3.13, windows-latest); the round-4 head went red on both
ubuntu legs (a new test needed a git identity, which the runners lack and
the author's `~/.gitconfig` masked locally); the round-5 commit carries
the identity-independence fixture that fixes that. Green is re-measured on
each push, never assumed.
