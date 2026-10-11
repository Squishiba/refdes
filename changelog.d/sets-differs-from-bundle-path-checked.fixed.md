- **A malformed `differs_from:` on a field of a `sets:` entry is a
  configuration error now, wherever it comes from.** Through the bundled
  standard (base or preset, which skip `configcheck`), such a field of a
  set *no type includes* was checked by nothing at load -- it never becomes
  `FieldSpec`s, and the vocabulary page renders raw set dicts -- so it
  surfaced as a raw `dict(42)`-style TypeError/ValueError while *rendering
  the page*. It is now the same load-time SchemaError naming the path
  (`sets.<set>.fields.<field>.differs_from`) that every other
  `differs_from:` gets.
