- A newly created project `.gitignore` no longer writes entries the
  project's own `.gitignore` files already cover (finding R11-F3 of the
  run-11 release-gate simulation). The coverage question ran only on the
  append path, so a project nested in a repository whose root `.gitignore`
  ignores `.refdes/` got all five of init's lines while git read three of
  them as covered by the root. The create path asks git the same question
  now: `check-ignore --no-index` matches a path that is not on disk, and
  the patterns covering a fresh project's files live above it -- the
  repository's own `.gitignore` files. Git's answer is read for those
  shared rules only: a match from the machine's global `core.excludesFile`
  or the clone's `.git/info/exclude` is one checkout's configuration, not
  the project's position, and init writes the entry so every clone gets
  the ignore (#328 review, finding 2). Outside a repository nothing is
  ignored, so all entries are written there, as before. When git reads
  every entry as covered, init creates no `.gitignore` at all and prints
  no `wrote .gitignore` line -- an empty file announces nothing.
