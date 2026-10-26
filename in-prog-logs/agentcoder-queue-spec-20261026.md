# AgentCoder queue mode — implementation specification

Date: 2026-10-26. Status: historical full design proposal; slice 1 shipped in
PR #376. The design below remains the long-term target where explicitly marked
future. The shipped behavior and current evidence are summarized here and in
`in-prog-logs/agentcoder-queue-spec-v1-20261026.md`.

| PR #376 implements | Future work retained from this design |
| --- | --- |
| Opt-in single-job `supervise`, atomic locked state, retained attempts, owned-agent recovery, bounded retry/nudge budgets, maintenance stop, and durable `queue wait`. Existing publication remains controlled by its prior gate. | Multi-job queue initialization/enqueue/scheduling, dependencies, capacity checks, overlap reservations, live status polish, and queue-level publication changes. |
| Permission handling for captured `{id,agentId,agentShortId,name,description}` rows. No structured command/path is present. Outside/risky evidence denies; unknown evidence parks unless an exact operator-trusted ID or `queue.trust_owned_agents: true` grants cooperative trust to a recorded owned agent. | OS-enforced path containment, structured-input permission parsing, a command broker, and hard isolation. Cooperative trust is not containment. |
| The orchestrator reports six live supervised pilot runs; the slice worker started none. Captured facts and findings are summarized in `in-prog-logs/agentcoder-queue-slice1-20261026.md`. | Live variants not captured remain fail-closed and park with evidence. |

The proposal sections below are retained as historical design intent, not a
claim that their CLI or permission broker shipped. All paths are repository-
relative. Source citations in the baseline describe the original drafting
snapshot; they are not current line anchors.

## 1. Scope and non-goals

Build a persistent, unattended scheduler around AgentCoder, preserving its
coder / blind designer / executor separation. Planning happens before enqueue;
review happens after publication. The scheduler makes no inference requests:
it runs deterministic policy and ordinary CLI subprocesses. Worker and optional
Sol turns consume their own model resources; queue supervision consumes zero
orchestrator tokens. Never send completion callbacks, nudges, or escalations to
the orchestrator model. Emit local events and plain-command notifications.

Run independent jobs concurrently in separate role workspaces. Preserve the
workspace reuse change in PR #373 (local history identifies it as 78c8954;
verified using `git log -4 --oneline`). Preserve frozen acceptance tests,
executor-owned checks, path scopes, and HEAD-to-expected-branch publication.

Non-goals: generating plans, interpreting arbitrary natural-language completion,
automatically merging PRs, solving merge conflicts, unrestricted shell approval,
cleaning up workspaces, hostile-agent isolation through prompts alone, and a
new general workflow engine. Keep the existing single-job interface usable.
Queue implementation may use small modules beside the driver; do not force a
scheduler and permission parser into its existing single file.

## 2. Current driver facts relied upon

Primary source alias **D** means `tools/agentcoder/agentcoder.py`; **R** means
`tools/agentcoder/README.md`. Every D:line and R:line below names that file.

| Fact verified by source inspection | Evidence |
| --- | --- |
| Commands are `run SPEC.json [JOBDIR]`, `resume JOBDIR`, `status JOBDIR`; default job directory is `.scratch/agentcoder/<task_id>` under the normalized repo. | D:1078–1111; also ran `python tools/agentcoder/agentcoder.py` with no arguments and observed usage. |
| Initial `job.json` has `jobdir`, `task_id`, complete normalized `spec`, `phase: spawn`, `status: running`, `reason: null`. It grows role agent/cwd/workspace fields, `reviewers`, pinned `base_sha` and contract, test/coder/landed/pushed SHAs, round counters and candidate results, PR number and stop records. | D:1109–1111, D:280–301, D:417–433, D:462–490, D:534–544, D:642–690, D:873–905, D:926–1011. |
| Writes flush/fsync a fixed `job.json.tmp` then replace `job.json`. There is no file lock or parent-directory fsync in this helper. Reports are direct text writes. | D:118–125, D:1034. |
| Phases are spawn → test_review → execute → candidate → land → report → done. Handlers can return a different phase; execute re-enters test review for changed tests and land re-enters candidate for a moved head. | D:23, D:815–816, D:943–944, D:1050–1059. |
| `Pause` records paused/reason, writes report, exits 1; `Escalate` records escalated/reason, writes report, exits 2. Escalate is an exception outcome, not a stronger-model dispatch. Done reports ready-for-human-gate and exits 0. | D:20, D:36–41, D:1046–1071. |
| Resume uses the recorded phase, resets non-done status/reason, and rechecks preflight only until `preflight_ok` is recorded. Done resume emits its summary without rerunning work. | D:304–317, D:1115–1135. |
| Recorded coder/designer IDs absent from `live_ids()` are dropped; missing cwd is derived from listing; recorded live roles are wait-confirmed. `live_ids` excludes missing status, closed and error. Reviewer IDs have analogous adoption/respawn logic. | D:528–531, D:547–594, D:655–666. |
| Blocking run/send are turn completion signals. Last JSON parsing tolerates banners/multiple JSON documents; run requires completed and agentId plus derived cwd; send requires completed; wait requires JSON idle, not merely success exit. | D:88–103, D:417–447, D:515–525. |
| Each role lazily obtains one workspace, persisted before launch; reviewer rounds reuse reviewer workspace. Spawn always uses `--workspace`, never a fresh workspace per agent. Existing spec workspace IDs must be active; coder and designer cannot share an ID. Tracked dirt prevents checkout/reset; the check excludes untracked files. | D:230–258, D:450–505, D:560–569; `tests/test_agentcoder_workspaces.py`:82–174, 176–240. |
| Blindness is instructed, not a security boundary: designer prompt forbids other branches/worktrees/history. The shared git object store remains visible. | D:330–345; R:355–362. |
| Spec validation checks task ID/ref formation/length, title, git repo normalization, existing contained contract, base, relative nonempty path globs without parent components, cases path within test scope, fixed argv containing literal `{tests}` and substring pytest, integer bounds, model strings and workspace mapping. Unknown top-level keys are not rejected. Base existence is resolved at preflight. | D:135–259, D:280–284. |
| Defaults: max_rounds 2, agent_timeout 1800s, test_timeout 120s, qwen_cap 8, reserve 1; default worker model opencode/qwenlocal/Qwen3.8-Flash-Next. Current capacity check counts running providers containing qwen only, once preflight passes, and does not reserve room for both initial roles. | D:21–26, D:215–225, D:295–301, D:1098–1102. |
| Other tool calls default to 60s; git helper 120s; push 300s; wait CLI receives agent_timeout with subprocess timeout that value + 30s. Initial role processes launch together, then communicate sequentially with per-process timeout. No queue-level wall-clock or nudge policy exists here. | D:25, D:69–74, D:106–114, D:518–520, D:565–590, D:978. |
| Executor expands test globs, writes JUnit XML in jobdir, applies prlimit, judges declared cases from XML (not prose), requires intended failure on base and all declared cases passing on candidate. Reviewer final nonempty line must be a VERDICT. | D:667–681, D:693–784, D:824–870, D:892–918. |
| Scope matching: plain path includes itself and descendants; wildcard pattern uses Python fnmatch (slash is not a component boundary). Scope includes deletions and both sides of renames; all in-prog-logs paths are currently exempt. Coder scope is checked at candidate; designer scope at execute, not a fresh complete scope check inside land. | D:597–617, D:818–820, D:885–889. |
| Land rejects unchanged coder, re-gates moved head, checks dirt, adopts only the exact frozen-blob test-commit crash case, commits frozen tests, pushes `HEAD:refs/heads/ac/<task_id>/coder`, then adopts or creates a PR. It does not merge or rebase onto a newer main. | D:926–1013; `tests/test_agentcoder_land_push.py`:81–120; `tests/test_agentcoder_tool.py`:1520–1569. |
| Crash recovery is not exactly once: a side effect before its save can replay; completed turns are recorded only after result parsing/cwd lookup. Killing the CLI does not itself stop an agent. Existing temp executor worktrees are cleaned/reset/removed; XML is unlinked before execution. | D:417–433, D:534–544, D:735, D:787–807; R:160–169, R:371–384. |

Existing tests are substantially fake-CLI based (`tests/test_agentcoder_tool.py`:1–6).
Read the named workspace and land-push suites and the tool's validation, pause,
feedback, save-point, malformed-report and landing regressions. Do not mistake
them for live-daemon coverage.

### CLI verification and evidence boundary

Ran `paseo --help`, `paseo ls --help`, `paseo permit --help`, and help for
`permit ls`, `permit allow`, `permit deny`, `run`, `send`, `logs`, `inspect`,
`stop`, `wait`. Verified available command syntax includes:

- `paseo ls -g --json` (global directory scope, archives excluded by default).
- `paseo permit ls --json`; `permit allow <agent> <req_id> --json`;
  `permit deny <agent> <req_id> --message <text> --json`. Never use `--all`.
- `paseo run --workspace <id> --provider <provider/model> --label <key=value>
  --env <key=value> --json <prompt>`; `send <id> --no-wait --json <prompt>`.
- `paseo logs <id> --tail <n> --json`, `inspect <id> --json`,
  `wait <id> --timeout <seconds> --json`, `stop <id> --json`.

Historical evidence at the time of drafting: `paseo ls -g --json` and
`paseo permit ls --json` returned `DAEMON_NOT_RUNNING`, so payloads were then
unverified. This was superseded during PR #376 by real captures and six live
supervised pilot runs reported by the orchestrator; the slice worker ran none.
Captured facts are recorded in the slice task log. Captured
permit rows have no structured command/path. Uncaptured wait/provider/recovery
signals remain unverified and park; no invented token-count, turn-count,
last-activity, context-limit, or server-health field is assumed.
Forum workflow and failure history are owner-supplied requirements, not an
independently audited incident history.

## 3. Queue model (historical future scheduler design)

Historical scheduler proposal (not shipped in PR #376): `agentcoder.py queue init QDIR`, `queue add QDIR SPEC.json`,
`queue start QDIR`, `queue status QDIR [--live] [--json]`,
`queue pause QDIR [--stop-agents]`, `queue resume QDIR [TASK_ID]`,
`queue set-cap QDIR N`, and `queue retry QDIR TASK_ID`.
`start` stays foreground; an ordinary service manager can restart it. `resume`
without a task clears maintenance mode; with a task authorizes its retry.
These remain future interfaces, not verified existing commands. Shipped entry
points are `supervise SPEC.json JOBDIR`, `queue wait QDIR [TASK_ID] --after
EVENT_ID [--timeout SECONDS]`, `queue stop JOBDIR`, and `queue resume JOBDIR`.

QDIR is `.scratch/agentcoder-queues/<queue_id>` within a dedicated queue-control
worktree. Each job owns separate coder/designer/reviewer worktrees. Queue control
files are never worker-writable; role prompts cannot read sibling trees. Reuse
one workspace per role per job; no new workspace for a nudge or review round.

```text
QDIR/
  config.json                 # versioned settings, immutable queue identity
  control.json                # maintenance state and generation
  queue.lock                  # brief configuration/index transactions
  runner.lock                 # one scheduler coordinator, lifetime lock
  jobs/<task_id>/
    entry.json                # immutable normalized job spec + queue metadata
    state.json                # queue status, budget, operations and event outbox
    job.json                  # existing phase engine state (extended version)
    job.lock                  # shared lock for ALL job-owned writable files
    report.md                 # driver report
    events.jsonl              # structured durable job events
    attempts/<attempt_id>/    # retained executor worktrees, XML, CLI output
  notifications.json          # command delivery outbox
  notifications.lock
  admission.json              # daemon gate receipts/cache, not authority
```

The control directory is logically job-management storage, not an exception
allowing workers to write outside their own worktree. OS enforcement must make
that distinction real (section 8). All scratch files including probe transcripts
stay beneath the relevant worktree's `.scratch/`.

Reuse the complete existing job spec without replacing its contract/checks.
Add exactly one optional top-level `queue` object, consumed by the queue adapter
and removed before passing the spec to the existing validator:

```json
{
  "task_id": "widget-fix",
  "title": "Add widget subtraction",
  "repo": ".",
  "base": "main",
  "contract_file": "docs/widget-contract.md",
  "allowed_code_paths": ["src/widget.py"],
  "allowed_test_paths": ["tests/test_widget.py", "tests/widget-fix.cases.json"],
  "test_command": ["python", "-m", "pytest", "-q", "{tests}"],
  "queue": {
    "depends_on": [],
    "priority": 0,
    "plan_ref": {"file": "docs/widget-plan.md", "anchor": "subtraction"},
    "shared_paths": [],
    "max_nudges": 2,
    "job_wall_timeout": 14400,
    "escalation": "human"
  }
}
```

New keys and defaults: `depends_on` unique same-queue task IDs (empty);
`priority` integer -100..100 (0); `plan_ref` optional contained existing file
and nonempty heading anchor (null); `shared_paths` additional relative write
patterns (empty); `max_nudges` integer 0..10 (2), shared across all roles and
reasons; `job_wall_timeout` positive seconds (14400); `escalation` enum human
(default) or sol. Reject unknown queue keys, booleans masquerading as integers,
duplicate task IDs, missing dependencies, self-edges and cycles on enqueue.
Enqueue parents first. Resolve relative repo from the enqueue cwd, other paths
from repo. Pin contract, plan section, hashes, settings snapshot and base when
first dispatched. Include only the pinned plan section with the contract in
both initial briefs; never reveal coder findings to designer.

`shared_paths` reserves hot files but grants no editing permission: each actual
edit must also be in that role's allowed scope. Use a separate final integration
job to edit shared manifests/changelogs whenever possible. Queue mode restricts
the existing broad progress-log exemption to exactly
`in-prog-logs/<task_id>-coder.md` and `...-designer.md`. Include these paths and
cases_file in reservation footprints. Reject code/test scope intersection within
a job, keeping test ownership separate. Reviewer is read-only except private
scratch, with no progress-log exemption.

Future queue config proposal: `schema_version`, `queue_id`, `concurrency_cap`
(proposed default 3), `provider_caps` (empty map), `notification_command` (null or fixed
argv), `poll_seconds` (5), and `escalation_model` (fixed permitted value
`codex/gpt-6.1-sol`). Provider caps are positive integers keyed by exact
provider/model string or explicit prefix ending `/*`; all matching limits
apply. Never infer provider membership from a substring. Snapshot job recovery
budgets; reread capacity settings on every scheduler cycle and before dispatch.
Legacy qwen_cap/reserve are not authoritative in queue mode: reject explicitly
supplied legacy capacity fields with a migration message, and bypass their
single-job preflight check only through the mandatory queue admission adapter.

| State | Entry / meaning | Allowed exits |
| --- | --- | --- |
| queued | Valid immutable entry; may be waiting on deps, scope or slots. | running on admission; paused by operator; failed on irreparable validation/state fault. |
| running | Owns path reservation; role executing, executor checking, or ready to publish. | paused for bounded recovery/maintenance; parked for exhausted or ambiguous recovery; landed after publication; failed for terminal infrastructure/state corruption. |
| paused | Saved phase with retry_at and typed reason, or intentional operator pause. No blind automatic resume of arbitrary Pause exceptions. | running after bounded classified recovery/admission; queued if never started; parked on budget expiry; failed on corruption. |
| parked | Reported issue requires explicit human/Sol disposition. Independent jobs continue. | paused after explicit queue resume/retry authorization; failed if abandoned. |
| landed | Tests gated, expected branch pushed, PR recorded; means ready-for-human-gate, NOT merged. | Terminal; review fixes are new queue entries. |
| failed | Invalid/corrupt/unrecoverable or explicitly abandoned. Preserve evidence. | Terminal; corrected work gets a new task ID. |

Track `merge_state` separately (unknown/open/merged/closed) and `blocked_by` /
`wait_reason` separately from state. A dependency is satisfied only when its PR
is verified merged and its result is included in the selected base. Landed alone
is insufficient. Parked/failed ancestors mark descendants dependency-blocked;
after one cycle park them with ancestor IDs, rather than leave them looking
runnable. Unrelated entries continue.

### Locking, durability and restart

Linux local filesystem only initially; refuse network filesystems without a
validated locking contract. Use advisory `flock` on stable lock files that are
never replaced or deleted. `runner.lock` prevents duplicate coordinators.
`queue.lock` protects config, control, enqueue publication and admission cache;
`job.lock` protects entry/state/job/report/events, CLI output and attempt-file
creation; `notifications.lock` protects its outbox. Per-repository landing and
path-reservation registry locks live in that repository's authorized queue-control
worktree, shared by every queue for that repository. Daemon-wide admission lock
belongs to the admission service, not to one queue. Every multiprocess writable
file is assigned one of these locks; workers never write driver files. A check
process gets an exclusive attempt directory under the job lock and owns its XML;
no other process may access it until its result is sealed under the same lock.

Lock order: admission service → repository registry → queue → job (sorted task
IDs) → notification. Never wait for an agent or network while holding local
transaction locks. Use a durable job execution lease and generation to exclude
a surviving child after coordinator restart; a lease is not permission to
relaunch until reconciliation proves the old owner/agent inactive. Lease fencing
must be checked before every external side effect.

For each JSON replacement: unique same-directory temp, flush, fsync, atomic
replace, fsync parent. Never silently load a partial/corrupt record. Entry/state
publication uses generation numbers. State is authoritative and contains an
outbox of numbered events; append/fsync events under job.lock and acknowledge in
state, deduplicating by event ID after crashes. Ignore only an incomplete final
JSONL line, retaining it as evidence in a new recovery record. Reports and CLI
transcripts use atomic publication; commands cannot overwrite another attempt.

Before create-workspace, run, send, stop, push or PR-create, persist operation ID,
intent, expected workspace/role/SHA and phase. Tag agents with queue/task/role/
operation labels (`run --label` verified in help). Record returned IDs as soon as
creation is observed, before waiting for completion. Do not rely on truncated
titles. After restart, list agents/workspaces, inspect exact IDs and labels,
read git state and remote PR/ref state, then adopt completed side effects. Stop
only confirmed owned agents. Unknown or multiple matching objects park that job.
A timed-out CLI launch is not proof no agent exists.

No verified Paseo idempotency-key API exists here. For a send with uncertain
acceptance, inspect retained logs for its operation marker; if acceptance cannot
be proved or disproved, park rather than replay. This gives idempotent resume
without promising exactly-once delivery: restart either adopts, safely retries a
proven unperformed action, or parks. Never reset a recovered role branch to base;
retain its committed and uncommitted work and resume on that branch. Existing
D:459/D:550 respawn behavior needs a queue-specific path.

## 4. Historical future scheduler and mutable capacity

`concurrency_cap` is a variable C, not a job-count limit. Each initial role,
reviewer, resumed turn and Sol analysis needs one admission. Jobs may start with
one role when only one slot is free; blind designer and coder can run at different
times from the same pinned base. Track active jobs separately from active turns.

Each cycle obtains a fresh `paseo ls -g --json`. Count all nonarchived agents
across directories and providers, including unrelated reviewers, orchestrator
workers and agents waiting on permission. Adapter classifies verified inactive
states versus occupied states; running/starting/waiting/unknown consume capacity;
verified idle/closed/dead do not. Error/errored consume a slot during recovery
grace until proven inactive. Never count only queue children or only Qwen.
Missing/malformed listing stops admission globally. Deduplicate by full agent ID.
Let L be occupied agents and R accepted launch reservations not yet visible in
that listing: dispatch only if L + R + 1 <= C, and every applicable provider/model
limit also permits it. Receipt-to-agent reconciliation prevents double counting.

**Hard-cap prerequisite:** `ls` plus local locks cannot atomically prevent an
unrelated UI/CLI caller launching between listing and queue spawn. Require a
Paseo daemon admission gate covering ALL run/send/resume entry points, including
UI and external agents, with atomic reservations and the same runtime limits.
This is proposed infrastructure, not a verified existing capability. Queue
refuses unattended hard-cap mode until that gate is available and live-tested.
A cooperative wrapper alone is not sufficient. If external activity already
exceeds C when enabled or lowered, do not stop it; prohibit new turns until there
is headroom. C limits new admissions, not historical overcommit.

`queue set-cap QDIR N` validates a positive integer (never bool, zero, fraction
or numeric string in JSON), atomically updates config under queue.lock, increments
config generation, and updates daemon admission authority before acknowledging.
Gate rejects old-generation dispatches. Scheduler rereads each cycle and again
on admission; no restart. Raising permits additional dispatch next cycle.
Lowering never kills running agents/jobs; block new dispatches, sends and
replacements until occupied capacity is below the effective limit. Invalid
command/config update preserves previous valid value and records an error;
unreadable/torn/unknown-version config holds new dispatches until repaired.

Optional provider caps use identical runtime transaction semantics via
`queue set-cap QDIR N --provider <selector>`. Global C always applies; provider
limits can make local Qwen stricter than hosted turns. On one daemon multiple
queues share one authoritative global setting: conflicting queue configs are
rejected, not silently combined. Status shows requested/effective cap, source
`QDIR/config.json#concurrency_cap` (or proposed-default), generation, last reload,
provider selectors/limits, occupied/reserved counts and cap wait reason.

Reserve paths before starting a job; hold through publication and confirmed
agent stop. Across all queues for one git common directory define footprint
F(job) as code union tests union shared_paths union exact role logs and cases.
For normalized relative POSIX path p, membership follows D:597–602's plain-path
prefix semantics and Python fnmatch wildcard semantics. Intersection means
there EXISTS a possible path p in both languages, including files not yet
created. Never expand only the current checkout or compare pattern strings.

Implement overlap as regular-language intersection emptiness: plain patterns
become literal p or p followed by slash plus suffix; compile *, ?, bracket
classes/ranges/negation to the supported fnmatch language, intersect product
machines with the valid relative-path language (nonempty components, no dot or
parent components, no NUL). On Linux matching is case-sensitive. Treat ** as
ordinary repeated * for scope, not glob's component-recursive semantics. Reject
unsupported/malformed character classes at enqueue; computational budget
exhaustion means overlap, never disjoint. Normalize trailing slashes; forbid
symlink scope escapes. Cases: `src/*` overlaps `src/x/y.py`; `src/a.py` overlaps
`src/[ab].py`; `src/a.py` and `src/b.py` are disjoint. A plain `src` reserves its
whole subtree. Landing rechecks actual changed paths against the same policy.

Overlapping jobs serialize through the repository reservation registry. A parked
job releases its reservation only after owned agents are confirmed stopped and
leases fenced; daemon uncertainty retains reservation and blocks only overlapping
jobs. Resume must reacquire it. Globally unavailable daemon blocks all dispatch.
Hot files such as package.json, lockfiles, CHANGELOG.md and test aggregators must
be declared in allowed role paths and shared_paths, or left untouched for a
separate dependency-ordered integration job. Per-task changelog fragments and
auto-discovered tests are preferred. Undeclared hot-file edits fail the final
scope gate; this is not repaired by silently broadening scopes.

Fairness: eligible turns ordered by effective priority = priority + floor(ready
wait minutes / 10), then enqueue sequence, task ID and role. No maximum aging
boost; old low-priority work eventually wins. Give each runnable job one turn
before assigning its second when peers can use the slot. A waiting high-ranked
job reserves no agent slots, but once highest-ranked it blocks admission of newer
overlapping jobs until it starts, avoiding repeated hot-file starvation.
At the cap, show external full agent IDs and providers occupying slots; poll at
poll_seconds without nudging/stopping unrelated agents or notifying orchestrator.

## 5. Stall and failure recovery

Defaults: poll 5s; transient error grace 120s; inactivity suspicion 300s; no-progress
window 600s; tool-call timeout 60s (retain existing git/test bounds); retry backoff
15, 30, 60, 120, then 300s, no jitter required for one coordinator. At most five
infrastructure retries per incident and ten per job, max_nudges total follow-ups
per job, one replacement agent per role and one optional Sol analysis per job.
Nudges are separate from existing max_rounds feedback, and neither budget resets
on restart. job_wall_timeout includes retries/slot waits after first dispatch,
excluding explicitly recorded maintenance intervals; maximum continuous
maintenance is 24h, then require operator resume. Queued dependency/cap waits do
not consume job wall time. At deadline stop owned agents, preserve evidence,
park. A stop cannot be confirmed while daemon is unreachable: mark stop-pending,
retain its reservations, and reconcile before dispatch resumes.

The following are owner-reported/project-relevant modes. Signals below use
help-verified CLI commands; live payload fields remain conditional on adapter
verification described above. Persist observed raw payloads and typed diagnoses.

| Mode | Detection signal | Bounded action and park condition |
| --- | --- | --- |
| Qwen outage/restart | `ls -g --json` status changes plus `logs <id> --tail 60 --json` errors or failing run/send; no assumed health field. Classify outage only from verified provider error signatures, otherwise unknown infrastructure fault. | Pause affected Qwen dispatch, allow hosted independent work; backoff probes use listings/logs, never inference. Once agent is inactive and server recovery is evidenced by resumed activity or owner maintenance resume, nudge existing context. If no recoverable context, one same-workspace replacement from preserved HEAD; five incident retries or wall cap parks. Never restart model server automatically. |
| Context overflow with self-recovering errored | Listing status `error` or provider-specific `errored`, corroborated by error log text; exact variants need pilot fixture. | Observe for 120s before intervention; if running returns, clear transient incident without send. Persistent overflow: stop/confirm then one replacement from same role workspace with bounded brief; shared nudge/replacement budgets apply, recurrence parks. |
| Pending permission | `permit ls --json`, exact full agent ID and request ID with tool input/cwd after live schema verification. Existing D:404 heuristic is insufficient. | Apply policy below to individual request; reread to confirm resolution. Unknown attribution/shape holds dispatch and parks owned affected job after grace. Never approve foreign request. Repeated denied request twice parks without further nudges. |
| Idle without finishing | Listing verified idle plus wait JSON idle; missing expected role artifacts (commit/cases/verdict), not simply absence of prose DONE. | One role-specific continuation, then executor re-evaluates. Consume max_nudges; unchanged artifacts across two completed recovery turns or exhaustion parks. |
| Garbled finished report | CLI invalid/missing final JSON, completed without identifiable agent, or reviewer lacks final VERDICT (D:417–429, D:671–676). | Reconcile exact operation/agent first. If committed role output passes deterministic gates, prose is irrelevant; malformed transport is never accepted as success. Ask existing reviewer once for exact verdict. Ambiguous identity/send acceptance parks immediately; recurring bad verdict consumes budget then parks. |
| Turn limit | `logs` error/text has pilot-verified provider limit signature, idle/error plus incomplete outputs; no assumed turnCount field. | Send continuation only after inactive confirmation and admission. Same budget; no larger hidden turn limit. One fresh same-role context allowed if required and safe; recurrence/exhaustion parks. |
| Looping | Hash committed HEAD, tracked/untracked diff, sealed executor failures and log-tail cursor/digest each cycle. Repeated same failure/tool signature with no substantive artifact improvement for 600s, even if text is streaming. | Stop owned turn, confirm, send one checkpoint continuation. Mere log activity does not reset progress. Two no-progress windows or exhausted nudges parks; 1800s agent turn timeout remains upper bound per turn. |
| Paseo daemon unreachable | CLI nonzero/timeout or JSON `error.code`, including observed DAEMON_NOT_RUNNING; never interpret empty/unavailable list as zero agents. | Hold all admissions/permits, backoff globally; do not start/restart daemon. Reconcile surviving agents when back. After five probes mark affected jobs parked/stop-pending, emit one degraded notification; keep low-frequency read-only probes for recovery, require explicit resume for parked work. |
| Executor timeout, red checks, bad cases or scope | Existing typed Pause/Escalate and persisted test results, not logs saying finished. | Keep existing executor/max_rounds feedback. Timeout is infrastructure Pause, never blame test author automatically. One bounded infrastructure retry; malformed cases/repeated scope/max_rounds map to parked with report. Never reset budgets or weaken tests. |

Follow-up messages are fixed templates with escaped data, no generated advice:

**Continuation** (idle, turn limit, recovered outage):
`[queue op={op_id}] Continue task {task_id} as {role} in this SAME workspace from
its current HEAD and saved edits. Read the pinned contract and your existing
progress log. Allowed paths: {role_paths}. Use relative paths; scratch only in
.scratch/. Do not inspect other roles or branches. {role_rule} Commit your work
on the current branch. The executor, not your report, decides completion. If
blocked, end with BLOCKED: followed by one concrete reason.`

role_rule for coder: `Never edit, weaken, skip, or delete acceptance tests.`
For designer: `Remain blind to implementation; write tests and cases_file only
within your scope, with declared base outcomes.` For reviewer: `Remain read-only;
end with exactly VERDICT: APPROVE or VERDICT: CHANGES REQUESTED.`

**Loop checkpoint**: prepend `The queue stopped your turn after no artifact
progress. Do not repeat the same failing command unchanged. Consult the last
executor result below; make one concrete scoped correction or report BLOCKED.`
Then continuation plus bounded executor tail (existing PROMPT_CAP), excluding
coder output from every designer message.

**Verdict repair**:
`[queue op={op_id}] Your final test-review verdict was missing or malformed.
Review only the pinned contract and frozen tests already in this workspace.
Do not edit files. End with exactly one line VERDICT: APPROVE or VERDICT:
CHANGES REQUESTED. Do not infer approval from your previous prose.`

**Replacement brief**: continuation with `Your predecessor stopped. Preserve
current commits and edits; do not reset to base. Its role-only checkpoint is:
{checkpoint}.` Never include cross-role implementation information.

### Historical structured permission policy (not shipped)

This section preserves the original structured-input design. It is not the
permission contract implemented by PR #376: live `permit ls --json` records
contain no structured command or path. The shipped cooperative policy is below.

### Shipped permission contract for PR #376

The captured record is `{id, agentId, agentShortId, name, description}` and
contains no structured command/path or verified cwd. Exact request and agent
IDs must agree with a fresh listing, and foreign requests are untouched.
Outside-workspace or risky evidence always denies the exact owned request;
unclassifiable evidence parks with the raw record. Unknown requests may be
allowed only for an exact operator-supplied trusted full ID or an owned agent
when `queue.trust_owned_agents: true`; this is cooperative trust in
agent-controlled description text, not containment. A `-` or empty description
is no evidence: it parks by default and is eligible for owned-agent trust.
File-change permits contain no path, so even that allow cannot prove scope.
The default remains no automatic allow.

The structured policy that follows is historical proposal text:

Auto-allow only a known structured read/write tool request whose complete inputs,
verified cwd and resolved file targets are provably within that role's own
worktree (including its .scratch), and writes also match its role scope or
private scratch. Resolve symlinks and every existing ancestor; reject escapes,
ambiguous cwd, symlink races and opaque payloads. Apply sandbox restrictions at
execution too; a permission-time path check alone cannot prevent races.

Never auto-allow rm/delete/unlink/cleanup, git push, sudo, package/network install,
network download, writes outside the worktree, or arbitrary shell scripts. Shell
parsing is not proof: reject substitutions, redirects, pipelines, eval, arbitrary
interpreters and unknown wrappers. Only permit exact registered nonmutating
argv templates with bounded args (for example read-only git status/diff) after
cwd/path proof. Test and scoped git commit operations run through a separately
installed trusted command broker with explicit allowed inputs, no hooks and no
arbitrary command approval. An opaque shell pytest request is not auto-approved.
Deny risky and unknown requests individually with:
`Queue policy denied this request: {reason}. Use only scoped relative paths and
approved commands in your worktree; do not retry the denied operation.`
Use full IDs and req_id, never `permit allow --all`, prefix matching or modified
input to disguise an operation. Persist request hash/decision before applying;
verify still pending and unchanged. If allow/deny response is ambiguous,
reconcile before retry. Policy installation is a prerequisite, not a prompt-only
guarantee. Legitimate denied operations park for the human; do not widen policy.

Escalation defaults to human: retain report, notify once, continue other jobs.
Opt-in sol launches exactly one `codex/gpt-6.1-sol` analysis turn through the same
capacity gate, with read-only scoped role-specific evidence and a 1800s limit.
It produces diagnosis, not permission overrides or merges. Keep test-side and
code-side evidence separate; never feed a code-aware diagnosis to the blind
designer. Park pending explicit disposition; do not automatically execute Sol's
free-form commands. Verify model availability in pilot; unavailable Sol falls
back to parked human report. No orchestrator model fallback exists.

## 6. Historical future scheduler landing order and PR flow

Use one per-repository landing lease across queues; ready candidates ordered by
ready time then task ID. Hold it for base freshness check, local integration,
regating and publication, but not for subsequent human review. On long command
failure save and release after fencing owned processes; never block independent
jobs indefinitely. A PR-ready job is landed even while orchestrator is absent.

At dispatch select latest verified target tip containing merged dependencies,
pinning it as that attempt's base. Before first publication fetch/recheck target
in trusted driver context. If target moved, do NOT rewrite job.base_sha and
reuse old expected-red evidence. Build a retained integration attempt from the
new target, apply only the original scoped code delta (not the driver's frozen
test commit), and apply the unchanged frozen tests separately for executor
checks. Record old/new base, candidate and frozen test SHAs. Re-run controls and
intended reds on new base, then candidate green, and full final scope gate.
If base now passes an intended red, park as superseded/changed contract; do not
silently relabel it. Do not show implementation to designer during integration.

Any rebase/cherry-pick/merge conflict pauses the attempt and immediately parks
that job, preserving conflict state and report; never ask a worker to guess a
resolution unattended. Initial implementation should use scoped delta application
rather than rewrite already-pushed history. No force push. If a published PR
needs a later refresh, require explicit operator retry and append a merge of
new target with new executor evidence, or enqueue a replacement task; no silent
history rewrite. Worker contexts are stopped before final gates, and recheck
HEAD/diffs immediately before publishing.

Reuse land's test-commit adoption and explicit HEAD refspec, adding a final
code/test/log scope and frozen-blob equality check at landing. Queue knows the
validated integrated candidate SHA; a different head returns to candidate, never
inherits green status. Trusted driver performs push and `gh pr create` on behalf
of job workers: this is how workers deliver PRs under the existing flow (D:978–1011),
not permission to approve worker push requests. Only push the task branch,
never base. PR lookup/adoption and exact remote SHA reconciliation make restart
safe. A closed/unmatched PR parks. Orchestrator later reviews diffs, reruns
checks and merges PRs one at a time; queue never invokes orchestrator or merges.
This may defer dependency jobs overnight until an independently authorized merge
is observed. Fixes from review are new queue entries with explicit dependencies.

## 7. Historical future status and observability

`queue status QDIR` reads committed state; `--live` refreshes every poll_seconds
without mutating jobs, `--json` provides versioned fields. Display queue identity,
maintenance/degraded status, heartbeat age, current/effective C and source,
config generation and error, provider caps, external occupied and pending
reservations. Per job show state/phase/role, base/candidate/test SHA, PR and merge
state, dependency/path/cap blockers, full agent/workspace IDs, last artifact
progress age, retry_at, nudges used/max, wall deadline, stop-pending and report
path. Example cap cell: `C=<configured> source=config.json generation=<g>
occupied=<L> reserved=<R> wait=external-capacity`.

Every transition, observation-based recovery decision, permit decision, operation
intent/result, config change and deliberate stop gets a timestamped numbered
job event with queue/job/operation IDs and bounded diagnostic tail. Secrets and
full shell environments are excluded. Queue-level events such as cap changes
are stored in control's durable outbox under queue.lock and projected into
`queue-events.jsonl` under that lock. Rotation creates numbered files, never
truncates/deletes them. status is useful while daemon is down and says stale.

notification_command is a trusted operator-configured fixed argv executed with
no shell, JSON event on stdin, queue-control cwd and scrubbed environment.
It is a plain command, not an LLM hook; never default to paseo send. Timeout 10s,
maximum two retries, durable event IDs for receiver deduplication (at least once
semantics). Hook failure logs an event and never blocks dispatch. Notify parked,
landed, queue drained, maintenance and daemon degraded/recovered, coalescing
repeated infrastructure failures. A drained queue distinguishes all-landed from
parked/failed/dependency-blocked results. No per-turn completion messages to
orchestrator. `start` remains available to retry parked work rather than spinning
on it; exit on operator interrupt with durable checkpoint.

## 8. Historical safety and maintenance proposal

No automatic deletion: retain workspaces, attempt dirs, transcripts and XML;
no cleanup command, git clean, forced worktree removal or file unlink in queue
execution. Deletion or rename requiring removal is unsupported initially and
parks for the human; queue mode rejects deletion diffs before executor/land.
This deliberately narrows current single-job deletion support (D:801–807).
Fresh attempt names replace D:787–798 reset/cleanup reuse; per-attempt XML avoids
D:735 unlink. Atomic state replacement is allowed; it is not destructive cleanup.
Disk free-space threshold (operator-configured service prerequisite) holds new
work before exhaustion, reports usage and asks the human to manage retention.

Workers use relative paths, own worktree and .scratch only; never use /tmp or
any shared temporary root, and never write to sibling worktrees. Trusted queue-control writes are confined
to its own worktree. Git's shared object/ref metadata and daemon registry changes
are explicit trusted broker operations, not arbitrary worker filesystem access.
Provision role worktrees under the queue-control worktree's .scratch through
approved workspace placement; actual placement support requires live validation.
If Paseo cannot supply compliant placement, pre-provision workspaces and pass
existing IDs; refuse launch if cwd falls outside the authorized layout.

Use OS-enforced write boundaries for workers AND model-authored executor tests,
with read-only source/standard-library/dependency mounts, disabled network and
only own scratch writable; trusted broker handles scoped commits into shared
git metadata. Shared git object-store reading still makes designer blindness
procedural unless object access is separately filtered. Same-user prompts and
permit inspection alone do not enforce filesystem boundaries. Test this sandbox
with attempted escaped writes before unattended release; no silent fallback to
full-access. No automatic sudo/network installation to provision it.

Per-job environment rule: never run editable install against a shared venv.
A `pip install -e .` can repoint its shared import metadata at one worker tree;
then another job's tests may import that tree. Provision isolated per-role and
per-executor-attempt venvs inside their .scratch from an offline dependency
wheelhouse, no writable shared site-packages or caches. Driver uses that attempt's
Python explicitly, sets cache/temp/home under scratch and verifies imported
project module paths are under the attempt being tested. Install project only
inside its private env; no worker network installs. Record environment manifest,
Python/dependency hashes and import-origin check in gate evidence. Base and
candidate may share immutable wheels, never writable editable metadata. Missing
prebuilt dependencies parks setup rather than changing the host environment.

`queue pause QDIR` durably records maintenance generation and stops NEW dispatches,
including nudges, reviewers and Sol, while current turns finish. `--stop-agents`
first records deliberate_stop intent per exact owned ID, then interrupts only
those agents and records acknowledgments; retain commits/edits and budget.
Timeout/unknown stop becomes stop-pending, never a crash-replacement trigger.
Other queues/external agents are untouched. Paused queue cannot land or run
checks; already-started trusted operations reconcile and checkpoint.
`queue resume QDIR` requires fresh daemon inventory, stop-intent reconciliation,
server readiness/operator confirmation and capacity reread, then resumes saved
role contexts without branch reset. Maintenance time is excluded as above;
other operator pauses do not reset recovery budgets. Restart during maintenance
stays paused. Do not automatically restart daemon or Qwen server.

## 9. Test plan and release gates

Historical test/release proposal as drafted before PR #376. Its old pilot gate
and status claims are superseded by six live pilots reported by the orchestrator
(the slice worker ran none) and the deferred
signal list recorded at the top of this document and in the slice task log.

Add `tests/test_agentcoder_queue.py` with a deterministic clock, multiprocess
fixtures, real git worktrees/bare origin under .scratch, and fake CLI fault
injection. Run with explicit scratch basetemp; do not use external temporary
paths. Existing tool/workspace/land-push suites remain regression gates.

Required named cases (names are proposed, not claims tests exist):

- `test_queue_reuses_existing_spec_and_rejects_unknown_queue_keys`,
  `test_queue_rejects_cycles_missing_deps_and_duplicate_ids`,
  `test_dependency_requires_merged_commit_in_base`,
  `test_parked_parent_parks_descendants_only`.
- `test_global_cap_counts_external_agents_and_reviewers`,
  `test_every_run_send_reviewer_and_sol_requires_admission`,
  `test_single_free_slot_starts_one_role`,
  `test_unknown_inventory_blocks_admission`,
  `test_provider_cap_combines_with_global_cap`,
  `test_daemon_gate_external_launch_race`.
- `test_raise_cap_at_runtime_dispatches_without_restart`,
  `test_lower_cap_while_running_never_stops_agents`,
  `test_invalid_cap_preserves_previous_value`,
  `test_status_reports_cap_value_source_and_generation`,
  `test_config_reload_failure_holds_dispatch`,
  `test_stale_generation_admission_rejected`.
- `test_overlap_includes_nonexistent_paths_and_slashes`,
  `test_overlap_bracket_negation_and_plain_prefix`,
  `test_overlap_unknown_is_conservative`,
  `test_cross_queue_hot_file_reservations_serialize`,
  `test_disjoint_jobs_run_concurrently`, `test_aging_prevents_hot_file_starvation`.
- `test_kill_before_and_after_every_operation_reconciles_once`,
  `test_uncertain_send_parks_without_duplicate`,
  `test_restart_adopts_agent_created_before_id_save`,
  `test_two_coordinators_and_surviving_children_are_fenced`,
  `test_state_fsync_replace_and_event_outbox_recovery`,
  `test_corrupt_state_fails_closed_without_overwrite`.
- `test_qwen_outage_backoff_is_bounded`,
  `test_transient_errored_recovers_without_nudge`,
  `test_idle_turn_limit_and_loop_share_nudge_budget`,
  `test_garbled_report_cannot_satisfy_gate`,
  `test_unknown_permit_payload_never_auto_allows`,
  `test_permission_exact_ids_and_fail_closed_paths`,
  `test_risky_shell_and_symlink_escape_denied`,
  `test_daemon_loss_retains_reservations_and_stop_pending`,
  `test_sol_opt_in_never_falls_back_to_orchestrator`.
- `test_landing_serialized_across_queues`,
  `test_target_move_regates_without_mutating_original_base`,
  `test_conflict_parks_and_next_independent_job_lands`,
  `test_final_scope_and_frozen_blob_checks`,
  `test_queue_pushes_head_to_expected_branch_without_force`,
  `test_pr_create_crash_adopts_existing_pr`.
- `test_maintenance_stop_intent_survives_restart`,
  `test_resume_preserves_dirty_and_committed_role_work`,
  `test_no_cleanup_or_external_writes`,
  `test_private_venvs_import_each_attempt_not_shared_editable_tree`,
  `test_notification_failure_never_blocks_queue`.

Mutation checks are mandatory: replace overlap with string equality or expand
only existing files (nonexistent overlapping path test must fail); remove
cross-kind code/test union (cross-kind conflict test must fail); make wildcard
slash-aware (nested-path test must fail). Remove external-agent counts, bypass
send/reviewer admission, change <= admission boundary, omit launch reservations,
or cache C across cycles: respective cap/race/runtime tests must fail. Save
mutation commands and failing assertions under .scratch, not just a pass count.

**Required live pilot, blocking unattended release:** against the REAL target
Paseo daemon and actual local Qwen, run a trivial throwaway add/subtract contract
in an isolated repository/worktree under .scratch. This is future implementation
validation, not a pilot claimed completed by this spec author. Capture CLI
version, command transcripts and exact JSON for listing, run, send, wait,
inspect/logs, workspace reuse and a harmless deliberate permission request.
Confirm exact agent/request IDs and structured permission input schema; if no
safe structured schema exists, automatic approval stays disabled and release
cannot claim unattended permission recovery.

Exercise one base control and one intended red, frozen-test candidate green,
one nudge, driver kill/restart during a live turn, deliberate maintenance stop
and resume without workspace growth or work loss, and a second independent job
continuing after the first is parked. Exercise global cap with an unrelated
agent and a concurrent external launch, runtime raising/lowering/invalid update,
and optional Qwen-only limit while a hosted test agent occupies global capacity.
Use capacity values chosen for the pilot environment, not hardcoded constants.
Prove daemon gate rejects external admissions at the boundary. Capture unknown
status/permission behavior rather than mapping it by guesswork. Replay recorded
fixtures offline afterward. Do not restart shared servers for fault injection;
use controlled endpoint loss or a disposable daemon for outage tests.

Publication leg uses a disposable bare origin to prove remote expected branch
SHA equals worktree HEAD; an explicitly authorized disposable forge PR verifies
real create/adopt separately, never merges. Failure to get forge authorization
leaves that pilot leg pending, not waived. Pilot must also prove sandbox escaped
writes denied and per-attempt import origins correct. A fake-CLI pass cannot
substitute for any of these live gates. Current author could not perform a live
payload probe because local daemon was unreachable; see section 2.

## 10. Historical implementation roadmap

Estimates are added/changed production + test + docs lines, not generated
fixtures. Each slice remains default-off until its gates pass; source-only
preparatory slices may land independently without enabling overnight operation.

| Order / slice | Estimated lines | Required tests / completion condition |
| --- | --- | --- |
| A. Typed job adapter, locked atomic state and retained attempts; preserve single-job behavior | 450–700 | Existing suites; state/operation crash tests; no-cleanup and workspace-preservation tests. |
| B. Daemon-wide admission prerequisite and runtime cap protocol, with queue client | 650–1000 across Paseo + driver | External-launch race, reservations, unknown inventory, all runtime cap and provider tests; live daemon gate proof. Separate Paseo PR required; cannot pretend local polling closes this gap. |
| C. Queue entry validation, dependencies and durable controls | 350–550 | Spec, cycle, merge-dependency, enqueue concurrency, corrupt state and pause persistence tests. |
| D. Overlap reservation registry and fair turn scheduler | 500–800 | Cross-queue/hot-file/disjoint/fairness tests, all role admission tests; overlap/cap mutations. |
| E. Permission adapter and OS/broker/private-environment prerequisite | 650–1000 | Real permission schema fixture, risky request/escaped-write/venv tests and live sandbox probe. Auto-allow stays off until this passes. |
| F. Bounded recovery, maintenance, optional Sol routing | 450–700 | Outage/context/idle/loop/turn-limit/garbled/uncertain-send/stop-intent tests; no orchestrator fallback. |
| G. Serialized fresh-base integration and PR publication | 350–600 | Target movement/conflicts/frozen scope/HEAD push/PR adoption and existing land regressions. |
| H. Status, event/notification delivery and operator docs | 250–400 | Cap-source/status/outbox/hook failure tests; manual maintenance walkthrough. |
| I. Recorded live pilot, fixture hardening and release gate | 250–450 | Every live leg above, mutations and full existing/new suites; attach evidence report, no fake-only release. |

Candid total: roughly 3900–6200 lines including tests/docs, plus environment
packaging variation and live pilot work; reserve another 20–30% for integration
findings. This is several reviewed PRs, not a small switch around `run_loop`.
The daemon gate and enforced permission boundary are the costliest external
requirements. Omitting them yields a useful cooperative scheduler but does not
satisfy the requested hard cap and fail-closed unattended safety guarantees.

## 11. Risks and owner questions

Primary risks: unverified CLI payloads/provider error variants; arbitrary
external launch races without daemon admission; same-user execution escaping
policy without OS isolation; shared git visibility limiting blindness; broad
scopes serializing most jobs; stale target invalidating intended reds; storage
growth under no-deletion retention; indefinite dependency waits before human
merges; ambiguous non-idempotent RPC delivery necessarily parking some work.
Deterministic recovery cannot repair every semantic implementation bug. Preserve
reports and continue independent work instead of adding unlimited nudges.

Recommended defaults stand unless the owner changes them. Open questions:

1. Will Paseo accept a daemon-wide admission gate shared by UI/CLI callers?
   Recommend making it a prerequisite for the hard-cap claim.
2. Which initial provider selector/limit should constrain local Qwen separately
   from global concurrency_cap? Recommend explicit configured model prefix;
   leave provider_caps empty until supplied, never infer it.
3. Should Sol analysis be enabled for any queue? Recommend human by default,
   opt-in per entry with one bounded read-only analysis.
4. Can the deployment provision OS isolation, offline dependencies and compliant
   workspace placement? Recommend refusing unattended mode if unavailable.
5. Are deletion/rename jobs needed in the first release? Recommend excluding
   them under the requested no-deletion policy and retaining evidence.
6. Which disposable forge repository is authorized for the required real PR
   create/adopt pilot? Recommend a dedicated fixture repo with no merge action.

SPEC COMPLETE.
