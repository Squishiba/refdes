- `refdes ls --keys` adds a surrogate-key column (each item's key exactly as
  `refdes index` reports it, blank for an item whose key has not been
  minted), and `refdes thread <ref> --keys` prints the header's labels in
  composite `ID@key` form; under `refdes thread --json` every entry now
  carries its `key` (`null` when there is none). The key half of a composite
  `ID@key` pin — what a merge of items files needs — is no longer reachable
  only by scraping the index JSON. Plain `ls` bytes and the plain thread
  view are unchanged: the columns are opt-in.
