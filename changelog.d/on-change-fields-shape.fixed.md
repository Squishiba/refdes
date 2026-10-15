- An item's `on_change:` mapping with `fields:` written as anything other
  than a mapping — a list, a string, a number, `null` — crashed every
  command that computes a content hash with a raw `AttributeError`
  traceback. It is now a clean load diagnostic naming the file, line and
  the expected shape (`on_change fields: must be a mapping of field name
  to mode ... -- write it as fields: {status: timeline}`); the entry is
  dropped and the rest of the override still applies.
