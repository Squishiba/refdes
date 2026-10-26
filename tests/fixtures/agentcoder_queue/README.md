These replay files are reduced from `.scratch/live-fixtures/` captured by the
orchestrator from the real Paseo daemon. Agent titles and wait activity are
redacted. The permit
list capture was empty; `permit-record-shape.json` uses only the four keys
provided in the orchestrator's capture note and contains synthetic values for
policy tests. It is not claimed as a captured pending request. No run, send,
stop, inspect, logs, workspace-create, or non-idle wait response fixture was
captured; those payload shapes remain unverified and may not authorize an
automatic recovery action.
