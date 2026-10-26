# AgentCoder queue v1 slice 1 progress

Status: implementation advanced; the live pilot and several runtime signal
adapters remain unverified, so unattended-release readiness is not claimed.

## Captured evidence and adapter boundary

- Used `.scratch/live-fixtures/README-orchestrator.txt` and the supplied
  snapshots. `ls-g.json` rows have exactly `id`, `shortId`, `name`, `provider`,
  `thinking`, `status`, `cwd`, `created`; captured status set is `running`,
  `idle`, `closed`. `workspace-ls.json` rows have exactly `workspaceId`,
  `project`, `name`, `isolation`, `cwd`. Captured `wait-idle.json` has exactly
  `agentId`, `status`, `message`, with status `idle`.
- `permit-ls.json` is `[]`. The orchestrator supplied the pending row schema
  `agentShortId`, `id`, `name`, `description`; `permit-record-shape.json` is
  synthetic policy input using only those keys, not a captured pending record.
- No run/send/stop response, logs/inspect output, workspace-create response,
  non-idle wait response, structured tool input/cwd, or provider error signature
  was captured. These remain unverified; the queue path rejects unknown field
  sets/statuses, does not infer safe containment from description prose, and
  parks ambiguous external operations with bounded evidence.
- The provided `auto-perm-reference.py` risky and safe-scope expressions were
  ported. Reference outside/risky requests are denied by exact full agent ID
  (mapped from one exact `agentShortId`) and request ID. Safe-scope prose still
  lacks the v1 structured input/cwd/target proof and is denied/parked, never
  auto-allowed. Foreign exact IDs remain untouched.
- No Paseo or GitHub commands were run in this continuation, per the user's
  instruction. The orchestrator owns the live pilot and PR.
- `paseo run --json` output was not among the supplied captures. To avoid
  guessing its schema, supervised mode now retains that output and parks before
  interpreting/adopting the new turn. Saved owned full IDs can still reconcile
  on resume. Workspace creation is also unavailable until its output is
  captured. This means a fresh supervised launch cannot complete its first
  role turn yet; the pilot must supply a run-result fixture before that gate can
  be implemented.

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
  Supervised roles run serially and reuse prepared workspaces without resetting
  edits. Workspace creation is refused because its response shape was not
  captured; operators must pass existing role workspace IDs.
- `publish` defaults false in supervised mode. Optional plain-command terminal
  hook is bounded to two attempts and cannot erase/suppress the durable event.
- Task tests include every test name in the first v1 slice row, exact captured
  fixture replay, owned-agent/status adoption, foreign permit preservation,
  maintenance-stop persistence, and two disposable source mutations per run.

## Verification

- New queue suite: 20 passed with explicit `.scratch/` basetemp.
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

- Real live pilot, including actual run/send/stop/workspace-create payloads and
  a killed-supervisor-during-turn replay, is delegated to the orchestrator.
- Fresh supervised launches currently park after retaining `paseo run` output,
  because that response schema is unknown. The exact captured shapes that remain
  unverified are run/send/stop responses, logs/inspect output, workspace-create
  response, and non-idle wait payloads.
- Transient provider signature extraction, idle-artifact/turn-limit detection,
  streamed loop signature sampling, and garbled run/verdict parsing are not
  wired to live Paseo outputs because no corresponding payload/log fixtures were
  supplied. Their transition policies are bounded and tested; unverified live
  signals park rather than trigger a retry.
- The queue cannot auto-allow any captured permit row: no captured row has the
  structured cwd/input/target data required by the accepted containment policy.
- Multi-process supervisor-kill fencing during a child run, plus full batch
  generation semantics, remain outside this single-job slice implementation.

## Review rounds

Two implementation passes, one fixture-boundary correction, and one legacy
regression run completed; unresolved live/schema gates are listed above.
