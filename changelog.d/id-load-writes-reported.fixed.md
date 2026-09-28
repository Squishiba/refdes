- `refdes id` now says when its own load rewrote your files. A run with
  nothing left to allocate printed only "no items are missing an id" while the
  load on the way in had already minted `key:` lines and rewritten bare link
  targets into `DISPLAY-ID@key` composites (docs/design/keys.md §2) — three
  lines of your project changed and the tool reported a no-op. Such a run now
  leads with `(minted 2 key(s) and rewrote 1 reference(s) while loading)`.
  Nothing about when minting or expansion happens changed: a steady-state
  project, and every `--no-write`/`--dry-run` run, print exactly what they
  printed before.
