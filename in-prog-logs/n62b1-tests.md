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
- No PR opened (task: push the branch only) — superseded: the implementer
  opened the PR carrying the branch.
- No real VS Code window exists anywhere in this slice: it pins the pure
  decision logic only; commands, menus, toasts and the real vscode API are
  S6.2b-2 (plan §7: "Cannot prove: any VS Code UI behavior").
- The `Origin`/`token` source-pin bans are substring bans (case-sensitive
  `Origin`, case-insensitive `token`) — an implementer who names the launch
  secret or header policy in a comment hits them; that is deliberate (same
  form as test_vscode_navis_tree.py's token pin).

# n62b1-impl — `editors/vscode/navisActions.js` (implementer, 2026-11-08)

Slice IMPLEMENTER N6.2b-1-impl. Created `editors/vscode/navisActions.js`
(pure CommonJS, five exports as pinned; no navisTree.js change, no
extension.js/package.json/commands/UI — S6.2b-2). Status: DONE.

- Red: 9 failed (module absent). Green: 9 passed. Neighbours (navis_tree,
  extension_http_client, extension, crossplatform_lint): 67 passed. Full
  suite: run once before push. No .py source touched → ruff n/a; JS
  `node --check` clean.
- Wording constants: the source pins demand `KEYLESS_HINT`/`ORPHAN_HINT`
  verbatim INSIDE navisActions.js — a require cannot satisfy that — so the
  literals live here (navisTree.js untouched; runtime equality holds; the
  tests docstring's "reuse the constant or pin equality" fork).
- 200 branch reads no body fields (mintOk fixture); generic fallbacks name
  the status, never the body; sanitiser caps at 300.
- No changelog.d fragment: nothing user-visible until S6.2b-2 (per the
  "Not done" note above). No real VS Code window exists in this slice:
  pure logic under bare node (plan §7).

## Review round 2 (same day, owner-triaged reviewer findings)

Red-first, then green: the ambiguous message composes its candidate list
OUTSIDE the 300 cap (per-text 80 cap + `...`, 20 named, `(+N more)`);
table flags key on `kind`/`reason`, a missing `error` falls back safely
(a lock stays a lock, naming --no-write); C1 controls stripped too; a
null row disables all; the `{error}` docstring covers post()'s
unparseable-200. Authorized test edits: real security-403 fixture texts
(`forbidden`, the launch-token denial) + a JSON-500 passthrough pin.
In-file 14 passed, neighbours 67; `node --check` + ruff clean; suite and
CI re-run (see PR).
