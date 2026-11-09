# Refdes for VS Code

Live diagnostics, ID completion, hover previews, go-to-definition, and inline calc
results for [Refdes](https://github.com/Squishiba/refdes) projects — reference
documentation for hardware design decisions.

## Setup

This extension is a thin client over the `refdes` command line tool, so **install
that first**:

```
pip install refdes
```

Then open any folder containing a `refdes-project.yaml`. The extension activates on
its own.

If `refdes` is not on your `PATH` — for instance it lives in a project virtualenv —
point the setting at it:

```json
{
  "refdes.command": ".venv/Scripts/python.exe -m refdes.cli"
}
```

A status bar item appears once the project loads. If it never shows up, the
extension could not run the CLI; check the setting above.

## What it does

**Inline calc results.** Evaluated values appear greyed at the end of each line in
a `calc` block, updating on save:

```calc
V_out            = 3.3 V                                     → 3.3 V
P_diss           = V_out * I_load * (1/eff - 1) | W           → 0.2981 W
P_dens           = P_diss / A_board | W/in^2                  → 0.2366 W/in²
```

Values with tolerance show their bounds; a failed line shows the error inline.
Toggle with **Refdes: Toggle inline calc results**.

**Diagnostics.** Errors and warnings appear as squiggles and in the Problems panel,
refreshed on save. Includes everything the CLI reports — unit mismatches, failing
checks, broken links, unverified requirements, append-only violations.

**Completion.** Type two or more uppercase letters, or `[[`, to get item IDs with
their titles. Matching isn't limited to the id and title: the file an item is
declared in and its board (when the project has boards) are also part of what
gets matched, so typing `power` narrows the dropdown to items declared in
`power.yaml`, or on the `power` board, even before you remember how its id
starts. After a field name like `status:`, you get that field's allowed
values from the schema. At the start of a front-matter line, once the current
item's `type:` is known from context, you get that type's own field and link
key names — the same data, just a second way of using it, and the piece that
closes the gap `.yaml`'s `yaml.schemas` completion (below) can't reach for
`.md` files.

**Schema completion for `.yaml` list files.** This extension declares
`redhat.vscode-yaml` as a dependency and `refdes init` writes
`.vscode/settings.json` pointing `yaml.schemas` at `.refdes/schema.json` —
together they give full IntelliSense (required fields, `additionalProperties:
false` catching a typo the moment it's typed, hover documentation) for
`items/**/*.yaml`. This does **not** currently work for `.md` front matter —
an upstream vscode-yaml limitation, not a refdes gap — which is what the
field/link key completion above exists to cover in the meantime. See [editor
support](https://github.com/Squishiba/refdes/blob/main/docs/standard-library.md#editor-support-json-schema-emission)
for the full story.

**Hover.** Hover any ID for its type, title, key fields, coverage stage, and any
failing checks. An item that was [renumbered](https://github.com/Squishiba/refdes/blob/main/docs/ids.md#renumbering-former-ids)
also says *formerly known as …*, so hovering the id you have from a schematic
or a commit message tells you which item it is now. When a live snapshot is connected (see [Live snapshot](#live-snapshot)),
the hover also carries the three facts only a snapshot has — coverage stage, check
state, and the diagnostics attributed to that item — under a *From `refdes serve`*
heading.

**Go to definition.** <kbd>F12</kbd> or ctrl-click an ID to jump to where it is
defined, including inside a list file or a multi-item markdown file (several
`---`-fenced items sharing one `.md` file, optionally under a leading
`defaults:` block).

**Open in editor.** A CodeLens sits on an item's own `id:` line. It opens that
item's form in the browser editor, in your system browser. The extension never
renders a form and never writes an item file — the browser editor owns both.

**Syntax highlighting** for `calc` blocks in both markdown and YAML bodies —
variables, units, unit assertions, numbers, functions, and tolerances.

**Commands** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>):

| Command | Does |
|---|---|
| Refdes: Build site | `refdes build --keep-going` |
| Refdes: Check | `refdes check` |
| Refdes: Allocate missing IDs | `refdes id` |
| Refdes: Open built site | Opens `_site/index.html` |
| Refdes: Refresh index | Re-reads the project |
| Refdes: Toggle inline calc results | Show/hide the inline values |
| Refdes: Attach to running server | Use a `refdes serve` you started yourself |
| Refdes: Show server log | The output channel behind the snapshot status item |
| Refdes: Refresh Navis | Re-reads the Navis list (starts the server if needed) |
| Refdes: Mint keys | Writes a key into every keyless Navi marker — asks first |

A status bar item shows item count and error count; click it to run a check. A
second one shows the live snapshot — see below.

## Live snapshot

Three of the facts above — an item's coverage stage, its check state, and the
diagnostics attributed to it — come from a running `refdes serve` rather than from
`refdes index`, because a snapshot is the only place they exist as *current* state.
Everything else still comes from the index, and which path produced what stays
visible in a second status bar item:

| Status | Means |
|---|---|
| `Refdes: no server` | nothing has asked for a snapshot fact yet |
| `Refdes: starting server` | `refdes serve` is booting |
| `Refdes: snapshot 7` | connected — 7 is the serial from `GET /api/revision` |
| `Refdes: server died` | the process exited, or stopped answering |

Click it for the Refdes output channel, which carries everything the server printed,
prefixed `[serve]`.

The server starts on demand — the first hover on an ID asks for it — one per project
per window, and it is killed when the window closes. Its launch token lives in the
extension host's memory and nowhere else: not in a setting, not on disk, not in a
command line. It never appears in the output channel either.

To run the server yourself instead — to watch it, or to share it with a browser tab —
start it and paste the launch URL it prints into **Refdes: Attach to running server**.
If a hover shows no snapshot facts, the status item says why.

## Follow the cursor (docs-context)

`refdes.docsContext.url` points the extension at a running docs-context viewer
(`python tools/docs_context/server.py <page>.md`), a maintainer tool that renders the
references one docs page makes. With the setting on, moving the cursor in an open file
inside the workspace posts `{path, line}` — the workspace-relative path and the 1-based
cursor line — to `/api/focus` on the url's origin (a path in the url is ignored), so
the viewer scrolls to the block you are looking at. Nothing else travels: never file
contents, never selection text.

Off by default (empty string = no network call of any kind). Only loopback urls are
honoured (`127.0.0.1`, `localhost`, `::1`); any other host is ignored with a single
line in the Refdes output channel, because the extension never posts file paths off
the machine. Posts are debounced (~300 ms) and fire-and-forget: failures produce at
most one throttled output-channel line, never a popup, and clearing the setting stops
posting immediately.

## Navis view

The Explorer gains a **Refdes Navis** section listing the project's Navis —
the same rows the site panel and the served preview render, read live from
`GET /api/navis` on the window's `refdes serve`. The section starts collapsed,
and expanding it asks for the server, exactly like the first hover does (one
per project per window, killed when the window closes) — opening a project
starts nothing.

- Active Navis are listed in the projection's order, labelled `key6 · text`
  (long texts truncate; the full text is in the tooltip). Archived ones sit
  behind a **Show all (N)** group, a keyless row says *No key yet — use Mint
  keys*, and an archived row whose marker was hand-deleted says *marker not
  found*. When keyless rows exist, a **Mint keys (N)** row sits on top of the
  list; **Refdes: Mint keys** is also in the command palette and on the
  section's title bar.
- Clicking a row opens the marker's file at its line; an archived row opens
  the location its record snapshot saved. The row's inline globe action,
  **Refdes: Open Navi in editor**, hands the row's item to the browser
  editor's form through the same deep link as the CodeLens. A keyless row has
  no item form to open, and says so.
- The row menu carries the writes. **Refdes: Archive Navi** shows on keyed
  active rows, **Refdes: Restore Navi** on keyed archived rows (an archived
  row with no marker keeps Restore disabled with the hand-restore hint).
  Neither touches a body byte: archiving writes one gzip record under
  `.refdes/navis/`, restoring deletes it, so `git diff` stays empty.
  **Refdes: Mint keys** is the one action that writes files — it splices a
  key into every keyless marker in the project — so it asks one modal
  confirmation first. Clean editors of the touched files reload from disk; a
  dirty buffer gets VS Code's own external-change prompt (the same note goes
  to the Refdes output channel). The mint is project-wide and idempotent; if
  some markers cannot be keyed (a flow-style YAML list body, say), the mint
  says how many stayed keyless.
- The section's badge counts the active rows. The list refreshes on save, on
  **Refdes: Refresh index**, on **Refdes: Refresh Navis**, and whenever the
  snapshot serial moves.

The rows come from the served snapshot, which is disk state, so a row can lag
an unsaved editor buffer — the same lag the preview panel has. A Navi archived
in a terminal (`refdes navis archive`) shows up on the next refresh, not
instantly: the archive is read at request time and moves no watched input, so
nothing pushes.

| Situation | What you get |
|---|---|
| No `refdes-project.yaml` found | the view says *No refdes-project.yaml found.* |
| No server started yet | the view says *No server — hover an item, or run Refdes: Attach to running server*; expanding the view starts one; a write command answered before that says *refdes serve is not running* |
| Server died, or a stale launch token | the view says *Refdes: server died — run Refdes: Attach to running server*; a stale token goes through the same respawn/re-attach recovery as the hover poll |
| A project with no Navis | the view says *No Navis in this project* |
| `refdes --no-write serve` | reads work; the first write shows the server's own refusal, locks Archive, Restore and Mint for the rest of the session, and the status bar shows a lock and *Refdes: read-only* (the refusal as its tooltip) until a new server starts or you attach to one |

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `refdes.command` | `refdes` | How to invoke the CLI |
| `refdes.checkOnSave` | `true` | Re-index and publish diagnostics on save |
| `refdes.showCalcResults` | `true` | Inline calc values |
| `refdes.docsContext.url` | `""` | Docs-context viewer url to follow the cursor (loopback only; empty = off) |

## How it works

Almost everything comes from one call to `refdes index --compact`, which emits the
whole project as JSON — items, fields, links, source locations, calc results,
coverage, and diagnostics — without rendering the site. The three live-snapshot
facts come from `GET /api/item/<ref>` on `refdes serve` instead. Either way the
server decides them and the extension renders them: it has no parser and no
validation logic of its own, so it cannot drift from the real tool. Where the two
paths could disagree about the same fact — coverage stage — the snapshot's answer
is the one the hover shows, and the status item tells you a snapshot is behind it.

The one exception is the TextMate grammar, which necessarily re-implements the unit
lexer. If highlighting and the parser ever disagree, the parser is right.

## Not yet

- **Live preview pane.** "Open built site" opens the built HTML in a browser. A
  proper in-editor webview with auto-refresh is the obvious next step.
- **Diagnostics as you type.** Currently on save; live would need debounced runs
  against unsaved buffers.
- **Snippets** for new requirements, decisions, and log entries, inserted directly
  in the editor. `refdes new <type>` covers the same need today from the CLI —
  `refdes new decision > items/power/dec-005.md` — generated from the identical
  resolved schema, just not yet wired into VS Code's own snippet/IntelliSense UI.

## Developing

No build step — it is plain JavaScript. Open `editors/vscode/` in VS Code and press
<kbd>F5</kbd>; a second window opens with the extension loaded. Open a folder
containing a `refdes-project.yaml` in that window.

There is automated coverage, but it is static rather than live.
`tests/test_vscode_extension.py` runs with the project's test suite and checks
this extension's source as text against the server it talks to: the activation
marker, the `refdes serve:` launch line, the `X-Refdes-Token` header, the
item-view facts the hover renders, and the ban on writing an item file from
here. `tests/test_vscode_adapter_contract.py` pins the server side of that same
contract, driving a real `refdes serve` over real sockets.

What that does not do is run the extension inside VS Code: there is no
`@vscode/test-electron` harness, so checking the features above still means
exercising them in a real instance. Reading the source can show the pieces are
wired together, but it is not the same as having watched them work.

## Licence

MIT.
