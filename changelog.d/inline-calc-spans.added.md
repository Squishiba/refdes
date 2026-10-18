- A single-backtick code span of the form `` `name := expression | unit = result` ``
  in an item body is now an **inline calc**: `check` and `build` evaluate the
  expression with the ordinary calc grammar and verify the stored result.
  A stored result outside half of its last written place (trailing zeros and
  exponents included) is the warning
  `inline calc <name>: stored result says X, now computes Y`; a missing
  result, an unparseable span, an expression failure, and an incompatible
  stored unit are errors at the span's line. Nothing rewrites the source.
  Inline names share the item's calc scope and source order with fences, and
  `{{name}}` renders them; spans without `:=` are ordinary code, and a
  double-backtick span is never triggered. Calc fences that read cross-item
  values or `source()` keys *only* through inline spans are not yet seen by
  the build's evaluation order or by `refdes fetch` — keep such reads in a
  fence for now. See `docs/math.md`, "Inline calc".
