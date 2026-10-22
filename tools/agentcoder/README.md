# agentcoder — a small driver for coder / blind test designer / executor loops

`tools/agentcoder/agentcoder.py` is a **plain driver script** (stdlib only,
one file, kept under 700 non-blank/non-comment lines — a goal, not enforced
by a check) that runs the AgentCoder paper loop against Paseo agents:

- a **CODER** agent implements a contract,
- an **INDEPENDENT, BLIND test designer** writes acceptance tests from the
  contract alone — blind **by instruction**: its prompt forbids touching
  anything but its test paths and inspecting other branches, but the
  worktrees share one git object store, so a designer that ran
  `git log --all` *could* see the coder's commits. This is procedural
  independence, not a security boundary (the same-user Limits note below),
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
error/paused. `status` on an existing job prints the job's recorded fields
as JSON and exits 0; `status` on a missing/invalid jobdir prints a paused
JSON (`"no job.json in ..."`) and exits 1. Exits that have a `JOBDIR` (preflight pause, mid-run pause, escalation,
completion) print JSON **and** write `JOBDIR/report.md`; the exits with **no**
jobdir (unknown command, unreadable/invalid spec, jobdir already in use)
print the JSON on stdout as their entire output; running with no arguments
prints the usage text (not JSON) and exits 1.

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

- `base` is resolved to a SHA at its **first resolution** (in preflight) and
  pinned in `job.json`; later resumes never re-resolve the ref, so a base
  branch that moves while the job is paused cannot drift the job.
- `cases_file` is where the designer writes its per-test expectations
  (`expected_on_base: "pass"|"fail"`); it defaults to
  `tests/<task_id>.cases.json` and must sit inside `allowed_test_paths`.
- `{tests}` in `test_command` expands to the `allowed_test_paths` globs;
  the driver appends `-rA` to pytest invocations to capture per-test outcomes.
- `test_reviewer_model` optional — when absent the test-review phase is
  skipped and the report says so.
- The start gates — `paseo ls -g --json` must show running Qwen agents
  below `qwen_cap - reserve`, and `prlimit` must be on `PATH` unless the
  spec sets `"allow_no_prlimit": true` (the executor never silently drops
  the limits) — are re-checked on **every** `resume` until all of them pass
  at once; only a fully-passed preflight is recorded as passed, so a pause
  inside preflight can never let `resume` skip a gate.
- `agent_timeout` (default 1800s) bounds only the agent `paseo run`/`paseo
  send` calls (an agent's whole turn). Every other blocking call has a
  fixed timeout: other `paseo`/`gh` calls 60s, `git` 120s, `git push` 300s.
  `test_timeout` (default 120s) bounds each `test_command` run — a test run
  that exceeds it **pauses** the job (the output is never judged, no agent
  is fed it).

## State machine

`JOBDIR/job.json` is rewritten atomically (temp + `os.replace`) after **every**
phase transition, and `resume` continues from the recorded phase with
recorded agent ids (`paseo wait`). Phases are **not all idempotent**: a
crash after a side effect but before the next save replays it. Safe to
replay: **spawn** (each completed turn records its agent id, and only the
role with no saved id is re-spawned; a real re-spawn collides with the
already-checked-out branch and pauses for a human, it never forks) and
**land** (an existing PR for the branch is adopted, never
forked). What can repeat: a **feedback send** to a designer/coder whose
turn ended during the crash window — agents are re-prompted with the same
text, which a human reviewing the PR can see. The driver never claims to
have deduplicated a send it did not record.

```
spawn ──► test_review ──► execute ──► candidate ──► land ──► report ──► done
```

1. **spawn** — two worktrees at the base SHA, created **in parallel** via
   `paseo run --new-workspace worktree --worktree-mode branch-off
   --new-branch ac/<task>/{coder,designer} --base <sha> ...` (each blocking
   call is that agent's whole turn). The designer is told: tests only under
   `allowed_test_paths`, never touch anything else, never inspect other
   branches (`git log --all`), commit, and write
   `cases_file` (default `tests/<task>.cases.json`) declaring each test id as
   `expected_on_base: "pass"` (a control that must pass on old code) or
   `"fail"` (new behavior) plus a one-line requirement. The coder is told:
   implement the contract, touch only `allowed_code_paths`, do **not** write
   the acceptance tests.
 2. **test_review** (optional) — one reviewer agent per round on an
     `ac/<task>/review-r<n>-<sha6>` branch created at the frozen test SHA,
     with a checklist; the driver parses its final
    `VERDICT: APPROVE|CHANGES REQUESTED` line. Findings are `paseo send`-ed to
    the designer (blocking); at most `max_rounds`, then escalate. The gate is
    SHA-scoped: if the designer commits new tests after an APPROVE, execute
    returns to this phase and the new SHA gets a fresh reviewer before any
    coder runs on it.
3. **execute** — freeze the test commit SHA; its changed paths must fit
   `allowed_test_paths` (violations escalate). In a temp detached worktree of
   the **base** with the frozen tests checked out, run `test_command` under
   `prlimit` when available (CPU/address-space/file-size/process bounds;
   preflight refuses to start without it unless `allow_no_prlimit`), a
   scrubbed environment, and a timeout. Outcomes are compared with `cases.json`:
   a `pass` control that is not PASSED on base, or a `fail` test that is not
   FAILED on base (SKIPPED/XFAIL/XPASS/missing all count), is a **TEST bug** —
   the mismatch goes to the designer, up to `max_rounds` rounds, then escalate.
 4. **candidate** — temp detached worktree of the coder's HEAD + frozen tests;
    coder's changed paths checked against `allowed_code_paths`. A round is
    green only when the pytest run exits 0 **and** **every** id declared in
    `cases.json` shows outcome PASSED for the coder's code; SKIPPED/XFAIL/
    XPASS/ERROR/missing and exit 5 (nothing collected) all count as red even
    if the exit code is 0, with the observed outcome fed back per id.
   Failures are fed to the coder as the last 150 output lines + failing ids
   (blocking `paseo send`), at most `max_rounds`; the coder's head is re-read
   (`rev-parse`) each round, never trusted from memory. Tests are never
   loosened.
 5. **land** — escalates if the coder worktree's tracked tree is
     dirty. Its HEAD must be the gated candidate SHA (or land's own
     driver-recorded test-commit/pushed SHA on a resumed land); if the coder
     moved the branch after gating, land **bounces back to the candidate
     phase** — the new head is re-gated, and only a green re-gate lands.
     The frozen test files are then committed
     into the coder's branch (authored `agentcoder <noreply@refdes.local>`,
     trailer `Co-authored-by: <name> <noreply@refdes.local>` where `<name>`
     is the last path segment of `coder_model`) and the branch is pushed;
     the pushed SHA is recorded.
     `gh pr list --state all` runs first: an **OPEN** PR for the branch (the
     crash window between `gh pr create` and the state save leaves exactly
     this) — or a MERGED one whose head is the SHA the driver recorded as
     pushed (a human merged it; the work is on main) — is adopted, so a
     second PR can
     never fork; a CLOSED, unmerged PR **escalates** for a human; a failing
     `gh pr list` **pauses** (the driver won't run `gh pr create` blind).
    Otherwise `gh pr create` opens the PR with `report.md` as the body —
    the last 20 lines of the contract, the base/test/coder SHA lines, the
    per-round candidate results table, and the status line (it reads
    `running` while landing) — and the PR number is printed.
    **Nothing is merged, no merge holds touched, no permissions approved.**
6. **report** — `JOBDIR/report.md` + JSON summary (base/test/code SHAs,
   controls green, intended reds, candidate results per round, review
   verdict, PR number, status).

Temp worktrees under `JOBDIR` used by execute/candidate are removed
(`git worktree remove --force`) at the end of each round, including on
failure.

Operational anomalies — a command/quota failure, a timeout, a missing
verdict, an agent in an error state, a pending permission prompt (detected
via `paseo permit ls` showing the job's agents), a failing `gh pr list` —
**pause** the job: state saved, precise reason, `resume` continues (after
re-running the preflight gates). Expected loop outcomes — a contract/scope
violation, `max_rounds` exhausted, a coder branch that moved or went dirty
before land, a CLOSED unmerged PR — **escalate** (exit 2) for a human. The
driver never guesses and has no stale-SHA detection of its own: coder heads
are re-read from git each round, while the base SHA is pinned at its first
resolution.

## Limits / what it deliberately does NOT do

- Tests are **model-authored code** executed as **the same user the Qwen
  workers already run as**. v1 bounds them with the fixed argv, a timeout,
  `prlimit` when available (preflight refuses to start without it unless
  `allow_no_prlimit: true`), and a scrubbed env; a `bwrap`-style wrapper is a
  possible later flag. There is no sandbox runtime. The designer's blindness
  is part of the same bargain: **by instruction, not enforcement** — its
  worktree shares the repo's object store, so a designer that disobeys its
  prompt (`git log --all`) can see the coder's commits; independence here
  is procedural, not a security boundary.
- No daemon, no hooks, no event journal, no receipts, no run-identity
  machinery, no caching layers, no retry framework.
- No merges, no approvals, no auto-resume across reboots — `resume` is
  manual and explicit.
- No parallel candidate rounds; rounds are sequential by design.
- The kill-at-every-save-point test sweep covers the default path (no
  reviewers, no feedback round-trips); save points inside those loops are
  reasoned about, not swept.
- `allowed_test_paths`/`allowed_code_paths` are matched with `fnmatch` for
  the scope checks (so `tests/**` matches `tests/pkg/t.py` there), then
  handed to `test_command`/pytest **raw** as `{tests}`. The two dialects
  diverge in both directions: fnmatch treats `{`, `,`, `}` literally, so a
  brace pattern like `tests/{a,b}.py` does NOT match a designer commit of
  `tests/a.py` — the scope check **escalates** loudly; and fnmatch's `*`
  crosses `/`, so a pattern like `tests/**` passes the scope check for
  nested files pytest (given the raw pattern) never collects — silently.
  Keep the patterns in the dialect pytest accepts.
- If a job is paused mid-`send`, resuming re-sends the feedback (agents are
  idempotently re-prompted, not deduplicated).
- Running this repo's test suite with `--basetemp` pointed **inside the
  repo tree** makes ~15 scaffold/sealing tests fail spuriously (they are
  sensitive to their temp dir living in a git repo); use pytest's default
  basetemp, which is where the green numbers were measured.
