- An `imports:` artifact that is not valid UTF-8 is now the same clean
  `import <name>: could not read <path>: ...` error as a missing file or
  unparseable JSON, not a raw `UnicodeDecodeError` traceback: `json.load`
  decodes lazily, and the read only caught `OSError` and
  `json.JSONDecodeError`.
