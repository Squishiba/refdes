- **Every built site gets a `vocabulary.html` page** — one entry per term
  the project's schema resolves to: item types, link verbs, field sets, and
  the engine-reserved keys (`id`, `type`, `key`, `body`, `history`, …). Each
  entry shows the definition written next to its declaration (the `doc:` key
  from `standard-definitions`), its scope, the fields it carries with their
  definitions, and for a type what points at it — computed from the schema,
  including a verb declared under its inverse name. It is generated from the
  *resolved* schema (base standard, presets, then the project's overlay), so
  a preset the build does not enable is not on the page and a type the
  project adds of its own is, with the project's own definition. Project
  terms are not required to define themselves: an undefined term renders
  plainly as "No definition" rather than being left off. The page is
  project-wide like the tree, static — no script of its own — and prints.
  The documentation site carries the same content as a `docs/vocabulary.md`
  page, generated from this repo's pin by `docs-site/gen_examples.py` and
  gated against staleness by the test suite.
