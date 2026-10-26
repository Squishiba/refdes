- Add opt-in AgentCoder queue supervision with locked state, retained attempts,
  owned-agent recovery, bounded recovery and permission budgets, maintenance
  stop intent, and durable completion events. Run, send, and wait responses
  share status handling; accepted sends are never replayed after a permission
  response. Permit auto-allow requires explicit cooperative trust, while
  outside or risky evidence is denied and unclassifiable requests park. Permit
  transport failures, task-qualified event cursors, and reviewer permissions
  are handled safely. POSIX directory fsync remains best-effort, and Windows
  skips the unsupported directory-handle operation.
