- A hand-deleted `key:` line is reported once. `refdes check` and `refdes build`
  printed the same `key deleted since baseline 'r1': was '…', now no key is
  declared.` twice for one item — once as an ERROR, from `keys._validate_deleted_keys`
  during the build, and once as a byte-identical WARNING, from `keys.report_deleted_keys`
  during the load's minting step, both from the same `deleted_key_records()` and the same
  `deleted_key_message()`. The run's own tally (`3 errors, 2 warnings`) counted one broken
  key as two findings. The ERROR is the one the standard's Layer-4 table in
  `docs/design/keys.md` calls this — "no item declares `K`; an item with display id `D` has
  no key | **key deleted — error**" — so the load-time warning is gone and the error stays
  exactly as it was, with the old key, the record it came from, and both remedies. Nothing
  else was reporting it: `refdes audit` and `refdes ls` print neither level of it today,
  because they print only the load errors captured before `build()` runs. Minting still
  leaves the item keyless — that protection lives in `missing_assignments()`, not in the
  removed warning.
