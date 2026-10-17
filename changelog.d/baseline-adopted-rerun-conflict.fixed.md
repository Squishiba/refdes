- In a project that has run `refdes keys adopt`, re-stamping an existing
  revision/release name with byte-identical content is now recognized as an
  unchanged no-op instead of falsely reporting "different content" and writing
  nothing.
