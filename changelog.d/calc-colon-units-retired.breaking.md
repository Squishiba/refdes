- **Breaking:** the `name : unit = expression` calc spelling is retired.
  Any old-spelling line in a project is now a build error that names the
  exact rewrite for that line, and `refdes calc-rewrite` converts a whole
  project in one transactional pass. The one exception: a retired line
  inside a *sealed* append-only entry is reported as a warning instead of
  an error — a sealed entry cannot be edited without resealing, so the
  build refuses to break history it cannot fix. Retired lines still
  evaluate (a sealed entry must keep rendering its numbers, and
  `calc-rewrite` compares every value before and after), so the fix is
  mechanical: run `refdes calc-rewrite`, review the diff, rebuild.
  Misplaced tolerances (`P : W ± 10% = V * I`) report the same way and
  rewrite to `P = V * I ± 10% | W`.
