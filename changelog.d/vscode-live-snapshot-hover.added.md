- **The VS Code extension reads a live `refdes serve` snapshot now — read-only.**
  Hovering an item id gains the three facts only a snapshot carries: its coverage
  stage, its check state (`none` / `pass` / `unknown` / `fail`), and the
  diagnostics attributed to that item — each rendered from what
  `GET /api/item/<ref>` returns, not from anything the extension computes. A
  CodeLens on an item's own `id:` line, **Open in editor**, opens that item's form
  in the browser editor in your system browser. The extension starts
  `refdes serve` itself on first use — one per project per window, killed when the
  window closes — or attaches to one you started: **Refdes: Attach to running
  server** takes the launch URL your terminal prints. That per-launch token is held
  in memory only: never in a setting, never on disk, never in a command line, and
  never in the output channel. A second status bar item names which of the four
  states you are in — `no server`, `starting server`, `snapshot 7`, `server died` —
  with the server's own output one click away. Nothing is written: no field, no
  body, no link, no item file. The browser editor stays the only write path.
  (docs/design/editor-vscode-adapter.md §8, Slice V0.)
