# vscode-beta-label

Task: label the VS Code extension (editors/vscode, 0.2.0 — version untouched)
BETA before Jared publishes it.

## Done

1. `editors/vscode/package.json`: added `"preview": true` (top-level, after
   `version`). Source for the flag: installed `@vscode/vsce` from npm into
   `.scratch/vsce/` and read `out/package.js:308-309` —
   `if (manifest.preview) { flags.push('Preview'); }` — i.e. the manifest
   field sets the gallery `Preview` flag, which is what shows the Preview
   badge on the Marketplace. The vsce README itself does not document it.
2. `editors/vscode/README.md`: blockquote Beta note after the intro
   paragraph — Navis view (tree, archive/restore/mint, Mint keys row,
   read-only indicator, Open in editor) verified by automated tests against
   `refdes serve`, not yet by hand in a VS Code window; links the issue
   tracker from package.json `bugs`
   (https://github.com/Squishiba/refdes/issues).
3. `release.py` untouched.
4. Pins: grepped tests/ for package.json / README references. The vscode
   tests (extension, navis_commands, navis_polish, navis_tree, docs_focus,
   adapter_contract, navis_actions, extension_http_client, post_body,
   navis_lock_tooltip) read `contributes.*` keys and `activationEvents`
   only — no top-level-key-set pin, no README content pin. Ran all ten:
   152 passed. No conflict, so the PR was opened.

## Notes

- The note shifts `editors/vscode/README.md` line numbers; the line-range
  citations in `docs/design/editor-vscode-adapter.md` (109-110, 113-116)
  drift by 6 lines. Not fixed here (out of scope; no test pins them).
- Changelog fragment: `changelog.d/vscode-beta-label.changed.md`.
- PR-size gate: 0 added src/ lines.

## Verification

- Red/green: none — no behavior change, so no new tests; the ten existing
  vscode test files are the guard (152 passed, above).
- Full suite: see final reply (run once before pushing).
