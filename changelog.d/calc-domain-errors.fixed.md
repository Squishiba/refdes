- `refdes build` crashed with an unhandled `TypeError` on a calc line that left
  the reals, instead of reporting a calc error. `v = sqrt(-1)` in a ```calc fence
  is the reported case: pint answers a negative argument with a *complex*
  Quantity rather than raising, so evaluation succeeded, the value was recorded,
  and the build then died inside the formatter with `float() argument must be a
  string or a real number, not 'complex'` — a traceback naming no file, no line,
  and no square root. Every other route out of the reals is now a diagnostic on
  the line that asked for it, in the same shape as any other calc error, and the
  build reports and exits 1 as usual: `sqrt()` of a negative value, `ln()` or
  `log10()` of zero or a negative value, an `exp()` that overflows a float, and a
  fractional power of a negative (which used to raise a bare
  `TypeError: '<' not supported between instances of 'complex' and 'complex'` from
  the interval comparison). The domain is checked on every corner of a tolerance
  range, not just the nominal value: `5 ± 6` is `[-1, 11]`, so `sqrt(v)` is now
  rejected on its low bound instead of crashing in `format_bounds`. Formatting a
  value the evaluator already accepted is now guarded at the same place, so a
  failure there is reported on its line rather than aborting the command.
