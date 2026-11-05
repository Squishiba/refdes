- **New docs page: the Navis guide.** `docs/navis.md` is the first
  user-facing page for Navis (flying notes): what a Navi is (a one-line
  `<!--navi: …-->` marker, keyless at first, its key minted by the next
  writable command, inert where the renderer treats text as literal), the
  `refdes navis ls|all|show|archive|restore` verbs and the three selector
  forms (full key, unique key prefix, `all` ordinal), the exit codes, and
  the archive states — the byte-identical item after archiving, the frozen
  snapshot and its "marker text has changed" note after an edit, and the
  orphan whose deleted marker makes `restore` refuse. It also covers the
  read-only top-right site panel and the `serve` API
  (`GET /api/navis`, `POST /api/navis/archive|restore`) with its
  status/`kind` table. Every command, response, and byte-identity hash was
  captured from real runs on a throwaway project. Nav, markdown, and
  CLI-reference cross-links added.
