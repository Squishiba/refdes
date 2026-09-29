- `editors/vscode/README.md` described activation, completion, diagnostics
  and the serve panel as though they were verifiable features, with nothing
  saying otherwise. The extension has no automated or headless test coverage
  -- no `scripts` or `devDependencies` in its `package.json`, no test file
  anywhere under `editors/vscode/`, and the `.vscode-test/` entry in
  `.vscodeignore` names a directory that does not exist (an anticipated
  harness, never built, as `docs/design/editor-vscode-adapter.md` already
  records). The "Developing" section now says in two sentences that verifying
  the surface means exercising it in a real VS Code instance, so a release gate
  is not left to report "no defects found by reading" as if it were "verified".
