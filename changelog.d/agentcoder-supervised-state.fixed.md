- Fixed supervised AgentCoder's initial `owned_agents` state shape and added
  clear state-schema validation. Newly spawned IDs are journaled write-ahead
  and preserved when the child exits; unexpected exceptions now park with a
  short event outcome while retaining the traceback in the attempt transcript.
