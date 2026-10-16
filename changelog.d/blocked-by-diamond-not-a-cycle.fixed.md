- A `blocked_by:` diamond is no longer reported as a `blocked_by cycle:`
  error. Two paths reaching the same blocker (e.g. X blocked by both A and
  B, with A also blocked by B) is a reconvergence, not a cycle; only an
  edge closing back on a node already on the walk's own path is one. Real
  cycles (self-loops included) still stop the build with the full path.
