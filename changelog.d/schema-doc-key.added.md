- **`doc:` is a recognised definition key in the schema** — a type, a field, a
  field-set entry, or a link type may now carry its own prose definition next to
  its declaration, in the bundled standard or in a project's
  `refdes-schema.yaml`: `doc: A statement of the heat a board is allowed to
  produce.` The value must be a non-empty string; a number, a list, a mapping or
  a bare `doc:` is a configuration error naming the block path, and a misspelled
  `docs:` is the unknown-key error every other config key already gets. A
  declared definition reaches the editor through the exports that already exist
  — `.refdes/schema.json` carries it as the JSON Schema `description`, so
  vscode-yaml shows it on hover and in completion, and `items.json`'s `types`
  payload carries it as `doc` on the type and on each field. Nothing is required:
  a project that declares no `doc:` keys gets byte-identical `schema.json`,
  `items.json` and site output to the ones it got before the key existed. This
  is the first chunk of the generated vocabulary reference (design finding 38) —
  the key only; the definitions for every `hardware@3` term, the completeness
  lint, and the generated SVG diagram are the chunks after it.
