- Citations: a negative recorded `page_count:` is a lockfile refusal, so
  every command reading `.refdes/citations.yaml` now says the same thing
  about it (CITE-LOCK-012). The split was loud in opposite directions: a
  record with `page_count: -3` made `refdes fetch` print `page 99 is not in
  this document -- it has -3 page(s)` straight off the record, while
  `_apply_page` read any count below 1 as *no count* and `refdes check` and
  `refdes build` published the citation quietly (exit 0, `0 warnings`) —
  the silence on the command a release gate runs. It is refused at load
  instead: `page_count(data)` is `len(reader.pages)`, never negative, so —
  unlike `page_count: 0`, a real count of a document pypdf opens and finds
  no pages in, which stays sound — a negative count is a line the tool
  never wrote, and one refusal at the reader is what makes `check`,
  `build`, `audit`, `index`, the editor's accept-pins operation, and
  `fetch` (which refuses and leaves the file byte-identical) report one
  diagnostic at one line.
