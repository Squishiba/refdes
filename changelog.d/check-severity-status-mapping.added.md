- A type's `check_severity:` may now be written as a mapping from `status`
  values to severity levels, so the same failing check is reported at
  different levels across an item's life — `candidate: info`,
  `selected: error` — instead of one level per type. The mapping must cover
  every declared status or declare a `default:` fallback; an uncovered
  status, an unknown key, a bad level, or a mapping on a type with no
  `status` field are all load errors naming the fix. Scalar
  `check_severity:` is unchanged, byte for byte: projects that never use
  the mapping form see identical diagnostics, ordering, and exit codes.
  The `info_check_failures` release gate resolves severity per item, so a
  status change alone can move a failing check between the (default-off)
  info bucket and a build-blocking error.
