- `refdes init` now writes a `.gitignore` entry for
  `.refdes/serve-write.lock` too. `refdes serve` takes a cross-process lock on
  that file while it saves, so two instances on one project cannot save over
  each other; the file is created empty by the first save (not at startup, and
  not for reads) and carries no state a commit could carry to another clone. A
  project that had saved once and never been `init`ed by this version saw it as
  an untracked file in `git status` -- the refdes repo's own `.gitignore` has
  covered it since the lock landed, which is the only reason the gap was not
  reported sooner. `init` remains the only writer of a project's `.gitignore`,
  so an existing project still adds the line by hand; the file table in
  `docs/cli-reference.md` and the note in `docs/getting-started.md` say so.
