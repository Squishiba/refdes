- The sealing opt-back-in note now prints once, not on every run (run-6a
  F10). `refdes check`/`refdes build` of a project whose `refdes-schema.yaml`
  opts a type back into build sealing used to print
  `note: refdes-schema.yaml opts the 'log' type back into build sealing -- ...`
  on every invocation — "a permanent one-liner in every CI check log
  [that] trains people to skim notes". It now prints when the decision is
  news: the first run after the opt-in appears, and again when the set of
  opted-in types changes (removing the overlay is recorded, so re-adding it
  prints again) — the same posture as the `.refdes/schema.json ... refreshed`
  note, with the announced set recorded in
  `.refdes/sealing-optin.json`, gitignored per-checkout state: `refdes init`
  adds it to a new project's `.gitignore` beside the `.refdes/schema.json`
  entry. A `--no-write` (or `build --dry-run`) run
  prints by the same rule and records nothing, so the next writable run
  still prints; `--verbose` always prints. The note's text, its stderr home,
  and its silence in the counts and exit codes are unchanged.
