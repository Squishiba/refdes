- `refdes init` now writes a `.gitignore` entry for the project's
  cross-process write lock, `.refdes-write.lock` at the project root, too.
  `cli.main` runs its commands inside that lock (`serve`, `init`, `new` and
  `schema` exempt, as are read-only runs) and `refdes serve` takes it across a
  save's final revision check and write, so two writers on
  one project cannot write over each other; the file is created empty by the
  first write (not at startup, and not for reads) and carries no state a
  commit could carry to another clone. A project that had written once and
  never been `init`ed by this version saw it as an untracked file in
  `git status` -- the refdes repo's own `.gitignore` has covered it since the
  lock landed, which is the only reason the gap was not reported sooner.
  `init` remains the only writer of a project's `.gitignore`, so an existing
  project still adds the line by hand; the file table in
  `docs/cli-reference.md` and the note in `docs/getting-started.md` say so.
