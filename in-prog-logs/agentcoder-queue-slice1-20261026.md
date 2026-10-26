# AgentCoder queue v1 slice 1 progress

Status: implementation advanced; the live pilot and several runtime signal
adapters remain unverified, so unattended-release readiness is not claimed.

## Captured evidence and adapter boundary

- Used `.scratch/live-fixtures2/README-findings.txt` first, then the verbatim
  files. Sanitized fixtures preserve those payload keys/types. Run blocking JSON
  is `{agentId,status,provider,cwd,title}` on stdout, with `Using workspace ...`
  on stderr; detached run uses the same keys with status `running`; permission
  is another captured run status. Send is
  `{agentId,status,message}`; idle wait is `{agentId,status,message}`. Workspace
  create/archive, inspect, logs, stop, and permit allow/deny shapes are captured.
- `logs --json` is plain text. Stop returns `{stoppedCount,agentIds}` and leaves
  a stopped agent `idle`, so queue maintenance intent is recorded before stop.
  The pending-permit row is `{id,agentId,agentShortId,name,description}` with no
  structured command/path. The description is free text and cannot establish
  containment. `NO_PENDING_PERMISSIONS` after a listing is treated as a benign
  race only when fresh listing confirms the exact request is gone.
- Outside-scope and reference-risky evidence denies the exact owned request.
  Other unclassifiable requests park with bounded raw evidence unless the
  operator explicitly supplies that exact full ID in `queue.trusted_agents`;
  alternatively `queue.trust_owned_agents: true` opts this job's recorded
  agents in. This cooperative opt-in allows the captured workspace-write text
  only after re-list confirms disappearance. Descriptions are agent-controlled
  and provide no containment proof. Outside/risky evidence always overrides
  trust. Foreign rows remain untouched.
- Non-idle/timeout wait, transient-provider error, turn-limit, loop signature,
  and garbled-finish payloads/signatures were not captured. Those signals remain
  unverified and park with evidence. The real probe workspace was archived by
  the orchestrator. The README's `error(?)` listing status was uncertain and is
  not accepted as a captured status. No Paseo or GitHub command was run by this
  worker.

## Implemented

- Opt-in `supervise`, `queue wait`, `queue stop`, and `queue resume`; legacy
  `run`/`resume`/`status` behavior remains gated by absence of the opt-in flag.
- Atomic fsync/replace state under stable job locks; retained attempt output;
  terminal outbox event committed before optional fixed-argv hook; waiter reads
  durable state before one-second rechecks.
- Bounded backoff 15/30/60/120/300 seconds, five retries per outage incident,
  ten per job; 120-second transient grace; shared max-two nudges; 600-second
  no-progress windows; one replacement per identified role; one verdict repair;
  14,400-second active wall cap with recorded maintenance intervals excluded.
  Unknown signals park. Only daemon-unreachable retry is currently detected and
  automatically driven by the supervisor; other signals require verified
  observations and otherwise park.
- Exact full-ID reconciliation from captured listing fields; missing/malformed
  IDs/statuses park instead of relaunch. Run intents persist before launch;
  saved role IDs adopt on resume. Unresolved run/send intents are never replayed.
  Supervised roles run serially, validate/create captured workspace payloads,
  and reuse prepared workspaces without resetting edits. Fresh completed run,
  send, idle wait, and workspace-create payload adapters now use captured shapes.
- Permission/running run responses persist the exact agent ID and reconcile the
  spawn operation before checking permits and waiting for the captured idle
  response. Unknown run statuses still park. Owned-agent trust defaults off;
  `queue.trust_owned_agents: true` or the retained exact-ID allowlist is an
  explicit cooperative opt-in, never a containment guarantee.
- `publish` defaults false in supervised mode. Optional plain-command terminal
  hook is bounded to two attempts and cannot erase/suppress the durable event.
- Task tests include every test name in the first v1 slice row, exact captured
  fixture replay, owned-agent/status adoption, foreign permit preservation,
  maintenance-stop persistence, and two disposable source mutations per run.

## Verification

- New queue suite: 31 passed with explicit `.scratch/` basetemp.
- Round-4 RED check ran three new behavior tests against the old code: the
  permission run failed at `agentcoder.py:475`, job trust failed with
  `process_permits() got an unexpected keyword argument 'trust_owned_agents'`,
  and the risky-description assertion exposed that `rm -rf` text classified as
  UNKNOWN. The unknown-status control passed.
- Existing AgentCoder tool/workspace/land suites: 129 passed with explicit
  `.scratch/` basetemp.
- `py_compile` passed. Scoped `ruff check tools/agentcoder/queue_mode.py
  tests/test_agentcoder_queue.py --select F` passed. `git diff --check` passed.
- Old-code RED check used a disposable copy of the pre-continuation
  `queue_mode.py`: 9 selected recovery/adoption/permit/maintenance cases failed
  on missing implementations. First failures included
  `test_outage_backoff_bounded` at `queue.bounded_recovery` and
  `test_unknown_permit_parks` at `queue.process_permits`.
- Mutation probes are retained under `.scratch/agentcoder-mutation-*`.
  Disabling the risky classifier failed the probe assertion
  `classify_permit_record(row)[0] == 'DENY'`; changing nudge `>=` to `>` failed
  `action == 'park'` after the third continuation. Both are caught by every
  queue-suite run.

## Remaining unsatisfied

- The orchestrator's round-4 supervised pilot ran and exposed the early
  permission-status run response. This worker did not rerun that live pilot
  after the fix; killed-supervisor-during-turn replay also remains unrun.
- Exact missing evidence to capture: non-idle/timeout `paseo wait --json`; a
  transient provider error in `logs`/inspect output; a turn-limit signature;
  repeated loop-signature logs/artifact state; and a garbled final run/report
  payload. These remain parked rather than inferred.
- Transient provider signature extraction, idle-artifact/turn-limit detection,
  streamed loop signature sampling, and garbled run/verdict parsing are not
  wired to live Paseo outputs because no corresponding payload/log fixtures were
  supplied. Their transition policies are bounded and tested; unverified live
  signals park rather than trigger a retry.
- The captured permit row cannot prove containment. Auto-allow is therefore
  off by default and available only as explicit cooperative trust in an exact
  full agent ID; no structured request classifier can prove this row in-scope.
- Multi-process supervisor-kill fencing during a child run, plus full batch
  generation semantics, remain outside this single-job slice implementation.

## Review rounds

Two implementation passes, one fixture-boundary correction, and one legacy
regression run completed; unresolved live/schema gates are listed above.
