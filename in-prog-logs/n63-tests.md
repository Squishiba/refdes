# n63-tests — S6.3 contract tests (freshness polish + secondary actions)

Slice N6.3-tests of docs/design/navis-vscode-panel-plan.md, plus the two
items the S6.2b-2 review deferred (lock text surviving the index repaint;
the Mint log line). TEST AUTHOR ONLY: wrote ONE new file,
tests/test_vscode_navis_polish.py (24 tests). No editors/ file touched, no
existing test touched. Branch base: main at 9f15af87 (ff-confirmed; the task
states N6.2b-2 as merged, so the tests are written against the
feat/n62b2-navis-commands state as base — on plain main navisCommands.js is
absent outright, which only deepens the red).

## What the tests pin for the implementer

- (2) navisTree.js: createNavisTree grows `mintRow(payload, state)` ->
  TreeItem | null (separate factory — childrenFor must NOT grow the row by
  default; the shipped tree tests pin its exact length). Label/tooltip are
  mintAvailable's exact pill strings, command {command: "refdes.navisMint"}
  with no arguments, contextValue the single word "refdesNaviMint" (no
  shipped when-clause matches it — pinned mechanically for every
  view/item/context entry), null on count 0 and on lock, plain strings, no
  row text reaches the pill, badgeFor unchanged (counts.active).
- (4) navisCommands.js: createNavisCommands grows `openInEditor(item)` and
  deps grow EXACTLY openExternal + deepLink (injected). Order pinned:
  server-ready first (matches archive/restore; the no-client+keyless
  scenario warns, not informs), then rowForItem/selectorFor (keyless/no
  row -> ONE information naming the missing key, no calls), then
  openExternal(deepLink(key)) with the FULL key (collision -> first row).
  Throwing deepLink -> plain-string error, openExternal untouched. Source
  pin: the module spells no URL/loopback/token.
- (5) mint logs EXACTLY ONE line on success naming the minted-list length
  and the word "reload" (+ "disk"), via the injected log dep; zero lines on
  dismiss/403/transport failure.
- (1) package.json: refdes.refreshNavis title "Refdes: Refresh Navis",
  palette-visible (pinned as ABSENCE of a commandPalette when:"false"
  entry); extension.js: registered as () => refreshNavisTree(true) (the
  ensureServe/showNavisPlaceholder body pinned so the command inherits
  boot=true semantics: quiet on success, placeholder with no server).
- (4) package.json: refdes.navisOpenInEditor "Refdes: ... Open in editor",
  hidden from the palette (when "false"); view/item/context entry, group
  "inline", exact when-clause pinned + visibility table (keyed active and
  keyed archived allow; keyless, the Mint word, placeholders refuse). No
  keybindings, activation events unchanged (folded into a red-first test).
- (3) mechanism chosen: RE-APPLY IN THE REFRESH PATH, not a dedicated
  status item — plan §2's inventory counts two status-bar items, and a
  permanent third piece of chrome for a transient lock is the larger
  change. Pinned in extension.js: setNavisWriteStatus keeps the lock text
  verbatim; applyNavisLockStatus() re-applies it ONLY while
  navisWriteLock.locked() (lock is the source of truth, .reset() is the
  clear, pinned count >= 2: boot + attach); updateStatusBar() (the repaint
  refreshIndex runs — the eraser) calls the helper after statusBar.show().

## Red/green evidence

- Untouched tree: 8 failed source/JSON pins + 16 fixture errors ("Cannot
  find module .../navisCommands.js", "mintRow is not a function") = 24 red.
- Green-after proof: reference implementations in .scratch/n63-tests/ref/
  (NOT shipped; navisCommands.js = b1b772eb's + openInEditor + mint log,
  navisTree.js + mintRow, extension.js/package.json = b1b772eb's + S6.3
  edits), run via REFDES_NAVIS_{COMMANDS,TREE}_JS / REFDES_VSCODE_{PACKAGE
  _JSON,EXTENSION}_JS -> all 24 pass.
- Neighbours (test_vscode_navis_tree, test_vscode_navis_actions) +
  test_crossplatform_lint: 66 passed. ruff clean on the new file. Full
  suite not run (task rule).

## Notes / conservative choices (no question tool)

- The neighbour's when-clause evaluator (test_vscode_navis_commands.py)
  only loops over the NEGATED parenthesised clauses and passes a positive
  clause vacuously — my mint-word menu test exposed it (against the
  reference, ARCHIVE_WHEN "allowed" refdesNaviMint). Grown evaluator here
  (positive un-parenthesised clauses evaluated too); neighbour file not
  edited per instructions.
- Server-refusal-before-key-refusal order chosen (consistency with the
  S6.2b handlers); the task wording listed key first — noted here.
- "disk" added to the mint-log pin beyond the task's loose floor (count +
  "reload"); the log sentence is specified, so the pin is honest.

## Honest limits

No real VS Code window exists in CI: tree-item rendering, real menus/when
clauses, the status bar and vscode.env.openExternal are pinned at
logic/JSON/source level only; plan S8 acceptance is "checklist 1-6 re-pass"
— Jared's manual checklist covers the window.

## N6.3-impl (implementer pass)

Merged origin/main into the branch (clean, no conflicts). Implemented all
five pins in editors/vscode/ only: navisTree.mintRow (pill/tooltip from
mintAvailable, contextValue refdesNaviMint, bare refdes.navisMint command,
null on count 0 / lock; the provider's getChildren prepends it, childrenFor
untouched); navisCommands.openInEditor (server refusal first, rowForItem +
selectorFor, information naming the missing key, openExternal(deepLink(key))
passthrough, throw -> plain-string error) with deps openExternal/deepLink;
the mint success log line (one line, minted-list length + reload-from-disk
wording); extension.js refreshNavisTree(true) registration, the
navisOpenInEditor registration, the two deps wired to
vscode.env.openExternal/serve.deepLink, and applyNavisLockStatus() re-applied
at the end of updateStatusBar's repaint; package.json: refreshNavis
(palette-visible) + navisOpenInEditor (palette-hidden, inline keyed-rows
entry) + the mint-log. Version NOT bumped (S6.4's job). New file: 24/24
green; node --check clean on the three touched .js.

STOP POINT -> RESOLVED (no PR opened at the stop): three tests in the
MERGED tests/test_vscode_navis_commands.py pin the pre-S6.3 shapes the new
file's pins make unsatisfiable together —
test_module_exports_the_command_surface (api == archive/mint/restore
exactly; the new file pins openInEditor as a fourth handler) and the two
mint-success sequence tests (exact rec sequences with no "log" entry; the
new file pins exactly one log line on every mint success). Reported; the
authoriser approved the narrow fix as proposed: S6.3 deliberately changes
those pre-S6.3 shapes, so the api pin grows to the four names and "log"
lands after "refresh" in the two sequences (nothing else in the file
touched). Full suite at the stop: 3 failed (all the above), 6309 passed, 2
skipped; after the fix all tests/test_vscode*.py + the crossplatform lint
re-ran green (174 passed). The author's green-proof run listed only
tree/actions/lint as neighbours (66 passed) — the commands file was not in
it, so this collision is not a regression against the author's own
evidence, it is a gap in it. No real VS Code window: menus/
status bar/openExternal are logic-level only.

