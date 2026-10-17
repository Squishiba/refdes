- A newly created project `.gitignore` no longer writes entries git reports
  as already covered (finding R11-F3 of the run-11 release-gate simulation).
  The coverage question ran only on the append path, so a project nested in
  a repository whose root `.gitignore` ignores `.refdes/` got all five of
  init's lines while git read three of them as covered by the root -- and a
  global `core.excludesFile` was out-answered the same way, against #328's
  posture that inside a repository git is the judge. The create path asks
  git the same question now: `check-ignore --no-index` matches a path that
  is not on disk, and the patterns covering a fresh project's files live
  above it (the repository's own `.gitignore` files, `core.excludesFile`).
  Outside a repository nothing is ignored, so all entries are written
  there, as before. When git reads every entry as covered, init creates no
  `.gitignore` at all and prints no `wrote .gitignore` line -- an empty
  file announces nothing.
