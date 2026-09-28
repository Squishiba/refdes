- `refdes fetch` on a `source()` line naming a `.pdf` no longer dies with an
  uncaught `TypeError: PdfReader.extract() got an unexpected keyword argument
  'label'`. The pdf reader was never given the `label` keyword the source-reader
  protocol and the CSV reader gained, so every path that reads a cited file's
  source values — fetch, the source-drift warning, and the editor's accept —
  crashed instead of reporting. It reports again: the path is `FAILED` with the
  reader's own reason (a PDF's values are picked from a page's candidates and
  re-extracted from the quoted row), fetch exits 1, and nothing is pinned. No
  value changes and no new capability appears; a PDF is still not a source a
  `source()` line can read.
