- **`editors/vscode/README.md` no longer claims the extension has no test
  coverage.** It does: `tests/test_vscode_extension.py` runs with the project's
  suite and pins the extension's own invariants — the activation marker, the
  `refdes serve:` launch line, the `X-Refdes-Token` header, the item-view facts
  the hover renders, and the ban on a second write path — by reading the
  extension's source and cross-checking it against the server. The earlier note
  had searched `editors/vscode/` for tests, which is the wrong tree: this
  project's extension tests are Python, in `tests/`. The "Developing" section now
  says what the coverage is and what it is not: the real remaining gap is a live
  extension host (`@vscode/test-electron`), which
  `docs/design/editor-vscode-adapter.md` §7.2 defers to whichever slice first
  ships a webview, so the features still have to be exercised in a real VS Code
  instance.
