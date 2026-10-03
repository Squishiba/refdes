Status: proposed (drafted 2026-09-27) — a design spec, not a decision. It designs
the one Later item of `docs/design/browser-editor.md` that was left with no
design behind it: "VS Code custom-editor adapter over the same application
services" (`docs/design/browser-editor.md:1100`), and is cross-referenced from
that line. Every open question in §6 carries a recommendation, and each
recommendation is the default if Jared lets it stand unanswered. §9 records what
was considered and rejected. Nothing here is implemented, and §2's claims about
current behaviour were each checked against the files named at the claim.

The constraint this document works under is not negotiable and is quoted rather
than paraphrased: "Python remains the only implementation of the schema, parser,
validator, ID ledger, surrogate keys, link resolver, Markdown renderer, figures,
seals, and writes" (`docs/design/browser-editor.md:13-16`), and "VS Code is a
later adapter. It reuses the service operations; it does not define the editor's
architecture" (`docs/design/browser-editor.md:1242-1244`). So this is a proposal
for a **new client of an API that already shipped**, not a second editor and not
new server semantics.

## 1. Problem

The browser editor answers "where do I author an item?" The VS Code adapter
answers a different question: "where am I already?" An author who lives in VS
Code all day — reading `items/power/dec-005.md`, editing it by hand, reviewing a
diff, chasing a failing check — currently leaves the editor to do anything
structured. `docs/design/backlog.md` §15 named that friction as the real one:
"the recurring friction across real authoring has been the authoring surface
itself, not the data model" (`docs/design/backlog.md:299-301`).

What hosting in VS Code buys over opening `refdes serve` in a browser tab is
specific, and it is worth naming rather than assuming:

- **Proximity.** The item is one keystroke away from the file the author is
  already in: hover an ID for its resolved state instead of switching windows;
  a CodeLens on the item's own front matter that opens its form.
- **The facts are already there.** The extension already publishes diagnostics,
  completion, hover, go-to-definition, and inline calc results
  (`editors/vscode/extension.js:510-512`) — the surface where a resolved value,
  a coverage stage, or an attributed diagnostic belongs is already built and
  already used.
- **The editor's own conflict model already assumes VS Code is a writer.**
  "Disk has moved — another tab, VS Code, a `git checkout`, a CLI write"
  (`docs/design/browser-editor.md:790`). Today that writer is unmanaged: VS Code
  can only break the browser editor's saves. An adapter makes the same facts
  visible from inside the writer, which is where a conflict is cheapest to see.

What it does **not** buy is a better authoring model. The browser editor is the
product (`docs/design/browser-editor.md:1242-1244`); this is an adapter, and the
burden of proof for each increment of UI is "the browser surface does not cover
this, and the author hits it daily."

## 2. Current state (verified 2026-09-27)

### 2.1 What is actually in `editors/vscode/`

Every file, named, from `ls -la` of the directory:

| Path | Size | What it is |
|---|---|---|
| `editors/vscode/extension.js` | 536 lines | The whole extension. Plain CommonJS, no build step ("Plain JavaScript on purpose: no build step, so F5 runs it as-is", `extension.js:9`). |
| `editors/vscode/package.json` | 94 lines | Manifest. `publisher: SquishingCo`, `engines.vscode: ^1.85.0`, `extensionDependencies: ["redhat.vscode-yaml"]` (`package.json:28`). No `scripts`, no `devDependencies` — there is no compile, lint, or test tooling here. |
| `editors/vscode/README.md` | 132 lines | User-facing docs for the shipped feature set. |
| `editors/vscode/LICENSE` | 21 lines | MIT. |
| `editors/vscode/icon.png` | 879 B | Marketplace icon. |
| `editors/vscode/syntaxes/calc.injection.json` | — | TextMate injection for ```` ```calc ```` fences into `text.html.markdown` and `source.yaml`. The README is candid that this is the one place the extension re-implements lexing ("necessarily re-implements the unit lexer… the parser is right"). |
| `editors/vscode/.vscodeignore` | 44 B | `node_modules/`, `.vscode/`, `.vscode-test/`, `*.vsix`. |
| `editors/vscode/.vscode/launch.json` | 482 B | F5 Extension-Development-Host config, opened on this repo itself. |

That is the complete inventory. There is **no** `webview`, no `contributes.customEditors`,
no `test/` directory, no `tsconfig.json`, no bundler, and no `node_modules`
committed. Two details in that inventory matter for this proposal:

- `.vscodeignore` already lists `.vscode-test/` — the output directory of
  `@vscode/test-electron`. A test harness was anticipated and never built.
- The README's own "Not yet" list names "Live preview pane… A proper in-editor
  webview with auto-refresh is the obvious next step"
  (`editors/vscode/README.md:113-116`). Aspirational, not present.

### 2.2 How the shipped extension gets its facts

One call, on a timer and on save: `refdes index --compact`, spawned through
`child_process.spawn` with the command taken from the `refdes.command` setting
(`extension.js:66-89`, `refreshIndex` at `extension.js:91-121`). Everything the
extension shows — diagnostics (`extension.js:143-169`), hover
(`extension.js:213-222`), go-to-definition (`extension.js:224-235`), completion
(`extension.js:237-314`), inline calc decorations (`extension.js:358-415`),
status bar (`extension.js:128-141`) — is rendered from that one JSON document.
It has no parser of its own and cannot drift from the tool. That is the correct
ownership boundary and this proposal keeps it.

Cost of that shape: a fresh Python process and a whole-project build per
refresh, debounced 250 ms after save (`extension.js:123-126`), and diagnostics
only as of last save. The `refdes serve` snapshot is the same built project
already sitting in memory, rebuilt by a debounced poller
(`src/refdes/serve/state.py:291-311`), with a `/api/revision` endpoint to poll
(`src/refdes/serve/api.py:35`).

### 2.3 A blocker no summary mentions: the shell does not activate on a current project

`findRoot()` walks up looking for `refdes.yaml` (`extension.js:40-51`, the test
at `extension.js:44`), and `activationEvents` is
`["workspaceContains:**/refdes.yaml"]` (`package.json:27`). But `refdes.yaml` is
retired: `refdes-project.yaml` is the project marker and a directory holding
only the legacy file "is not a project" (`src/refdes/schema.py:5`, `LEGACY_CONFIG_NAME`
at `src/refdes/schema.py:47`, the walk rule at `src/refdes/schema.py:341`; and
`src/refdes/serve/edit.py:63` `CONFIG_NAME = "refdes-project.yaml"`).

So the claim "the VS Code extension is the natural second client" is true of its
architecture and false of its current runtime behaviour: **as shipped it does not
activate in a current refdes project, and its "no refdes.yaml found" warning
(`extension.js:423`) is the only thing an author gets.** Nothing in this document
can be exercised in a real VS Code window until that one-line-each fix lands.
It is a bug, not a design question; §8 makes it Slice V−1 and §6 Q4 records it
for the record.

### 2.4 What the server side already ships

`refdes serve` exists and is complete enough to be the only thing an adapter
talks to. Verified surface:

- **Process and launch.** `cmd_serve` constructs one `EditorApp` and prints
  `refdes serve: <launch_url>` as its first line, flushed, before serving
  (`src/refdes/cli.py:230-249`, the print at `:236`). `--no-open` suppresses the
  browser (`src/refdes/cli.py:1379-1381`); `-c/--config` and `--no-write` are
  global flags (`src/refdes/cli.py:1349-1355`). `EditorApp.launch_url` is
  `http://127.0.0.1:<ephemeral>/?token=<256-bit token>`
  (`src/refdes/serve/server.py:293-295`).
- **The API.** `api.handle` dispatches `GET /api/revision`, `GET /api/items`
  (filtered), `GET /api/item/<ref>`, `POST /api/item/<ref>/edit`,
  `GET /api/create/schema`, `GET /api/create/preview`, `POST /api/items/create`,
  `GET /api/images?item=`, `POST /api/assets`, and the three
  `/api/item/<ref>/sources…` reads (`src/refdes/serve/api.py:34-66`).
- **The write service.** `serve.edit.apply_edit(project_root, EditRequest)` is
  the single mutation entry point, with four result types — `Applied`,
  `Conflict`, `Refused`, `Invalid` — and its own per-project write lock
  (`src/refdes/serve/edit.py:199-217`, `write_lock_for` at `:171-183`, the
  seven-step order in the module docstring at `:33-49`). `_apply_edit` maps
  those to 200 / 409 / 422 / 422 / 400 and, on `--no-write`, 403
  (`src/refdes/serve/api.py:372-460`).
- **The browser UI.** 1,783 lines of plain ES modules in
  `src/refdes/serve/static/` (15 files: `app.js`, `editor.js`, `item.js`,
  `links.js`, `create.js`, `images.js`, `drafts.js`, `filters.js`, `list.js`,
  `controls.js`, `preview.js`, `update.js`, `api.js`, plus `index.html` and two
  CSS files). This is the thing a webview would be tempted to re-implement, and
  the size of that temptation should be stated in lines.

## 3. Proposal

### 3.1 One process, one project: how the extension gets a server

`docs/design/browser-editor.md` already answers the process question and this
document does not re-derive it:

> "The command imports refdes modules in-process; it does not shell out to a
> configurable command. One process owns one project, one write lock, and one
> in-memory project revision." (`:592-596`)

Two consequences for VS Code:

1. **The extension cannot embed the server logic.** It is TypeScript in a Node
   process; the semantics are Python. Any attempt to "call the server logic
   directly" is either a reimplementation (forbidden by §4) or a Python
   subprocess.
2. **A Python subprocess *per operation* is ruled out by the same sentence.**
   Each spawn would own its own write lock and no shared in-memory revision or
   snapshot, and would pay a full project build per hover. The lock in
   `write_lock_for` is explicitly per-process (`src/refdes/serve/edit.py:171-183`
   — "the lock stops *this* server from interleaving saves; cross-process
   protection is the content revision"), so N short-lived processes is N locks,
   not one.

So: **exactly one long-lived `refdes serve` process per project, and the
extension is an ordinary HTTP client of it.** How that process comes to exist:

- **Extension-managed (recommended default).** On first use of a refdes feature
  in a workspace, spawn `<refdes.command> -c <config> serve --no-open` as a
  child, read its first stdout line, parse the launch URL. Kill it on
  `deactivate()`. Key the child by resolved project root so one window does not
  spawn two servers for one project.
- **Attach to a server the author started (fallback).** A command that shows an
  input box; the author pastes the launch URL from their terminal and the
  extension parses the token out of it. This works today with **zero server
  change**, because the token is already in the printed URL
  (`src/refdes/cli.py:236`).

Both paths converge on one object — a `ServeClient` holding `{base, port, token}`
— and everything downstream is identical.

**On Option C's "narrow CLI/RPC bridge."** `docs/design/browser-editor.md:215-218`
said a future extension could "invoke the same Python operations through a
narrow CLI/RPC bridge" rather than requiring HTTP. That was written on 2026-09-16,
before `serve/api.py` and `serve/edit.py` existed. They exist now, they are
tested, and they are the narrowest bridge available. Building a *second*
transport to the same services would itself be new server behaviour — new
framing, new error mapping, and a second security review of a surface that today
has one. This proposal therefore uses HTTP and flags the deviation from that
sentence as §6 Q1 rather than pretending the sentence does not say what it says.

### 3.2 The launch token, worked through

This is the hardest part of the adapter, so it gets the mechanism spelled out
before the options.

**What the server demands** (`src/refdes/serve/security.py`, `server.py`):

- Bind is IPv4 `127.0.0.1` on an ephemeral port only; there is no host flag
  (`security.py:24`, `LOOPBACK_ADDRESS`).
- `Host` must be exactly `127.0.0.1:<port>` or `localhost:<port>`, checked
  before routing (`security.py:52-54`, `server.py:388-389`).
- Every `/api/` request — **reads included**, a decision, not an oversight
  (`docs/design/browser-editor.md:968-972`) — must carry
  `X-Refdes-Token: <token>`, compared in constant time
  (`security.py:23`, `:31-35`, enforced at `server.py:510-511`).
- Every `POST` must additionally carry an `Origin` that is one of the two
  accepted origins **and** agrees with the `Host` it arrived on; missing and
  `null` never pass (`security.py:56-66`, enforced at `server.py:514-516`).
- The navigable surfaces (`/edit/`, `/preview/`) take the token as a
  `SameSite=Strict` `HttpOnly` cookie that only the launch URL sets, followed by
  a redirect that strips the token from the address bar
  (`security.py:8-11`, `server.py:402-404`, `:420-429`).

**Why there is no session flow to reuse.** The cookie path is a browser dance:
GET `/?token=…` → `Set-Cookie` → 302. An extension-host HTTP client has no cookie
jar it is required to use and no reason to acquire one — the header path exists
precisely so a non-navigating client can authenticate. And a webview cannot ride
the cookie path into the shipped editor either: `EDITOR_CSP` ends with
`frame-ancestors 'none'` (`security.py:70-83`), so a VS Code webview is refused
as an ancestor of `/edit/` by the server's own headers. That closes the
"just iframe the existing editor" idea (§9.2) and it closes it in shipped code,
not in this proposal.

**How the extension obtains the token.** Five candidate answers, worked:

| # | Mechanism | Verdict |
|---|---|---|
| 1 | **Parse the launch URL off the child's stdout.** `cmd_serve` prints `refdes serve: http://127.0.0.1:<port>/?token=<t>` as its first line, flushed, before `serve_forever()` (`src/refdes/cli.py:236-238`). Spawn with `--no-open` so no browser tab fires, read one line, parse. | **Recommended.** Zero server change; the token never enters argv, never touches disk, never lands in `settings.json`, and dies with the process that owns it. |
| 2 | **Paste the launch URL** (attach to an author-started server). | **Recommended fallback.** Zero server change; the token already passes through the clipboard the same way it passes through the terminal, which the CLI already warns about (`src/refdes/cli.py:237-238`: "keep it out of screenshots and shared terminals"). |
| 3 | A token file (`serve --token-file <path>`), so attach is automatic. | Rejected for v1. It is new server behaviour, it persists a per-launch secret to disk against the design's own rule ("never persist or include it in rendered files/logs", `docs/design/browser-editor.md:942-946`), and it needs a lifecycle — stale files, ownership, Windows ACLs — for a problem #2 already solves. |
| 4 | The extension supplies the token (`serve --token=…`). | Rejected. argv is readable by any local process via the process list, which turns a per-launch secret into a machine-visible one, and it makes the extension the authority on secret generation for a server that already generates a better one. |
| 5 | Persist the token in `SecretStorage` (`context.secrets`) or a setting. | Rejected for the launch token, which is dead the moment its server is. Persisting it guarantees a future "why is everything 403" and stores a secret with no lifetime. (If some credential ever *does* outlive a process, `context.secrets` is the right place — encrypted, per-platform, not synced across machines — and not `settings.json`.) |

**Where the token lives, stated plainly.** In the extension host's memory, in
one `ServeClient` object, and **never handed to a webview**. Webviews cannot
call the VS Code API and communicate only by message passing (VS Code webview
API docs); this design makes that a security property, not a limitation: the
webview posts `{op: "getItem", ref}` and the extension host performs the HTTP
call with the header. Consequences worth naming:

- the token is absent from every webview's HTML, devtools console, and CSP;
- no webview needs `connect-src http://127.0.0.1:*`, so its CSP stays
  `default-src 'none'` plus `webview.cspSource` for its own assets;
- every request the extension makes is one place to log, rate-limit, and test.

**Failure modes, and how each is made loud** (the project's standing rule is
that a quiet failure is the bug class):

- *Child exits or never boots* (bad project, `refdes` not on `PATH`): read
  stderr into the existing Refdes output channel
  (`extension.js:481-483` already creates one) and set the status bar to
  `$(error) Refdes`; hover and CodeLens then say "refdes serve is not running"
  rather than returning nothing. Never a silent empty hover.
- *Port changes every launch*: never cache the port; the only handle is the URL
  parsed this launch.
- *403 from `/api/`*: the token is from a dead launch. Retry the handshake once
  (respawn), then say so in the status bar with the child's stderr one click
  away.
- *An Origin-less POST is refused* (`security.py:56-66`): the client sets
  `Origin: http://127.0.0.1:<port>` explicitly on every mutation, matching the
  `Host` Node derives from the URL. Pin this in a test (§7), because it is the
  kind of header a future refactor drops and the failure is a 403 with no
  explanation.
- *Always use the printed `127.0.0.1` form, never `localhost`.* The Origin/Host
  pair must agree (`security.py:56-66`) and `localhost` may resolve to `::1`
  while the server binds IPv4 only
  (`docs/design/browser-editor.md:936-941`).

### 3.3 What the extension calls

Nothing here is new server behaviour; the right column is shipped code.

| Extension need | Route | Notes |
|---|---|---|
| Is the snapshot current? | `GET /api/revision` | `revision`, `serial`, `stale`, `load_error`, advisory git (`serve/state.py:279-290`). Poll it; do not rebuild. |
| Find an item from a cursor | `GET /api/items` with the filter query | Answered from the built project, never a file scan (`serve/api.py:34-66`, `serve/filters.py`). |
| Everything about one item | `GET /api/item/<ref>` | id, key, type, title, board, workspace, tags, source file/line, body, fields, inheritance, external/origin, append_only, sealed, resolved links in and out, coverage, check state, per-item diagnostics, and the `edit` block (`serve/api.py:221-266`). `<ref>` accepts the handle, the display id, the key, or a retired id some item records in `former_ids:` (`serve/api.py:89-125`). |
| May this field be edited, and why not? | same response, `edit.fields.<name>.{editable,reason}` | The server decides; the client renders. Includes sealed and imported reasons (`serve/api.py:146-215`). |
| Save one field / body / link | `POST /api/item/<ref>/edit` with `expected_revision` | `op` ∈ `set_field`, `set_body`, `add_link`, `remove_link`; results are 200/409/422/422/400, and 403 under `--no-write` (`serve/api.py:372-460`). |
| Conflict screen | same, on 409 | `current_text` and a unified `diff` come back ready to render (`serve/edit.py:106-131`). |
| Create | `GET /api/create/schema`, `GET /api/create/preview`, `POST /api/items/create` | Not in v1 of the adapter (§5). |
| Open the browser form for this item | `…/edit/#/items/<key>` | The exact deep link the server injects into preview pages (`serve/server.py:_decorate`). Open it with `vscode.env.openExternal`; the launch URL's `?token=` sets the cookie and strips itself. |

### 3.4 What VS Code actually offers, and the real tradeoff

VS Code gives an extension four relevant surfaces, and they are not four points
on one slider — they differ in who owns the document, which is the thing that
decides everything else.

**A. Providers over the raw text — no webview.** Hover, CodeLens, diagnostics,
completion, inline decorations: exactly what `extension.js` already does, fed by
the live snapshot instead of a per-save `index --compact` spawn. VS Code owns
the file; the extension owns no state; there is no second UI. Cost: near zero
new surface. Does: shows facts and links out to the real editor. Cannot: author.

**B. A webview view in the sidebar (`WebviewViewProvider`).** One persistent
panel — item list, inspector, diagnostics — that posts messages to the extension
host. VS Code still owns the text files; the webview owns only its own view
state. Cost: a real UI, in a frame, that must be themed (`vscode-dark`/
`vscode-light`/`vscode-high-contrast` and the `--vscode-*` CSS variables) and
kept in step with the browser editor's 1,783 lines. Does: browsing and
filtering without leaving VS Code, and later, buttons that POST.

**C. A custom editor (`contributes.customEditors` + `CustomTextEditorProvider`).**
The shape `docs/design/backlog.md:302` proposed and `docs/design/browser-editor.md:202-219`
deferred. VS Code's own guidance is that custom editors are for replacing the
standard text editor for a resource class, that `CustomTextEditorProvider` uses
VS Code's `TextDocument` as the model and expresses every change through
`WorkspaceEdit`/`applyEdit`, and that webviews are "resource heavy" and should
be used "sparingly and only when VS Code's native API is inadequate" (VS Code
Custom Editor API and Webview API docs). The `selector` is a glob, so
`**/items/**/*.md` would claim every multi-item source file.

The tradeoff is not "more UI vs less UI." It is this:

> **A webview is a second UI to maintain; a custom editor is a second *write
> path* to reconcile.**

§3.5 is why that sentence decides the ordering.

### 3.5 The two-write-path problem (why the custom editor is last, not first)

`apply_edit`'s conflict proof is a hash of the **file on disk**:
`expected_revision` is the sha256 of the target file's bytes as the client saw
them (`serve/edit.py:185-197`, compared under the lock in the step-3 order at
`serve/edit.py:16-37`), and a mismatch is a `Conflict` carrying the current text
and a diff.

A `CustomTextEditorProvider` introduces a second buffer with its own idea of
truth: VS Code's `TextDocument`, which can be **dirty** — full of unsaved edits
the server cannot see. Now put the two next to each other:

1. The author types in the plain text editor; the `TextDocument` is dirty, disk
   unchanged.
2. The custom editor's form POSTs `set_field` with the `file_revision` it read
   earlier. Disk has not moved, so **the server's conflict check passes** and
   the patcher rewrites the item span.
3. The author hits save in the text editor. VS Code writes its whole buffer over
   the file. Step 2's edit is gone, and nothing on either side ever disagreed.

That is precisely the failure the browser design refuses to build a merge for:
"a YAML merge that guesses which of two edits to a hand-authored item wins
produces a file that parses cleanly and means something neither author wrote"
(`docs/design/browser-editor.md:796-800`). A custom editor would reintroduce it
by construction, because VS Code's dirty-buffer model and the server's
content-revision model are two conflict detectors that cannot see each other.
`onDidChangeTextDocument` does not help: it fires for buffer changes, and the
server's write is not a buffer change.

Three honest responses:

- **(i) Don't own the document.** Surfaces A and B never write the file, so the
  problem does not exist. **Recommended.**
- **(ii) A read-only custom editor** (`CustomReadonlyEditorProvider`) that
  renders the item and offers "Open in editor". No save, no undo, no dirty state
  — VS Code's docs note that a readonly custom editor is much simpler to
  implement precisely because it skips save and backup. Viable if a rendered
  per-item view inside the editor area is ever wanted; it is still a webview UI.
- **(iii) A writable custom editor** would have to make the `TextDocument`
  incapable of being dirty except through the API path — i.e. the extension
  becomes the only writer of that file and must re-read after every server save.
  That is a real project, it fights VS Code's model (undo, revert, split editors,
  hot exit), and it buys nothing the browser editor does not already do with a
  tested write path behind it.

Corollary, and it applies to surfaces A/B too: **the extension must never write
an item file with `workspace.applyEdit`.** Every mutation goes through
`POST /api/item/<ref>/edit` with the `expected_revision` it just read, or it
does not happen.

### 3.6 Recommended shape

Surface **A** first, over a real `ServeClient`, read-only. Then **B** only if A
is used enough to justify a panel. **C** not at all in this plan's horizon; if it
ever comes it arrives as (ii), read-only, and it still has to answer §3.5.

## 4. What must NOT be reimplemented

The rule from `docs/design/browser-editor.md:13-16` and the CLI-parity decision
("a second command surface would be a second implementation, and the whole value
of this design is that one Python service sits behind both surfaces",
`:561-562`, recorded as a decision at `:1246-1250`) applies verbatim to TypeScript. Each row is a semantics the
extension must *call*, never *hold*.

| Semantics | Single Python owner | How the client reaches it |
|---|---|---|
| Validation and the delta diagnostic gate | `serve/edit.py` step 6, `_apply_locked` (`:16-37`) | Implicit in every `POST`; blocking diagnostics come back on 422 (`serve/api.py:454-465`). |
| Source patching and fidelity | `src/refdes/patcher.py` via `apply_edit` | The client sends an intent (`set_field`, `set_body`, `add_link`, `remove_link`), never a range, offset, or text span. |
| Conflict detection | `file_revision` / `state.content_hashes` (`serve/edit.py:185-197`) | The client stores and echoes `file_revision`; it never decides whether disk moved. |
| Sealed-entry refusal | `seal.is_sealed`, repeated under the write lock (`serve/api.py:163-164`, `serve/edit.py` step 4 at `:25-26`) | The client renders `sealed`/`editable:false`/`reason`; the server refuses again regardless. |
| Imported-item read-only | same `edit_state` block (`serve/api.py:161-164`) | Rendered, not re-derived. |
| Identity: display IDs, keys, ledger | `ids`/`keys` via `create_item` (`serve/edit.py:586`) | `GET /api/create/preview` is advisory; the authoritative allocation is under the save lock. |
| Link composites `DISPLAY-ID@key` | `src/refdes/links.py` | The client sends a handle, display id, or key; Python writes the composite. |
| Allowed link target types | `ItemType.links` (`serve/api.py:201-210`) | Sent per verb; the picker filters by what it is told. |
| Field controls, required-ness, enum choices | `edit_state` / `create_schema` (`serve/api.py:146-215`, `:392-430`) | The client renders `control`, `choices`, `required`, `value_type`. |
| Dates in the project's `date_format` | `src/refdes/dates.py` | `date_format` arrives from `/api/create/schema`. |
| Diagnostics and their attribution | the build; `_diagnostics_for` (`serve/api.py:100-120`) | Payload only. |
| Filtering semantics | `serve/filters.py` | Query params; the client never filters a file scan. |
| Markdown image reference spelling | `api.image_markdown` / `referenceable` (`serve/api.py:646-675`) | The `markdown` field is inserted verbatim. |
| `source("…","…")` composition | `sources.propose_payload` (`serve/api.py:325-352`) | "the browser never assembles the text and never learns the grammar" — same rule for TypeScript. |

What the extension may own, exhaustively: the HTTP client and its token, the
mapping from a VS Code cursor position to an item ref, the rendering of
server-provided state, and VS Code-specific affordances (CodeLens, hover,
Problem matcher, decorations). The existing TextMate grammar stays the one
exception the README already declares (`editors/vscode/README.md:109-110`), and
this proposal adds no second exception.

## 5. Non-goals for v1

- **No writes at all from VS Code.** Read-only hover/CodeLens/diagnostics and a
  jump to the browser form. Writes are §8's last slice and may be cut forever.
- **No `CustomTextEditorProvider`**, for the reasons in §3.5.
- **No item creation, no link editing, no asset upload, no source-value picker**
  in VS Code. Those exist in the browser editor; duplicating a form is exactly
  the second-UI cost §3.4 names.
- **No drafts.** The browser's draft story is `sessionStorage` in a tab
  (`docs/design/browser-editor.md:763-780`). VS Code has no equivalent that is
  not a persistence layer nobody asked for; a closed panel discards.
- **No conflict UI beyond showing the server's text.** If a write slice ever
  lands, the 409 payload's `current_text` and `diff` are displayed as-is with
  the same three offered outcomes — keep mine, keep theirs, copy by hand
  (`docs/design/browser-editor.md:790-793`) — and no merge.
- **No rename, no schema/settings/defaults/section editing, no git UI** — same
  deferrals as the browser editor.
- **No remote or web VS Code.** `refdes serve` binds loopback *in the machine it
  runs on*; over SSH/WSL/devcontainers that loopback is not the client's
  loopback. Port forwarding is a support question, not a v1 feature, and the
  honest v1 statement is "local VS Code, local server".
- **No webview panel serializer, no hot-exit integration, no undo/redo** for
  refdes state.
- **No marketplace publishing changes.** Whether and when the extension is
  published is untouched here.
- **No removal of `refdes index --compact`.** It stays the fallback when no
  server is running (§6 Q3).

## 6. Open questions for Jared

**Q1 — Transport: HTTP to `refdes serve`, or the "narrow CLI/RPC bridge" Option C named?**
`docs/design/browser-editor.md:215-218` promised a future extension could go
through a CLI/RPC bridge instead of HTTP.
*Recommendation:* HTTP. The bridge sentence predates `serve/api.py`; the HTTP
surface is shipped, tested, loopback-only, and token-gated, and a second
transport would be new server behaviour with its own security review. Accept the
cost: using the adapter means running the server (§3.1).

**Q2 — Who owns the server process?**
*Recommendation:* the extension spawns `refdes -c <config> serve --no-open`
lazily on first refdes feature use and kills it on deactivate, one child per
resolved project root; plus a `Refdes: Attach to running server` command that
takes a pasted launch URL. No new server flags.

**Q3 — Keep `refdes index --compact` in the extension, or move everything to the API?**
Two fetch paths is a smell, but the existing providers work today and the API
payload is a different shape.
*Recommendation:* keep `index --compact` as the fallback and add the server only
for what it uniquely provides — per-item view, attributed diagnostics, coverage,
check state, `edit` affordances, and `/api/revision` freshness. One rendering
path per feature, two fetch paths, and the choice is visible in the status bar
("snapshot" vs "index"). Revisit if the split starts producing different answers
for the same fact — that would be a bug worth a test (§7).

**Q4 — The stale activation marker (`refdes.yaml`).**
Not really a question — the extension cannot activate on a current project
(§2.3). *Recommendation:* fix it first, as its own one-commit change
(`extension.js:44`, `extension.js:423`, `package.json:27`), before any adapter
work, since nothing else here is testable in a real window until it lands.

**Q5 — May VS Code ever write?**
*Recommendation:* not in v1. If it ever does, the only permitted write is
`POST /api/item/<ref>/edit` with a freshly-read `expected_revision`;
`workspace.applyEdit` on an item file is banned outright, and §7 pins that with
a test that greps for it.

**Q6 — Two VS Code windows on one project: one server or two?**
Window B cannot attach to window A's server — discovering another process's
token is exactly what §3.2 refuses to build.
*Recommendation:* let each window spawn its own. Cross-process safety is the
content revision, not the lock (`serve/edit.py:171-183`), so a lost update is
still impossible; the costs are N previews and N pollers, and two snapshots that
can transiently disagree (each converges within the poll interval,
`serve/state.py:291-311`). Name that in the UI rather than pretending it away.
If it turns out to hurt, the fix is Q3.2's token file, reopened with evidence.

**Q7 — Should the rendered preview live in VS Code (a webview framing `/preview/`)?**
*Recommendation:* no. Framing needs a CSP change (`PREVIEW_CSP`/`EDITOR_CSP`
`frame-ancestors`, `security.py:70-96`) and a cookie ride a webview cannot
take, which is new server behaviour weakening a shipped posture.
`vscode.env.openExternal` on the launch URL already gives the same review, and
the extension's existing "Open built site" command
(`extension.js:455-468`) is the shape to upgrade to the live preview URL.

**Q8 — How much of the browser editor's look should the adapter match?**
*Recommendation:* none of it in v1 (no webview). If B lands, use VS Code's own
theme variables, not the browser's `style.css` — a panel that mimics the web UI
inside VS Code is the "easily out of place" failure the webview docs warn about.

## 7. Named tests

The project's convention is to verify against the real thing and make quiet
failures loud: `tests/serve_support.py` drives a live `EditorApp` over real
sockets, `tests/test_serve_editor_e2e.py` replays one author session and hashes
the whole tree between steps, and `tests/test_no_write.py` pins byte-identical
trees. The adapter's tests follow the same posture, and the split is deliberate:
**the facts the extension depends on are pinned in Python, where CI runs them.**

### 7.1 Python-side contract tests (`tests/test_vscode_adapter_contract.py`)

These do not test the extension; they pin the guarantees the extension is built
on, so a server change that breaks the adapter fails in CI rather than in
Jared's window.

- `test_serve_prints_launch_url_as_first_stdout_line` — spawn the real CLI
  (`python -m refdes.cli -c <cfg> serve --no-open`) as a subprocess, read one
  line, assert the exact `refdes serve: http://127.0.0.1:<port>/?token=<t>`
  shape, then use the parsed token against `GET /api/revision` and assert 200.
  This is §3.2 option 1, and it is the single test that lets the extension parse
  stdout at all.
- `test_launch_url_token_never_appears_in_argv` — assert the child's command
  line contains no token, so the recommendation in §3.2 stays true.
- `test_token_gates_reads_as_well_as_writes` — `/api/items` without
  `X-Refdes-Token` is 403; with it, 200. (Pins the decision at
  `docs/design/browser-editor.md:968-972` for a client that will be tempted to
  skip it on reads.)
- `test_mutation_without_origin_is_refused` and
  `test_mutation_origin_must_match_host` — an `Origin`-less POST and an
  `Origin: http://localhost:<port>` POST against `Host: 127.0.0.1:<port>` are
  both 403. These two are the reason the client sets `Origin` explicitly
  (§3.2), and they are the header a future refactor is most likely to drop.
- `test_item_view_reports_edit_state_for_every_field` — every field in
  `GET /api/item/<ref>` carries `editable` and, when false, a non-empty `reason`;
  on a sealed log and an imported item, every field is false with the same
  reason. The extension renders these verbatim, so "the UI never decides
  editability itself" (§4) is a server-side assertion.
- `test_conflict_payload_carries_current_text_and_diff` — edit the file behind a
  held `file_revision`, POST, assert 409 with non-empty `current_text` and
  `diff`, and assert the file is byte-identical afterwards. The conflict screen
  in a later write slice has nothing else to work with.
- `test_no_write_server_refuses_every_mutation_route` — under `--no-write`,
  `POST /api/item/<ref>/edit` is 403 and the tree does not move, matching the
  second test of `test_serve_editor_e2e.py`.
- `test_editor_csp_refuses_framing` — `GET /edit/` (via the cookie flow) carries
  `frame-ancestors 'none'`, pinning §9.2's rejection in shipped behaviour.
- `test_deep_link_shape_matches_server_toolbar` — the `/edit/#/items/<key>` the
  preview toolbar injects is the same shape the extension's "Open in editor"
  builds, so the two affordances cannot drift.

### 7.2 Extension-side tests

There is no JS test harness in the repo today (no `scripts`, no
`devDependencies`; `.vscodeignore` merely anticipates `.vscode-test/`). Rather
than add a Node test runner CI does not run, drive the extension's own logic
from pytest:

- `tests/test_vscode_extension_http_client.py` — a pytest module that shells out
  to `node` against the real `ServeClient` module
  (`editors/vscode/serveClient.js`, a pure module with no `vscode` import so it
  is testable without an extension host), pointed at a live `EditorApp` fixture,
  and asserts: it parses the launch line, it sends `X-Refdes-Token` on reads, it
  sends a matching `Origin` on POST, a 409 surfaces `current_text`/`diff`, and a
  dead child produces an error object rather than a hang.
  `@pytest.mark.skipif(not shutil.which("node"))` — and the skip is loud: the
  module emits a `pytest.skip` reason naming the file that did not run, so a
  machine without Node reports "not verified" instead of "verified".
- `test_no_direct_item_file_writes_in_extension_source` — grep
  `editors/vscode/*.js` for `applyEdit`, `fs.writeFile`, `fs.appendFile`, and
  `fs.writeFileSync` touching an item path, and fail on a match. This is §4's
  "never a second write path" enforced as a test rather than as a comment.
- `test_extension_activates_on_current_project_marker` — assert
  `package.json`'s `activationEvents` and `extension.js`'s `findRoot` name
  `refdes-project.yaml` and that neither names the retired `refdes.yaml`. Cheap,
  and it is the regression that made the whole extension dead in the water
  (§2.3).
- `test_hover_facts_come_from_the_api_not_a_local_guess` — for one fixture item,
  compare the hover payload the Node module builds against
  `GET /api/item/<ref>` field by field; any fact the hover shows that the API
  did not say is a failure. This is the drift test for Q3's two fetch paths.

A full `@vscode/test-electron` harness (real extension host, real webview) is
deferred to whatever slice first ships a webview, and is explicitly *not* a
prerequisite for the read-only slice.

## 8. Phasing

Every other editor capability in this repo went read-first: Slice 0 was
side-effect-free loading, the source picker landed Slice A ("the service reads")
before any Accept, the image picker landed as Phase 0 with no upload, and the
browser editor's own Slice 1 was read-then-write
(`docs/design/browser-editor.md:1038-1070`; `docs/design/editor-source-picker.md`
status header; `docs/design/editor-image-upload.md` §17 Phase 0). The adapter
follows the same order, and the first slice is deliberately smaller than
anything above.

**Slice V−1 — make the shell alive (a bug fix, not a feature).**
`findRoot` and `activationEvents` point at `refdes-project.yaml`
(`extension.js:44`, `package.json:27`); the warning text follows
(`extension.js:423`); README setup follows. Nothing in V0 can be seen in a real
window until this lands. No design content; included because a plan that starts
with an extension that does not activate is not a plan.

**Slice V0 — read-only hover and one deep link. (The slice that proves the token.)**

- `ServeClient`: spawn `<refdes.command> -c <config> serve --no-open`, parse the
  first stdout line, hold `{base, port, token}` in memory, kill on deactivate;
  plus `Refdes: Attach to running server` taking a pasted launch URL.
- One new fact per item, from `GET /api/item/<ref>`: coverage stage, check state,
  and the item's own attributed diagnostics, added to the existing hover
  (`extension.js:213-222`).
- A CodeLens on an item's `id:` line offering **Open in editor**, which opens
  `…/edit/#/items/<key>` externally.
- Status bar states for "no server", "starting", "snapshot serial N", and
  "server died", each with the output channel behind it.
- **No webview, no writes, no new server code, no new server flags.**

V0 is the whole token question, the whole process-lifecycle question, and the
whole "does the extension host talk to this API correctly" question, resolved
against the real server, at the cost of a hover. If it is not used, nothing
further is built — which is the point of making it this small.

**Slice V1 — read-only sidebar view (only if V0 earns it).**
A `WebviewViewProvider` panel: the filtered item list from `GET /api/items`, and
the selected item's inspector from `GET /api/item/<ref>`, with "Open in editor"
as the only action. Still no writes. This is the first place the second-UI cost
of §3.4 is paid, and it is paid only after V0 shows the demand.

**Slice V2 — writes (may be cut permanently).**
Field and body editing from the sidebar form, through
`POST /api/item/<ref>/edit` with a freshly-read `expected_revision`; the 409
payload rendered as-is with keep-mine / keep-theirs / copy-by-hand and no merge.
Link editing, creation, upload, and the source picker stay in the browser editor
until someone makes the case that doing them without leaving VS Code is worth a
second form.

**Never in this plan:** a writable `CustomTextEditorProvider` over `items/**`.
If it is ever proposed, §3.5 has to be answered first, in writing.

## 9. Considered and rejected

**9.1 A Python subprocess per operation (or embedding refdes in the extension host).**
Rules out the single-process invariant the design already settled
(`docs/design/browser-editor.md:592-596`): N locks, no shared revision or
snapshot, a full build per hover, and — since no CLI command exists for
`apply_edit` — a new flag language mirroring the form, which the CLI-parity
decision explicitly refuses (`docs/design/browser-editor.md:1246-1250`).

**9.2 Iframe the existing `/edit/` inside a webview.**
Refused by shipped code, not by taste: `EDITOR_CSP` ends with
`frame-ancestors 'none'` (`src/refdes/serve/security.py:70-83`), and the session
is an `HttpOnly` `SameSite=Strict` cookie only the launch URL sets
(`security.py:8-11`, `server.py:420-429`). Relaxing either to make framing work
weakens a posture the browser editor was designed and tested behind, for the
convenience of not writing a client.

**9.3 A token file or an extension-supplied token.** §3.2 rows 3 and 4: new
server behaviour, a per-launch secret persisted to disk or exposed in argv, for
a problem the pasted-URL fallback already solves.

**9.4 A stdio JSON-RPC bridge to the same services.** Genuinely attractive on
paper — no port, no token, the pipe is the trust boundary — and it is the closest
reading of Option C's "narrow CLI/RPC bridge". Rejected for v1 because it is new
server behaviour (framing, error mapping, a second transport's security review)
while the HTTP surface is shipped and tested, and because the token problem it
solves has a zero-server-change answer (§3.2). Reopen if Q6's multi-window case
or a remote-session case ever produces real evidence.

**9.5 Reimplementing the browser form in a webview as the first slice.**
1,783 lines of `serve/static/` plus the write path's four-way result handling,
re-expressed in a second UI, with §3.5's two-write-path problem attached. The
read-only-first ordering in §8 exists to make this unnecessary until there is
evidence it is wanted.
