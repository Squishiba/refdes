- **`sealing: history` — an append-only type backed by captured history
  instead of the build-time lock** (living-notes plan Phase H5). A type-level
  key, `sealing: build | history`. The bundled `hardware@3` `log` declares
  `history`, so a `hardware@3` project's log entries are no longer sealed (a
  project can opt its log back into the lock with `types: log: sealing:
  build` in `refdes-schema.yaml`); `build` stays the default for every other
  type, and `hardware@1`/`hardware@2` are untouched. On a `sealing: history`
  type, a build seals nothing; an edit is never a
  build error (a captured entry gets the `edited after captured` warning; an
  entry never captured gets the `edited while uncaptured` warning while a
  legacy seal record still holds its prior hash, and nothing when no record
  names it);
  a bare `follows:` on an entry a seal file already mentions freezes and is
  captured instead of being refused as "already sealed"; existing seal files
  are read as legacy-seal markers ("recorded hash only; original content was
  not captured"), whose records `build`, `check`, `--reseal` and `revise`
  never change or delete -- though a seal file shared with a type still on
  `sealing: build` is re-serialized whole when that type legitimately writes
  to it, so its bytes (e.g. an old header) can change with the legacy records'
  data intact; deleting an entry one mentions is a
  warning naming the record and the seal file, not an error;
  `build --reseal` says `sealing no longer applies to the '<type>' type;
  nothing was rewritten` and captures nothing. A changed key under a legacy
  seal record stays an error. `audit` marks history-backed rows in "Append-only
  entries edited after sealing" as legacy seals and gains an "Entries edited
  after captured" section. `sealing: history` requires `append_only: true`, and
  a subtype cannot declare it under a parent that keeps the build lock.
  Switching a type to `history` -- including picking up this default for
  `log` -- has one surprising side effect: a retired calc unit
  spelling inside an existing (formerly sealed) entry, which was only a
  warning because the entry could not be fixed without resealing, becomes a
  `retired_unit_spelling` build error -- and `refdes calc-rewrite`,
  which skipped sealed entries, now rewrites it. See `docs/design-log.md` §
  History-backed types.
