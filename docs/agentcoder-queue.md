# AgentCoder supervised mode

`tools/agentcoder/agentcoder.py` retains its existing `run`, `resume`, and
`status` commands. The opt-in `supervise SPEC.json JOBDIR` entry point stores
locked JSON state in the job directory, keeps per-invocation output under
`attempts/`, and writes a numbered terminal event before returning. `queue wait
QDIR [TASK_ID] --after EVENT_ID [--timeout SECONDS]` checks durable event state
before each one-second recheck, so a completion committed before registration
can still be observed.

The supervisor delegates acceptance checks and workspace management to the
existing AgentCoder driver. Its recovery policy is conservative: nonterminal
failures are parked unless the legacy job record proves a terminal result. It
does not yet provide the full queue v1 retry matrix or an owned-agent inventory
adapter.

Permission requests must be attributed to exact full agent IDs. The current
Paseo daemon was unavailable during implementation, so its permit payload schema
was not verified. No permit request is auto-approved by this adapter; unknown
input remains unknown. The local classifier supports only a narrow structured
file-request shape and is not an isolation boundary.

The real-daemon worker pilot is still required before unattended use. The daemon
reported `DAEMON_NOT_RUNNING` for global listing and permit listing, and the
spec prohibits starting shared services during maintenance. A live worker leg,
provider request fixture, supervisor-kill adoption, and maintenance stop against
the real daemon therefore remain unverified.
