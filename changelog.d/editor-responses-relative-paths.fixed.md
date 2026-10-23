- **Editor write-route responses no longer embed the server's absolute
  project paths.** The `message` of a 409 was
  `conflict: /home/you/your/project/items/REQ-001.md changed since this
  edit was planned ...`, the `message`/`describe` of a 200 quoted the
  target as `... insert source at /home/you/your/project/items/REQ-007.md:6`,
  and the create route's `message` ended in `in /home/you/your/project/
  items/decs.yaml` — the machine's project root, served to whoever holds
  the launch token, while the sibling `path` field of the same response
  has always been project-relative (user-sim run 13, section 3.5). The
  prose is built at the service layer from absolute paths, so the rule is
  enforced once at the route's exit: every string in an edit/create
  response payload — `message`, `reason`, `describe`, the diff, the
  diagnostics, and whatever field is added next — has absolute paths
  rewritten to the project-relative forward-slash spelling
  (`items/REQ-001.md`, and `items/REQ-007.md:6` when a line suffix
  follows; the root itself becomes `.`), in both separator spellings, and
  a drive-letter root matches case-insensitively. A path outside the
  project root is reduced to its bare file name — the leaf is the part an
  author can act on, the directories outside the project are the leak.
  Relative spellings and non-path text pass through unchanged; reads,
  uploads and the patch contract are unchanged.
