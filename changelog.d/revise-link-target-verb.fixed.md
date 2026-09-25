- `refdes revise` validates a type rename's target in both directions but not a
  link rename's: `links: {refines: narrows}` on a project declaring no
  `narrows` rewrote every `refines:` line to `narrows:` and reported success,
  and because an unknown link verb is only a warning (not the `unknown type`
  error that rolls a type rename back) nothing downstream noticed — every edge
  the rename touched had silently stopped being an edge. A link rename onto a
  verb the project doesn't have is now refused up front, before anything is
  written, with the remedy named. A verb counts as known from either end of the
  edge, so `refines: refined_by` is still accepted, and `refdes standard
  upgrade` is exempt so a bundled migration can still rename a verb the current
  version has never heard of (hardware v2's `equivalent` -> v3's `drop_in`).
