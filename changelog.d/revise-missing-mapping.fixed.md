- `refdes revise <mapping-file>` on a file that doesn't exist (or isn't a
  file, or doesn't parse as YAML) died with a raw `FileNotFoundError` /
  `IsADirectoryError` / PyYAML traceback and exit 1, past the `except
  SchemaError` that turns a bad mapping into the exit-2 the exit-code table
  promises. All three are now refused in `load_mapping`, before the project is
  even loaded, with a one-line `error: no such mapping file: PATH` /
  `error: mapping file could not be parsed: PATH: <detail>` and exit 2.
