# agentcoder driver

Goal: replace the old Paseo-plugin AgentCoder with a small plain driver
script. Done: `tools/agentcoder/agentcoder.py` (560 non-blank non-comment
lines, cap 700), `tools/agentcoder/README.md`, `tests/test_agentcoder_tool.py`
(20 tests, all passing). Committed on branch `feat-agentcoder-driver` off
main tip.

## Design (as shipped)

- `run <spec.json> <jobdir>` / `resume <jobdir>` / `status <jobdir>`.
- Phases: spawn -> test_review -> execute -> candidate -> land -> report ->
  done. `job.json` rewritten atomically (temp + `os.replace`) at every
  transition, so resume is crash-safe (verified by a parametrized
  kill-at-every-save test).
- Tools resolved via `AGENTCODER_PASEO` / `AGENTCODER_GH` env vars; the
  tests use fake `paseo`/`gh` scripts this way.
- Executor runs `test_command` in a detached temp worktree of base (and of
  coder HEAD) with frozen test files checked out from `test_sha`, scrubbed
  env, `prlimit` prefix when available, `-rA` appended for pytest;
  per-test outcomes parsed from the summary lines.
- Land: commit author `agentcoder <noreply@refdes.local>` +
  `Co-authored-by:` trailer, push, `gh pr create`.
- Exit codes: 0 ready-for-human-gate, 2 escalated (scope violation, cap,
  unresolved rounds), 1 paused/error.

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
- Full-suite baseline: 15 failures on main tip
  (`test_scaffold.py` x14, `test_sealing_optin_note.py` x1) pre-date this
  change; the suite is otherwise green (4267 passed) and `ruff check
  tools/agentcoder/agentcoder.py tests/test_agentcoder_tool.py --select
  E9,F` is clean.

## Status

Finished. PR: "feat(tools): agentcoder -- a small driver for coder / blind
test designer / executor loops" (not merged, human gate).
