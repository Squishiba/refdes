# AgentCoder queue v1 — cooperative overnight core

Date: 2026-10-26. Proposed implementation contract; no code changes in this task.
This is the owner's approved scope cut of
`in-prog-logs/agentcoder-queue-spec-20261026.md` (the **full spec**), which remains
unchanged as the long-term target. This document overrides its daemon-admission,
OS-isolation and release-prerequisite requirements for v1. Overnight batches are
routine; ship the cooperative core, default-off until each slice's gates pass.
The latest owner simplification governs Qwen admission: soft variable caps,
Paseo inventory only, acceptable race overshoot, no corrective parking.

## 1. Deliver first: recovery, permissions and reliable parent wake-up

The driver is deterministic: no direct inference API, no orchestrator nudges,
permission babysitting or per-turn completion callbacks to an orchestrator model.
It launches workers through Paseo and optional Sol analysis explicitly chosen by
an entry. These worker turns consume model resources; supervision does not.
The parent awaiting completion is an ordinary process, not a model turn.

Implement the first slice as opt-in `supervise SPEC.json JOBDIR` around one
existing AgentCoder job, with durable controls and a minimal `queue wait` surface.
Run role turns individually rather than the current paired initial spawn; the
multi-job dispatcher follows in the next slice. Keep publication disabled unless
explicitly enabled for that job. Recovery, permission decisions and terminal
wake-up must be useful before parallel scheduling or a polished live UI exists.

Current-source evidence, reread for this cut: `tools/agentcoder/agentcoder.py`
(**D** below) pins base/contract and performs its old Qwen-only preflight at
D:280–317; it only pauses on pending permits and uses heuristic attribution at
D:388–414; it parses completed turns at D:417–447; it persists/reuses role
workspaces at D:450–505; it matches scope at D:597–617; it pushes HEAD and
creates/adopts PRs at D:926–1013; Pause/Escalate exit the loop at D:1054–1071.
No bounded queue recovery or durable parent-wake protocol is claimed present.
Full spec §2 supplies the remaining source-cited baseline and timeout facts.

Re-ran `paseo ls --help`, permit allow/deny help, run/send help and
`paseo ls -g --json`. Help confirms global listing, exact-request allow/deny,
run labels/workspace/environment options and nonblocking send syntax. Listing
returned `error.code: DAEMON_NOT_RUNNING`; live status/permission payloads remain
unverified. Do not guess their fields from the current heuristic. The owner's
model server is down for maintenance; this task does not start it or run a pilot.

### Exact v1 guarantees and limits

Guarantees are implementation requirements subject to the trusted-worker
operating rules below, not claims about current code:

| Given in v1 | Exact extent |
| --- | --- |
| Deterministic overnight supervision | Bounded classified retries/nudges, durable outcomes and parked reports; independent eligible work continues. No orchestrator-model escalation. |
| AgentCoder acceptance contract | Blind designer by instruction, frozen tests, executor-run base/candidate checks, final code/test/path/log scope and frozen-blob checks before publication. A completion message cannot substitute for checks. |
| Workspace continuity | One workspace per role per job, reused across nudges/replacement/review; retain commits and edits on recovery, never reset them to base. |
| Fail-closed permission decisions | Only provably local, recognized requests may be allowed. Outside/risky requests are denied; unclassifiable requests park with their raw bounded evidence. Foreign requests are untouched. |
| Durable control and parent completion | Locked atomic state, numbered terminal events and a blocking waiter that cannot lose completion during registration/restart; hooks are supplementary. |
| Cooperative overlap serialization | Every cooperating queue shares repository path reservations; possibly intersecting scopes never run together. Conservative false positives are accepted. |
| Runtime admission policy | Before each new run/send/reviewer/Sol turn, compare fresh global and configured-prefix live counts with current positive-integer settings. Lowering holds new work and never kills running work. This is a soft performance policy. |
| Restricted publication | Serial trusted-driver publication pushes HEAD to the expected task branch, adopts/opens PR, never merges. Conflict or stale-base ambiguity parks. |
| No deletion/rename jobs | Reject those diffs, retain attempt directories/artifacts, no automated cleanup. |

NOT given in v1:

- No hard global or Qwen capacity bound, atomicity with other launchers, or
  request/sequence telemetry. Inventory can lag and rare overshoot is acceptable.
- No OS isolation, hostile-code containment, syscall interception, symlink-race
  protection at execution, or protection from operations the provider executes
  without asking permission. Local permitted tests/scripts can write elsewhere
  or use network if the host/provider permits it. The classifier does not make
  arbitrary code safe, and it does not prevent all writes outside a worktree.
- No enforced blindness against a disobedient designer reading shared git
  objects, no integrity boundary protecting queue state from same-user workers.
- No exactly-once external RPC delivery: uncertain acceptance parks, rather than
  risk duplicate sends or agents. Parent event delivery is at least once by ID.
- No automatic conflict resolution, fresh-base integration/rebase engine,
  arbitrary shell approval, deletion support, host/server repair or dependency
  installation. No promise every batch finishes without human intervention.
- No orchestrator wake through an LLM notification. Process wake-up and optional
  plain-command hooks must be connected by the caller; neither merges PRs.

### Operating rules compensating for missing guarantees

Use trusted workers and reviewed contract/check commands on a dedicated checkout.
Keep credentials and sensitive unrelated work out of worker environments. Require
a permission-requesting provider mode; never bypass/full-access as a substitute
for the classifier. Unknown provider/request schema means park, not allow.
Treat executable checks and repository hooks as trusted reviewed code. These
rules reduce risk; they do not provide the full spec's filesystem isolation.

Routine local Qwen jobs, including orchestrator-requested work, launch ONLY
through the queue. The owner reports the PR reviewer rotation uses no local Qwen,
so queue routing covers routine Qwen launches. Hand-started Paseo agents are
nevertheless included in admission counts. A manual exception can race a launch;
accept slowdown and let existing turns finish. Do not stop someone else's agent.
Multiple queues use the same configured control registry and caps, not separate
competing global settings. Cooperating workers must not edit undeclared files.

Use only relative worker paths, scratch beneath that worker's `.scratch/`, never
/tmp, cleanup, deletion or rename. Trusted driver writes stay within its own
control worktree; git/daemon metadata changes remain explicit trusted operations.
Use pre-provisioned private per-role/per-attempt environments and offline
libraries. Never repoint a shared editable venv with `pip install -e .`.
Explicitly select the attempt Python and verify project import origins before
checks. Reusing immutable wheels is fine; writable site-packages/caches are not
shared. Missing dependencies park setup, never trigger a network install.

## 2. Recovery and permission policy

Adopt the failure matrix, fixed continuation/loop/verdict/replacement templates
and role-blindness restrictions of full spec §5. In v1 these are mandatory:

| Mode | v1 detection / bounded action |
| --- | --- |
| Qwen outage/restart | Failed run/send and verified provider error signatures in listing/logs; pause Qwen admission, backoff, recover same context after inactivity confirmation. Never restart server. Other hosted jobs may proceed. |
| Self-recovering error/errored/context overflow | Pilot-recorded listing/log signature; observe 120s first, with no send if it recovers. Persistent error permits one same-workspace replacement from retained HEAD; ambiguity parks. |
| Permission block | Exact owned agent/request IDs and full structured tool input/cwd from verified `permit ls --json` payload. Apply classifier below; no prefix-ID guess. |
| Idle without output / turn limit | Verified idle plus missing committed role artifacts, or pilot-recorded limit signature. One admitted continuation, then executor re-evaluation. No assumed turnCount field. |
| Garbled finished report | Invalid/missing final JSON or missing reviewer final VERDICT; reconcile operation identity first. One verdict repair when safe; unknown send acceptance parks. Never infer green from prose. |
| Loop | Same HEAD/diff/failure signature with no substantive improvement for 600s, regardless of streamed prose. Stop/confirm own turn then bounded checkpoint follow-up; two no-progress windows park. |
| Daemon unreachable | Timeout/nonzero/JSON error, including observed DAEMON_NOT_RUNNING. Hold all admissions/permit decisions, backoff, preserve leases and stop-pending. Never treat failed listing as zero live agents. |
| Red checks / bad cases / scope / executor timeout | Keep executor evidence and max_rounds; test timeout is infrastructure Pause, not author blame. Bad cases, repeat scope or exhausted feedback parks; never weaken tests. |

Defaults retained from full spec: poll 5s; backoff 15/30/60/120/300s; at most five
infrastructure retries per incident, ten per job; max_nudges 2 across all roles
and causes, separate from max_rounds; one replacement per role; active job wall
cap 14400s. Existing agent/test/tool timeouts still apply. A bounded outage never
becomes infinite continuation. Budgets and retry_at survive restart. Deliberate
maintenance intervals are excluded from active wall time; cap-wait time after
first dispatch is included. Whole-queue pause/resume and deliberate stop intents
follow full spec §8, without an OS sandbox prerequisite. Never classify an
intentional maintenance stop as a crash or spend a nudge on it.

On park, stop only exact owned active IDs; confirm inactivity before releasing
path reservations. Unknown stop outcome keeps reservation and stop-pending until
reconciled. Parked work requires explicit resume authorization and reacquires
scope. Daemon-wide outage necessarily prevents all new dispatch, while a local
job failure blocks only its dependencies/overlapping paths.

### Permission classifier, without OS isolation

Classify into ALLOW / DENY / UNKNOWN before any action, with request hash and
reason persisted. Requests must be attributed to a full recorded owned agent ID
and request ID; never use `--all` or modify input to evade policy.

- ALLOW: a known structured file read/write whose verified cwd and all resolved
  targets are inside that role worktree, including its `.scratch/`; writes must
  also match role scope, exact progress-log path or private scratch. Resolve
  existing parents/symlinks and reject escape/ambiguous targets. Allow known
  structured read-only tools with the same containment proof.
- DENY: every outside-worktree target and the risky class: rm/delete/unlink,
  git push, sudo, network/package install or download, cleanup, destructive git
  operations, and writes outside the worktree. Containment never makes these
  operations auto-allowable. Deny the exact owned request, persist the decision
  and park if the task needs it. No deletion/rename tasks are supported.
- UNKNOWN: malformed schema, unknown tool, opaque shell, unresolved cwd/path,
  symlink ambiguity or incomplete inputs. Never allow. Persist bounded raw
  input and classifier reason, stop/park the job. If the exact request is
  safely attributable, deny it with the reason before stopping; otherwise do
  not touch a possibly foreign request.

Shell text is not containment proof. No substitutions, pipelines, redirects,
wrappers, interpreters, eval or arbitrary scripts auto-approved. Permit only
small exact argv templates whose complete effect is known: read-only git
status/diff restricted to cwd; scoped git add/commit with explicit paths, fixed
message arguments, disabled hooks/signing/external filters; reviewed fixed check
commands whose referenced script paths are local. The last category proves
command/path provenance, not the behavior of executable code: it is allowed only
under the trusted-check operating rule. Unknown flags/templates park. Structured
file edits remain preferred. Do not relax classification to get a pilot green.

Use full spec §5's denial text and follow-up messages unchanged. Current
D:388–414's malformed-payload skip and ID-prefix heuristic must not govern v1
auto-approval. Pilot must demonstrate the actual provider emits enough input
for at least the approved local edits/commands; otherwise that job parks. The
missing OS boundary, provider bypasses, shared-user access and path-check races
are accepted limitations, explicitly listed above, not future release blockers
for this cooperative cut.

Sol stays human-by-default, opt-in per entry: one read-only
`codex/gpt-6.1-sol` analysis, admitted like any other turn, bounded to 1800s.
Its diagnosis does not execute free-form commands, widen permissions, merge,
or reveal coder evidence to the designer. Unavailable Sol parks for human;
never fall back to the orchestrator model.

### Completion protocol: reliably wake a waiting parent process

Add proposed `queue wait QDIR [TASK_ID] --after EVENT_ID [--timeout SECONDS]`.
Without task ID, wait for the sealed batch generation captured on registration:
all entries present then must become landed/parked/failed. New entries create a
new batch generation. This avoids a moving drain condition or busy-looping on
one already-parked task. Per-task waiter returns that task's next terminal event.

Commit terminal state and an outbox event together under job.lock; assign a
stable event ID and fsync before announcing it. Queue-drained completion similarly
commits under queue.lock after reconciling all included tasks. Waiter checks the
durable event/state first, installs any local wake hint, then rechecks before
blocking. Hints may be a pipe/socket or filesystem notification; they are never
the sole source. A maximum 1s timed recheck prevents a lost hint, process restart
or completion-before-registration race from stranding a waiter. No RPC to an LLM.

Wait prints one JSON envelope with event ID, batch/task ID, status, outcome counts
and report paths, flushes stdout and exits: 0 all selected work landed; 2 any
parked/failed; 124 timeout; 1 corrupt/unreadable state. An explicit maintenance
pause is observable but not terminal. Parent persists the returned ID and passes
it on reconnect for deduplication; if the terminal event was committed before
its waiter started, return it immediately when its ID exceeds the cursor.
The bounded wake-up promise assumes the waiter is scheduled and storage readable;
it does not promise delivery after arbitrary host/storage failure.

A parent can simply block on the supervise child process; terminal state/report
is durable before its exit, with the same outcome codes. Separate wait handles
supervisor restart. Optional notification_command uses full spec §7's durable
at-least-once plain-command hook, bounded execution and retry. Hook failure never
blocks jobs or suppresses waiter exit. No completion callback into a Paseo parent
agent is enabled by default. The caller can use the process/event protocol
without generating an orchestrator turn for every worker completion.

## 3. Queue, scheduler and runtime variables

Reuse the full spec §3 entry format and queue states, including depends_on,
priority, pinned plan_ref, shared_paths, max_nudges, job_wall_timeout, human/sol
escalation. Dependencies require verified merged results in the selected base;
landed means PR-ready, not merged. Park dependency-blocked descendants with
ancestor IDs; keep unrelated jobs eligible. Parent review/merge remains outside
queue supervision. Keep basic queue status and terminal hooks in the first slice;
UI polish follows scheduling.

Reuse full spec §3's directory layout, stable advisory locks for every
multiprocess writable file, atomic fsync/replace/directory-fsync writes, event
outbox, role-ID adoption and uncertain-operation parking. No daemon admission
service/receipts, capacity reservations or RPC fencing protocol are required.
Retain job execution ownership/generations to prevent two supervisors mutating
one job. One coordinator per control registry, all queues registered beneath it;
other registries cannot share path/cap coordination and are unsupported on that
repository. Repository reservation transactions remain locked; these locks are
for state/overlap consistency, not an atomic Qwen launch check.

Cap settings live in `QDIR/config.json`: `concurrency_cap` C (shipped global
default 3); `provider_caps` mapping configured prefix to positive integer.
Qwen prefix is exactly `opencode/qwenlocal/`; its cap Q is supplied at init by
the operator, with no fixed numeric default in this spec. Persist both value
and explicit/default source. Runtime setters are proposed
`queue set-cap QDIR N` and `queue set-cap QDIR N --prefix opencode/qwenlocal/`.
All registered queues use this shared registry's values.

Setters validate positive integers, excluding booleans, zero, negatives,
fractional values and JSON numeric strings. Under queue.lock, atomically replace
config and increment generation; invalid updates leave prior valid values intact.
Scheduler reloads every cycle and before dispatch. Invalid direct edits are
reported with last valid values retained, while new dispatch is held pending
repair; no silent return to a shipped default. Raising permits new work next
cycle; lowering never interrupts agents/jobs and holds new turns until counts
are below all applicable caps. Existing overcommit is not a reason to park.
Legacy single-job qwen_cap/reserve are rejected in queue entries with migration
help; queue-supervised preflight uses this adapter instead of that old check.

Count fresh global nonarchived live activity from `paseo ls -g --json` before
each run, send, reviewer and Sol turn. Deduplicate full agent IDs. Use
pilot-verified status mapping: active/running and ambiguous active states count,
verified idle/closed/inactive do not. Permission-blocked or transient error
states conservatively count until confirmed inactive. Unknown/missing provider
identity holds admission if its prefix membership cannot be established. Failed
or malformed inventory holds dispatch globally. No provider substring guesses.
For each new turn, hold if global count >= C OR any matching-prefix count >=
its cap; otherwise dispatch. All matching configured prefixes apply. Ready role
turns are evaluated one at a time using this policy; do not launch a paired batch
using one old count. There is no capacity reservation or post-launch correction.

### Qwen admission guard (soft performance policy)

The whole v1 Qwen check is: obtain `paseo ls -g --json`, count live active agents
matching the configured provider/model prefix `opencode/qwenlocal/`, and do not
dispatch another matching turn while count >= current Q. These listings include
agents started by hand through Paseo, not just queue children. Verified idle
agents hold no sequence and are excluded; permission/unknown-state overcounting
is intentionally conservative. Actual server occupancy is concurrent requests,
not number of agent records; even active-agent counts can over-restrict when an
agent is using tools rather than making a request. That is the safe performance
direction, not accurate sequence accounting.

Q is another runtime-variable soft per-prefix cap, using the same setter/reload
mechanism as C. No number representing a server maximum is baked in. No daemon
admission gate, launch lock, launch recount, or park-newest-job behavior exists
in v1. Any other launcher or inventory lag can cause rare overshoot. Accept it
as a performance effect and let running work finish. The owner's operating
premise is that the server queues excess requests and slows down; this policy
is not crash prevention. No capacity safety property depends on that premise.

Possible later refinement, OUTSIDE v1: sample running plus waiting requests
from `http://localhost:8080/metrics` to see non-Paseo clients as well. Candidate
names `vllm:num_requests_running` and `vllm:num_requests_waiting` are UNVERIFIED,
**to be verified in the live pilot against the real server** when it is back;
no endpoint probe or metric-support claim is made here. Any future metrics
signal may only tighten admission, never relax the Paseo-based decision; missing
or unreachable metrics would fall back to Paseo and log the source. No metrics
client, source-fallback tests or metrics release gate is included in v1.

### Overlap and landing: conservative, deliberately small

Use full spec §4's logical footprint: code union tests union shared_paths union
cases_file and exact per-role progress logs. Existing broad log exemption becomes
those exact paths in queue mode. Scope matching retains D:597–602 semantics,
including fnmatch wildcards spanning slash. A hot file must be in shared_paths
AND the editing role's allowed paths; otherwise final scope fails. Prefer a
final integration job for package/test lists and per-task changelog fragments.

For v1, defer the full glob-language automaton. Compute a conservative reservation
subtree for each pattern: a plain path reserves itself and descendants; a glob
reserves its literal directory prefix ending at the last slash BEFORE its first
`*`, `?` or `[`; no such directory means repository root. Strip trailing slash
for comparisons. Reserve two subtrees as overlapping when equal or either is a
component-boundary ancestor of the other; root overlaps everything. Two jobs
serialize if ANY footprint reservations overlap. Reject parent/dot/absolute
components, malformed patterns and symlink escapes at enqueue. Never use only
existing files to compute overlap. This is an over-approximation of possible
path intersection, including paths not created yet; false positives cost
throughput, never permission to parallelize a possible intersection.
Examples: `src/*` and `src/x/y.py` conflict; `src/[ab].py` and `src/a.py` conflict;
plain `src/a.py` and plain `src/b.py` can run together. Two distinct globs within
src may serialize even if their actual languages are disjoint. Narrow literal
paths give best v1 throughput. Keep full spec §4's priority aging and per-job
turn fairness; never reserve agent slots for a blocked job.

One repository publication lease serializes final checks and D:926–1013 land
calls. Recheck actual complete role diffs, no deletion/rename, frozen blobs and
current HEAD; stop owned contexts before final publication. Workers deliver PRs
through the trusted driver; their own git push requests remain denied. No automatic
merge/rebase/new-base replay in v1: if target has moved since pinning, pause and
park with old/new SHA, release after confirmed stop, continue other jobs. Conflicts
are reported/preserved, never guessed. This intentionally defers full spec §6's
fresh-base integration engine. Owner/orchestrator reviews and merges PRs outside
the queue; subsequent jobs pin the newly verified target as appropriate.

## 4. Independently landable implementation slices

Original full-spec A/C/D/F/H/I are recut below; only the permission classifier and
private-environment operating rule are pulled in from E. Daemon gate, OS sandbox
and automatic new-base integration are deferred. Estimates include changed
production code, meaningful tests and docs, excluding generated probe output.
Each slice lands default-off, with explicit opt-in only after its own offline
and live gates pass. Existing single-job behavior must pass regression tests.

| Slice / order | Lines | Tests and live gate carried with slice |
| --- | --- | --- |
| Recovery first: single-job supervise, locked state/retained attempts, owned-ID adoption, fail-closed permission policy, budgets, deliberate maintenance stop and durable completion wait | 850–1200 | `test_outage_backoff_bounded`, `test_transient_error_recovers_without_nudge`, `test_idle_turn_limit_loop_share_budget`, `test_unknown_permit_parks`, `test_risky_or_outside_permit_denied`, `test_foreign_permit_untouched`, `test_verdict_garbage_not_green`, `test_recovery_preserves_workspace_and_edits`, `test_uncertain_send_parks`, `test_maintenance_stop_intent_survives_restart`, `test_wait_completion_before_registration`, `test_wait_lost_hint_rechecks_durable_state`, `test_wait_survives_supervisor_restart`, `test_terminal_hook_failure_still_wakes_parent`; pilot steps A–C and final scope/HEAD regressions. |
| Scheduler: entries/deps, cooperative soft cap variables, conservative cross-queue overlap, fair role dispatch, minimal serialized publication | 650–950 | `test_entry_validation_and_dependency_cycles`, `test_dependency_waits_for_merged_base`, `test_disjoint_jobs_progress_after_park`, `test_overlap_future_paths_and_nested_slashes`, `test_overlap_code_test_shared_union`, `test_cross_queue_hot_file_serialization`, `test_scheduler_aging`, `test_hand_started_qwen_agent_counted`, `test_below_cap_dispatch`, `test_at_cap_hold`, `test_global_and_prefix_caps_both_apply`, `test_idle_agents_excluded`, `test_cap_raised_at_runtime`, `test_cap_lowered_while_running_no_interrupt`, `test_invalid_cap_keeps_previous_value`, `test_all_turn_types_check_caps`, `test_listing_unreachable_holds_dispatch`, `test_landing_target_change_parks_only_job`; pilot D and mandatory mutations. |
| Status/notification polish: live and JSON status, counts/source/generation, durable event export, coalesced command hooks and parent cursor ergonomics | 180–300 | `test_status_cap_values_prefix_source_generation`, `test_wait_batch_generation_and_cursor`, `test_hook_retry_deduplicates_event_id`, `test_hook_timeout_does_not_block_dispatch`, `test_status_stale_daemon_and_stop_pending`; pilot E. |
| Pilot evidence and fixture hardening: final end-to-end run and recorded payload fixtures | 180–300 | `test_live_queue_trivial_contract` opt-in integration harness, permission/status fixture replay, existing three AgentCoder suites; full A–F pilot, mutations and saved report. No fake-only waiver. |

Total approximately 1860–2750 lines, plus 20–30% integration contingency.
Soft admission is only a listing/filter/config check; there is no daemon patch,
metrics parser, launch-race correction, exact glob intersection engine or OS
broker to inflate this cut. Do not replace durable parent completion with a
best-effort hook to meet a line target. Unexpected schema work belongs in pilot
hardening, not ten rounds of guessed fake fixtures.

## 5. Live-pilot script outline and mutations

This is a script OUTLINE for implementation; no new queue commands are claimed
runnable yet. Save all artifacts under `.scratch/queue-v1-pilot/<run_id>/` and
retain them. Parent harness and CLI probes must use bounded timeouts. Do not
start/restart shared services during maintenance. Pilot waits for the real
Paseo daemon and real Qwen to be available; an unavailable service leaves the
live gate pending, not passed. No isolated fake daemon substitutes for the real
happy-path/permission/persistence run.

A. **Preflight and fixture.** Capture `paseo --version`, relevant help, global
   JSON, permission JSON and workspace list. Record actual full provider/model,
   statuses, agent/request IDs and tool input/cwd shape; create replay fixtures.
   Initialize a throwaway fixture repository/branch under scratch with a broken
   tiny add/subtract implementation, offline private environment and bare origin.
   Enqueue one control-pass/intended-red contract with exact code/test/log paths.
   Set C and Q to operator-chosen values; do not infer a server maximum.
B. **First-slice savings and permission.** Start a real supervised worker with
   a harmless local structured edit that requests permission; auto-allow it only
   when input is provably local. Generate safe pending examples of outside/risky
   and unknown input (never execute the destructive command); verify deny versus
   park, exact ID attribution and report. Trigger one idle incomplete turn and
   verify bounded fixed continuation, then base red/candidate green through the
   executor. Verify task checks use the private attempt's import origins.
C. **Parent wake and restart.** Start an OS parent waiting through queue wait;
   ensure it wakes on terminal state with event ID and exit code. Repeat with
   completion BEFORE registration, an intentionally dropped hint and a hook
   that fails. Kill/restart only the driver during a live agent turn, adopt the
   same agent/workspace, and verify no duplicate continuation. Exercise deliberate
   queue pause/stop/resume, preserving commits/edits and nudge budget. Park one
   deliberately incomplete job after budget exhaustion; waiter returns issue.
D. **Scheduling and runtime caps.** Run disjoint jobs plus one declared hot-file
   overlap; show serialization including nonexistent target paths. Start a manual
   Qwen through Paseo as an explicit pilot exception and verify it is counted.
   Set soft cap equal to live count to hold a new turn; raise it to permit that
   turn; lower it below ongoing activity and verify nothing is interrupted.
   Reject invalid update without losing previous value. Include a hosted reviewer
   in global counts and verify prefix filtering. Independent job proceeds after
   another parks. No overshoot-triggered stop or park assertion belongs here.
E. **Status, events and maintenance.** Verify status values/sources/generation,
   blocker reports, cursor replay and command-hook retries; no model callbacks.
   Test a controlled unreachable endpoint for driver failure handling without
   restarting shared server/daemon; after reconnection reconcile stop-pending.
F. **Publication.** Against disposable bare origin verify expected remote branch
   equals landed HEAD, including differently named local branch; fail stale-base
   publication and continue an independent task. If real PR-create/adoption is
   needed, owner authorizes a DRAFT PR in this repo from a unique fixture head
   onto this repo's dedicated fixture base branch, never main. Use only harmless
   fixture content, mark as pilot, verify create/adopt after restart, then CLOSE
   UNMERGED and verify closed state. Never merge or delete branch/workspace.
   Retain PR URL, hashes, transcripts and outcomes. This author is specifying the
   future pilot, not opening or closing any PR in this docs task.

Required mutations in disposable source copies under scratch:

- Replace overlap with pattern-string equality, or expand only files currently
  present: `test_overlap_future_paths_and_nested_slashes` must fail.
- Drop tests/shared_paths from the footprint: `test_overlap_code_test_shared_union`
  must fail. Make subtree ancestry slash-insensitive: a disjoint literal sibling
  fixture must expose false conflict. Change wildcard prefix extraction to a
  component-only wildcard assumption: nested-slash conflict must still be caught.
- Remove external IDs or restrict counts to queue children:
  `test_hand_started_qwen_agent_counted` must fail.
- Change hold condition from >= to >: `test_at_cap_hold` must fail. Always hold:
  `test_below_cap_dispatch` must fail. Cache caps instead of reloading: runtime
  raise/lower tests must fail. Ignore prefix/global conjunction or skip admission
  for send/reviewer/Sol: applicable cap tests must fail.
- Remove durable-state recheck after wake registration, then drop the hint:
  `test_wait_lost_hint_rechecks_durable_state` must fail by bounded timeout.

Save mutation, failing test name/assertion and fixture output, not only a count.
No launch-lock/recount, park-newest-job or metrics tests are part of this cut.

## 6. Status and upgrade path

Even before UI polish, basic status shows job state/phase/agent/workspace, last
progress, nudge/retry/wall budget, blocked_by, PR/report and stop-pending. Cap
cells show `global C=<value>` and `prefix opencode/qwenlocal/ Q=<value>`, each
with config/default source, generation, live count and last refresh age. Label
both SOFT. Source is `paseo-ls`, never metrics in v1. Whole-queue maintenance,
config reload error and daemon-stale inventory are visible without an LLM.
Use full spec §7 for plain-command hooks, redaction and coalesced events; durable
wait completion is required before the first slice is enabled.

Upgrade incrementally toward the unchanged full spec: optional daemon-wide
admission if hard coordination ever becomes useful; OS isolation and trusted
broker if stronger containment is needed; exact glob-language intersection to
reduce conservative serialization; full §6 fresh-base integration to reduce
stale-target parking. Metrics remain a possible independently validated
performance refinement. All retain the v1 entry/state/event compatibility or
carry explicit version migrations. None is a prerequisite to routine trusted
v1 batches under the owner-approved operating rules.

No owner questions remain open for this cut. Live CLI payload compatibility,
provider request shapes and candidate metric names are verification work, not
unresolved product decisions. The pilot forge fixture branch is provisioned by
the pilot harness; missing server availability is a pending gate, not a request
to change the accepted design.

SPEC V1 COMPLETE.
