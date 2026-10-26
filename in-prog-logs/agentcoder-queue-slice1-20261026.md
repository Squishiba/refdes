# AgentCoder queue v1 slice 1 progress

Status: slice implementation complete. The orchestrator reports six live
supervised pilots; the slice worker started none. Several runtime signal
adapters remain unverified, so unattended-release readiness is not claimed.

## Captured evidence and adapter boundary

- Sanitized committed fixtures preserve the captured payload keys/types. Run blocking JSON
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
- Other captured shapes: `paseo ls -g --json` is a JSON array with each agent
  row carrying `id`, `shortId`, `name`, `provider`, `thinking`, `status`, `cwd`,
  and `created`; workspace creation returns `workspaceId`, `project`, `name`,
  `isolation`, and `cwd`; permit allow/deny is verified by a fresh permit list.
  Blocking `run --json`, accepted `send --json`, and `wait --json` each return
  one stdout object; the run workspace banner is stderr text.
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

- Queue suite before round 10: 48 passed with explicit `.scratch/` basetemp.
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

- Pilots exposed early permission statuses for run, wait, and send, plus the
  initial state-shape crash and sequential permission prompts; these are covered
  by replay/regression tests. The orchestrator reports six live pilots and
  pilot #5 passed end-to-end. This worker did not run a live pilot;
  killed-supervisor-during-turn replay remains unrun.
- Still unverified live: timeout/non-idle wait, transient provider errors,
  turn-limit/loop signatures, and garbled finish payloads; they park with
  evidence. Multi-process supervisor-kill fencing and batch generation remain
  outside this single-job slice. Permit descriptions still cannot prove
  containment; owned-agent auto-allow is cooperative trust.

## Review-round summary

Rounds 5–8 fixed owned-agent write-ahead, run/wait/send permission handling,
Windows lock import, and fixture redaction; the POSIX fallback shim passed while
native Windows CI was unavailable, and the orchestrator reports six live pilots.
Round 9 tests first went RED: permit transport errors raised `UnboundLocalError`
(`queue_mode.py:792`), reviewer permission was skipped (`agentcoder.py:270`),
`a:1` hid unseen `b:1`, and the backoff-clock helper was absent; all regressions
now pass. `prior_state` already contributed durable owned IDs and is now read via
`_durable_agent_ids`; README and both specs distinguish shipped behavior from
legacy/future design. Seven review reports read; queue: 51 passed; legacy: 130.
Review-log access returned `DAEMON_NOT_RUNNING`; no daemon or GitHub command ran.

Round 10 reproduced the Windows directory-open failure in
`test_atomic_json_windows_skips_unavailable_directory_open` before the fix.
Directory fsync now skips Windows and tolerates OS errors; file fsync and POSIX
directory fsync remain covered. Audit: queue and supervised driver use no
signals, `killpg`, `getpgid`, chmod, or platform-only `O_*` flags. JSON uses
UTF-8 text with newline-tolerant readers; exclusive `x` temp creation is
portable; monotonic timers are platform-supported. Relative spec globs use
forward-slash matching and `path_matches`; it normalizes separators and folds
case on Windows (tested with a simulated platform). Resolved filesystem
containment uses native `os.sep`. No explicit long-path layer exists; those
filesystem cases cannot be exercised in this Linux run. `os.replace` targets
are closed before replacement in both state writers; native Windows sharing
behavior remains unverified here.

Round-10 verification: queue 51, legacy 130, py_compile, scoped Ruff `F`, and
diff checks passed. Four fragments were consolidated; the guide remains indexed.

Round 11: six new regression cases were first run RED against the prior code;
all now pass. Running waits sleep one bounded second, non-publishing land
refreshes its report, send timeouts persist uncertain operations, and supervised
mode is an explicit child argument rather than an environment opt-in. Permission
no-progress time resets on handled prompts and running responses; prompt count
remains separately bounded. Fixture README inventories all evidence-only files;
duplicate stale/listing twins were removed. Six live pilots are orchestrator-
reported; this worker ran none. No daemon or GitHub command ran.

Rounds 11–13: regressions exposed wait-budget overrun, reconciliation clobber, running-wait spin, stale reports, uncertain/duplicate sends, env opt-in, permission timer, generic outside paths, missing attempts, stop side effects, terminal replay, and task-qualified wait; each round's required regressions were RED before fixes. All review dumps were read; docs and fixtures label implemented/deferred behavior, and spec/fixture artifacts name the task log. Queue: 70 passed; legacy tool/workspace/land: 131 passed; py_compile, scoped Ruff `F`, and diff checks passed. This worker ran no daemon or GitHub command.
