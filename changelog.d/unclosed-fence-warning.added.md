- **An unclosed fenced code block in a markdown item body is now a warning.**
  A `---` line inside an *open* fence is example text (#331), and an opener
  that is never closed protects nothing: the rest of the file renders as code
  and a front-matter example inside it mints a live phantom item — silently.
  One easy-to-hit spelling is a fenced example whose closing line mirrors the
  opener with its info string (```` ```yaml ```` … ```` ```yaml ````): a
  closing fence cannot carry an info string, so that fence is exactly such an
  unclosed opener (finding R11-F1 of the run-11 release-gate simulation).
  `refdes check` (and the `index` payload editors read) now warns once at the
  opener's line, naming the file, and — when the file ends with a line that
  looks like a closer carrying an info string — names that line as the likely
  cause. Fences inside front matter stay opaque (no warning; a ` ``` ` there
  is YAML string content), a closed fence stays silent, and a `~~~` fence
  legitimately containing ` ``` ` lines warns about neither. The split itself
  is byte-for-byte unchanged: what parses today keeps parsing.
