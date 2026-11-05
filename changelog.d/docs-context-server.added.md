- Added `tools/docs_context/server.py`, a read-only local web viewer for the
  references one docs page makes — a maintainer-only tool, not shipped in
  the package, that imports DC-1's `refs.py` and so needs the refdes
  project dependencies: run
  `python tools/docs_context/server.py docs/<page>.md` and open the printed
  loopback URL to see, per block, the code refs, file refs, commands, and
  links the page makes, each with its DC-1 card and a red flag on anything
  broken (missing file, cited line past the file end, missing symbols, broken
  anchor, unknown command). Polls the file's mtime and re-renders in place on
  edits; stdlib only, loopback only, GET/HEAD (every other method is a 405
  JSON), writes nothing. A page edit that touches no command now re-resolves
  in milliseconds: the per-command `--help` cards are memoized per repository
  and verb path, keyed on the CLI source's (mtime, size), so editing
  `src/refdes/cli.py` — the help those cards quote — invalidates them and the
  next resolve re-runs the (list-argv, shell-free) spawns.
