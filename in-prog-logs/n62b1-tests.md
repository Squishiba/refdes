# n62b1-tests — contract tests for `editors/vscode/navisActions.js` (S6.2 decision logic)

Slice: TEST AUTHOR ONLY, N6.2b-1-tests. Delivered `tests/test_vscode_navis_actions.py`
(9 tests) pinning the module the implementer builds; the module is not written here.
Branch base: main at the N6.2a merge (post-#402 size gate); fast-forward confirmed,
tree clean before starting.

## What is pinned (the exact export contract)

Plain CommonJS, no `vscode`/http/fetch/fs/child_process require, plain strings only,
nothing token-like in output, exports exactly five functions (node-verified):

- `planResult(result)` -> `{kind, refresh, lockWrites, message}`, kind in
  `refresh|error|warn|lock`. Mapping pinned per plan §4's Result-mapping table:
  200 (changed true/false) -> refresh, message "" (silent success);
  400 -> error + server text; 403 `kind:"refused"` -> kind "lock",
  lockWrites true, message names `--no-write`; 404 -> warn + server text +
  refresh:true; 409 ambiguous -> warn naming every candidate's key, text and
  `file:line`, refresh:false; 409 conflict keyless -> warn + server text,
  refresh:false; not_archived -> warn + refresh:true; orphan -> warn with the
  hand-restore hint, refresh:false; journal_pending -> warn with the store's
  refusal text, refresh:false; 500 -> error + `error`; `{error}` transport ->
  error carrying that text, no lock, no refresh. Unnamed status / unnamed JSON
  `kind` / non-object body (post() raw-text case) / non-object 200 -> generic
  error naming the status, never the raw body (proven by marker strings).
  Server text verbatim except truncation to 300 chars (pinned: <=300, prefix
  preserved) and control characters removed (pinned via \n\t\0 fixture).
- `rowActions(row, {writesLocked})` -> `{archive:{enabled,tooltip},
  restore:{enabled,tooltip}}`; matrix over (active/archived) x (keyed/keyless)
  x (orphan/not) x (locked/not), 10 combos, one node run. Tooltips pinned
  verbatim: keyless `"No key yet -- use Mint keys"` (navisTree.js's string),
  orphan `"Marker not found -- hand-restore the marker, then it re-links by
  key"` (navis-panel.js ORPHAN_TITLE, the wording docs/navis.md quotes);
  locked tooltips must contain `--no-write`. Keyless-archived (impossible) row:
  no crash, Archive disabled.
- `selectorFor(row)` -> full `row.key`; null for keyless (pinned null, not a
  throw — conservative: caller must not POST; pinned `!= key6` too).
- `mintAvailable(payload, {writesLocked})` -> `{enabled, count, label, tooltip}`;
  count = keyless rows among ALL rows (archived keyless counted), enabled iff
  count>0 and unlocked, label `Mint keys (N)` (docs/navis.md:260-272 pill).
- `createWriteLock()` -> `{locked(), lock(), reset()}`: per-instance session
  lock, idempotent lock, reset on re-attach; two instances independent.

## Real server shapes (run, not recalled)

Probed once against live `EditorApp`s (`.scratch/n62b1-probe/`, shapes.json
kept there) and re-captured in-test: the test builds its fixtures by POSTing
the real routes (4 short-lived EditorApps, port 0), per the task's
cheap-fixture rule — the fixtures ARE the server's JSON. Findings vs the plan:

- All plan §4 kinds/fields match the live JSON exactly (`ok/bad_request/
  refused/not_found/ambiguous/conflict+reason` + `error`; candidates carry
  `key/text/file/line` as promised).
- Naming note: the table's "body adds `verb` and `key`" is true for the
  archive/restore 200 only; the mint 200 is
  `{kind:"ok", changed, minted[], still_keyless}` (docs/navis.md "Mint keys").
  So the 200 branch must not read those fields — pinned by the mint fixture.
- The journal_pending refusal text (live): "an editor transaction is in flight
  (unknown); navis archive/restore refuse to write while
  .refdes/editor-transaction exists (design §12)" — pinned as a verbatim
  passthrough, not by literal text (contains a non-ASCII §).

## Ambiguities resolved (conservative, per the task's rule)

- `selectorFor` keyless -> null (task: "choose null").
- Security-layer 403 (text/plain body, no JSON `kind:"refused"`) is a GENERIC
  error, `lockWrites:false` — plan §3 "With a stale token": token problem, not
  the read-only lock. Locking writes on a token hiccup would be the worse bug.
- Non-object 200 body -> generic error, not refresh (conservative).
- Generic messages: pinned to contain the status number and to exclude the raw
  body (marker strings); exact wording left to the implementer.
- 300-char truncation pinned as: result <= 300 chars and the 250-char prefix
  survives (any `slice(0,300)` implementation passes; ellipsis not required).

## Red / green evidence

- Red (untouched tree, module absent): `9 failed` — every test, node drivers
  and source pins alike; captured in the PR report. The live-capture helper
  asserts nothing, so no test is green-by-construction (unlike the N6.1
  neighbours, the task demanded all-red).
- Green proof without committing a module: a reference implementation at
  `.scratch/n62b1-ref/navisActions.js` (NOT committed) passes all 9 via the
  documented `REFDES_NAVIS_ACTIONS_JS` module-path override; the override
  defaults to the real path, so CI is unaffected.
- No node on PATH: 7 node tests skip, 2 source pins run (verified with an
  empty PATH).
- Neighbours green with the new file present: test_vscode_navis_tree.py,
  test_vscode_extension_http_client.py, test_serve_navis_write.py
  (88 passed). Full suite not run (task waived it).
- `ruff check tests/test_vscode_navis_actions.py` (full default set): clean.
  `tests/test_crossplatform_lint.py`: 26 passed.

## Cross-platform posture

subprocess.run(node) with `encoding="utf-8"`; all fixture writes
`newline=""`; port 0 via EditorApp; no fixed ports; no
`Path.read_text(newline=)`; no POSIX-only tools; node bounded by
NODE_TIMEOUT_S=120 (one node process per scenario group: plan-live,
plan-generic, row-matrix, api).

## Not done / notes

- No changelog.d fragment: tests-only PR, nothing user-visible (the S6.2b-2
  implementer ships the feature fragment).
- No PR opened (task: push the branch only).
- No real VS Code window exists anywhere in this slice: it pins the pure
  decision logic only; commands, menus, toasts and the real vscode API are
  S6.2b-2 (plan §7: "Cannot prove: any VS Code UI behavior").
- The `Origin`/`token` source-pin bans are substring bans (case-sensitive
  `Origin`, case-insensitive `token`) — an implementer who names the launch
  secret or header policy in a comment hits them; that is deliberate (same
  form as test_vscode_navis_tree.py's token pin).

# n62b1-impl — `editors/vscode/navisActions.js` (implementer, 2026-11-08)

Slice IMPLEMENTER N6.2b-1-impl. Created `editors/vscode/navisActions.js`
(pure CommonJS, five exports exactly as pinned; no navisTree.js change, no
extension.js/package.json/commands/UI — those are S6.2b-2). Status: DONE.

- Red before the module: 9 failed. Green after: 9 passed. Neighbours green:
  test_vscode_navis_tree.py + test_vscode_extension_http_client.py +
  test_vscode_extension.py + test_crossplatform_lint.py = 67 passed.
  Full suite: run once before push (see PR).
- No .py source touched → nothing for ruff; `node --check` clean on the JS.
- Wording constants: the task said "import, do not copy strings", but the
  test author's source pin demands `KEYLESS_HINT` and `ORPHAN_HINT` appear
  as literals INSIDE navisActions.js (a pure require of navisTree.js cannot
  satisfy `KEYLESS_HINT in actions`). The tests are the unmodifiable
  contract, so the two literals live in navisActions.js (navisTree.js
  untouched — its own pin keeps the tree string); the docstring's
  "reuse the constant or pin equality" is the test author's own
  acknowledgement of this fork. Runtime equality holds.
- The comment ban caught one word: a comment quoting plan §3's "stale
  token" heading tripped the case-insensitive `token` substring ban;
  reworded. Deliberate design, as the test log predicted.
- 200 branch reads no body fields (mint's 200 has no verb/key — captured
  fixture `mintOk` proves it); any plain-object 200 is a refresh.
- Generic (unhandled) messages name the status, never the body; sanitiser
  strips C0+DEL and caps at 300 (long400 prefix pin, hostile400 verbatim
  pin both green).
- No changelog.d fragment: internal module, nothing user-visible until
  S6.2b-2 wires the commands (per this log's earlier "Not done" note).
- No real VS Code window available anywhere in this slice: pure decision
  logic under bare node only (plan §7: "Cannot prove: any VS Code UI
  behavior").
