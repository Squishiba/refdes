- **A malformed `page:` now says what to write instead.** `page: '2-4' is not a
  page number -- page: must be a positive integer, counted from 1` was the only
  new diagnostic in the `page:`-check delta that stopped at naming the rule, and
  it is the delta's only *breaking* change — a project whose `page: "14-15"`
  passed yesterday now fails, and it is the first thing an upgrading user meets
  from that delta. It was the only message in the delta that ended without the
  remedy-plus-published-URL shape the rest of it uses, so a user had nowhere to
  go: *I cited pages 2 to 4, what do I write instead?* The answer was
  documented nowhere at all. Now:

  ```
  ERROR   items/decisions/dec-pwr-001-regulator.md:2 [DEC-PWR-001] — citations[0]:
  page: '2-4' is not a page number -- page: must be a positive integer, counted
  from 1. One entry names one page, so a range is one entry per page for the
  same path. See https://squishiba.github.io/refdes/troubleshooting.html#citations.
  ```

  The remedy sentence is chosen by the *shape* of the refused value, because the
  rule is not a remedy on its own for the two shapes where the author believes
  they have cited something. A **range** gets one entry per page for the same
  `path:` — verified to build clean and to render one row and one `#page=`
  fragment per page — and not `section:`, which resolves a heading to the single
  page it starts on and is the citation for a heading that moves between
  revisions rather than for a span. A **printed page number** (`xiv`, `iv`,
  `eight` — a book's front matter is numbered in roman numerals, which is where
  `xiv` usually comes from) is told that `page:` counts the PDF's own sheets from
  1, the number the rendered `#page=` fragment opens. Every message now ends
  `See <url>`, and the shapes the rule already answers on its own (`0`, `-1`,
  `1.5`, `9 9`, empty) get no extra sentence: this fires once per bad `page:`,
  and restating the rule back at the user is noise there. The rule sentence, the
  severity, the load-time refusal, the exit codes and every other citation
  diagnostic are unchanged. The pointer is a new `docs_url.CITATION_PAGE_DOCS`
  (`troubleshooting.html#citations`, the anchor checked against `pages._slugify`
  and against the built `troubleshooting.html`, not guessed), and
  `docs/markdown.md` and `docs/troubleshooting.md` now carry the two shapes.
