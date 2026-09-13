- **Calc blocks can call named equations the project defines** (new
  `equations:` block in `refdes.yaml`, documented in `docs/math.md`), so a
  formula is written once and reused instead of retyped per output, per
  rail, per input: declare
  `current_limit: {params: [K, V, R], expr: K * V / R}` once and call
  `current_limit(2500, 0.8 V, 3.3 kohm)` from any calc block on the site.
  Calling one is not a new evaluator — arguments bind to `params` and the
  body evaluates exactly as if written inline, so units come from the
  arguments (`V / kohm` returns amps, and passing a mass where a resistance
  belongs is an ordinary dimensionality error at the call site) and
  tolerances propagate as usual, whether carried by an argument or attached
  to the result. `note:` on each equation is provenance (a datasheet page,
  an application note) for whoever maintains it; nothing reads it at build
  time. The namespace is project-wide, like `units:`. Three rules: an
  equation may call another equation, but a cycle is a build error naming
  the path that closes it (`equation cycle: a -> b -> a`); an equation
  cannot shadow a built-in (`sqrt` has to mean one thing everywhere, so
  redefining it is rejected, not silently preferred); and arity is checked
  against `params` by the same call path that checks built-ins, so
  `current_limit() takes 3 argument(s) (K, V, R), got 2` reads like any
  other call error.