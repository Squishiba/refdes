# agentcoder — a small driver for coder / blind test designer / executor loops

`tools/agentcoder/agentcoder.py` is a **plain driver script** (stdlib only,
one file; currently 955 non-blank/non-comment lines — ~1000 is a soft
sanity ceiling, not enforced by a check) that runs the AgentCoder paper
loop against Paseo agents:

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

It deliberately replaces the earlier Paseo-plugin attempt (hooks, journal,
receipts). There are **no event hooks here**: `paseo run` and
`paseo send` block until the agent's turn ends, so *the blocking subprocess
call is the completion signal*. No daemon, no journal, no subscriptions.

## Usage

```
python tools/agentcoder/agentcoder.py run SPEC.json [JOBDIR]
python tools/agentcoder/agentcoder.py resume JOBDIR
python tools/agentcoder/agentcoder.py status JOBDIR
python tools/agentcoder/agentcoder.py supervise SPEC.json JOBDIR
python tools/agentcoder/agentcoder.py queue wait QDIR [TASK_ID] --after EVENT_ID [--timeout SECONDS]
```

The first opt-in supervised entry point stores locked state and retained
attempt transcripts in `JOBDIR`; terminal state is committed with an event
before the process exits. `queue wait` reads durable events before waiting and
rechecks at most once per second. See [the supervised mode guide](../../docs/agentcoder-queue.md)
for current limits and the pending real-daemon gate. Existing `run`, `resume`,
and `status` behavior remains the default.

`JOBDIR` defaults to `<repo>/.scratch/agentcoder/<task_id>/` — keep job
dirs out of tracked paths (in this repo `.scratch/` is gitignored). Exit
codes: **0** done (`ready-for-human-gate`), **2** escalated, **1**
error/paused. `status` on an existing job prints a fixed **subset** of
the job's recorded fields (task_id, phase, status, reason, the SHAs,
pr_number, test_review, and the round counters) as JSON and exits 0; `status`
with no job.json file prints paused JSON with reason
`"no job.json in <jobdir>"`, and with an unparseable job.json
`"unparseable job.json: ..."`, both exiting 1 and writing no report.
Exits that run the loop with a `JOBDIR` (preflight pause, mid-run pause,
escalation, completion) print JSON **and** write `JOBDIR/report.md`; the
jobdir-in-use exit has a jobdir (the existing one) and writes **no**
report. The exits with **no** jobdir (unknown command, unreadable spec
file, invalid spec) print the JSON on stdout as their entire output; an
**unparseable** spec file exits `status: "paused"` with rc 1 (the no-jobdir
list is not exhaustive: a Pause raised by a git call inside
`validate_spec` exits the same way). Running
with no arguments prints the usage text (not JSON) and exits 1 — as do
`resume`/`status` given no JOBDIR argument (usage text, rc 1; a stray
`./job.json` is never read). `resume` of a **completed** job prints only
`{status, reason, pr_number}` as JSON and exits with the recorded status
(0/2); it never rewrites `report.md`.

The driver drives a **Linux Paseo host** (`prlimit`, git worktrees,
`paseo`); its test suite is skipped on **non-Linux** and on Linux where
`prlimit` is absent (the preflight gate needs
it, a Linux tool), and the driver is untested on Windows/macOS.

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
  "reserve": 1,
  "workspaces": {"coder": "wks_...", "designer": "wks_...", "reviewer": "wks_..."}
}
```

- `repo` is validated as a git repository and normalized (expansions and
  symlinks resolved) at validation time; everything after that uses the
  normalized absolute path.
- `base` is resolved to a SHA at its **first resolution** (in preflight) and
  pinned in `job.json`; later resumes never re-resolve the ref, so a base
  branch that moves while the job is paused cannot drift the job.
- `workspaces` (optional) maps roles — `coder`, `designer`, `reviewer` — to
  **existing active workspace ids** (see "Workspaces" below). Validation
  rejects unknown role keys, ids that are not active workspaces per
  `paseo workspace ls --json`, and coder/designer sharing one id (the
  designer must stay blind to the coder's tree). A role with no id gets its
  workspace **created** at first spawn — the driver never asks Paseo for a
  new workspace per agent.
- `contract_file` is read **once** in preflight and its text is pinned in
  `job.json` (undecodable bytes replaced, NULs stripped — the text rides
  argv in every spawn prompt); prompts and `report.md` use the pinned
  text afterwards, never a re-read of the live checkout.
- `cases_file` is where the designer writes its per-test expectations
  (`expected_on_base: "pass"|"fail"`); it defaults to
  `tests/<task_id>.cases.json` and must sit inside `allowed_test_paths`.
- `test_command` is a fixed argv list that must contain a literal `{tests}`
  element, and at least one element must **contain the substring `pytest`**
  — a substring check, not an invocation check (outcomes are judged from
  pytest's `--junitxml` output only).
- `{tests}` in `test_command` expands to the files matching the
  `allowed_test_paths` globs, expanded by the driver with
  `glob.glob(..., recursive=True)` relative to the job's worktree, keeping
  only **directories and `.py` files** (a `tests/**` glob also matches the
  designer's data files, and pytest exits rc=4 on those). pytest does not
  expand patterns itself; the driver expands them, and pauses when ALL the
  `allowed_test_paths` globs together match no files — pytest is never run
  against an empty selection. For pytest commands the driver appends
  `--junitxml` (written into the job dir — by default under the repo's
  `.scratch/`, untracked and outside the worktrees under test) and
  `--rootdir` (the worktree under test),
  and judges per-test outcomes from that XML only: agent-written stdout
  (e.g. a conftest printing `PASSED` lines) is not gate input. The guard
  protects against mistakes, not hostile coders — a coder who can edit
  `conftest.py` or pytest plugins can forge the XML too.
- `test_reviewer_model` optional — when absent (or `null`) the test-review
  phase is skipped and the report says so. `coder_model`/`designer_model`/
  `test_reviewer_model` must be non-empty strings when present.
- The start gates — `paseo ls -g --json` must show running Qwen agents
  below `qwen_cap - reserve`, and `prlimit` must be on `PATH` unless the
  spec sets `"allow_no_prlimit": true` (the executor never silently drops
  the limits) — are re-checked on **every** `resume` until all of them pass
  at once; only a fully-passed preflight is recorded as passed, so a pause
  inside preflight can never let `resume` skip a gate.
- `agent_timeout` (default 1800s) bounds the agent `paseo run`/`paseo
  send` calls (an agent's whole turn) and the `paseo wait` confirmation of
  recorded agents (whose subprocess timeout sits slightly above it). Every
  other blocking call has a fixed timeout: other `paseo`/`gh` calls 60s,
  `git` (through the driver's `git()` helper) 120s, `git push` 300s —
  the git calls `validate_spec` itself makes are the exception: they use
  the 60s `run_guarded` default.
  `test_timeout` (default 120s) bounds each `test_command` run — a test run
  that exceeds it **pauses** the job (the output is never judged, no agent
  is fed it). All four (`agent_timeout`, `test_timeout`, `max_rounds`,
  `qwen_cap`/`reserve`) are validated as ints before the job starts.

## State machine

`JOBDIR/job.json` is rewritten atomically (temp + `os.replace`) after **every**
phase transition and every recorded agent id, and `resume` continues from
the recorded phase with the recorded ids — for coder, designer **and**
reviewer: an id saved by a completed turn is adopted on resume only while
it is live in `paseo ls`; a recorded id that is gone from `paseo ls` is
dropped and the role respawned (all three roles follow the same rule), so
re-spawn onto the role's reused workspace is a real resume outcome. The
recorded live agent is confirmed by `paseo wait <id>
--json`: a status other than idle **pauses** the job; `paseo wait` was
observed (live) to exit 0 for a not-found id with `Agent not found` in the
output, so the exit code is never the completion signal, only the JSON
status is. Phases are **not all
idempotent**: a crash after a side effect but before the next save
replays it. Safe to replay: **spawn** (each completed turn records its
agent id, and only the role with no saved id is re-spawned; a real
re-spawn reuses the role's recorded workspace and resets its branch onto
the base with `git checkout -B` — a dirty tree **pauses** for a human
rather than silently resetting uncommitted work) and **land** (an existing PR for the branch is
adopted, never forked). What can repeat: a **feedback send** to a
designer/coder whose turn ended during the crash window — agents are
re-prompted with the same text, which a human reviewing the PR can see.
The driver never claims to have deduplicated a send it did not record.

```
spawn ──► test_review ──► execute ──► candidate ──► land ──► report ──► done
```

1. **spawn** — one workspace **per role** (see "Workspaces" below): coder
   and designer each get a worktree workspace at the base SHA (the spec's
   `workspaces` id for that role, or one the driver creates), then both
   agents launch **in parallel** via `paseo run --workspace <id> ...`
   (each blocking call is that agent's whole turn). The driver never
   spawns with `--new-workspace`. At the end of the phase every recorded
   live agent is confirmed with `paseo wait <id> --json` — a status of
   anything but `idle` **pauses** (the rc is 0 for all of them, so only
   the JSON status decides). The designer is told: tests only under
   `allowed_test_paths`, never touch anything else, never inspect other
   branches (`git log --all`), commit, and write
   `cases_file` (default `tests/<task>.cases.json`) declaring each test id as
   `expected_on_base: "pass"` (a control that must pass on old code) or
   `"fail"` (new behavior) plus a one-line requirement. The coder is told:
   implement the contract, touch only `allowed_code_paths`, do **not** write
   the acceptance tests.
  2. **test_review** (optional) — one reviewer agent per round, all rounds
      sharing **one** reviewer workspace; each round's agent starts on the
      `ac/<task>/review-r<n>-<sha6>` branch of that workspace, reset to the
      frozen test SHA,
     with a checklist; the driver parses its final
    `VERDICT: APPROVE|CHANGES REQUESTED` line. Findings are `paseo send`-ed to
    the designer (blocking); at most `max_rounds`, then escalate. The gate is
    SHA-scoped: if the designer commits new tests after an APPROVE, execute
    returns to this phase and the new SHA gets a fresh reviewer before any
    coder runs on it.
3. **execute** — freeze the test commit SHA; its changed paths — the
   **unfiltered** diff list: additions, modifications, DELETIONS, and both
   halves of a rename — must fit `allowed_test_paths`; a violation buys the
   designer ONE "revert these paths" feedback round per offending sha
   (counts against `max_rounds`, resume-safe), and only a repeat after that
   escalates. The checkout list from the frozen SHA is the added/modified
   subset (a deleted path cannot be checked out), minus every
   `*.cases.json`-suffixed file AND the exact `cases_file` (so a
   custom-named cases file is excluded too). In a temp detached worktree of
   the **base** with the frozen tests checked out, run `test_command` under
   `prlimit` when available (CPU/address-space/file-size/process bounds;
   preflight refuses to start without it unless `allow_no_prlimit`), a
   scrubbed environment, and a timeout. Outcomes are compared with `cases.json`:
   a `pass` control that is not PASSED on base, or a `fail` test that is not
   FAILED on base (SKIPPED/ERROR/missing all count), is a **TEST bug** —
   the mismatch goes to the designer, up to `max_rounds` rounds, then escalate.
 4. **candidate** — temp detached worktree of the coder's HEAD + frozen tests;
    coder's changed paths (same unfiltered list: a DELETION of an
    out-of-scope file is a violation too) checked against
    `allowed_code_paths`. A round is
    green only when the pytest run exits 0 **and** **every** id declared in
    `cases.json` shows outcome PASSED for the coder's code; SKIPPED/ERROR/
    missing count as red even when pytest exits 0, and exit 5 (nothing
    collected) is red by itself — with the observed outcome fed back per id. Outcomes come from
    junit XML, which has no XFAIL/XPASS status: a non-strict xfail arrives as
    SKIPPED (red), and an xfail that passes (XPASS) as a plain PASSED
    testcase — XPASS therefore counts as PASSED, by decision.
   Failures are fed to the coder as the last 150 output lines + failing ids
   (blocking `paseo send`), at most `max_rounds`; the coder's head is re-read
   (`rev-parse`) each round, never trusted from memory. Tests are never
   loosened.
  5. **land** — checks the coder worktree's HEAD **first**: it must be the
     gated candidate SHA, or the driver's recorded test-commit SHA
     `test_landed_sha`. A moved HEAD is adopted **only** as the driver's
     own test commit, and only strictly: `HEAD~1` is the gated coder SHA,
     the commit touches **only paths in the frozen `test_paths`**, and
     every one of those paths has the **same git blob** in HEAD as at the
     frozen test SHA (`rev-parse HEAD:<p> == rev-parse <test_sha>:<p>`).
     A coder-authored commit that merely lands inside the test paths
     fails this and **bounces the job back to the candidate phase** — the
     new head is re-gated (and re-scope-checked against
     `allowed_code_paths`), and only a green re-gate lands. Only then is
      the tree checked for dirt: only paths in the **frozen `test_paths`
      list** are accepted (the `allowed_test_paths` GLOBS are not the
      standard — a coder-staged `tests/conftest.py` sits inside the globs
      and **escalates**: it is the coder's, never the driver's to land);
      dirt in the frozen list is the driver's own interrupted checkout —
      reset and re-checked-out from the frozen SHA.
      The frozen test files are then committed
      into the coder's branch **with an explicit pathspec
      (`git commit … -- <frozen test paths>`), so nothing outside them can
      ride the land commit** (authored `agentcoder <noreply@refdes.local>`,
     trailer `Co-authored-by: <name> <noreply@refdes.local>` where `<name>`
     is the last path segment of `coder_model`) and the branch is pushed;
     the pushed SHA is recorded. The push is by HEAD refspec
     (`git push -u origin HEAD:refs/heads/<branch>`), so a respawned coder
     on a differently named local branch still lands correctly.
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
**pause** the job: state saved, precise reason, `resume` continues (the
preflight gates are re-run only until they have
all passed once: a fully passed preflight is recorded, and later resumes of
mid-run pauses start directly from the recorded phase). Expected loop outcomes — a scope violation
repeated after its one-shot revert round,
`max_rounds` exhausted, dirt at land outside the frozen test paths (a
coder head that MOVED is not an escalation: it bounces back to candidate
for a re-gate), a CLOSED unmerged PR — **escalate** (exit 2) for a human. The
driver never guesses and has no stale-SHA detection of its own: coder heads
are re-read from git each round, while the base SHA is pinned at its first
resolution.

## Workspaces

Every agent the driver spawns runs in a workspace via
`paseo run --workspace <id>` — the driver **never** passes
`--new-workspace`, so the job creates at most **one workspace per role**
(`coder_workspace`, `designer_workspace`, `reviewer_workspace` in
`job.json`), not one per agent. Respawn after a pause, feedback rounds,
and review round N all reuse the role's workspace; an early version that
spawned with `--new-workspace` per agent is what left one real pilot with
130+ abandoned workspaces.

- Creation is lazy and ordered: the first agent of a role takes the id
  already recorded in `job.json`, else the spec's `workspaces` id for that
  role, else the driver creates one — `paseo workspace create --isolation
  worktree --mode branch-off --new-branch ac/<task>/<role> --base <sha>
  --json` — and records the returned `workspaceId` before launching.
- Before every spawn the workspace's tree is reset to a clean checkout of
  the branch that agent needs (`git checkout -B <branch> <sha>`; the
  reviewer's SHA is the frozen test SHA). A **dirty** tree **pauses** the
  job — the driver refuses to reset uncommitted work; commit, revert, or
  clean it, then `resume`.
- The driver never archives and never deletes a workspace. After the PR
  lands (or the job dies for good), the **human** cleans up:
  `paseo workspace archive <id>` for the job's one to three workspace ids
  (they are in `job.json`).

## Verified against the real CLI

The two real pilot tasks (ids `chk-attr-003c`, the CHK-ATTR-003 fix, which
produced PR #357, and `edit-03`, which produced PR #358) exercised, against
the live `paseo` CLI and real Qwen agents: `run`/spawn of both
agents in parallel, designer and coder turns, `execute` (controls and
intended reds on the base commit under `prlimit` with driver-owned junit
XML), the candidate round, `land` + real `gh pr create`, one feedback
`send` + `resume` (the `edit-03` scope round), and `resume` after
a permission pause. Every live-verified statement in this README comes
from those two runs plus the author's direct observations of `paseo ls`
and `paseo wait` output, plus (for the workspace model) direct probe runs
against the live CLI: `workspace create --isolation worktree --mode
branch-off --json` (returns `workspaceId`/`cwd`, no `id` key), `run
--workspace <id> --json` landing the agent in that workspace's recorded
`cwd` with its plain `Using workspace <id>` banner preceding the JSON
(two runs on one id, no new workspace in `workspace ls`), and
`workspace archive` (returns `status: "archived"`, drops out of
`workspace ls`); the probe workspace was archived afterwards. **Not
verified live** (offline-tested against the
fake only, incl. the dirty-tree respawn pause): the remaining feedback
`send` loops (test-review changes,
executor
feedback, scope-feedback rounds, candidate-red feedback), the `test_review`
phase end to end, the crash-window recovery paths in `land`, and
`paseo wait`/`stop` semantics under failure.

All subprocess output and text reads (child stdout/stderr, spec,
`job.json`, the contract file) decode with `errors="replace"`: an agent
or test that emits undecodable bytes, or a binary contract file, can
never raise a `UnicodeDecodeError` out of the driver and strand
`job.json` in `running`.

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
- On a spawn-turn timeout the driver kills the `paseo run` clients, then
  finds this job's agents by title (`paseo ls -g`), stops them (`paseo
  stop`), and records the ids in `stopped_agents` in job.json; agents whose
  ids are already recorded in job.json are spared (a recorded id means the
  turn completed).
  Remaining
  gap: a resume re-spawns any role with no recorded agent id — or with a
  recorded id that no longer appears in `paseo ls` (dead recorded ids are
  dropped, see the state machine above). With workspace reuse the branch
  collision is gone (the re-spawn's `git checkout -B` resets the branch
  onto the base, and a dirty tree pauses first), but that same reset
  discards a stopped agent's committed work on the role branch — start a
  fresh jobdir if that turn's output must be kept.
- Candidate rounds are recorded one-per-round: a resume re-runs the round
  and replaces its entry in `candidate_results` instead of appending a
  duplicate.
- `allowed_test_paths`/`allowed_code_paths` are matched for the scope
  checks by `path_matches`: a pattern with no `*?[` is compared as a
  plain path (the file itself, or anything under that directory), and
  fnmatch applies only to patterns containing `*`, `?` or `[`. For
  `{tests}` they are expanded with `glob.glob(..., recursive=True)`. The
  two dialects diverge: fnmatch's `*` crosses `/` (`tests/*.py` also
  matches `tests/sub/x.py` in a scope check), `glob.glob`'s does not;
  a brace pattern like `tests/{a,b}.py` matches nothing in **both**
  dialects (neither fnmatch nor `glob.glob` expands braces) — such a
  commit is then flagged, buys the one-shot revert round,
  and the scope check **escalates** loudly on the repeat.
  The job **pauses**
  when the expansion of ALL `allowed_test_paths` globs together matches no
  files. Both are loud; keep patterns in a dialect both sides read the
  same way. `in-prog-logs/` is exempt from **both** scope checks, for
  both agents (the AGENTS.md progress logs) — designer and coder logs
  ride along into the PR.
- If a job is paused mid-`send`, resuming re-sends the feedback (agents are
  idempotently re-prompted, not deduplicated).
- Running this repo's test suite with `--basetemp` pointed **inside the
  repo tree** has been observed to fail scaffold/sealing tests spuriously
  (they are sensitive to their temp dir living in a git repo; the exact
  count was never pinned down — treat "~15" as unverified); use pytest's
  default basetemp, which is where the green numbers were measured.
- **JSON key names** for `paseo` were verified against live commands:
  `paseo ls -g --json` entries carry `id`/`shortId`/`name`/`provider`/
  `thinking`/`status`/`cwd`/`created` (there is **no** `agentId`/`title`/
  `model` in ls output; `name` is the title truncated to ~60 chars, so
   title matching uses the truncated prefix), `paseo run --json` returns
   `agentId`/`status`, and `paseo wait --json` returns `agentId`/`status`
   with a `message` (live-verified: a missing agent gives status
   `"error"`, rc 0 — the status is the signal, never the rc). **Unverified** and handled tolerantly: the entry keys
  of `paseo permit ls --json` (matched across `id`/`agentId`/`agent`/
  `shortId`, prefix-tolerant) and the `status` field of
  `paseo send --json`; `gh pr list --json` uses the documented gh fields.
