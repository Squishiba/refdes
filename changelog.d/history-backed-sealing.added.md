- **`sealing: history` — an append-only type backed by captured history
  instead of the build-time lock** (living-notes plan Phase H5). A type-level
  key, `sealing: build | history`, defaulting to `build`: every existing
  project, and the bundled `hardware@3` `log`, keep sealing exactly as before.
  On a `sealing: history` type, a build seals nothing; an edit is never a
  build error (a captured entry gets the `edited after captured` warning);
  a bare `follows:` on an entry a seal file already mentions freezes and is
  captured instead of being refused as "already sealed"; existing seal files
  are read as legacy-seal markers ("recorded hash only; original content was
  not captured") and never rewritten by `build`, `check`, `--reseal` or
  `revise`; deleting an entry one mentions is a
  warning naming the record and the seal file, not an error;
  `build --reseal` says `sealing no longer applies to the '<type>' type;
  nothing was rewritten` and captures nothing. A changed key under a legacy
  seal record stays an error. `audit` marks history-backed rows in "Append-only
  entries edited after sealing" as legacy seals and gains an "Entries edited
  after captured" section. `sealing: history` requires `append_only: true`, and
  a subtype cannot declare it under a parent that keeps the build lock. See
  `docs/design-log.md` § History-backed types.
