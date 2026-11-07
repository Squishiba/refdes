- `refdes fetch` (plain and `--update`) now says which `values:` keys it
  removes. A key of a citation's lockfile record that no `source()` span
  references any more is pruned -- that has always been the record's
  documented shape, exactly the keys in use -- but the removal was silent: a
  key added by hand next to the pins was gone with no word, and `check` said
  nothing about it. Each removed key now gets one
  `source: dropped <path>: <key>` line naming the cited file and the key, on
  a run that still exits 0. A run that prunes nothing prints nothing new, and
  nothing about what is written to the lockfile changed.
