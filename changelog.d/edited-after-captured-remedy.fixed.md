- The `edited after captured` warning now says what to do about it. It used to
  name the entry and the capture event and stop there, while the
  `sealing: build` error it replaced for the same edit ended with the advice
  that actually applies -- `Append a new entry with `amends: [LOG-001]`
  instead`. A reader told their append-only log was edited, in the one tool
  that can tell them, was not told how an append-only log is edited. The
  warning now carries that sentence (the `amends:` half only: `--reseal` is
  not an escape for a history-backed type, where `build --reseal` says it has
  nothing to do) and a link to the page that already documents it,
  `docs/troubleshooting.md`'s `## The design log`. Trigger logic, level, and
  exit code are untouched -- it is still a warning that never fails a build.
