- **`component`'s `equivalent` link verb is now `drop_in`** — the pair that
  records interchangeability between two parts is now `drop_in` (no review
  needed) and `alternate` (functionally close, check before substituting).
  `equivalent` reads as the weaker of the two — "sort of equivalent" — which
  is backwards from what the verbs mean: the one that used to carry that word
  is the one that needs no review at all, and the difference between them is
  safety-adjacent, so the unambiguous industry phrase goes on the verb that
  means a part may be swapped without anyone re-checking it. Nothing else
  about the pair changes: both stay self-inverse, declared on `component`,
  restricted to `component` targets, and `alternate`'s required `rationale`
  is untouched. `refdes standard upgrade --to 3` rewrites every `equivalent:`
  line in a hardware@2 project automatically. A project pinned at
  `hardware@3` that still writes `equivalent:` fails the build with an error
  naming `drop_in` — an unknown link verb is normally only a warning, and an
  edge that silently stops being an edge is exactly the thing that must not
  pass quietly; the targets are still applied under the new name in the
  failing build, so nothing else in the report cascades off their absence.
  `hardware@1` and `@2` are untouched and keep spelling it `equivalent`. (The
  bundled `hardware@3` is itself unreleased — a project pinned at `v1` or `v2`
  sees none of this.)
