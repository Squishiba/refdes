- **Editor write-route responses no longer embed the server's absolute
  project paths.** A conflict's `message`, a 200's `message`/`describe`,
  and the create route's `message` used to quote the target file with
  the machine's project root in it (`conflict:
  /home/you/your/project/items/REQ-001.md changed since this edit ...`),
  while the sibling `path` field has always been project-relative
  (user-sim run 13). The rule is enforced once, at the write routes'
  exit: every string in an edit/create response payload — `message`,
  `reason`, `describe`, the diff, the diagnostics, and whatever field is
  added next — has every recognized absolute path under the root
  rewritten to the project-relative forward-slash spelling
  (`items/REQ-001.md`, `items/REQ-007.md:6` with a line suffix; the bare
  root becomes `.`), in every separator spelling, inside quoted spans as
  well as bare text; a Windows-flavored root (drive letter, UNC) renders
  its whole remainder with forward slashes — the `path` field's spelling,
  on every platform — case-insensitively, spaces included; a local
  `file:` URI goes with its prefix. Outside the root only the bare file
  name survives — the directories outside the project are the leak. The
  root never survives anywhere in a response: a root glued into a web
  URL or onto a preceding word — bytes no path rule can rewrite — has
  its root text replaced with the marker `<project root>`, everything
  else byte for byte. Known limits of the path reader: dot-segments,
  percent-encoding, 8.3 short names, long-path aliases, and
  escaped-space roots (`proj\ demo`) are not recognized; backslashes in
  the remainder of a POSIX-rooted path are kept as filename characters;
  outside the root only the final path segment survives (a path ending
  in a separator yields its last directory name); path-shaped prose (a
  regex, a `/verbose` switch) is shortened while an isolated `/`
  (arithmetic, a table cell) is left alone; a token extended over a
  space crosses at most one space and a `:line` suffix closes the
  reference; text after a path span is re-emitted byte for byte; alike
  keys get `#2`, `#3` suffixes. Reads, uploads, and the patch contract:
  unchanged.
