- **`refdes index` says what it prints** (docs/design/vocabulary-review.md
  P13, landed as P14 prescribes for a vague name: help text, not a new name).
  `--help` and the first line of its CLI-reference section no longer describe
  the command as "print items.json to stdout without rendering the site" --
  an artifact and a negation -- but as the machine-readable payload editor
  tooling reads: `title`, `version`, `coverage`, `types`, `items` (with their
  fields, links, backlinks, calcs, checks and `file:line`), `next_ids` and
  `diagnostics`, plus `boards`/`workspaces` for a project that declares those
  registries, `threads` for one that has any, and the
  `captured`/`edited_after_captured` pair for items in the captured-history
  store. No behaviour changed: same payload, same exit codes.
