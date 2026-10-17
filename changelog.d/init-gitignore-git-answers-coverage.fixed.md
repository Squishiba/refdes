- `refdes init` now asks git itself whether a path is already covered.
  Inside a repository the project's `.gitignore` can carry git's pattern
  language, and init used to miss it: a file pair like `.vscode/*` then
  `!.vscode/*` -- an explicit intent to *track* the editor settings -- was
  invisible to init, which appended its own `.vscode/settings.json` line,
  and git's last-match rule made the appended line win, re-ignoring the
  file its author had just chosen to track. `git check-ignore --no-index -v`
  now answers the question in a repository (with the entry's parent
  directory asked as well, so a `!.vscode/` on the directory is read as a
  position on its contents too), and a winning match of any polarity --
  ignore *or* negation -- counts as the project having decided. Outside a
  repository, and for a git that cannot be run, init's literal spelling
  list answers exactly as before.
