- Editor: the link picker now offers candidates for a verb declared with an
  empty target-type list. `links: {verb: []}` means unrestricted everywhere
  the server reads it -- `Project.accepts_type` ("an empty list is
  unrestricted"), `build.resolve_links` (no type check), and the editor's
  link gate ("accepts any declared type") -- and the standard itself
  declares such a verb: `log.blocked_by: []` in hardware@3. The picker was
  the exception: `links.js` built one `/api/items?type=` query per declared
  type and issued none at all for an empty list, so the verb rendered
  "no candidates match" -- a picker offering nothing for a link the server
  accepts to every item. An empty list now fetches the unfiltered
  `/api/items`, so the picker offers exactly what the server accepts; verbs
  with declared target types keep their filtered per-type queries. The
  picker now also asks the list API for its full page (the server's
  5000-row maximum, not the default 500) and labels a list that even that
  page truncates ("showing N of M targets"), so a candidate list never
  silently hides valid targets.
