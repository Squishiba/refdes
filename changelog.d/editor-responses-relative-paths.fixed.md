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
  `file:` URI goes with its prefix. A path outside the root is reduced to
  its bare file name: the leaf is the part an author can act on, the
  directories outside the project are the leak. Known limits of the path
  reader: dot-segments, percent-encoding, 8.3 short names, and long-path
  aliases are not recognized; a root glued inside a web URL or behind a
  preceding word is left as written; path-shaped prose (a regex, a
  `/verbose` switch) is shortened like a path; text after a path span is
  re-emitted byte for byte; keys that scrub alike get `#2`, `#3` suffixes.
  Reads, uploads, and the patch contract: unchanged.
