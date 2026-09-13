# changelog.d — one fragment per change

Do not edit `CHANGELOG.md`'s `[Unreleased]` section by hand. Each change
that deserves a changelog entry gets one fragment file here, and
`release.py` folds the pending fragments into `[Unreleased]` and deletes
them at release time. What a release will contain is whatever this
directory holds.

## Adding a fragment

Name the file `<slug>.<category>.md` — a short kebab-case slug followed by
one of the categories this project uses (Keep a Changelog's set, with
Breaking first):

- `breaking` — existing projects must change
- `added` — a new feature or capability
- `changed` — existing behaviour changed, non-breaking
- `fixed` — a bug fix
- `removed` — a feature or capability dropped

Example: `citations-field-set.breaking.md`.

The file's content is the changelog bullet(s) for the change, written the
way existing entries are written: for a reader of the project, saying what
changed and what they must do about it. Start each bullet with `- `; no
headings inside the file. Commit the fragment together with the change it
describes.

`README.md` here is documentation and is never folded into the changelog.