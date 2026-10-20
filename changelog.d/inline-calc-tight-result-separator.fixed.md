- **The result separator in an inline calc span no longer needs surrounding
  spaces.** The `=` that introduces a stored result was required to have
  whitespace on both sides, so a tight spelling — ``x := 1 V*4|V=4 V``, and
  the no-space-equals on each side it implies — was read as a calc missing its
  `= result`, a false error on a valid span (finding R12-F3 of the run-12
  release-gate simulation). The separator is now the last unquoted,
  bracket-balanced `=` whose right side is a stored-result literal, matching
  the ordinary calc line. `:=`, a comparison operator (`==`, `<=`, `>=`, `!=`),
  and an `=` inside quotes or brackets are delimiters, never the separator, so
  they stay in the expression where the evaluator rejects them. A span that
  could be split more than one way as a whole calc is reported as ambiguous
  naming each reading, never resolved silently.
