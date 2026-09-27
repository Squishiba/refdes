- The editor's source picker can now browse a cited PDF. A cited `.pdf`
  appears in the item's source list with `reader: "pdf"` and the page its own
  citation names — `page:`, or the page `refdes fetch` resolved for a `section:`
  and only while that page still belongs to the bytes the lockfile pins — and
  `GET /api/item/<ref>/sources/page?path=&page=` returns one page as positioned
  text: every extracted text run with its coordinates, the rows those runs group
  into, and every number in them as a candidate with the value `fetch` would pin
  for it, its index in the row, and its column-header *guess* (`MIN`/`TYP`/
  `MAX`) labelled as a guess and recorded nowhere. Every number in a row is
  offered and none is chosen, a min/typ/max row included; a page with no
  extractable text, one with no numbers, and one too dense to read all say so
  visibly and offer nothing. Candidates are the reader's own ASCII decimal
  grammar and no other, so the picker cannot offer a value `refdes fetch` would
  refuse. A remote datasheet browses only when the fetch kept its bytes, read
  and checked against its pinned sha256; a hash-only URL citation is refused
  with the fix, because the editor fetches nothing over the network. Reads are
  bounded by named caps (32 MiB per PDF, 200 candidates per page, 1000 text
  runs per page) enforced where the file is read, and no PDF byte and no
  absolute server path ever leaves the process. Read-only: picking and
  accepting a datasheet value are not here yet. Uses the existing optional
  `refdes[pdf]` extra — no new dependency.
