# n62b2-impl — Navis write commands wired into the VS Code extension (IMPLEMENTER)

Slice N6.2b-2-impl of docs/design/navis-vscode-panel-plan.md (S6.2's command
surface). Continues on the test author's branch base (merged origin/main in;
fast-forward was not possible — the branch carries its own test commit).
Read first: tests/test_vscode_navis_commands.py (26 tests), the author's log,
plan §4/§6/§7.2, and the five editors/vscode modules. No src/ change, no test
touched.

## Shipped

- editors/vscode/navisCommands.js (NEW): CommonJS, host injected via
  createNavisCommands(deps) -> {archive, restore, mint}; requires only
  ./navisActions and ./navisTree. Row recovery recomputes navisTree's OWN
  rendered fields (calls its exported label/description/tooltip/contextValue
  functions — no copied logic), first match wins. Handler order pinned by the
  tests: locked -> shipped locked reason (names --no-write), no client/not
  ready -> "refdes serve is not running" (ServeClient's own sentence, spelled
  here as a literal — serveClient does not export it), rowActions-disabled ->
  shipped tooltip, then POST selectorFor(row) and planResult rendered
  (refresh silent; warn/error + refresh when the table says; lock ->
  lock()+setStatus+warn, no refresh). Handlers never throw: a rejecting
  client is fed through planResult's transport row (its sanitizer, not a
  re-implementation). Mint: refusals first (locked, no server, nothing to
  mint = information), then ONE modal showWarningMessage(text,{modal:true},
  "Mint keys"); only the button posts; 200 with still_keyless>0 -> an info
  naming the count.
- package.json: the three commands ("Refdes: ..." titles), view/item/context
  with the pinned when clauses, mint view/title button (group navigation,
  icon $(key)), palette hides for the two row commands, mint kept in the
  palette (when refdes.active). No keybindings, activationEvents unchanged.
  Version NOT bumped (Q6: S6.4).
- extension.js: thin wiring only — createWriteLock constructed in activate,
  reset on a new serve (startServe AND commandAttachServer),
  createNavisCommands with real deps (getClient=()=>serve, refreshTree=
  refreshNavisTree(false), getRows=()=>navisPayload — the S6.1-stored payload,
  never a second fetch; setStatus -> the index status-bar item; log=logServe),
  three registerCommand lines. No planResult/rowActions calls there.
- changelog.d/navis-vscode-actions.added.md.

## Red/green evidence

- Untouched tree: `pytest tests/test_vscode_navis_commands.py` -> 26 red
  (5 failed pins + 21 errors, navisCommands.js missing) — matches the
  author's log.
- After the change: 25 passed, 1 failed. The one failure is
  test_package_json_context_menus_gate_on_the_context_value_words, which is
  unsatisfiable as written (see Findings). node --check clean on
  navisCommands.js/extension.js; package.json parses.
- Neighbours (navis_actions, navis_tree, extension, extension_http_client,
  adapter_contract, crossplatform_lint, docs_focus): all green (141 passed
  with the new file, 76 s). Full suite: see below.

## Findings (test file, reported not fixed — HARD RULE 1)

- tests/test_vscode_navis_commands.py::
  test_package_json_context_menus_gate_on_the_context_value_words cannot
  pass for ANY package.json. Why: its `_when_allows` helper regex-matches
  only PARENTHESIZED `viewItem =~ /.../` clauses; the pinned RESTORE_WHEN
  and MINT_ITEM_WHEN constants have an unparenthesized positive matcher, so
  the helper evaluates them as True for every contextValue, while the
  visibility table the same test pins demands False for non-matching rows
  (fails on the first: restore for "refdesNavi"). Second, independent
  contradiction: the pinned RESTORE_WHEN lacks a keyless negation, so it
  matches "refdesNavi refdesNaviArchived refdesNaviKeyless", while the
  table pins restore hidden for archivedKeyless (the panel rule rowActions
  encodes). Proposed narrow change:
    RESTORE_WHEN = f"view == {VIEW_ID} && (viewItem =~ /refdesNaviArchived/) && !(viewItem =~ /refdesNaviKeyless/)"
    MINT_ITEM_WHEN = f"view == {VIEW_ID} && (viewItem =~ /refdesNaviKeyless/)"
  (ARCHIVE_WHEN passes the table as pinned — its negations decide all four
  rows — and is shipped verbatim.)
- Shipped package.json carries the table-correct clauses (restore gated
  with !(viewItem =~ /refdesNaviKeyless/); the two positive matchers
  parenthesized — VS Code's `&&` binds looser than `=~`, so the
  parenthesized form is semantically identical for the real host, and it is
  the form the test's own evaluator parses). After the proposed test change
  this test goes green with the shipped JSON unchanged; the only red
  asserts today are the two verbatim string equalities (restore, mint) and
  the two table rows the helper cannot evaluate.

## Honest limits

No real VS Code window exists here: the menu `when` behaviour, the modal
prompt, the view/title button and the status-bar write state are pinned at
logic/JSON level only (plan §7.2 — Jared's checklist 3, 4, 5 cover the
window). The setStatus copy ("$(lock) Refdes: read-only" + the server's
text) is a legibility choice, not a test pin.
