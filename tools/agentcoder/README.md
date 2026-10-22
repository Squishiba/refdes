# agentcoder — a small driver for coder / blind test designer / executor loops

`tools/agentcoder/agentcoder.py` is a **plain driver script** (stdlib only,
one file, kept under 700 non-blank/non-comment lines — a goal, not enforced
by a check) that runs the AgentCoder paper loop against Paseo agents:

- a **CODER** agent implements a contract,
- an **INDEPENDENT, BLIND test designer** writes acceptance tests from the
  contract alone (it never sees the implementation),
- an **EXECUTOR** (this driver, via fixed-argv `test_command` runs) freezes
  the tests, checks them against the *base* commit, then runs them against
  the coder's candidate and feeds precise failures back.

It deliberately replaces the earlier Paseo-plugin attempt (~8,100 LoC of
hooks/journal/receipts). There are **no event hooks here**: `paseo run` and
`paseo send` block until the agent's turn ends, so *the blocking subprocess
call is the completion signal*. No daemon, no journal, no subscriptions.

## Usage

```
python tools/agentcoder/agentcoder.py run SPEC.json [JOBDIR]
python tools/agentcoder/agentcoder.py resume JOBDIR
python tools/agentcoder/agentcoder.py status JOBDIR
```

`JOBDIR` defaults to `<repo>/.scratch/agentcoder/<task_id>/` — keep job
dirs out of tracked paths (in this repo `.scratch/` is gitignored). Exit
codes: **0** done (`ready-for-human-gate`), **2** escalated, **1**
error/paused. Every run — every exit path, including spec-invalid,
jobdir-exists, unknown-command and preflight-pause — prints a JSON object
with at least `status` and `reason` on stdout, and writes
`JOBDIR/report.md`.

The driver drives a **Linux Paseo host** (`prlimit`, git worktrees,
`paseo`); on Windows it is untested and its test suite is skipped.

`paseo` is resolved via `AGENTCODER_PASEO` and `gh` via `AGENTCODER_GH`
(env vars), which is also how the test suite fakes them.

## SPEC.json

```json
{
  "task_id": "widget-fix",
  "title": "PR title",
  "repo": "/abs/path/to/repo",
  "base": "main",
  "contract_file": "docs/contract.md",
  "allowed_code_paths": ["src/**"],
  "allowed_test_paths": ["tests/**"],
  "cases_file": "tests/widget-fix.cases.json",
  "test_command": ["python", "-m", "pytest", "-q", "{tests}"],
  "max_rounds": 2,
  "coder_model": "opencode/qwenlocal/Qwen3.8-Flash-Next",
  "designer_model": "opencode/qwenlocal/Qwen3.8-Flash-Next",
  "test_reviewer_model": null,
  "qwen_cap": 8,
  "reserve": 1
}
```

- `base` is resolved to a SHA **once** and recorded in `job.json`.
- `cases_file` is where the designer writes its per-test expectations
  (`expected_on_base: "pass"|"fail"`); it defaults to
  `tests/<task_id>.cases.json` and must sit inside `allowed_test_paths`.
- `{tests}` in `test_command` expands to the `allowed_test_paths` globs;
  the driver appends `-rA` to pytest invocations to capture per-test outcomes.
- `test_reviewer_model` optional — when absent the test-review phase is
  skipped and the report says so.
- Before starting: refuses to run if `paseo ls -g --json` shows
  running Qwen agents >= `qwen_cap - reserve`.

## State machine

`JOBDIR/job.json` is rewritten atomically (temp + `os.replace`) after **every**
phase transition. `resume` re-attaches to recorded agent ids (`paseo wait`)
and continues from the recorded phase; every phase is idempotent.

```
spawn ──► test_review ──► execute ──► candidate ──► land ──► report ──► done
```

1. **spawn** — two worktrees at the base SHA, created **in parallel** via
   `paseo run --new-workspace worktree --worktree-mode branch-off
   --new-branch ac/<task>/{coder,tests} --base <sha> ...` (each blocking
   call is that agent's whole turn). The designer is told: tests only under
   `allowed_test_paths`, never touch anything else, never inspect other
   branches (`git log --all`), commit, and write
   `cases_file` (default `tests/<task>.cases.json`) declaring each test id as
   `expected_on_base: "pass"` (a control that must pass on old code) or
   `"fail"` (new behavior) plus a one-line requirement. The coder is told:
   implement the contract, touch only `allowed_code_paths`, do **not** write
   the acceptance tests.
2. **test_review** (optional) — one reviewer agent per round in a worktree at
   the frozen test commit, with a checklist; the driver parses its final
   `VERDICT: APPROVE|CHANGES REQUESTED` line. Findings are `paseo send`-ed to
   the designer (blocking); at most `max_rounds`, then escalate.
3. **execute** — freeze the test commit SHA; its changed paths must fit
   `allowed_test_paths` (violations escalate). In a temp detached worktree of
   the **base** with the frozen tests checked out, run `test_command` under
   `prlimit` (CPU/address-space/file-size/process bounds), a scrubbed
   environment, and a timeout. Outcomes are compared with `cases.json`: a
   `pass` control that fails on base, or a `fail` test that passes on base,
   is a **TEST bug** — the exact mismatch goes to the designer, one round.
4. **candidate** — temp detached worktree of the coder's HEAD + frozen tests;
   coder's changed paths checked against `allowed_code_paths`. Failures are
   fed to the coder as the last 150 output lines + failing ids (blocking
   `paseo send`), at most `max_rounds`; the coder's head is re-read
   (`rev-parse`) each round, never trusted from memory. Tests are never
   loosened.
 5. **land** — the frozen test files are committed into the coder's branch
    (authored `agentcoder <noreply@refdes.local>`, trailer
    `Co-authored-by: <name> <noreply@refdes.local>` where `<name>` is the
    last path segment of `coder_model`), the branch is pushed, an existing
    PR for the branch is adopted if `gh pr list` finds one (so a crash
    between `gh pr create` and the state save cannot fork a second PR),
    `gh pr create` opens the PR (contract summary + executor
    results table + escalation notes), and the PR number is printed.
    **Nothing is merged, no merge holds touched, no permissions approved.**
 6. **report** — `JOBDIR/report.md` + JSON summary (base/test/code SHAs,
    controls green, intended reds, candidate results per round, review
    verdict, PR number, status).

Temp worktrees under `JOBDIR` used by execute/candidate are removed
(`git worktree remove --force`) at the end of each round, including on
failure.

Any error, quota failure, missing verdict, stale SHA, agent in an error
state, or a pending permission prompt (detected via `paseo permit ls`
showing the job's agents) **pauses** the job: state saved, precise reason,
`resume` continues. The driver never guesses.

## Limits / what it deliberately does NOT do

- Tests are **model-authored code** executed as **the same user the Qwen
  workers already run as**. v1 bounds them with the fixed argv, a timeout,
  `prlimit`, and a scrubbed env; a `bwrap`-style wrapper is a possible later
  flag. There is no sandbox runtime.
- No daemon, no hooks, no event journal, no receipts, no run-identity
  machinery, no caching layers, no retry framework.
- No merges, no approvals, no auto-resume across reboots — `resume` is
  manual and explicit.
- No parallel candidate rounds; rounds are sequential by design.
- If a job is paused mid-`send`, resuming re-sends the feedback (agents are
  idempotently re-prompted, not deduplicated).
