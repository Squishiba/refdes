- Serve: the three `POST /api/assets` refusals that share `kind="sealed"`
  (upload *for* a sealed entry, replace of a file a sealed entry references,
  capture of a bare reference a sealed entry writes) carried three
  incompatible `details` row shapes, so a client reading one key on a sealed
  row could find it missing on the other two. Every sealed row now carries
  the same core — `item`, `source_file`, `srcs` (the references naming the
  file in question, empty for an upload *for* the entry), `sealed`, and `why`
  — and a branch adds its own keys on top of the core, never instead of it
  (the capture row keeps `src` and `resolves_to`). Nothing was renamed or
  removed, so readers of the old keys keep working.
