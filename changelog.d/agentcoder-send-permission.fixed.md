- AgentCoder now classifies captured run, send, and wait statuses through one
  shared response adapter. An accepted send that returns `permission` is
  adopted, processed through the permit loop, and followed by wait for idle;
  it is never replayed.
