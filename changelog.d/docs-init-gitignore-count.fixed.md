- `docs/getting-started.md` no longer counts `init`'s `.gitignore` two ways in
  one sentence. It listed the four patterns `init` writes and then told a
  newcomer with a pre-existing project to "add those three lines" — and the
  antecedent of "those three" was the list of four, so a newcomer could not tell
  whether `.vscode/settings.json` was in scope. The passage now says four, the
  number `refdes init` actually writes, and names the one exception: a pattern
  the file already covers, which `init` does not add a second line for either.
  Finding F4 of `in-prog-logs/user-sim-release-gate-run4.md`.
  `docs/cli-reference.md`'s own "add the three lines by hand" is left as it is:
  its antecedent is the table of the three `.refdes/` paths directly above it, and
  it names all three, so it is not ambiguous the way this one was.
