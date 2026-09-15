# revise now rewrites flow-style `type:`/`section:`/`prefix:`/`id:` values

`refdes revise` only saw these four keys when each sat alone on its own
line, so a value written inside a one-line flow mapping -- a YAML item
`- {id: BND-001, type: bound}`, a `defaults: {type: bound, prefix: BND}`,
a flow section marker, or Markdown front matter `{id: BND-001, ...}` -- was
left behind while the run reported success (or renamed the id but not the
prefix, leaving the file disagreeing with itself). Flow mappings now rename
in place, quoted scalars included (`type: 'bound'` is the same type, and
keeps its quoting style).

Two spellings are refused with an error naming the file and line, never
silently mis-edited: a flow mapping that spells the same key twice (YAML
last-wins makes any rewrite a guess), and anything the single-line rewrite
cannot reach -- above every check, a post-rewrite guard re-parses the
rewritten text and refuses (rolling back, and leaving `--dry-run` with the
identical report) whenever any item, defaults or section marker still
carries an old type, section type, prefix, or old-prefixed id. "Nothing to
do -- mapping does not apply" is now a claim about the parsed project, not
about which spellings the regexes happened to match.
