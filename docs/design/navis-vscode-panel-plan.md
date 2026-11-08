Status: **plan, questions ratified** (2026-11-08). It answers the one deferred item of
the Navis design — `in-prog-logs/navis-design-20261025.md` §13 slice 6
"(Deferred, see §14) VS Code panel from the `index` payload" (line 424) and
its §14 question 5 (lines 438-440: "is a VS Code panel wanted, and is it v1
or later?") — and it is the Navis client of
`docs/design/editor-vscode-adapter.md` §3.3's shipped route table, whose
Navis row ("Everything about the project's Navis — `GET /api/navis`", §3.3)
the adapter doc already reserves. This is a plan, not a spec: the design
rules (§2 owner decisions, §11's one-projection rule) stand, and the job
here is to order the work into slice-ready steps, name the mechanism each
builds on, and put the open questions in front of the owner with a
recommended default each — the format of
`docs/design/thread-workbench-w5b-plan.md` §6 (options, trade-offs,
conservative default; that file lines 395-420).

**Citations.** Line numbers are against `main` at `b9eba32d` (post-#402, so
the pr-size gate is live). Every file:line below was opened for this
document; claims about API behavior cite the shipped renderer modules and
the captured transcripts in `docs/navis.md` §"The serve API" (lines
307-398), not memory. Where something is only checkable in a real VS Code
window, the plan says so.

# Navis in the VS Code extension: slice plan (N6)

## 1. The goal, and the one deferred sentence it lands

The Navis panel exists on the published site, the served preview, and the
browser editor (`docs/navis.md` §"The site panel" area, §"The served preview
panel" lines 243-305, §"In the editor" lines 291-305). The extension is the
fourth client: a Navis list in the author's editor, with Archive / Restore /
Mint as commands, clicking a row opening the marker's file at its line.
The design's slice-6 sentence says "from the `index` payload"; §3 below
recommends `GET /api/navis` instead, because the extension has been a serve
client since Slice V0 — the deviation is Q1.

Every design rule carries over unchanged: the panel is "a client of the same
projection, never a second implementation"
(`in-prog-logs/navis-design-20261025.md` §11, lines 366-369); archive and
restore touch no body, ever (§7.3, lines 241-252); minting a key *is* a body
write, by design (§7.2, lines 227-239); a Navi is never a derived row
(§2.7, lines 46-52).

## 2. What the extension has today, and which surface a Navis list fits

Verified inventory of `editors/vscode/` (adapter doc §2.1 lines 59-82 listed
it at 536/94 lines; it has grown — `extension.js` is now 1,002 lines,
`package.json` 103, and the adapter doc's own header, lines 13-14, declares
its §2 anchors stale):

- **Two status-bar items.** `statusBar` (index health, runs `refdes.check`
  on click, `extension.js:939-940`) and `serveStatusBar` (snapshot serial /
  server state, opens the log, `extension.js:941-942`, states
  `none|starting|connected|died` at `extension.js:504-526`).
- **One output channel** "Refdes" (`extension.js:937`), the `[serve]` log
  (`extension.js:495-497`).
- **A diagnostics collection** fed from `refdes index --compact`
  (`extension.js:938, 170-210`).
- **Four language providers** over markdown/yaml files: hover (index body +
  snapshot facts, `extension.js:530-544`), CodeLens "Open in editor"
  (`extension.js:552-573`), go-to-definition (`extension.js:575-586`),
  completion (`extension.js:588-685`).
- **Calc decorations** (`extension.js:729-787`).
- **Nine commands** (`package.json:30-40`, registered
  `extension.js:959-970`): build, check, allocateIds, openPreview,
  refreshIndex, toggleCalcResults, attachServer, openInEditor,
  showServerLog. Plus two `editor/title` buttons (`package.json:48-59`) and
  a `commandPalette` hide for the CodeLens-only command
  (`package.json:42-47`).

There is **no tree view and no webview**: `package.json` `contributes`
(lines 29-102) has no `views`/`viewsContainers`, and the adapter doc §2.1
confirms ("There is **no** webview, no `contributes.customEditors`",
lines 74-76). So the task's candidate — a `TreeView` fed by `GET /api/navis`
through `serveClient` — is **confirmed as the right fit, and refuted as
something that exists**: it is a *new* contribution, and the lightest one
VS Code offers for "a persistent, themeable, actionable list". §3.4 of the
adapter doc ranks the surfaces (providers / sidebar webview / custom
editor, lines 317-352); a native TreeView costs less than its B-surface
webview (no frame, no theming, no second UI to keep in step with the
browser's 1,783 lines, §2.4 lines 164-169) and pays the §3.4 "webview is a
second UI to maintain" sentence (§3.4, line 349-350) in full. It also
cannot drift into §3.5's two-write-path problem: a TreeView owns no
document (its provider is read/render only; every mutation is a POST the
server decides, §4's ban repeated as a test at
`tests/test_vscode_extension.py:108-110, 196-220`).

## 3. Data path: `GET /api/navis`, not the `index` payload

**The route.** `GET /api/navis` answers `200 {"navis": rows, "counts":
{"active", "archived"}}` — the panel rows through `navis_panel.panel_model`
over `navis.projection(project)`, exactly the pair the site panel renders
(`src/refdes/serve/navis_read.py:21-34`; row fields `key`, `key6`, `text`,
`item`, `href`, `file`, `line`, `archived`, `changed`, `orphan` per
`src/refdes/navis_panel.py:69-81`, shape also captured in `docs/navis.md`
lines 317-339). Dispatch: `src/refdes/serve/api.py:52-53` (GET/HEAD; other
methods 405, `api.py:95-102`).

**Why not the `index` payload** (design §13 slice 6's wording):

1. The extension is already a serve client — `ServeClient` shipped with
   Slice V0 (`docs/design/editor-vscode-adapter.md` §8 line 637;
   `extension.js:26, 339-383`), and the panel needs the server anyway:
   every action is a POST (`navis_write.py`, `navis_mint.py`). Splitting
   read (index) from write (API) is exactly the two-fetch-paths smell the
   adapter's §6 Q3 (lines 486-494) made a visible, deliberate choice for
   the *hover*; the Navis panel has no read path that works without the
   server, so there is no half to keep.
2. The index refresh is a spawned Python process doing a whole-project
   build, debounced 250 ms after save (`extension.js:99-153`); the panel
   wants a cheap GET on the already-built snapshot.
3. `GET /api/navis` merges the `.refdes/navis/` archive store **at request
   time** ("an on-disk archive is visible on the next GET",
   `navis_read.py:9-12`); the index payload carries the raw `projection`
   rows (`render.py:834-836`, absent-key convention) — no `key6`/`item`/
   `href` resolution, and the extension would re-implement
   `panel_model`'s presentation, which §11 forbids (lines 366-369).

**Refresh.** The extension already polls `GET /api/revision` every 5 s
(`SERVE_POLL_MS`, `extension.js:58, 410-446`) and stores
`serveSerial = res.body.serial` (`extension.js:443`). That is the signal:
each navis write route forces a synchronous rebuild before answering
(`navis_write.py:76-80`, `navis_mint.py:79-82` — `app.state.refresh
(force=True)`), and every `_build` increments the serial
(`src/refdes/serve/state.py:225`, `refresh` semantics lines 265-297,
`revision_info` lines 308-317). So: **on serial change, refresh the tree** —
the same signal the editor panel rides (`navis-panel.js:6`: app.js's poller
fires `refdes:rebuilt` when the served serial moves). Additional refresh
triggers, all cheap: after each of the extension's own actions, on save (the
`onDidSaveTextDocument` → `scheduleRefresh` hook, `extension.js:975-979`),
on view expand, and on the existing `refdes.refreshIndex` command.

**The freshness gap, stated plainly.** A Navi archived by a concurrent CLI
(`refdes navis archive`) moves no watched input, so no rebuild, no serial
change, and no push — the extension's tree stays stale until the next
trigger fires. This is the *same* parity the shipped panels have (the
store is read at request time, `navis_read.py:9-12`; the preview panel
converges on page reload). Not a new gap; a documented behavior.

**With no server attached.** The panel data does not exist offline (a Navi
is inert text in a body; nothing renders it without the projection). The
tree shows a placeholder item ("No server — hover an item, or run
*Refdes: Attach to running server*") and boots lazily via the existing
`ensureServe()` (`extension.js:377-383`) on expand — same lazy posture as
the hover (`extension.js:339-375`), no boot at activation (adapter §6 Q2,
lines 481-484; the child dies with the window, `deactivate`
`extension.js:995-1000`).

**With `--no-write`.** Reads work: the tree renders, the counts render, and
every write action is **disabled with the server's own reason** (a
`--no-write` POST answers `403 {"kind":"refused","error":…}` *gate-first*,
before body validation — `navis_write.py:57-58`, `navis_mint.py:59-60`;
table row `docs/navis.md:351`). On the first such 403 the extension mirrors
the editor panel: show the server's message, disable the write actions for
the rest of the session (`docs/navis.md:286-299` — the editor panel "locks
the panel's actions for the rest of the editing session").

**With a stale token.** A security-layer 403 carries a `text/plain` body
(`_deny`, `server.py:630-631`), not the JSON `kind:"refused"` of a
`--no-write` refusal (`navis_write.py:116-117`) — the client distinguishes
them (JSON body → read-only lock; plain body → token problem) and routes
the token case to the existing `handleServeForbidden()`: respawn once for a
spawned server, prompt re-attach for an attached one
(`extension.js:453-478`, wired into the poll at `extension.js:434-437`).

## 4. Actions: Archive / Restore / Mint

**Routes (shipped, `docs/navis.md:341-398`).**

- `POST /api/navis/archive` and `POST /api/navis/restore` — body
  `{"navi": <selector>}`; selector = full key, unique key prefix, or
  `refdes navis all` ordinal (`navis_write.py:84-104`).
- `POST /api/navis/mint` — body `{}`; project-wide, extra keys ignored
  (`navis_mint.py:49-96`).

**Headers the server enforces.** Every `/api/` request: `X-Refdes-Token`
(`security.py:24`, enforced `server.py:785`). Every POST additionally:
an `Origin` that is one of the two accepted origins *and* agrees with the
`Host` it arrived on (`security.py:57-65`, enforced `server.py:789`);
`Content-Type: application/json` (415 otherwise, `server.py:799-804`);
`Content-Length` (411, `server.py:807-809`). `ServeClient` today is
GET-only (`method: "GET"` hard-coded, `serveClient.js:234-274`) — slice
S6.2 adds a `post(pathname, body)` that sets `Origin:
http://127.0.0.1:<port>` explicitly, matching the Host Node derives
(adapter §3.2's failure-mode rule, lines 291-295: "Pin this in a test,
because it is the kind of header a future refactor drops"). The
non-200 response body arrives as a *string* from the current client shape
(`serveClient.js:258-260`); `post()` parses JSON for every status.

**Result mapping** (renderer: `navis_write.py:107-158`; table:
`docs/navis.md:347-355`):

| Status/`kind` | Extension behavior |
|---|---|
| `200 ok` (`changed` true/false) | refresh the tree; `changed:false` is a silent success (re-archive is a no-op) |
| `400 bad_request` | `showErrorMessage` with the server's `error` (a bug in the client — loud per §3.2's rule) |
| `403 refused` | disable write actions for the session, status bar tooltip names `--no-write` |
| `404 not_found` | `showWarningMessage` with the server's text (the selector row set moved under us — refresh, the number may be valid now) |
| `409 ambiguous` | `showWarningMessage` naming `candidates` (each `key`/`text`/`file`/`line`, `navis_write.py:127-140`) |
| `409 conflict reason:keyless` | row shows no Archive button in the first place (§4 of the preview panel's rules); if raced, `showWarningMessage` with the server's message |
| `409 conflict reason:not_archived` | warning with the server's text; refresh |
| `409 conflict reason:orphan` | row keeps Restore disabled; if raced, warning with the server's hand-restore hint (`navis_write.py:38-43`) |
| `409 conflict reason:journal_pending` | warning with the store's refusal text; the tree cannot act until `refdes recover` — same posture as the browser panel |
| `500` | `showErrorMessage` with `error`; never a silent failure |

**Disabled states, computed from the row** (no client-side rule invention —
each mirrors a shipped panel, `docs/navis.md:243-305`): `key === ""` →
no Archive, tooltip mirrors the preview panel's "No key yet — use Mint
keys"; `archived && orphan` → Restore disabled with the hand-restore hint;
`--no-write` (seen as 403) → all writes disabled. Mint appears as one
command (and one tree item when keyless rows exist, the preview panel's
`Mint keys (N)` pill shape, `docs/navis.md:260-272`); mint writes marker
bytes into item files (`navis_mint.py:34-35`) — a body write, visible in
open editors, gated behind an explicit command (Q4).

**Command surface.** `refdes.navisArchive`, `refdes.navisRestore`,
`refdes.navisMint` registered in `activate`, contributed to
`view/item/context` with `when` clauses on the tree item's `contextValue`
(`refdesNaviArchived`, `refdesNaviKeyless`, …) and to the command palette
(the two per-row commands hidden from the palette, the
`refdes.openInEditor` pattern, `package.json:42-47`).

## 5. Click-through: opening the marker's item at its line

Rows carry `file` and `line` (`navis_panel.py:76-77`; captured
`docs/navis.md:335-339`), and the extension already opens exactly this:
`definitionProvider` joins `index.root` with `item.source.file` and lands
on `line - 1` (`extension.js:575-586`). The tree item's command does the
same arithmetic — `vscode.Uri.file(path.join(index.root, row.file))` with a
single-character `Range` at `row.line - 1` (`vscode.open` with
`Range`, or `showTextDocument` with a selection), so a click lands the
cursor on the marker line. `index.root` is the project root recorded by the
last index refresh (`extension.js:144`); with no index the command shows
the existing "no refdes-project.yaml found" warning (`extension.js:792-795`).
Orphan rows (marker not found — `file`/`line` from the record snapshot,
labelled "marker not found") keep the click: the snapshot location is the
best available pointer, and the row label says so.

Secondary click (the browser form) reuses the shipped deep link:
`commandOpenInEditor` resolves the key (row's item → `GET /api/item/<ref>`
when needed) and opens `client.deepLink(key)` externally
(`extension.js:855-890`, `serveClient.js:297-300`) — the shape pinned
against the server toolbar by `tests/test_vscode_adapter_contract.py:619-667`.

## 6. Security: the row text is untrusted input

Every string in a row is author text, unbounded and untrusted (`text` is
"Navi text, any single line not containing `-->", design §4 lines
113-117). Verified posture:

- `TreeItem.label`, `.description`, `.tooltip` as **plain strings only**.
  `tooltip` accepts a `MarkdownString`; the plan **forbids** building one
  from row data. Plain strings render literally — no markdown parsing, no
  link syntax, no command URIs. (The extension's existing `MarkdownString`
  use is the hover, which escapes through `mdEscape`
  `extension.js:233-236` and never sets `isTrusted` — commands in
  markdown do not execute without it; the tree simply does not use
  markdown.) Pin with a grep test (§7).
- **No command-URI surface**: each item's `command` and
  context-menu commands are constructed by the extension (fixed command
  ids, args = the row's key string); nothing in a server payload names a
  command.
- **The token never enters the tree**: it lives in the `ServeClient`
  object (`serveClient.js:9-11`) and in the deep link built for
  `openExternal` (`serveClient.js:297-300`); labels/tooltips are rendered
  row fields only, and `redact()` (`serveClient.js:47-49`) keeps the log
  clean as today.
- Tree labels are truncated for display (e.g. 120 chars, the hover's
  field-row precedent `extension.js:308`) — length is a legibility
  choice, not a security one; truncation never re-introduces markup
  semantics into a plain string.

## 7. Testing strategy without a VS Code binary

Three shipped layers, each with a stated limit, plus the real-window
checklist. (Adapter §7.1/§7.2, lines 541-615, is the design of this split.)

1. **Python contract tests** — `tests/test_vscode_adapter_contract.py`
   (live `EditorApp` over real sockets, `serve_support.Client`, plus
   subprocess CLI runs). Add Navis pins, mirroring the §7.1 posture:
   the row shape + `counts` of `GET /api/navis`; the token gates *this*
   read too; `POST /api/navis/archive` without `Origin` is 403; the
   `--no-write` server refuses all three navis routes and the tree does
   not move (extend `test_no_write_server_refuses_every_mutation_route`,
   lines 538-581); mint is idempotent; the ambiguous-prefix 409 carries
   `candidates`. **Proves:** the facts the extension renders. **Cannot
   prove:** that the extension renders them.
2. **Source-text + node-execution tests** —
   `tests/test_vscode_extension.py`: regex pins on the JS source (the
   launch-line two-sided pin, lines 139-159; the token-header pin
   against `security.py`, lines 162-193; §4's write ban, lines
   196-220), and *executed* extractions under `node -e` with
   `@pytest.mark.skipif(NODE is None)` (lines 336-397, 403-447, 455-548;
   `NODE_TIMEOUT_S = 120`, line 333, for cold Windows runners). Add:
   the tree-provider logic (row → TreeItem mapping, contextValue rules,
   truncation) extracted and executed like `itemsById`; a pin that
   `serveClient.js` sets `Origin` and `Content-Type: application/json`
   on POST; a grep ban on constructing a `MarkdownString` from navis
   rows; the launch-line/header pins keep covering the new POST path by
   construction. **Proves:** wiring and invariants in the JS logic.
   **Cannot prove:** any VS Code UI behavior (view rendering, `when`
   clauses, menus, tooltips, the real `vscode` API), and every node test
   reports "not verified" (skips) on a machine without node.
3. **Live client test** — `tests/test_vscode_extension_http_client.py`
   (named by §7.2 line 589, not yet built): node driving the real
   `serveClient.js` — a pure module with no `vscode` import
   (`serveClient.js:1-18`) — against a live `EditorApp`: POST the three
   routes with real headers, assert the 200/403/409/404 mapping, a 403
   surfaces the JSON `kind:"refused"`, a dead child yields an error
   object not a hang. **Proves:** the wire contract of the new `post()`.
   **Cannot prove:** UI; that needs a window.

`@vscode/test-electron` (real extension host, `real TreeView`) stays
deferred as §7.2 lines 613-615 defers it — nothing here ships a webview
that forces the harness; the S6 slices' UI states are accepted by hand.

**Manual checklist for Jared (real window, F5 Extension Development Host
per `.vscode/launch.json`):**

1. Open a project with 2+ Navis (one keyless). Tree shows active rows
   newest-first per the projection order, `key6 · text`, count in the
   view badge; keyless row has no Archive and the "Mint keys" hint.
2. Click a row → the file opens at the marker line.
3. Archive → row moves to Show-all (archived section), body file
   `git diff` empty (no bytes). Restore → back; no bytes again.
4. Mint keys → marker gains its key in the file; an open **clean** editor
   reloads; with a **dirty** buffer in that file, VS Code's external-
   change prompt wins (record what you see).
5. `--no-write` server: panel lists, first Archive click shows the
   server's refusal, actions lock.
6. Kill the server process: status goes `server died`; tree placeholder
   matches; Attach to running server recovers.
7. Paste a stale launch URL: one 403, re-attach prompt, per
   `handleServeForbidden`.
8. Theme: rows readable in light/dark/high-contrast (native TreeView,
   expected free).

## 8. Slices

The pr-size gate counts added lines under `src/` only
(`tools/pr_size.py:28, 66-68, 113`; budget 350 at line 20) — these slices
touch `editors/vscode/` and `tests/` only, so the gate is green by
construction. That is not a licence to widen them: each slice stays small
(≤ ~250 JS lines), and **no slice adds src/ code** — every route it needs
is shipped (§3.3's table is the whole surface).

**S6.1 — the read-only tree.** `contributes.viewsContainers`/`views` +
`NavisProvider` (getChildren/refresh/getTreeItem) over a new
`ServeClient.navis()` GET; rows per §2-3: active rows + "Show all"
group, key6 label, truncated text, orphan/keyless notes, count in the
view badge; click-through per §5; placeholder states (no project / no
server / server died / Navis-free); refresh on serial move + save +
expand + `refdes.refreshIndex`. *Tests:* contract test for the GET row
shape; provider logic extracted + node-executed; source pins (token
header reused by construction, no MarkdownString-from-rows grep).
*Acceptance:* checklist 1, 2, 6. Verifiable here: all logic; UI by hand.

**S6.2 — the three POSTs and the command surface.** `ServeClient.post()`
(Origin/Content-Type/Content-Length/JSON-parse-all-statuses); commands
`refdes.navisArchive` / `refdes.navisRestore` / `refdes.navisMint`;
context-menu contributions with `contextValue` `when`s; the §4 mapping
table; `--no-write` session lock; row-disabled states. *Tests:* contract
tests for Origin-on-mutation and `--no-write`-refuses-all-three
(extend the shipped route tests); a node live-client test of `post()`
(§7.3); pins that POST sets `Origin` + `Content-Type`; write-ban test
unchanged (POSTs are not file writes). *Acceptance:* checklist 3, 4, 5.
UI by hand.

**S6.3 — freshness polish + secondary actions.** refresh triggers beyond
serial-move (post-action, 404-then-refresh, manual `Refdes: Refresh
navis` command), "Open in editor" (deep link) as a row secondary, mint's
keyed-file reload note in the log. *Tests:* serial-compare logic
extracted; deep-link pin already shipped (contract test 10).
*Acceptance:* checklist 1-6 re-pass.

**S6.4 — docs + publish.** README feature rows + the `--no-write`/
no-server table; a "In VS Code" section in `docs/navis.md`;
`changelog.d/navis-vscode-panel.added.md`; version bump (Q6). Docs-only.
*Tests:* `tests/test_docs_anchors.py`, docs-site build
(`python docs-site/gen_examples.py --check` + `refdes build` in
`docs-site/`, the docs.yml job).

## 9. Packaging impact

- **VSIX contents change**: `extension.js`, `package.json` (new
  `contributes.views*`/menus), README. `.vscodeignore` already excludes
  the right things; no new files, no bundler, no build step (plain
  CommonJS stays, `extension.js:17`).
- **Publisher id unchanged**: `publisher: SquishingCo`
  (`package.json:6`); no `extensionDependencies` change
  (`package.json:28`); `engines.vscode ^1.85.0` (`package.json:9`)
  covers `createTreeView`/`TreeItem`/context-value `when` clauses —
  no engine bump planned (verify in the window, S6.4 checklist).
- **Activation unchanged**: `workspaceContains:**/refdes-project.yaml`
  (`package.json:27`) — view contributions add no activation event; the
  provider is constructed inside `activate`, and the *server* boots
  lazily on expand, not on window open.
- **User-visible on publish**: a new sidebar tree, three commands,
  context menus — the marketplace description's feature list and README
  grow (the extension is published, so this is a product change, gated
  by Q6).

## 10. Changelog & docs surface (of the slices, not this plan)

- `changelog.d/<slug>.added.md` per slice with a user-visible delta
  (fragment types observed in `changelog.d/`: `.added.md`,
  `.changed.md`, `.fixed.md`).
- `editors/vscode/README.md`: command table, view, status notes; the
  "Not yet" list (line 157) is where the live-preview aspiration lives,
  untouched by Navis.
- `docs/navis.md`: a short "In VS Code" section pointing at the README
  (the guide's own scope line at `docs/navis.md:301-305` sets the
  precedent of naming the surface without repeating it).
- `docs/index.md`: **no change** — the site nav lists only docs/ guides
  and references (verified: `docs/index.md` lines 14-48 list no
  docs/design page); design plans are not nav items, and this page
  joins them.

## 11. Risks

1. **Mint writes under the author's feet** (the only body-writing
   action). It splices keys into item files server-side
   (`navis_mint.py:34-35`); VS Code reloads clean editors, prompts on
   dirty ones. The design's own §7.2 (lines 227-239) already accepts
   mint-as-body-edit; the plan adds only the UI to trigger it. Mitigate:
   mint is a command with a confirmation-carrying title (`Mint keys
   (N)`), never automatic, and the dirty-buffer behavior is a named
   manual-checklist item.
2. **Snapshot-vs-index drift**: the tree is serve-sourced, the status bar
   is index-sourced. §6 Q3's rule (adapter lines 486-494) applies: one
   rendering path per fact, the split visible. A Navi row's *text* from
   the server can lag an unsaved editor buffer (the served snapshot is
   disk state) — the same lag the preview panel has; say it in the
   README.
3. **Two windows, two servers** on one project (adapter §6 Q6): each
   tree converges within its own poll; a lost update is impossible
   (content revision), transient disagreement is named.
4. **Gate arithmetic honesty**: JS lines don't count against the 350
   src gate (`pr_size.py:28`); a 1,000-line extension.js keeps reviews
   honest the slow way — hence the ≤~250 JS lines/slice ceiling above.
5. **Long labels**: one-line Navi text is a sentence by grammar design
   (design §4, lines 113-124); truncation at ~120 chars with the full
   text in the plain-string tooltip.

## 12. Open questions for Jared

Each has options, the trade-off, and the recommended default this plan
assumes until told otherwise. All seven recommended defaults were ratified
by Jared on 2026-11-08, as written; each question below carries its Ratified
line.

**Q1 — data path: `GET /api/navis`, or the `index` payload the design's
slice-6 sentence named?** (a) `/api/navis` (b) `index` payload (c) both,
index-fallback. **Trade-offs:** (a) is one path, live store merge, the
shape the preview panel renders (`navis_read.py:1-13`); it requires the
server, which the actions require anyway. (b) works offline for reads
only, ships raw rows the extension must present, and pays a build per
refresh; the design's sentence predates V0's ServeClient. (c) is §6 Q3's
two-fetch-paths smell with no unique-fact justification. **Recommended
default: (a)**; design §13 slice 6's wording superseded for this slice.

**Ratified 2026-11-08: (a)** — `GET /api/navis` is the data path.

**Q2 — surface: TreeView, a webview panel, or the V1 sidebar webview
first?** (a) native TreeView (b) its own webview (c) wait for the V1
`WebviewViewProvider` panel (adapter §8 lines 656-660, not built) and
mount Navis there. **Trade-offs:** (a) costs the least, themes itself,
no second UI, actions are plain commands; it cannot show the site's
pretty panel shape. (b) pays §3.4's "second UI to maintain" for one
list. (c) couples Navis to V1, which §8 gates on "V0 earns it" — the
Navis panel should not be V1's reason to exist. **Recommended default:
(a)**; if V1 ships later, moving the list is a rendering swap over the
same `ServeClient.navis()`.

**Ratified 2026-11-08: (a)** — the native TreeView.

**Q3 — where does the view live?** (a) the Explorer (a `views` entry,
no activity-bar icon) (b) a dedicated "Refdes" container with its own
icon. **Trade-offs:** (a) is one collapsible section, zero permanent
chrome for a window that already has two status-bar items; (b) is
findable at a glance and buys the activity bar a third icon for every
user. **Recommended default: (a)** for the panel; promote to (b) on
demand.

**Ratified 2026-11-08: (a)** — an Explorer section, no activity-bar icon.

**Q4 — ship Mint in VS Code?** (a) yes, as an explicit command (b) ship
it CLI/preview-only. **Trade-offs:** (a) completes panel parity (§11's
reachability rule) and surfaces the keyless flow where the author sees
keyless rows, at the cost of the §11.1 write-under-feet risk (dirty
buffers prompt). (b) is the smallest surface; the author leaves the
window to mint. **Recommended default: (a)** — the write is the
tool's, announced by the server, idempotent
(`docs/navis.md:395-397`), and the risk is one named checklist item.

**Ratified 2026-11-08: (a)** — Mint ships as an explicit command.

**Q5 — does the tree boot the server on expand?** (a) lazy-boot on
expand (the hover's `ensureServe` posture) (b) placeholder + explicit
"Start server"/"Attach" only. **Trade-offs:** (a) is one click to
content, spawns a Python child per window on a gesture that is
unambiguous; (b) never spawns without an explicit ask, costs two
clicks. **Recommended default: (a)** — expanding a view named "Refdes
Navis" is the ask.

**Ratified 2026-11-08: (a)** — expanding the view lazily boots the server.

**Q6 — version + publish.** (a) bump `0.1.0 → 0.2.0` with the
first shipped slice and publish; (b) bump at S6.4; (c) ship to
open-vsx/marketplace on Jared's cadence only. **Trade-offs:** (a)
earliest user-visible delta; (b) one publish, one changelog set.
**Recommended default: (b)**; publishing itself stays Jared's call (the
extension is published under `SquishingCo`).

**Ratified 2026-11-08: (b)** — bump at S6.4, one publish; publishing
itself stays Jared's call.

**Q7 — what does the tree show for a Navis-free project?** (a) an empty
"no Navis" placeholder (b) hide the view (a `when` context — no shipped
mechanism; VS Code shows registered views regardless). (c) show it only
after Navis exist (no shipped mechanism either). **Recommended
default: (a)** — the payload is the same shape with zero counts
(`navis_read.py:22-24`), and a visible empty state is the extension's
own rule ("a quiet failure is the bug class", `serveClient.js:137-140`).

**Ratified 2026-11-08: (a)** — a visible empty "no Navis" state.

## 13. What this plan does not decide

- No writes from VS Code beyond the three navis POSTs; §3.5's
  two-write-path problem and §6 Q5's `applyEdit` ban stand untouched
  (adapter lines 354-402, 503-507).
- No webview, no custom editor, no drafts, no remote VS Code (adapter
  §5 lines 442-468).
- Page Navis, v1 scope of Navis-on-pages — design §14 Q1, unchanged.
- The V1 sidebar webview's scope (adapter §8) — Q2's (c) is its
  consumer, not its scheduler.
