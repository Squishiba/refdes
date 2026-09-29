- **The server facts the VS Code extension depends on are now pinned in CI.**
  `tests/test_vscode_adapter_contract.py` adds the ten contract tests
  `docs/design/editor-vscode-adapter.md` §7.1 names, so a server change that
  would break the extension fails in the test suite instead of in a window: the
  exact `refdes serve: http://127.0.0.1:<port>/?token=<t>` first stdout line and
  the credential it carries; the launch token's absence from the child's command
  line; the token gating reads as well as writes; an `Origin`-less and a
  mismatched-`Origin` mutation both refused; every field of `GET /api/item/<ref>`
  reporting its own editability, with a sealed log entry and an imported item
  read-only and explained; a 409 conflict carrying `current_text` and `diff`
  without touching the file; `--no-write` refusing every mutation route; the
  editor's `frame-ancestors 'none'`; and the deep link the preview toolbar
  injects matching the one the extension's "Open in editor" builds. Two of them
  spawn the real CLI as a subprocess; the rest drive a live `EditorApp` over real
  sockets. No server behaviour changes.
