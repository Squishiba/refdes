- `refdes calc-rewrite` refused the one line its own build error points it at.
  `check` reports `a tolerance belongs on the right-hand side ... write
  'P = V * I ± 10% | W'; run 'refdes calc-rewrite'`, and running
  `calc-rewrite` on that project failed with `was '' in unit 'W ± 10%', now
  evaluates to '14.4 W' in unit 'W' -- a rewrite must not change what a calc
  computes`. The transactional guard is supposed to skip a line that never
  computed (there is no before-picture to protect), but that skip read
  `result is None` while `CalcLine.result` is a `str` that build.py only
  assigns when a value exists — so an unevaluated line holds the default `""`
  and fell through to the comparison. Both halves of the reported difference
  were artefacts of the line never having computed. The tolerance line is now
  rewritten to exactly the form the build error names, and the post-rewrite
  validation still refuses the whole operation if the rewritten line does not
  compute. A line that *did* compute before is still guarded: a rewrite that
  would change its value still rolls everything back.
