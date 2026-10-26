- Supervised AgentCoder now treats captured `wait --json` permission responses
  as permission checks followed by another wait. Sequential prompts use a
  separate per-job count and no-progress deadline instead of continuation
  nudges. Empty and `-` permit descriptions are treated as no evidence: they
  park by default and may be allowed only for explicitly trusted owned agents.
