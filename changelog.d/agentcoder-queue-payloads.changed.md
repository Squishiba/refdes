- Updated opt-in AgentCoder supervision against captured real-daemon run, send,
  idle-wait, stop, workspace, and permission payloads. Run JSON is read from
  stdout while its workspace banner stays on stderr; stop intent is durable
  because Paseo reports stopped agents as idle. Permission rows lack structured
  command/path data, so unknown requests park unless an operator explicitly
  lists the exact full agent ID as a cooperative trusted agent. Outside/risky
  evidence is denied even for trusted agents; stale `NO_PENDING_PERMISSIONS`
  races are benign after a fresh listing confirms the request is gone.
