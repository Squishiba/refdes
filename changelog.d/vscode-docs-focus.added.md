- The VS Code extension can now drive the docs-context viewer
  (`tools/docs_context/server.py`, DC-4a) to follow the editor cursor. The
  new setting `refdes.docsContext.url` (default `""` = off, no network call
  at all) names the viewer's url; with it set, cursor moves in a file inside
  the workspace are debounced (~300 ms) and posted to `<url>/api/focus` as
  `{path, line}` — the workspace-relative path and the 1-based cursor line,
  and nothing else (never file contents, never selection text). Loopback
  urls only (`127.0.0.1`, `localhost`, `::1`): any other host is ignored
  with one line in the Refdes output channel, so file paths never leave the
  machine. The posts are fire-and-forget — failures yield at most one
  throttled output-channel line and never a popup, an in-flight post is
  never stacked behind a slow viewer, and clearing the setting stops
  posting immediately.
