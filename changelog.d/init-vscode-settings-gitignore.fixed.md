- `refdes init` now puts `.vscode/settings.json` in the project's
  `.gitignore`, and prints a note when it leaves an existing one alone
  (user-sim release gate run 2, BUG 3). The `yaml.schemas` path in that file
  is absolute deliberately -- `redhat.vscode-yaml` does not reliably scope a
  relative schema path to the workspace folder that declared it, so two refdes
  projects open in one VS Code session could validate one's files against the
  other's schema -- but nothing handled the consequence: the file was left
  looking committable (`git check-ignore .vscode/settings.json` exited 1), and
  committing it bakes one developer's home directory into every other clone,
  where schema completion then fails silently in a file neither tool complains
  about. `init` now appends the entry when it writes the file, creating
  `.gitignore` if the project has none, appending without disturbing anything
  already there, and skipping the write when an existing pattern already
  covers the path (including an explicit `!` negation, which is the author
  having decided). The entry names `.vscode/settings.json`, not `.vscode/`:
  a project's `tasks.json` or `extensions.json` are shareable and worth
  committing -- this repo commits its own. An existing settings file is still
  never overwritten or merged into (`.vscode/settings.json` is JSONC, comments
  are the norm, so a comment-preserving merge is a parser rather than a patch,
  and a merge would write a machine-specific path into a file the author may
  already track); it now gets a one-line note carrying the exact
  `"yaml.schemas"` line to add by hand, with the real absolute path filled in,
  instead of `init` exiting 0 without a word.
- `docs/standard-library.md` showed `"./.refdes/schema.json"` under "refdes
  init writes this for you" while the code emits an absolute path, so the
  documented snippet was the exact form the tool exists to avoid. The example
  now shows the absolute form, with the multi-root schema-resolution reason
  for it and the new `.gitignore` behaviour spelled out alongside; a test
  parses the documented snippet and asserts the key is absolute, so the page
  cannot drift from the code again.
