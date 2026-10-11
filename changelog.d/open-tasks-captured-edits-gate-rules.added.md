- Two new release-gate rules, both off by default (living-notes plan
  §H8): `open_tasks` blocks a release while any thread tip carries an
  open author task — it reads the same task fold `refdes thread`
  reads, so a forked thread counts every open tip, a fold that
  refused between differing equal-distance lists blocks too as a
  conflicting list, and derived worklist rows (an uncovered
  requirement, a failing check) are never counted as tasks because
  each is already its own rule. `captured_edits` blocks a release
  while any item's current content differs from its captured
  snapshot — the same fact the "edited after captured" warning
  prints, read from the history store, never recomputed. Both are
  declared like every other rule: entries in the `release_gate:`
  defaults of `{release: false, revision: false}`, enable-able per
  project through the existing overlay, with the same unknown-name
  rejection. A default project's stamped baseline gains exactly two
  `skipped` lines in its `gate:` block; nothing else about stamping
  changes. (docs/lifecycle.md)
