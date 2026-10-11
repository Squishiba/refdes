- **The schema reference stopped claiming a bare `doc:` is a configuration
  error.** The `doc:` section listed "`doc: 42`, `doc: [a, b]` and a bare
  `doc:`" as errors naming the block path, while the `differs_from:`
  section -- three paragraphs later -- said a bare `differs_from:` is *not*
  one, "like a bare `doc:`". The code agrees with the second sentence only:
  YAML null reads as no definition at all (`configcheck.definition` and
  `schema._doc_text` both return `""` for None; a scratch project with a
  bare `doc:` loads and builds fine). The `doc:` sentence now names the two
  wrong-typed shapes as errors and the bare key as not one.
