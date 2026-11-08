# N6.1-tests: red-first contract tests for the read-only Navis tree (S6.1)

Task: write `tests/test_vscode_navis_tree.py` for slice S6.1 of
`docs/design/navis-vscode-panel-plan.md` (the read-only Navis tree in the
VS Code extension). Red-first: tests land before the module they pin.
Branch `feat/n61-navis-tree`, base a8d50f06.

## What the file pins (naming decisions, resolved from the plan)

- Module `editors/vscode/navisTree.js`, pure CommonJS, NO `vscode`/`http`/`fs`
  import (plan says "e.g."; chosen by the serveClient.js/docsFocus.js
  precedent). Exports: TEXT_LIMIT=120, truncateText, navisLabel,
  navisDescription, navisTooltip, navisContextValue, navisBadge,
  navisOpenTarget, createNavisTree(vscode) (host injected, docsFocus.js
  posture).
- Provider surface: itemForRow / childrenFor / childrenOf / placeholderFor /
  badgeFor. Labels `key6 · text` (U+00B7), keyless = text alone; orphan
  description "marker not found" (cli.py's label), keyless "No key yet -- use
  Mint keys" (navis-panel.js KEYLESS_TITLE); tooltips full text, plain
  strings; contextValue tokens refdesNavi[Archived|Keyless]; badge
  counts.active; click-through = definitionProvider arithmetic
  (path.join(root, row.file), line-1, clamped 0); four placeholder states
  (plan S3 literal, S5 warning, checklist 6 "server died", ratified Q7
  "no Navis").
- Wiring pinned by name in extension.js: require("./navisTree"),
  `let navisTree = null;`, `async function refreshNavisTree(boot)` (calls
  serve.navis(), ensureServe on boot), refresh triggers = refreshIndex body
  (save + refdes.refreshIndex), pollServeRevision body (serial),
  onDidExpandElement -> refreshNavisTree(true); createTreeView
  ("refdes.navisTree", {treeDataProvider}); package.json views.explorer
  entry, NO viewsContainers (ratified Q3).
- ServeClient.navis() -> this.request("/api/navis") (shared token-header GET;
  header name pinned from src/refdes/serve/security.py's TOKEN_HEADER).
  Write ban: S6.1 module has no POST, no fs write, no MarkdownString
  (plan S6), no token name (plan S6).

## Live-server half (green by construction, N5a shipped)

Fixture: project with keyed active, KEYLESS active, archived (real
`navis archive` CLI), served read_only=True (the --no-write posture).
Four tests: row shape/counts/order, click-through location fields, token
gate parity with /api/items, no-write serves GET and refuses POST 403
without touching disk.

Difficulty: the first fixture ran the archive CLI with the keyless marker
already on disk -- a writable run mints every keyless marker, so the
keyless row had a key. Fixed by appending the keyless marker AFTER the
archive run.

## Node harness (tests are EXECUTED, not regexed)

LOGIC_DRIVER runs the module under bare node with a fake vscode
(TreeItem/TreeItemCollapsibleState/Uri/ThemeIcon/MarkdownString) and prints
JSON. Validated green against a throwaway reference implementation kept in
`.scratch/n61-ref/` (all 15 logic+live tests pass against it, so the red
tests are red for the right reason: the module is missing, not the harness
being unsatisfiable). Harness fixes found that way: plainify must emit
`command`/`description` as null (JSON.stringify drops undefined), `_joined`
must replace(os.sep), key6 is 6 chars.

## Red/green on the untouched tree

`pytest tests/test_vscode_navis_tree.py`: 8 failed, 4 passed, 10 errors --
the 4 passes are the live-contract tests; every pin of the unimplemented
extension (module, wiring, package.json, ServeClient.navis) is red (fixture
errors = the node driver dying on the missing require).
`ruff check tests/test_vscode_navis_tree.py` clean.
Full suite once: 6104 passed, 2 skipped; every failure/error is in this
file (by design, red-first).

## Not verifiable here

Real VS Code UI (rendering, when-clauses, native tooltips, menus) -- plan
S7.2 says so; pinned at logic/source level only. No PR (task said commit +
push, no PR).

# N6.1-impl: the implementer's pass (2026-11-08)

STATUS: complete. All 22 tests green; neighbours green; full suite
6122 passed / 2 skipped; PR #457 opened. First CI run: ubuntu, py3.13,
pr-size green; windows-latest red on 5 tests, diagnosed:

- `test_click_through_arithmetic...`: the expectation is slash-normalised
  (`_joined`) while `path.join` is per-OS -> the module normalises the
  joined target to `/` (Uri.file/open accept it everywhere; no-op Linux).
- The four label tests: `run_logic_tree`'s `subprocess.run(text=True)`
  decoded the node driver's UTF-8 stdout with the Windows locale codec
  (cp1252), so `·` arrived as `Â·` (reproduced the decode locally). No JS
  string UTF-8-encodes to a lone 0xB7 -- the fix belongs in the harness.

## What landed

- `navisTree.js` -- the pure module, exactly the author's exported
  surface; no vscode/http/fs import, `path.join` only. Two deliberate
  departures from the .scratch reference: the group captures the root at
  childrenFor time so archived children keep the same click-through
  (plan §5); and the word "token" (any case) appears nowhere, as the
  never-names-the-token pin requires (the reference's `tokens` local
  contains it -- it validated only the 15 logic/live tests, not the
  source pins).
- `serveClient.js`: `navis()` -> `this.request("/api/navis")` (shared
  token-header GET; no POST -- S6.2's).
- `package.json`: views.explorer entry `refdes.navisTree`
  (`when: refdes.active`), no icon, no viewsContainers (Q3), no version
  bump (Q6/S6.4).
- `extension.js`: `refreshNavisTree(boot)` (ensureServe on boot = Q5,
  serve.navis(), placeholder per failure) refreshed from refreshIndex
  (save + refdes.refreshIndex, incl. the no-root return),
  pollServeRevision on serial move, onServeExit, and the view's
  onDidExpandElement/onDidChangeVisibility with `refreshNavisTree(true)`;
  ViewBadge behind a `"badge" in view` guard (newer than ^1.85).
- README section + `changelog.d/navis-vscode-tree.added.md`.
- Design fit (not conflict): test_vscode_docs_focus.py activates the
  REAL extension.js under a fake vscode with no
  EventEmitter/TreeItem/createTreeView -- the emitter/view are built in
  `activate` behind a createTreeView-exists guard, TreeItems only inside
  the provider (the fake never drives it).

# N6.1-impl round 1 (review + orchestrator, 2026-11-08)

STATUS: complete; CI all checks green incl. windows-latest.

- HIGH (windows-latest): added `encoding="utf-8"` to the file's one
  `subprocess.run` (a grep found no other text=True reader of node
  output) with the test_editor_live_calc.py rationale, and named it in
  the docstring's cross-platform checklist.
- NITs: `POSIX_ROOT` -> `WIN_DRIVE_ROOT` (the value is a Windows drive
  root); the driver only asks `childrenOf` when the payload has an
  archived group, so no test leans on provider leniency.
- Orchestrator addendum: the views entry carries
  `visibility: "collapsed"` (+ pinning test; Q5: expand = the ask -- an
  expanded-by-default view would boot the child with no gesture) and
  the README says the section starts collapsed. NOT verified against a
  real window: that `visibility` is the accepted property name and that
  first expansion fires the boot (an unknown property is ignored, not
  an error).
