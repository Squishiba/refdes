# navis lock tooltip across index repaints

Task: red-first fix from the N6.3 review (#469). The plan promises the
read-only status bar's tooltip names `--no-write`; `applyNavisLockStatus`
re-applied only the lock TEXT after an index repaint, so a
`refdes.refreshIndex` (the index face repaints the shared status
bar) erased the tooltip until the next refusal. Fix = remember the lock's
tooltip next to the lock's text and re-apply it with the lock's lifetime.

## RED

`tests/test_vscode_navis_lock_tooltip.py` (committed first, 4fd6a17b): a
node harness drives the real `extension.js` against fakes of `vscode` and
`./serveClient` — activating the extension, running commands, observing
the status item. No real VS Code window exists; this is a logic-level
harness, same family as `test_vscode_navis_polish.py`.

Scenarios pinned: a mint refusal locks (text + tooltip name `--no-write`);
the index repaint keeps BOTH (the core pin); a second refusal refreshes
the remembered tooltip; a boot reset (deactivate, re-activate, boot with
payload null, repaint) erases the lock face; re-arming the payload and a
keyed archive refusal re-locks with the new text.

Red on the pre-fix source (HEAD copy of `extension.js`, run, deleted):
the repaint pin FAILS — the tooltip is erased to the index tooltip —
while the other pins PASS. Green after the fix: 4 passed.

## GREEN

`editors/vscode/extension.js`, 12 added lines:

- `let navisLockTooltip = null;` beside the other module state.
- `startServe`'s boot reset clears it (with `navisWriteLock.reset()`).
- the attach path's reset clears it.
- `setNavisWriteStatus` records `text` into it (every lock-setting write,
  keyed and keyless).
- `applyNavisLockStatus` re-applies it: `if (navisLockTooltip)
  statusBar.tooltip = navisLockTooltip;`.

## Checks

- Pin conflict: `test_vscode_navis_polish.py` pins
  `setNavisWriteStatus`'s lock-text write and `applyNavisLockStatus`'s
  existence; the fix keeps both verbatim — no conflict, untouched.
  Neighborhood suites (navis polish, docs focus, crossplatform lint):
  72 passed.
- ruff (E9,F) on the touched test file: clean.
- Full suite: 15 failures in `tests/test_scaffold.py` +
  `tests/test_sealing_optin_note.py` (gitignore `init` tests) on the
  first runs. Triaged to a machine-only cause, not the fix: those tests
  run `refdes init` in pytest basetemp dirs; when the basetemp is nested
  under this checkout, the repo's own `**/.refdes/...` patterns cover
  init's paths (git answers the coverage question per R11-F3), so init
  writes no `.gitignore` and the tests' child-repo `check-ignore`
  assertions fail. CI runs with basetemp under `/tmp`, outside the repo,
  so it is green there; nothing in the fix touches scaffold code. With
  the suite's temp space outside the checkout (the CI shape):
  6423 passed, 2 skipped.

## Status

Finished. Commit = the fix + the test file (harness finalized after the
RED commit: the boot-reset scenario replaced an unlocked-face phase that
pinned nothing new).
