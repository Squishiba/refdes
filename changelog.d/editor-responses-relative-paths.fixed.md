- **Editor write-route responses no longer embed the server's absolute
  project paths.** The `message` of a 409 was
  `conflict: /home/you/your/project/items/REQ-001.md changed since this
  edit was planned ...`, the `message`/`describe` of a 200 quoted the
  target as `... insert source at /home/you/your/project/items/REQ-007.md:6`,
  and the create route's `message` ended in
  `in /home/you/your/project/items/decs.yaml` — the machine's project
  root, served to whoever holds the launch token, while the sibling
  `path` field of the same response has always been project-relative
  (user-sim run 13, section 3.5). The prose is built at the service
  layer from absolute paths, so the rule is enforced once at the route's
  exit: every string in an edit/create response payload — `message`,
  `reason`, `describe`, the diff, the diagnostics, and whatever field is
  added next — has absolute paths rewritten to the project-relative
  forward-slash spelling (`items/REQ-001.md`, and `items/REQ-007.md:6`
  when a line suffix follows; the root itself — with or without a
  trailing separator — becomes `.`), in every separator spelling —
  including the doubled-backslash spelling the value quoting writes into
   file bytes and from there into the diff text, and a local `file:` URI
   spelling — any casing of the scheme, 0 to 3 slashes, an optional
   `localhost` authority, prefix removed together with the path (a
   dotted authority is a web URL and passes through) — and a
   drive-letter root matches
   case-insensitively; the root is matched literally, so a root
   containing spaces (`C:\Users\Jane Doe\...`) is no harder to scrub
   than any other. A path outside the project root is reduced to its
   bare file name — the leaf is the part an author can act on, the
   directories outside the project are the leak. The rewrite is a
   single scan of each string — quoted spans (a file's text quoted
   into a conflict message, source lines quoted into a diff) are
   decoded, scrubbed inside, and re-emitted with their quoting syntax
   kept, so an outside path with spaces inside quotes is reduced
   whole; a bare outside path containing spaces is reduced whole when
   the following words look like path components, and a bare token
   that does not is shortened to its last word — a documented limit
   shared with prose like `pattern /a+/g`, which reads as a path. A
   root that ends a sentence keeps its one period. Relative spellings
   and non-path text pass through unchanged: the rewrite consumes a
   path and its joining separator and never touches the text after
   it, so URLs keep every slash and a pasted absolute path is
   reduced, not re-emitted with its slashes collapsed; two payload
   keys that scrub to the same string are distinguished with `#2`,
   `#3` suffixes; reads, uploads and the patch contract are
   unchanged.
