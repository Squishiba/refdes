- **A link verb given an element that is not a string is named, not
  quoted.** A mapping inside a `satisfies:`-style list used to survive into
  the link graph as the `str()` of the loader's own line-tagged dict, and the
  dangling-reference rule reported it verbatim: `satisfies points at "{'name':
  'not-a-string', 'verdict': 'x', '__line__': 6}", which does not exist` —
  internal bookkeeping quoted at the person who has to fix the file, and the
  *shape* of the mistake never named. The entry is now refused where it is
  read, at the verb and the index that carry it —
  `satisfies[0]: {'name': 'not-a-string', 'verdict': 'x'} is not a string --
  a link target is one item id per entry` — with the entry shown as written
  (no `__line__`), the same granularity the `citations[0]:` and `options[0]:`
  diagnostics already use. A bare scalar link target (`satisfies: REQ-001`)
  is unchanged: one target, one edge.
