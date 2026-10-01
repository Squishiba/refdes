- **A citation's `page:` is checked now, in two ways.** It used to be free
  text that nothing validated, ever: `page: "99"` on an eight-page datasheet,
  `page: "0"` and `page: "eight"` all passed `check`, `build`,
  `build --require-citations` and `audit`, showed `ok` in the citations table,
  and published a dead `#page=` fragment into the site.

  A `page:` that is not a positive integer — `0`, `-1`, `eight`, `xiv`, `1.5`,
  `2-4` — is now a **declaration error**, refused at load beside every other
  malformed citation, because no file is needed to know `#page=eight` is not a
  page. It uses the editor picker's own page grammar, now shared rather than
  duplicated (`citations.page_number`, which `serve` also opens pages with), so
  the browser can never open a page the build would have refused to publish.

  A `page:` past the end of the document is checked against the real page count:
  `refdes fetch` counts the pages of the bytes it is pinning, records that count
  in the lockfile next to the sha256 (`page_count:`), and checks every cited
  page for that path while it still has the document open — including pages
  belonging to items outside the run's `--item`/`--path` scope, for the same
  reason a re-pin re-resolves every section. So a `page: "6"` pinned against an
  eight-page datasheet and re-pinned against the four-page revision that
  replaced it is reported at the re-pin — `docs/ds-main.pdf: page 6 is not in
  this document -- it has 4 page(s)` — and at every later `check` and `build`,
  which read the count out of the lockfile and never open a PDF. It is a warning
  naming the citer, escalated to an error by `refdes build --require-citations`,
  the same severity a `section:` that resolves to nothing gets; the pin still
  lands, because the pin is not what is wrong.

  Counting pages needs the optional `refdes[pdf]` extra, so a citation pinned
  without it records `page_count_error:` instead of a count and `check` reports
  the page numbers as *not checked*, with the reason and the command that
  establishes them — the same soft row, and the same words, as a `section:`
  fetched without the extra. A lockfile that records neither key makes no claim
  about its pages (hand-written, or written before this), so nothing is checked
  against it and nothing is reported; the first `refdes fetch` records the
  count. `state` is about the bytes and is unchanged — a citation whose sha256
  is right and whose page is wrong is still `"ok"`, with the page problem in
  `detail`, where a `section:` failure already showed. See
  [citing a datasheet](markdown.md#citing-a-datasheet).