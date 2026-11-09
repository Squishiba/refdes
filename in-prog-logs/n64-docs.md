# n64 — Navis-in-VS-Code docs + version (S6.4)

Branch `docs/navis-vscode-s64`, based on b3fbc704 (#469, post-#402 gate).
Docs-only slice per docs/design/navis-vscode-panel-plan.md §8 S6.4 and
ratified Q6 (bump here, one publish; Jared publishes — not done here, no
tag). No src/ changes, so the pr-size gate is green by construction (plan §8).

## What changed

- editors/vscode/README.md: replaced the stale "Navis tree (read-only)"
  section with "Navis view" — the real action surface, the one mint
  confirmation, the read-only indicator, and the no-server / --no-write
  table the plan calls for (S6.4 wording). Added the two palette-visible
  Navis commands to the Commands table.
- docs/navis.md: added "In VS Code" between "In the editor" and "The serve
  API" (short, links the extension README, names the serve dependency).
- README.md: Editor support row now names the Refdes Navis view.
- editors/vscode/package.json: version 0.1.0 -> 0.2.0 (only that field, per
  task), and the doubled-colon title fixed:
  before: `Refdes: Navis: Open in editor`
  after:  `Refdes: Open Navi in editor`
  (sibling style: "Refdes: Archive Navi" / "Refdes: Restore Navi", and the
  lowercase "in editor" of the CodeLens command "Refdes: Open in editor").
- tests/test_vscode_navis_polish.py: the ONE test pin on that title,
  `test_package_json_contributes_navis_open_in_editor_hidden_from_palette`
  (~line 926), pinned the substring "Open in editor" and went RED on the
  rename (captured: `assert (True and 'Open in editor' in 'Refdes: Open
  Navi in editor')`). Restyled the pin to prefix + the "in editor" suffix,
  which keeps the style intent. No version pin exists anywhere in tests/
  (grep: only the historical narrative in test_version_flag.py about the
  Python package's old `__version__`).
- changelog.d/navis-vscode-panel.added.md: two bullets, user-visible.
- Plan §8 S6.4: appended the one "landed" line (allowed by the task).

## Claim sources (every doc claim read from code, not memory)

- Labels/placeholders: navisTree.js (`key6 · text`, 120-char truncate +
  tooltip, "Show all (N) archived", the four placeholder strings, orphan
  "marker not found", keyless Mint hint).
- Menus/palette: package.json (Archive on keyed active rows, Restore on
  keyed archived, Mint on keyless rows + view/title key button + palette
  when `refdes.active`, Open-in-editor inline on keyed rows, row commands +
  open-in-editor hidden from palette, `Refdes: Refresh Navis` no palette
  entry = visible; view starts collapsed, `when: refdes.active`).
- Command behaviour: navisCommands.js (no confirmation on Archive/Restore;
  the ONE modal on mint, button "Mint keys"; "refdes serve is not running"
  when no client; keyless Open-in-editor is an information naming the
  missing key; mint log line "open editors of those files reload from disk;
  dirty buffers get VS Code's own prompt"; partial-mint information naming
  `still_keyless`), navisActions.js (result table, LOCKED_HINT),
  extension.js (lock resets on new serve boot and on attach; `$(lock)
  Refdes: read-only` status text with the server's refusal as tooltip,
  re-applied after every index repaint; lazy boot on expand/visible;
  refresh on save via refreshIndex, on serial move, on expand/visible, on
  Refresh index / Refresh Navis; stale-token 403 routed to
  handleServeForbidden + server-died placeholder), serveClient.js (the
  not-running string, navis()/post routes, deepLink).
- `refdes navis --help` and `refdes serve --help` run (venv, absolute
  PYTHONPATH): navis verbs ls/all/show/archive/restore; `--no-write` is the
  global flag (`refdes --no-write serve`, docs/navis.md line 277).

## Verification (all run)

- RED: the polish pin above, before the pin update (assertion output quoted).
- Targeted: `tests/test_docs_anchors.py` + all 8 `tests/test_vscode_*.py` +
  `tests/test_crossplatform_lint.py` = 176 passed (venv python, absolute
  PYTHONPATH=<worktree>/src, -p no:cacheprovider).
- docs.yml checks run offline: `python docs-site/gen_examples.py --check`
  (schema-reference.md + vocabulary.md up to date) and `refdes build` in
  docs-site/ -> "0 items, 0 errors, 0 warnings", site at ../_docs. The
  workflow's pip/checkout/pages steps are CI-only, not run here.
- Full suite ONCE: 6385 passed, 2 skipped, 118 s
  (`-n 4 --dist worksteal`).
- Links added: docs/navis.md links the extension README by absolute GitHub
  URL with `#navis-view` (the anchor test skips `://` links; GitHub
  slugifies "## Navis view" to `navis-view` — not machine-verifiable here);
  root README's existing fragment-less `editors/vscode/README.md` link is
  unchanged in kind.

## Left out (not verifiable here)

- Anything about how the view LOOKS (no real VS Code window): rendering,
  menu placement, icon appearance. The plan's S7 manual checklist is the
  real-window check; publishing is Jared's.
- The GitHub-side anchor above; the marketplace description field (task
  said "only that field" in package.json).

Finished: all six DO items done; nothing left mid-flight.
