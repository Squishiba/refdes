- `refdes init` now writes a `.gitignore` covering `.refdes/copies/` and
  `.refdes/schema.json`, not just `.vscode/settings.json`. Three places in the
  docs promised those two were gitignored and nothing in the product made them
  so: in a project `refdes init` had just created, `git add -A` staged a 6 MB
  copyrighted datasheet and a 1696-line generated schema, both still stageable
  (nothing `init` writes addresses them). `init` is the only writer of a
  project's `.gitignore`, so it is also the only place this could be fixed --
  appending, idempotently, one commented block per path, taking the file's own
  line ending, and skipping any path some existing pattern already covers
  (including an explicit `!` negation). The patterns name the one file or the
  one subdirectory rather than `.vscode/` or `.refdes/` wholesale: both
  directories hold things that are yours to commit. They carry no leading `/`,
  which makes them work whether the project is a repository root or one
  subdirectory of a larger repository (git resolves a pattern containing a
  slash away from its end relative to the `.gitignore`'s own directory).
  `init` now also announces the `.gitignore` it wrote or appended to, naming the
  paths it actually added -- and stays silent when it added none. An existing
  project keeps whatever `.gitignore` it had: `docs/cli-reference.md`'s file
  table, `docs/markdown.md` and `docs/standard-library.md` now say to add the
  two lines by hand.