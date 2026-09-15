- Baseline comparisons no longer report un-migratable older-format entries as
  `changed`. An entry whose stored hash doesn't match the item under its own
  recorded hash format proves only that refdes *can't tell* whether the content
  moved or just the hash definition — `refdes audit` now lists those ids on an
  `uncomparable N` line instead of folding them into `changed` (and never
  counts them as unchanged), and `refdes revision`/`refdes release` name them
  in the conflict output when re-stamping an existing name. Projects with no
  such entries see byte-identical output. What to do with one: review the
  item's content, then stamp a new baseline.
