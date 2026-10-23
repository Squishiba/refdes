# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a plain driver script.
Built: `tools/agentcoder/agentcoder.py` (one file), `tools/agentcoder/README.md`,
`tests/test_agentcoder_tool.py`. The driver runs a fixed phase loop
(spawn -> test_review -> execute -> candidate -> land -> report), saves
`job.json` atomically at every transition, and `resume` continues from the
last save. A blind designer agent writes acceptance tests, a coder agent
implements the contract; the driver gates both with pytest on base
(cases.json controls/intended-reds) and on the coder's HEAD, scope-checks
unfiltered diffs, lands the frozen test commit, opens the PR. It never
merges anything.

## Pilot runs (real CLI)

- The default path (no reviewer, no feedback round-trips) was run end to
  end on the real CLI; CHK-ATTR-003 produced PR #357.
- What the pilots found: `--model` alone fails (provider string via
  `--provider`; the fake now rejects every flag the real CLI lacks);
  absolute-path `cd` in prompts triggers broad permission prompts (prompts
  now demand relative paths); `paseo run --json` streams a running doc then
  the final one (the LAST json doc is parsed); `paseo ls -g` keys differ
  from the fake's invented ones; `in-prog-logs/**` is required of both
  agents by AGENTS.md (now scope-exempt).
- The EDIT-03 job added one live feedback send and one live resume.
- Everything else that needs a failure to exercise — the feedback loops,
  test review, crash-window recoveries, `paseo wait`/`stop` under failure —
  is covered by the fake only, except the two live events above.

## Difficulties

- Parallel spawns raced the fake's state file; fixed with `fcntl.flock`.
- Outcome judging started as a stdout regex (the `$` anchor missed
  `-rA`-style summary lines; a `dict(re.findall(...))` inversion inverted
  the map); it was replaced wholesale by driver-owned junit XML with a
  pinned `--rootdir`, so agent-printed `PASSED` lines can't forge a green.
- The fake had invented `paseo ls` keys, which silently disabled the Qwen
  cap, the sweep and resume adoption; every consumer moved to live-verified
  keys.
- `--basetemp` inside a repo tree fails the scaffold/sealing tests
  spuriously; every green number here is measured at pytest's default
  basetemp.
- One failure appeared on CI only: runners lack a git identity the author's
  `~/.gitconfig` masked; tests are identity-free now.

## Rounds

15+ review rounds; findings shrank from forgeable gates and fake-CLI key
mismatches to crash-window edge cases — round 15 closed the last HIGH: a
cases.json with zero expected-fail tests was a false-green machine (a
do-nothing coder passed the gate and landed a PR with no code change);
the driver now requires one, feeds the designer back, and refuses to land
a candidate sha equal to the base. Round 16 (last): validate_spec no
longer raises AttributeError on non-string `allowed_test_paths` entries
(the cases_file/path_matches checks are skipped while the globs list is
invalid; `path_matches` tolerates non-str), and contested README claims
were corrected or deleted (contract-violation escalation, the LoC
figure, the pytest-example clause, re-spawn collision moved to
not-live-verified, brace-pattern reframing, exact exit-path reasons).

## Numbers (measured on the final head)

- Driver: 883 non-blank non-comment lines. Driver tests: 114, all passing
  on Linux; the module skips off Linux and where `prlimit` is absent.
- Full suite on this branch: 4376 passed / 2 skipped / 0 failed.
  `ruff --select E9,F` clean on the two files.
- Exit codes: 0 ready-for-human-gate, 2 escalated, 1 paused/error.

## Follow-up 1 (post-merge, branch fix-agentcoder-followup1)

Six README corrections from the merged chunk-3 review (resume/preflight
wording qualified, dead recorded ids dropped+respawned for all roles incl.
the collision consequence, usage-exit + completed-resume exits documented,
git timeout split git()-120s vs validate_spec-60s, suite skips when prlimit
absent on Linux, `paseo wait` rc-0 claim scoped to the observed not-found
case) + two code edges with tests: land's dirt check uses `git status
--porcelain -z` (porcelain C-quotes space paths; a dirty frozen
`tests/test_a b.py` false-escalated - verified by probe), and check_permits
is one-way prefix-tolerant (a foreign permit id that is a PREFIX of a job
agent id no longer attributes to the job).
