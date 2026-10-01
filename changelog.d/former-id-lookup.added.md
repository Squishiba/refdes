- A retired id is now findable everywhere an item is: `refdes ls` free text
  matches `former_ids:` under the same substring and case rules as ids,
  titles and `tags:`, so `refdes ls REQ-PWR-001` prints
  `NEED-PWR-001  need  The 3V3 rail shall supply 1.2 A continuous. (formerly REQ-PWR-001)`
  instead of "no items match" — before this, `refdes audit` and the built
  `items.json` were the only places that knew where an old id had gone. A
  retired id that has since been reused by a different item resolves to that
  live item, and the item still recording the old one is named in a note
  under the table (that combination is already a build error).
- The built item page lists the item's own former ids under the title, so a
  reader who followed an old id from a schematic or a commit message lands on
  a page that says what it used to be called.
- Hover preview cards carry a **formerly known as** row for a renamed item, and
  so does the VS Code extension's hover (`GET /api/item/<ref>` returns
  `former_ids`; the hover falls back to the index row when no `refdes serve` is
  running). Matches what a prose mention of a retired id has always rendered.