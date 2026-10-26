# AgentCoder supervised mode

`tools/agentcoder/agentcoder.py` retains its existing `run`, `resume`, and
`status` commands. The opt-in `supervise SPEC.json JOBDIR` entry point stores
locked JSON state in the job directory, keeps per-invocation output under
`attempts/`, and writes a numbered terminal event before returning. `queue wait
QDIR [TASK_ID] --after EVENT_ID [--timeout SECONDS]` checks durable event state
before each one-second recheck, so a completion committed before registration
can still be observed.

The supervisor delegates acceptance checks to the existing AgentCoder driver.
Supervised jobs run one role at a time, accept pre-provisioned workspaces from
the `workspaces` spec field or create one from the captured workspace response,
and retain role trees across recovery. Publication
is disabled unless the spec sets `publish: true`. `queue.max_nudges` defaults to
2 (maximum 10), and `queue.job_wall_timeout` defaults to 14,400 seconds. The
recovery policy applies bounded outage backoff, a 120-second transient-error
grace, a shared continuation budget, a 600-second no-progress window, one
replacement per identified role, one verdict repair, and explicit park behavior
for ambiguous sends. Automatic signal extraction for transient errors, loops,
idle artifacts, and garbled reports still requires the live pilot; absent verified
signals park with retained evidence.

Permission requests use the captured fields `id`, `agentId`, `agentShortId`,
`name`, and `description`. Both IDs must agree with the fresh global listing,
and the full ID must belong to this job. Foreign requests are untouched.
Evidence of an outside target or risky operation denies the exact request and
parks the job. The record has no structured command/path, so other requests
park with bounded evidence. Operators may explicitly opt exact full IDs into
the cooperative `queue.trusted_agents` list; those agents' otherwise
unclassified requests may be allowed, after a fresh listing confirms the exact
request disappeared. Outside/risky evidence always wins over trust.

`queue stop JOBDIR` persists deliberate stop intent before sending exact owned
IDs to `paseo stop`, then confirms inactivity from a fresh captured listing.
`queue resume JOBDIR` requires explicit authorization and fresh reconciliation.
Supervised run, send, idle-wait, workspace-create, and stop outputs are checked
against captured stdout JSON shapes; run's `Using workspace ...` banner is
read from stderr. A deliberate stop is recorded in queue state before Paseo is
called, because Paseo reports the stopped agent as `idle`. The queue validates
the stop response and then records fresh listing evidence. An exact
`NO_PENDING_PERMISSIONS` response followed by an absent request is a benign
permission race. Uncertain run/send operations remain durable and are not
replayed.

The orchestrator supplied real-daemon fixtures for run, send, idle wait, stop,
workspace create/archive, inspect, logs, and permission responses. `logs --json`
is plain text, and only the captured idle wait is recognized. Non-idle/timeout
wait responses, transient provider errors, turn limits, loop signatures, and
garbled finishes have no captured payload and park with evidence. No live worker
was started in this work.
