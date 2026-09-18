- `refdes calc-rewrite`: transactionally rewrites retired
  `name : unit = expression` calc lines into the pipe form
  `name = expression | unit`, inside ```calc fences in item bodies only
  (Markdown and YAML block scalars; prose and `{{name}}` references are
  never touched). Indentation and comments survive byte-for-byte, and the
  command is idempotent. Like `refdes revise`, the whole plan is verified
  before anything is written, the rewritten project is reloaded and fully
  validated, and every calc's evaluated result and unit are compared
  against before -- any change in what a calc computes rolls every file
  back. Content hashes and calc hashes are carried forward across stamped
  baselines, so a spelling-only rewrite is not reported as a content
  change or as stale arithmetic. Sealed append-only entries are never
  rewritten: each old-spelling line inside one is listed (file:line, id)
  and left working on the old spelling until history-backed resealing
  lands. `--dry-run` reports every file and line on a throwaway copy of
  the tree (the same validation runs); `--no-write` behaves as dry-run.
