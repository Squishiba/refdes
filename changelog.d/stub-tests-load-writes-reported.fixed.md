- `refdes stub-tests` now says when its own load rewrote your files, the same
  way `refdes id` does. A run with nothing left to stub printed only "no
  coverable item is missing a verifying test" while the load on the way in had
  already minted `key:` lines and rewritten bare link targets into
  `DISPLAY-ID@key` composites (docs/design/keys.md §2) — your project changed
  and the tool reported a no-op. Such a run now leads with
  `(minted 3 key(s) and rewrote 1 reference(s) while loading)`. Nothing about
  when minting or expansion happens changed: a steady-state project, and every
  `--no-write`/`--dry-run` run, print exactly what they printed before.
