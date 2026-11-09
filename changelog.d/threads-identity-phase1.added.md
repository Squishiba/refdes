- An item with no `id:` but a non-empty `follows:` link is no longer pending — it's a real project member from the moment it parses: hashed, sealed, coverage-eligible, and rendered to its own page at `<key>.html` (docs/design/threads.md §2, Phase 1). `follows:` is
declared by the bundled `hardware@3` standard (see the `follows` entry in
these notes), so a `hardware@2` project sees this only when its own schema
declares a link literally named `follows:`; nothing about a project's
existing schema changes.
