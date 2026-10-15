- A `refdes-schema.yaml` type whose name is 11 characters of the key
  alphabet, such as `12345678901:`, no longer crashes `refdes check` with a
  `TypeError` traceback. YAML reads an all-digit name as a number, and the
  config loader was the one loader that did not keep such a scalar spelled as
  written, so the type name reached the schema as an int. It now loads under
  its own name, with the usual three-character prefix (`123`), like every
  other type.
