- **A scalar written for a list-shaped field is now a build error.** `tags:
  "power, analog"` -- a quoted string where a `[power, analog]` list belonged
  -- used to build clean: `refdes check` reported `0 errors, 0 warnings` and
  exited 0, and the value was stored as the *single* tag `"power, analog"`
  rather than two tags. Nothing downstream could tell the difference, and
  neither could a reader: `refdes ls --tag analog` still "found" the item,
  because tag matching is a substring test, so the wrong value looked right
  everywhere it could be looked at. A field declared `type: list` (or
  `checks`, `citations`, `options`) that receives anything other than a YAML
  list is now refused by name, by type, and with the value that was found:
  `field 'tags' is a list field, but it was given a string 'power, analog' --
  write it as a list, one entry per value (tags: [first, second])`. The value
  is never split on a delimiter: a comma guess is right for `"power, analog"`
  and silently wrong for a tag that legitimately contains a comma. The
  browser editor's create form already refused exactly these fields with
  exactly this reasoning, and now the loader and the editor share one
  constant (`model.NON_SCALAR_FIELD_TYPES`) rather than two copies of the
  same list. A link verb is unaffected and stays lenient: `satisfies: REQ-001`
  as a bare scalar is one target, one edge, and loses nothing. A project that
  has a scalar on a list-typed field today will now fail to build until the
  field is written as a list -- which is the whole point, since the value it
  was building with is not the value it looks like.
