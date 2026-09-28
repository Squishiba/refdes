- `refdes ls` free text now matches an item's **id** as well as its title and
  `tags:`, so `refdes ls REQ-SYS-001` finds that item instead of answering
  "no items match" — the query most people type right after `refdes id`
  prints one. Substring and case rules are the same as for title and tag
  matching, so a partial or lowercased id (`refdes ls req-sys-0`) works too;
  there is no exact-id-only mode. `ls --help` and the `ls` entry in
  `docs/cli-reference.md` now say the query matches id, title and tags. The
  browser editor's free-text filter is unchanged.
