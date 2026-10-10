- The documented remedy for a missing kept copy works now. `refdes audit`
  says `cache_missing` / `no copy` for a citation whose lockfile keeps a copy
  whose bytes are gone, and told the reader to "re-run `refdes fetch --path
  <path>` to put them back" — which cannot: an already-pinned path is skipped
  unless `--update` (the same page says so in its `refdes fetch` section), so
  the remedy made no network call, left the blob absent, and printed
  `skipped ... kept` — the same lockfile-flag-only claim to `kept` that PR
  140 had just removed from `audit`, now printed by the command the reader
  was told to run. The doc remedy is now
  `refdes fetch --path <path> --update`, verified end-to-end in
  `tests/test_citations.py::test_a_skipped_kept_copy_with_a_missing_blob_does_not_print_kept`
  (no network and no blob for the plain skip; the blob back after `--update`),
  and a `skipped` fetch line whose kept bytes are not on disk reads `no copy`
  — audit's word for the same fact — instead of `kept`. The pin words a real
  fetch prints (`kept` when its bytes landed, `hash-only`) are unchanged.
