- `refdes init` no longer calls `.vscode/settings.json` gitignored when git
  does not ignore it (finding R11-F2 of the run-11 release-gate simulation).
  The paren in `wrote .vscode/settings.json (gitignored -- ...)` keyed on
  "init wrote the file", never on the coverage answer #328 made init ask git
  for the append decision, so in DOC-REMEDY-018's own shape -- a negation
  like `.vscode/*` + `!.vscode/*` that means the author tracks the file --
  init printed the lie two lines before `git status` showed the file
  committable. The announcement now asks git the same question the append
  decision asks: inside a repository a winning `!` pattern reads as tracked,
  not ignored, and outside one (or with a git that cannot answer) the
  project's own ignore lines answer, a negated line not counting. When git
  does not ignore the file the line reads `wrote .vscode/settings.json (NOT
  gitignored -- ...)` and says what a commit ships. When the only rule
  ignoring the file is machine-local -- the global `core.excludesFile`,
  `.git/info/exclude` -- the paren says so: `(gitignored by a machine-local
  rule only -- the .gitignore line init added makes it ignored for every
  clone; ...)`, because that rule is invisible to every teammate (#328
  review, finding 2). The gitignored case reads exactly as before.
