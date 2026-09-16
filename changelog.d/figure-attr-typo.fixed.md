- An unknown attribute name in an image's `{...}` suffix now warns wherever
  the suffix lands. A mistyped `{widht=60%}` on a captioned figure previously
  did nothing at all, in silence; it now reports
  `'widht' is not an image attribute and is ignored` against the file, line,
  and item id, and the figure still renders everything it does understand.
  `width`, `caption` and `id` are unchanged — a correct suffix is still silent,
  and the rendered HTML of every valid figure is byte-for-byte what it was.
