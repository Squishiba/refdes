- **Changelog entries are now one fragment per change.** `CHANGELOG.md`'s
  `[Unreleased]` section is no longer edited by hand, so concurrent changes no
  longer collide on the same section. Each change that deserves an entry
  contributes `changelog.d/<slug>.<category>.md` (see `changelog.d/README.md`),
  and `python release.py cli <version>` folds the pending fragments into
  `[Unreleased]` and deletes them. What a release will contain is now a
  directory listing instead of a diff.
