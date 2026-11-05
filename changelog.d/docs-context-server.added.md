- Added `tools/docs_context/server.py`, a read-only local web viewer for the
  references one docs page makes: run
  `python tools/docs_context/server.py docs/<page>.md` and open the printed
  loopback URL to see, per paragraph, the code refs, file refs, commands, and
  links the page makes, each with its DC-1 card and a red flag on anything
  broken (missing file, cited line past the file end, missing symbols, broken
  anchor, unknown command). Polls the file's mtime and re-renders in place on
  edits; stdlib only, loopback only, GET only, writes nothing.
