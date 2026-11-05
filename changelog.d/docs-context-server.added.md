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

  Each card now carries three ask buttons (explain / misread / match) answered by
  a local model as a READING AID only: `POST /api/ask` takes nothing but a block
  line, a ref index, and one of the three fixed question names, builds the prompt
  from the server's own current analysis (the browser can never supply prompt
  text), and answers with plain text rendered via textContent. One request at a
  time (409 busy); `--llm-url` (default `http://127.0.0.1:8080/v1`) and
  `--llm-model` control the endpoint, which must be loopback — a non-loopback
  url is refused at startup, before any socket opens, so the prompt never
  leaves the machine.
