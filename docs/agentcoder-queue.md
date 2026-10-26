# AgentCoder supervised mode

`tools/agentcoder/agentcoder.py` retains its existing `run`, `resume`, and
`status` commands. The opt-in `supervise SPEC.json JOBDIR` entry point stores
locked JSON state in the job directory, keeps per-invocation output under
`attempts/`, and writes a numbered terminal event before returning. `queue wait
QDIR [TASK_ID] --after EVENT_ID [--timeout SECONDS]` checks durable event state
before each one-second recheck, so a completion committed before registration
can still be observed.

The supervisor delegates acceptance checks to the existing AgentCoder driver.
Supervised jobs run one role at a time, require pre-provisioned workspaces from
the `workspaces` spec field, and retain role trees across recovery. Publication
is disabled unless the spec sets `publish: true`. `queue.max_nudges` defaults to
2 (maximum 10), and `queue.job_wall_timeout` defaults to 14,400 seconds. The
recovery policy applies bounded outage backoff, a 120-second transient-error
grace, a shared continuation budget, a 600-second no-progress window, one
replacement per identified role, one verdict repair, and explicit park behavior
for ambiguous sends. Automatic signal extraction for transient errors, loops,
idle artifacts, and garbled reports still requires the live pilot; absent verified
signals park with retained evidence.

Permission requests use the captured record fields `agentShortId`, `id`, `name`,
and `description`. The short ID must map to exactly one full ID in the captured
global listing and that ID must be owned by this job. Foreign requests are
untouched. The record contains no structured tool input or cwd, so safe-scope
prose cannot establish the v1 containment proof and is denied/parked. The
reference policy's outside/risky phrases are denied. No permit is auto-allowed
from the captured schema.

`queue stop JOBDIR` persists deliberate stop intent before sending exact owned
IDs to `paseo stop`, then confirms inactivity from a fresh captured listing.
`queue resume JOBDIR` requires explicit authorization and fresh reconciliation.
Uncertain run/send operations remain durable and are not replayed.

The supplied live fixtures do not include `paseo run --json` output. For that
reason, supervised mode retains the run output and parks before interpreting a
new turn result; it cannot safely adopt a just-created agent from that response
yet. A previously saved owned full ID can be reconciled and adopted from the
captured global listing fields. Workspace creation is likewise unavailable
until its response shape is captured.

The real-daemon worker pilot is still required before unattended use. Run/send/
stop responses, logs/inspect output, workspace-create response, and non-idle
wait payloads remain unverified. No live worker was started in this work.
