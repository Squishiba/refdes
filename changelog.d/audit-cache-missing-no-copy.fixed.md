- `refdes audit` no longer calls a deleted kept copy `kept`. Reproduced by
  fetching a remote citation declared `keep_copy: true`, deleting
  `.refdes/copies/<sha256>.pdf`, and running `refdes audit`: the citation line
  read `cache_missing  kept  cited by CMP-PWR-001`. `cache_missing` was right —
  it is what `citations._resolve` sets precisely because the blob is not a file
  (`src/refdes/citations.py:995-1001`) — but `kept` is this project's word for
  *pinned with the bytes kept at `.refdes/copies/<sha256><ext>`*, and there
  were no bytes. The two columns contradicted each other, which
  `docs/cli-reference.md`'s audit section explicitly promises they never do.
  Such a row now reads `no copy`. The new pin word exists only for
  `state == "cache_missing"`; `unpinned`, `ok  hash-only`, `ok  kept` and
  `hash_mismatch  kept` (the blob *is* there; the state column is what says its
  bytes are wrong) are unchanged. The state column is untouched, so the
  release gate's `missing_kept_copies` rule — which filters on
  `state == "cache_missing"` (`src/refdes/lifecycle.py:577-585`) — still blocks
  a release and still names the item; that is now pinned by a test in
  `tests/test_lifecycle.py` alongside the new assertion in
  `tests/test_citations.py`. `docs/cli-reference.md` documents the fourth pin
  word and the `fetch --path` remedy.
