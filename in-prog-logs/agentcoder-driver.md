# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py`, `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py`, committed off main tip.

## Design (as shipped)

- Current size: driver 782 non-blank non-comment lines (~1000 soft sanity
  ceiling, plain readable lines); 77 driver tests, all passing on Linux,
  module skipped on non-Linux (prlimit is Linux-only); full suite
  4339 passed / 2 skipped / 0 failed; ruff (E9,F on the two files) clean.
  All measured with pytest's default basetemp: an earlier "15 failures"
  claim was an artifact of running with `--basetemp` inside the repo tree
  (scaffold/sealing tests are sensitive to a temp dir inside a git repo).
- `run <spec.json> [jobdir]` / `resume <jobdir>` / `status <jobdir>`: every
  run/resume/status exit prints a JSON object (`status` + `reason` at
  minimum); a bare `main()` call prints usage and exits 1 (not JSON). The
  JSON summary is printed exactly once per invocation; the PR line rides
  stderr.
- Phases: spawn -> test_review -> execute -> candidate -> land -> report ->
  done. `job.json` rewritten atomically (temp + `os.replace`) at every
  transition, so resume is crash-safe. The kill/resume test computes the
  dry-run save count and parametrizes over every save point.
- Default jobdir `<repo>/.scratch/agentcoder/<task_id>` (`.scratch/` is
  gitignored here); keep job dirs out of tracked paths elsewhere.
- Tools resolved via `AGENTCODER_PASEO` / `AGENTCODER_GH` env vars; the
  tests use fake `paseo`/`gh` scripts this way. The fake rejects any flag
  the real CLI does not accept (verified per `paseo <cmd> --help`).
- Executor runs `test_command` (must be pytest) in a temp detached worktree
  of base (and of coder HEAD) with frozen test files checked out, scrubbed
  env, `prlimit` prefix when available, `--junitxml` (job dir) + `--rootdir`
  pinned for pytest; temp worktrees are removed
  (`worktree remove --force`) after each round, including on failure.
- Scope guards: `in-prog-logs/**` (the AGENTS.md progress logs both agents
  must write) is always allowed; one genuine violation buys the agent one
  "revert these paths" feedback round before escalating.
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
- Reviewed in numbered rounds, one sentence each. Round 1 added Windows
  skip, spec validation, idempotent PR adoption at land, linked
  worktree repos, timeouts on every blocking call, `cases_file` and JSON
  on every early exit. Round 2 closed the false-green (strict outcomes from
  cases.json, worktree reset on reuse, preflight ordering, prlimit gate).
  Round 3 made preflight un-skippable via a `preflight_ok` flag, turned
  swallowed timeouts into honest pauses, and added the land guards and
  PR-state rules. Round 4 (docs) pinned `base_sha` at first resolution and
  documented idempotency, blindness-by-instruction, timeout/exit-code
  behavior and the basetemp caveat. Round 5 made land's moved-head guard
  forge-proof (no commit-message string matching), sha-scoped the
  test-review gate, persisted agent ids on every completed turn, and made
  the tests independent of the machine's git identity (the local
  `~/.gitconfig` had masked a CI-only failure).

## Rounds 7-11 (review passes)

Round 7: outcomes stopped trusting agent stdout (driver-owned `--junitxml`,
pinned `--rootdir`; forged `PASSED` lines can no longer satisfy the gate),
`{tests}` expands driver-side with a zero-match Pause, and the kill-sweep
stops job agents by title; tests 43->47.

Round 8: junit node ids resolve class-based classnames to real files, the
sweep spares recorded agents, resume respawns recorded-dead ones, XPASS
documented as PASSED, linux-only skip; tests 47->54.

Round 9: every `paseo ls` consumer moved to the live-verified keys (the
fake had invented keys that silently disabled the Qwen cap, the sweep and
resume), verdicts must be the final log line, deleted/renamed-away test
files no longer stall land, a failed land commit un-stages the driver's own
files, dead reviewers respawn; tests 54->63.

Round 10: land's two crash windows close (test-path-confined dirt on resume
is the driver's own interrupted checkout; a committed-but-unsaved test head
is adopted, not re-gated), a missing binary pauses instead of crashing,
cases.json entries must be objects; mid-round the 700-line cap was lifted
to ~1000 as a soft sanity ceiling and the fit-to-700 compressions were
un-golfed; tests 63->67.

Round 11 (first REAL pilot run end to end, plus round-10 reviews):
`paseo run` takes the provider string via `--provider` (`--model` alone
fails MISSING_PROVIDER; the fake now rejects unknown flags so this can't
regress), `in-prog-logs/**` is scope-exempt for both agents and the
designer's log rides along in the PR, out-of-scope gets one feedback round
before escalating, prompts demand relative paths (absolute `cd` triggers
permission prompts), a permission stop pauses with actionable text, the
final streamed JSON doc wins and the summary/PR line print exactly once,
dead = closed/error (no "stopped" in the real vocabulary), land's adopt
matches globs per path (disjoint globs adopted), non-pytest
`test_command` rejected up front, porcelain `R old -> new` rows parsed;
tests 67->77.

## Status

Finished: the driver ran the real loop end to end in the first pilot (see
the README's "Verified against the real CLI"). CI state is per-head, not
global: green is re-measured on each push, never assumed -- an early head
went red on CI only, where runners lack a git identity that the author's
local config masked; the identity-independence fixture fixed that.
