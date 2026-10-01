- `refdes fetch` now warns about a large download instead of saying nothing at
  all. A remote citation fetched over 100 MB (`FETCH_SIZE_WARN_BYTES`) prints
  one `WARNING` line naming the citation, the size it turned out to be, and
  where the bytes went — the kept copy's `.refdes/copies/<sha256><ext>` path,
  or that no copy was kept. Nothing is capped and nothing is refused: the pin
  still lands, the summary still says `0 failed`, and the exit code is the one
  a small fetch produces, because a datasheet is allowed to be enormous. Before
  this, `fetch_bytes` was one `urlopen` and one `resp.read()` with no
  `Content-Length` inspection and no bound of any kind, so a 26 MiB
  octet-stream was pinned in 0.49 s and reported like any other pin. The size
  is measured on the bytes actually received rather than the `Content-Length`
  header, because the received length is the length of the pin (what was
  hashed, what `bytes:` records, what a kept copy was written from) and a
  chunked response carries no header at all. There is therefore also no
  pre-download cap: a large body is read into memory before the warning
  appears, and there is no content-type check — what a citation's bytes are is
  the author's decision. `refdes check --refresh` is not covered; it pins
  nothing and keeps no copy. `docs/cli-reference.md` documents the threshold,
  the warning, and the 30-second per-operation socket timeout, which no docs
  page mentioned before.
