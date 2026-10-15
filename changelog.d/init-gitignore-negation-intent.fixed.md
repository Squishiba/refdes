- `refdes init`: a project whose `.gitignore` speaks of the settings file in
  git's own idiom is taken at its word. The "a pattern already covers this
  path" check used to be a literal whole-line whitelist, so it recognised
  neither a `.vscode/*` glob, nor a bare-basename `settings.json`, nor — the
  harmful one — a `!.vscode/*` negation, which is an explicit intent to
  *track* the file. Git takes the last matching pattern, so init appending
  its own `.vscode/settings.json` line at the end out-ranked that negation
  and left the fresh settings file un-addable. Inside a git repository,
  `git check-ignore --no-index -v` is now asked what the project's own
  `.gitignore` (its parent directory included, for a negation written on the
  directory) says about the path, and only a winning match from that file
  counts; outside a repository, where nothing is ignored in the first place,
  the literal set answers, widened to the basename and one-level glob
  spellings. The read-only `.gitignore` preflight asks the same question as
  the append, so a tracked-by-negation settings file keeps a read-only
  `.gitignore` from becoming a refusal reason, and a read-only
  `.gitignore` missing an entry is still refused by name (the #231 behavior).
