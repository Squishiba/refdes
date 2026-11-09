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
  The loopback rule is literal: only the name localhost and loopback ip
  literals (127.0.0.0/8, ::1) are accepted -- a lookalike name like
  127.evil.com is not -- and redirects from the endpoint are refused, so
  the prompt is never resent to a url the guard did not vet.

  The viewer can now follow the editor's cursor: `POST /api/focus` takes
  `{path, line}` (the same guards as `/api/ask`: the `X-Docs-Context: 1`
  header, own-Origin, 415 on a non-JSON body, a 1024-byte body cap), and
  when the path names the served doc the server resolves the line to its
  block from its own cached analysis and remembers it IN MEMORY ONLY (a
  lock-protected, monotonically increasing seq; nothing is ever written to
  disk); any other path is answered by string comparison alone
  (`{"followed": false, "reason": "other-doc"}`), never opened.
  `GET /api/focus` reports the remembered focus cheaply (never parses), and
  the page polls it on the existing mtime interval: with the default-on
  follow checkbox, the focused block is selected and scrolled into view; a
  manual click wins until the next posted focus; a page opened for another
  doc is never moved.
  (The viewer answers requests on one thread per connection, and
  the focus POST made the analysis cache a second concurrent writer, so the
  cache hit-check, eviction and store run under one lock — two threads
  evicting at the 32-key cap used to race the eviction — while the analysis
  itself stays outside the lock.)
