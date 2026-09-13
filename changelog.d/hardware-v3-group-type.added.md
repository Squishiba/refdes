- **`hardware@3` adds a `group` type (prefix `GRP`)** — a named collection of
  items ("the PCIe interface spec") that never stands in for its members.
  Membership is declared by the *member*, pointing at the group with a new
  `part_of:` link (available to `requirement`, `bound`, `decision`, `test`,
  and `component`); a group never lists its occupants, and `contains` exists
  only as the computed inverse backlink of `part_of`, so a group can never
  silently enlarge its own meaning as its contents grow. The two properties
  this type exists to guarantee are negative ones: a group is
  `coverable: false`, so it never appears in coverage and never acquires a
  coverage stage, and it is deliberately absent from every `satisfies:`
  target list, so nothing may claim it — the asymmetry that keeps a group
  from discharging its members' obligations by being satisfied itself, the
  failure mode this addition was framed against. To gather items under a
  name, author `part_of: [GRP-…]` on each member; a group's contents are
  read through its `contains` backlinks. (The bundled standard is itself
  unreleased — a project pinned at `v1` or `v2` sees none of this.)