# Captured Paseo fixture inventory

These payload fixtures are sanitized from orchestrator captures. IDs, project
names, paths, and free-text activity are redacted while payload keys and value
types are preserved. The task log summarizes the captured shapes and pilot
findings; ignored scratch paths are not required to interpret these fixtures.

`run-completed.json`, `run-running.json`, and `run-permission.json` preserve
blocking run responses. `run-blocking.stderr.txt` records the workspace banner
on stderr. `send-completed.json` and `send-permission.json` preserve accepted
send responses; `wait-idle.json` and `wait-permission.json` preserve wait
responses. A permission response from any of these accepted operations goes
through permit handling and then wait; send is never repeated. The detached
stderr fixture is byte-identical to the blocking banner fixture and records
that detached runs print the same workspace banner.

`ls-g.json` and `ls-g-permission.json` preserve global listing rows.
`workspace-ls.json` preserves the sanitized workspace listing. `workspace-create.json`
is exercised by tests; `workspace-archive.json` is unconsumed evidence. `stop-idle.json`
and `stop-running.json` preserve stop results. `inspect.json` and `logs-tail4.txt`
are unconsumed evidence; `logs --json` returns plain text despite the flag.

Permit records have `id`, `agentId`, `agentShortId`, `name`, and `description`,
with no structured command or path. `permit-pending.json`,
`permit-no-description.json`, and `permit-owned-write.json` are exercised by
tests. `permit-record-shape.json` and `permit-deny-response.json` are unconsumed
evidence. The latter is a `permit deny` response (`requestId`/`result`), not a
permit listing row; listing rows use `id` and `description`.
`permit-allow-stale.stderr.txt` is exercised by the stale-race test. The daemon's
`NO_PENDING_PERMISSIONS` error is stderr-only, so there is no corresponding JSON
stdout fixture. Duplicate permit listing twins were dropped from this fixture set.

`ls-statuses.json` is an unconsumed derived list of statuses accepted by the
classifier, not a Paseo payload; actual `paseo ls --json` rows are objects.
Some IDs and timestamps are fixture placeholders, and tests assert schemas and
control flow rather than live identity values.
