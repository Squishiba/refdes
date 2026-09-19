- A new append-only entry is no longer sealed in a build that reports an
  ERROR attributed to it. Sealing it over the broken text turned the fix
  the error itself asked for into "modified since it was sealed" — the
  author was punished for following instructions. The entry is reported
  once ("LOG-001 was not sealed because it has errors; it will be sealed
  on the first clean build") and seals on the first later build where it
  is error-free. The rule is per-entry, not per-build: an error on some
  other item never stops a healthy entry from sealing, and project-level
  diagnostics (attributed to no entry) never block sealing either.
  Entries without errors seal exactly as before; nothing else about
  sealing changes.
