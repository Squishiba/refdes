- `refdes audit` no longer prints `ok` for a citation whose pages could not be
  counted. A `hash-only` row's state column is a statement about the pin, and
  the lockfile knows one more thing than the pin does: whether the document's
  pages could be counted at all, which is what every cited `page:` is compared
  against. Three different outcomes printed the identical
  `ok  hash-only  cited by CMP-001` row — a document whose 8 pages were
  counted, a download too large to open, and a file that is not a PDF at all —
  while `refdes check` warned about the last two. `audit` never mentioned the
  `page_count_error:` the lockfile already held, so the command a release
  reviewer runs claimed a check that had not happened (run-5 gate finding F1).
  Such a row now reads `pages unchecked`, with the recorded reason on the line
  below it:

  ```
  Citations:
    http://127.0.0.1:8899/bad.pdf
      pages unchecked hash-only  cited by CMP-001
        the pages could not be counted, so no cited page number was checked:
        counting a document's pages failed: pypdf could not read the PDF:
        Stream has ended unexpectedly (EOF marker not found)
  ```

  Nothing else moves. The `state` field in `--json` output and the `state`
  table in `docs/output.md` are untouched, because the release gate's
  `missing_kept_copies` rule filters on `state == "cache_missing"`
  (`src/refdes/lifecycle.py`) and this is a report, not a gate. A pin whose
  count *is* on record keeps its `ok` even when a cited page is out of range:
  that page is a separate warning `check` already gives, and the pin itself is
  genuinely fine.
