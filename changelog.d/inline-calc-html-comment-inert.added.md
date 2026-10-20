- **Inline calc spans inside an HTML comment are inert, and an unclosed
  `<!--` is a warning.** A commented-out paragraph is a deliberate act of
  disabling, not a live calc, yet a calc span written inside it was scanned
  like prose: a stale stored result in a comment warned, and an expression
  that cannot evaluate errored, on text the author had written off (finding
  R12-F1 of the run-12 release-gate simulation):

  ```markdown
  The divider is settled: <!-- `Vout := 1 V * 2 = 99 V` --> done.
  ```

  `refdes check` and `build` now skip spans inside `<!-- … -->` comments the
  way they skip fenced code, across lines. An opener that is never closed
  protects nothing — the rest of the body renders as a comment — so it warns
  once at its line and treats the rest of the body as comment text, mirroring
  the unclosed-fence warning. A `<!--` inside a code span, and a `-->` with
  no opener, stay literal; a fence marker inside a comment is comment text
  and a comment opener inside a fence is fence content, each judged by
  whichever scanner is outside.
