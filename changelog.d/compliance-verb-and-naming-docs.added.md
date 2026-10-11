- Docs: three vocabulary-review fixes, no engine or standard change.
  `docs/links.md` gains a "Which compliance verb?" table for `refines`,
  `derives_from`, `governed_by`, `constrained_by`, `satisfies` and preset
  `met_by`, with the two columns that decide the choice — feeds coverage,
  and changes the target or just points at it — read off the resolved
  `hardware@3` schema and `build.compute_coverage`; it also records that
  the `met_by` preset no longer exists in `hardware@3`, which ships no
  presets at all. `docs/coverage.md`'s "Which links feed coverage" is
  restated with no exception: the suffix never tells you whether a link
  feeds coverage; the type's `satisfying_statuses` and `verifying_statuses`
  do (the legacy authored-`verified_by` spelling is now presented as what
  the rule implies, not as an exception to it). `docs/standard-library.md`
  gains "Three questions before naming a new thing", the pre-naming check
  for anyone adding a word to a standard, preset or project overlay.
  Nothing to do.
