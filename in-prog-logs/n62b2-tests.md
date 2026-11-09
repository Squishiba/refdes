# n62b2-tests — Navis write-command contract tests (TEST AUTHOR ONLY)

Slice N6.2b-2-tests of docs/design/navis-vscode-panel-plan.md (S6.2, Q4
ratified: Mint ships). Wrote ONE new file, tests/test_vscode_navis_commands.py
(26 tests). No module shipped, no editors/ file touched, no existing test
touched. Branch base: main at the #459 head (fast-forward confirmed).

## What the tests pin for the implementer

- editors/vscode/navisCommands.js: CommonJS, no top-level `vscode` require,
  exports exactly `createNavisCommands(deps)` -> `{archive, restore, mint}`;
  deps = {vscode, getClient, refreshTree, getRows, lock, setStatus, log}.
  No http/fetch/fs, no MarkdownString, no Origin/token text (source pins).
- Handler order in every command: locked -> warn naming --no-write, no call;
  no/not-ready client -> warn "refdes serve is not running", no call;
  rowActions(row,{writesLocked}) disabled -> warn with the shipped tooltip,
  no call; then the POST with selectorFor(row) (full key, pinned exact);
  planResult rendered: refresh silent, warn (+refresh when asked), error
  (+refresh when asked), lock -> lock()+setStatus(naming --no-write)+warn, no
  refresh. Handlers never throw (rejecting client -> plain-string error).
- Mint: one modal confirmation showWarningMessage(text,{modal:true},"Mint
  keys"); dismiss -> nothing. mintAvailable disabled -> showInformationMessage
  (the tooltip), no prompt, no POST. 200 -> refresh, and body.still_keyless>0
  -> an info naming the count. Archive/Restore: no confirmation (pinned by
  the exact call sequences).
- Row recovery (pinned): tree items carry no row field, so the handler matches
  the passed item against getRows().navis by recomputing navisTree's own
  rendered fields (label/description/tooltip/contextValue, unset description
  = ""), first match wins; no match (placeholder, null arg, null payload) ->
  rowActions(null)'s "No Navis row to act on" warning, no call. The
  key6-collision pair (KEY_A/KEY_B render identically) pins first-match and
  that the selector is the full key.
- package.json (JSON pins): the three commands with "Refdes: ..." titles;
  exact `when` clause strings on menus.view/item/context keyed to
  refdesNavi/refdesNaviArchived/refdesNaviKeyless (visibility table evaluated
  in Python against the contextValue words navisTree emits); mint view/title
  entry; the two row commands hidden from the palette (`when: "false"`), mint
  stays; no keybindings; activationEvents unchanged.
- extension.js (source pins): requires ./navisCommands, builds
  createNavisCommands, registers the three ids, constructs the write lock and
  calls .reset() (new serve), and contains NO planResult(/rowActions(.

## Red/green evidence

- Untouched tree: `pytest tests/test_vscode_navis_commands.py` -> 26 red
  (5 failed source/JSON pins, 21 fixture errors "Cannot find module ...
  navisCommands.js"). Red reason shown for the node group.
- Green-after proof: a throwaway reference implementation in
  .scratch/n62b2-tests/navisCommands.js (NOT shipped, mirrors the plan) run
  via REFDES_NAVIS_COMMANDS_JS -> all 22 node-driven tests pass; the 4
  package.json/extension.js pins stay red by design (they pin the repo's
  contributions, which the implementer lands).
- Neighbours + tests/test_crossplatform_lint.py: 76 passed. ruff clean on the
  new file. Full suite not run (task says not to).

## Conservative choices (no question tool)

- Mint refusal is showInformationMessage; locked/no-server refusals are
  showWarningMessage. "No Navis row to act on" reused as the unresolvable-item
  message. Exact when-clause strings pinned verbatim (regex form; substring
  matching is safe because refdesNaviArchived/Keyless are superstrings of the
  base word). setStatus text pinned by containing "--no-write", not verbatim.
- One bug found and fixed in my own harness mid-run: the transport case
  records the POST before it fails, so the sequence is [call, error].

## Honest limits

No real VS Code window exists in CI: menu `when` behaviour, the modal prompt
and the view/title button are logic- and JSON-level only; checklist items 3,
4, 5 are Jared's. The fake vscode shows the handlers call the right APIs with
plain strings; it cannot show what the window renders.
