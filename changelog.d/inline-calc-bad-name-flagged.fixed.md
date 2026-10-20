- **A span whose text before `:=` is not a calc name is now flagged as not a
  calc.** A filename, a range, an option list — ``src=a:=b.csv`` — is prose
  that happens to contain a colon-equals, not a calculation. Because the
  result separator required a surrounding space, its `=` was not the
  separator, so the span parsed as a calc missing its `= result` and the
  author got `stored result missing; write '= <quantity>'` for text they never
  meant as a calc (finding R12-F2 of the run-12 release-gate simulation). The
  text before the first `:=` must now be a calc name; when it is not, the
  span is flagged `'<text>' is not a calc name before `:=`` and the message
  names both ways out — the ``double-backtick`` escape hatch for literal text,
  the `name := expression = result` spelling for a real calc.
