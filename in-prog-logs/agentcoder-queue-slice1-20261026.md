# AgentCoder queue v1 slice 1 progress

Status: incomplete; implementation does not satisfy the full slice contract.

## Verified first

- Read `AGENTS.md`, the v1 slice contract, full-spec §§5/8/9, AgentCoder
  driver/README, and the named legacy suites.
- Ran `paseo ls -g --json` and `paseo permit ls --json`. Both returned this
  exact shape:

  ```json
  {"error":{"code":"DAEMON_NOT_RUNNING","message":"Cannot connect to daemon at home /home/jorb/.paseo: Daemon is not running for /home/jorb/.paseo. Start with: paseo daemon start --home \"/home/jorb/.paseo\"","details":"Start with: paseo daemon start --home \"/home/jorb/.paseo\""}}
  ```

- Ran `paseo wait --help`, `logs --help`, `send --help`, `stop --help`, and
  `workspace --help`; the CLI documents the listed commands, but the unavailable
  daemon means their JSON response payloads were not verified.
- Did not start the daemon or a Qwen agent. Full spec §5 says to wait for the
  real daemon/Qwen pilot; §8 says not to start/restart shared services during
  maintenance. Live payload fixtures and pilot are pending.

## Changes made

- Added opt-in `supervise SPEC.json JOBDIR` and `queue wait` dispatch while
  leaving legacy commands on their default path.
- Added atomic fsync/replace JSON writes, stable `flock` files, retained
  per-attempt transcripts, terminal event outbox entries, and durable-state
  polling for wait.
- Added conservative structured-file classification and exact full-ID permit
  attribution helper. The helper is not integrated into the old driver's
  heuristic permit path; this remains a blocking implementation gap.
- Added 16 offline tests and documented current limits. The tests do not cover
  the entire required failure matrix or full fake-Paseo role-turn recovery.

## Verification and difficulties

- New offline tests: 16 passed with an explicit `.scratch/` basetemp.
- Legacy regressions: first run failed because importing `agentcoder.py` from
  tests did not put its sibling module on `sys.path`; the failing assertion
  trace pointed to `tools/agentcoder/agentcoder.py:1081` (`ModuleNotFoundError:
  queue_mode`). Added the script directory before the opt-in import. Rerun:
  129 passed.
- The tests were not each shown RED on the old implementation before being
  added. Required mutation checks were represented as boundary assertions, but
  disposable source-copy mutations were not run. These requested gates remain
  incomplete.
- Implementation still lacks the specified owned-agent reconciliation,
  bounded classified retries/nudges, transient error observation, uncertain
  send reconciliation, deliberate-stop daemon acknowledgments, complete report
  parsing and role-artifact gates, batch-generation semantics, multiprocess
  crash windows, and hook behavior. Do not treat the feature as ready for
  unattended use.
- The real daemon and live worker gate could not be performed without starting
  a shared service during its stated maintenance interval. No worker workspace
  was created.

## Review rounds

One code pass and one legacy-regression correction were completed; remaining
contract gaps and pending live gates are recorded above.
