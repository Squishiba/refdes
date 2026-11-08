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

STATUS: complete on Linux; CI: ubuntu green, windows red on 4 tests of
this file only -- harness bug, reported below, implementer cannot fix it.

## Windows CI finding (PR #457)

- `test_click_through_arithmetic...` failed on Windows: the expectation is
  slash-normalised (`_joined`) while `path.join` is per-OS. Fixed in the
  module: the joined target is normalised to `/` (Uri.file/open accept it
  everywhere; a no-op on Linux).
- `test_top_level_rows...`, `test_show_all_children...`,
  `test_labels_are_truncated...`, `test_hostile_row_text...` fail on
  Windows only: `run_logic_tree`'s `subprocess.run(text=True)` decodes the
  node driver's UTF-8 stdout with the Windows locale codec, so `·` arrives
  as `Â·`. Unfixable from the module (no JS string UTF-8-encodes to a
  lone 0xB7); proposed test fix: pass `encoding="utf-8"` to `subprocess.run`.

## What landed

- `editors/vscode/navisTree.js` -- the pure module, exactly the author's
  exported surface (TEXT_LIMIT, truncateText, navisLabel, navisDescription,
  navisTooltip, navisContextValue, navisBadge, navisOpenTarget,
  createNavisTree). No vscode/http/fs import; `path.join` only. Kept the
  reference module's shapes, with two deliberate departures:
  - `childrenOf` resolves the group's rows AND the root captured at
    childrenFor time, so archived children get the same click-through as
    top-level rows (the .scratch reference passed an undefined root and
    dropped the archived rows' command -- untested by the pins, plan §5
    wants the click to survive).
  - the word "token" (any case) appears nowhere in the module, as the
    never-names-the-token pin requires. The .scratch reference used a
    `tokens` local, which contains it -- that reference validated only the
    15 logic/live tests, not the 7 source pins; the shipped file passes all
    22.
- `serveClient.js`: `navis()` delegating to `this.request("/api/navis")`
  (shared token-header GET; no second http path, no POST -- S6.2's).
- `package.json`: `contributes.views.explorer` entry
  `refdes.navisTree` ("Refdes Navis", `when: refdes.active`), no icon, no
  viewsContainers (ratified Q3). No version bump (Q6/S6.4).
- `extension.js`: require + `let navisTree = null`,
  `async function refreshNavisTree(boot)` (ensureServe on boot = ratified
  Q5, serve.navis(), placeholder per failure), refresh from refreshIndex
  (save + refdes.refreshIndex; also the no-root early return), from
  pollServeRevision on serial move, from onServeExit, and from the view's
  onDidExpandElement/onDidChangeVisibility with `refreshNavisTree(true)`;
  `createTreeView("refdes.navisTree", { treeDataProvider })`; badge set
  behind a `"badge" in navisView` guard (ViewBadge is newer than the
  ^1.85 engine floor).
- README: a "Navis tree (read-only)" section; changelog fragment
  `navis-vscode-tree.added.md` (read-only list, actions come next).

## The one design point the tests forced (not a conflict, a fit)

tests/test_vscode_docs_focus.py activates the REAL extension.js under a
fake vscode that has no EventEmitter, no TreeItem and no
window.createTreeView. So the emitter and view are created in `activate`
behind `typeof vscode.window.createTreeView === "function"`, and
TreeItems are built only inside the provider (which the fake never
drives). No test edited; no src/ change; the pins' regexes all match
inside the guard.

## Red -> green

- Red before the change: `8 failed, 4 passed, 10 errors` (matches the
  author's baseline exactly).
- Green after: `22 passed`.
- Neighbours: test_vscode_extension.py + test_vscode_adapter_contract.py +
  test_vscode_docs_focus.py + test_crossplatform_lint.py: `90 passed`.
- Full suite once: see the PR's CI (ubuntu+windows) -- all checks green.
- `node --check` clean on extension.js, navisTree.js, serveClient.js.
- ruff: no .py file touched.

## Not verifiable here

Same as the author's note: no real VS Code window existed, so view
rendering, `when` clauses, menus, native tooltips and the real vscode API
are verified only at source/logic level; the plan's manual checklist
(items 1, 2, 6 for S6.1) is Jared's.
