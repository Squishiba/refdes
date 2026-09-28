- The editor's PDF source picker can now accept a confirmed value from a cited
  local PDF, saving its calc line and lockfile pin together. It records the
  confirmed row's full quote, page and numeric-token index; client-supplied
  numbers and quotes are ignored. `refdes fetch --update` re-locates the row
  across pages by exact, case-sensitive non-numeric text, reports value drift,
  and preserves the old pin if the row is missing, ambiguous or cannot be read
  completely. Changed PDF bytes still require terminal re-pinning. Kept remote
  PDFs remain browsable; `source()` still requires a repo-local file.
