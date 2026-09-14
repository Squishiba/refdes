Status: draft proposal — not decided.

# Browser-based editor for refdes

## Recommendation

Add a local `refdes serve` command with two deliberately separate surfaces:

1. the existing rendered site, rebuilt and served as a preview; and
2. an `/edit/` application for structured authoring.

The editor is a thin browser client. Python remains the only implementation of
the schema, parser, validator, ID ledger, surrogate keys, link resolver,
Markdown renderer, figures, seals, and writes. The browser uses plain,
prebuilt ES modules and CSS shipped in the Python wheel. It does not require
Node, npm, a JavaScript framework, or a JavaScript build step.

This is a view over the existing plain-text files, not a new storage model.
YAML and Markdown remain the source of truth; `refdes check`, hand editing,
git diffs, and CI continue to work without the editor. The generated `_site/`
also stays an ordinary static site: the README promises no server, no reader
build step, and operation with JavaScript disabled (`README.md:339-356`). No
editor control, token, or write API is emitted into `_site/`.

The first released editor comprises Slices 0–3 below. Internal slices may land
separately, but Slice 1 alone is not the promised first version: creating all
item types including log entries, editing fields and Markdown bodies, and
adding/removing valid links must all work before the browser editor is called
shippable.

## Goals and non-goals

### First-version goals

- Browse and search local items using their current rendered context.
- Edit every supported field shape on an existing item. Schema fields drive
  the controls: text/person/limit inputs, enum selects, date inputs, scalar
  lists, and row editors for structured fields such as options, checks, and
  citations.
- Edit Markdown bodies in both representations: text after Markdown front
  matter and `body:` in a YAML list entry. Support Markdown, calc blocks,
  local images, figure attributes, `[[ITEM-ID]]`, and `[[fig:id]]` as source
  text, with an authoritative rendered preview.
- Add and remove structured links. Each link picker filters to the target
  types allowed by the current item's schema and writes a
  `DISPLAY-ID@surrogate-key` composite.
- Create every item type, including log entries. Allocate its display ID from
  the ledger and mint its surrogate key in the same transaction.
- Preserve hand-authored source outside the intended edit, detect concurrent
  changes, and never edit a sealed append-only entry.
- Show authoritative diagnostics before and after saving.

### Deferred

- Display-ID rename. The first version displays the ID as read-only. The
  display-half refresh has landed, but rename waits until that machinery has
  been exercised independently on real projects.
- Uploading or managing image files. The body editor can reference existing
  project files in the first version; upload is a later capability.
- Editing project settings, schema overlays, defaults blocks, section markers,
  narrative pages, baselines, seals, or ID-ledger files directly.
- Git staging, commits, branch switching, merge resolution, or history UI.
- A VS Code custom editor. VS Code may later host the same application model,
  but it is not the primary product.
- Remote or multi-user service operation.

## What exists today

### Data and authoring model

Refdes has one semantic item model and two source representations. Markdown
files may contain multiple fenced items plus a leading defaults block and
section markers; the text after each closing fence is that item's body
(`src/refdes/parse.py:484-625`). YAML files contain an `items:` sequence and
may also apply defaults and section markers (`src/refdes/parse.py:628-688`).
`id`, `type`, `history`, `body`, `former_ids`, and `key` are engine-reserved;
`prefix`, `board`, and `workspace` are conditionally overridable
(`src/refdes/parse.py:28-37`).

The parsed `Item` deliberately carries raw link spellings separately from
resolved, current display IDs. Writes and hashing need the raw value, while
graph traversal must use `resolved_links` (`src/refdes/model.py:335-367`). An
editor DTO therefore cannot flatten these two views.

The existing `items_json()` is useful but insufficient as the editor protocol.
It exports type field/link definitions and item source locations
(`src/refdes/render.py:394-434`), diagnostics and next-ID data
(`src/refdes/render.py:462-484`), but its item records do not include the raw
body or surrogate key (`src/refdes/render.py:414-459`). The editor API should
be generated from the same `Project`, `ItemType`, and `Item` objects, not by
parsing `items.json` back into a second model.

`refdes new TYPE` already generates required/defaulted fields and link hints
from the resolved `ItemType`, rather than per-type templates
(`src/refdes/scaffold.py:134-172`). Creation should reuse that resolved schema
logic, not parse the command's textual scaffold.

### Site and editor support

The current item page already puts fields, body, links, backlinks, source
location, and content hash in one review surface
(`src/refdes/templates/item.html.j2:5-63,148-202`). That makes the rendered
site the right preview and navigation context, but not the right place to hide
a write-capable application in static output.

The VS Code extension establishes the correct ownership boundary. It is plain
JavaScript and obtains items, schema-derived data, source locations, and
diagnostics by invoking `refdes index --compact`; it has no parser of its own
(`editors/vscode/extension.js:1-9,72-125`). It already publishes diagnostics,
completion, hover, and definition support, but registers no webview or custom
editor (`editors/vscode/extension.js:478-513`).

### Surrogate-key end state

This proposal targets the specified end state in `docs/design/keys.md`, not
only the code present while this document was written:

- Each item has an opaque immutable key; storage remains readable plain text
  (`docs/design/keys.md:3-15`).
- A structured link is stored as `DISPLAY-ID@key`; only the key resolves and
  the display half is tool-maintained (`docs/design/keys.md:380-403`).
- A renamed target refreshes inbound composite labels, with an ambiguous stale
  label reported rather than silently changed (`docs/design/keys.md:468-490`).
- Seals and baselines ultimately key records by surrogate key, with display ID
  retained only for readability (`docs/design/keys.md:662-715`).

At the baseline inspected for this proposal, composite expansion,
display-half refresh, and corruption lint Layers 1–5 are implemented.
`refdes keys adopt` and the planned `revise.py`/`former_ids.py`
simplification remain design only (`docs/design/keys.md:17-26`). Rename is
still deferred from v1 so the newly landed refresh path can be exercised
before the editor depends on it; adoption remains a prerequisite where
called out below.

## Shapes considered

### A. Edit in place on the rendered site

`refdes serve` could decorate every rendered item page with editable controls.
This has the smallest context switch and reuses the page that already shows
traceability and checks.

The boundary is dangerous. Generated HTML is currently a publishable artifact,
not an application shell. Conditional editor markup in the Jinja templates
would make security depend on which render mode called them and invite editor
assets or API assumptions into `_site/`. It would also force a review-oriented
page to carry form state and save conflicts.

**Verdict:** reject direct edit-in-place. Keep the site as preview, and allow a
server-only “Edit this item” link or toolbar to navigate to `/edit/items/<key>`.
That link is injected into the HTTP response or server preview wrapper; it is
never written by `render_site()`.

### B. Separate editor application served by `refdes serve`

A separate `/edit/` shell gives editing state, conflicts, diagnostics, and
security an explicit home. It can preserve the current site unchanged and
open a preview beside the form. Python can expose exactly the schema and item
operations the form needs without exposing filesystem paths as write targets.

The cost is a second presentation surface and some duplicated navigation. The
mitigation is to reuse design tokens/CSS where sensible, deep-link both ways,
and keep the editor utilitarian rather than recreate every report.

**Verdict:** recommended, paired with the rendered preview.

### C. VS Code `CustomTextEditorProvider`

A custom editor could reuse the existing extension and gain VS Code document
versions, workspace edits, tabs, and source diff tools. The backlog originally
named this shape (`docs/design/backlog.md:172-204`).

It is not a general browser editor; it requires VS Code and makes a multi-item
source file's ownership awkward because one custom editor normally owns one
text document while this UI edits one semantic item. Webview CSP, extension
packaging, and host message plumbing are additional constraints. It also
makes the authoring surface unavailable to someone reviewing the local site in
an ordinary browser.

**Verdict:** later adapter. Share application services and DTOs, not an HTTP
server requirement: a future extension can invoke the same Python operations
through a narrow CLI/RPC bridge.

### D. Serverless browser application

The File System Access API could let a static page open a project directory.
It removes the local server, but replaces it with Chromium-specific permission
behavior and cannot directly reuse the pip-installed Python parser, checker,
renderer, ledger, keys, or seals. Reimplementing them in JavaScript would
create a second refdes; shipping Pyodide would be much larger and slower than
the feature.

**Verdict:** reject.

### Comparison

| Shape | Semantic reuse | Source safety | Browser-independent | Static site stays static | Packaging cost |
|---|---|---|---|---|---|
| Edit-in-place site | High | Mixed boundary | Yes | At risk | Low |
| Separate `/edit/` shell | High | Explicit boundary | Yes | Yes | Moderate |
| VS Code custom editor | High | Good host primitives | No | Yes | Moderate |
| File System Access app | Low | Browser-dependent | No | Yes | High semantic duplication |

## User experience

### Launch and navigation

`refdes serve` loads exactly one project and prints a launch URL containing a
per-launch random token. The browser opens to the rendered project dashboard.
A server-only toolbar opens `/edit/`; an item page can open that item's form.
The editor shows the current git branch/HEAD when available and whether the
working tree or index is dirty. It never stages or commits. Git remains the
undo and review mechanism.

The item list filters by ID, title, type, board, workspace, and source file.
Imported items are visible but read-only. Sealed items are visible and
read-only, with an action to start a new log entry whose `amends` link targets
the sealed entry.

### Editing fields

Controls come from the resolved `ItemType`; their values come from the parsed
item. Required state, choices, target types, `on_change`, and conditional
requirements are displayed, not reimplemented as hard-coded type names.

Inherited values require explicit treatment:

- The UI labels a value inherited from file `defaults:` or a section.
- Changing it writes an item-local override; it never edits the shared default.
- Removing an item-local override reveals the inherited value.
- An inherited value with no local override cannot be “removed” from one item;
  the UI explains that the shared default is outside first-version scope.

The item's type, key, and display ID are read-only in the first version. Board,
workspace, and prefix overrides are editable where the current model permits
them.

### Editing and previewing bodies

The editor uses a plain textarea in the first version, with insertion helpers
for item references, figure references, image syntax, and calc fences. It does
not use a browser Markdown implementation.

A debounced preview request sends the unsaved candidate body to Python. The
server overlays it in memory, runs the same calc, Markdown-it, local-image,
figure-attribute, and `[[reference]]` pipeline used by a build, and returns the
rendered fragment plus diagnostics. The authoritative sequence is in
`render_bodies()`: Markdown-it with raw HTML disabled, then images, figures,
and reference linkification (`src/refdes/build.py:1230-1277`). Figure numbering
and `[[fig:id]]` resolution remain document-dependent
(`src/refdes/build.py:1143-1227`); the preview labels which context it is
showing, defaulting to the standalone item page.

Existing images resolve relative to the item's source file and are
content-hashed into site assets (`docs/markdown.md:72-97`). Figure attributes
and references use the existing syntax (`docs/markdown.md:99-137`). The
recommended first-version boundary is an assisted picker for existing files,
not upload: upload introduces destination choice, overwrite handling, binary
conflicts, extension/MIME policy, and git status changes unrelated to the item
transaction.

### Link picker

For each link verb, the API supplies its allowed target types from
`ItemType.links`. An empty allowed list means unrestricted; the server remains
authoritative. This is the same rule `resolve_links()` validates today
(`src/refdes/build.py:314-366`).

The picker searches current display IDs and titles, filters by allowed type,
and displays board/workspace/source context. Selecting a target stores its key
in form state. Saving emits `CURRENT-DISPLAY-ID@key`; the browser never
constructs the composite from stale text. Removing a chip deletes that target
from the link field. Imported targets require keys in the import payload; until
that keys-design gap is closed, they are shown but unavailable with an explicit
explanation rather than written as a fragile bare ID
(`docs/design/keys.md:73-77`).

Prose `[[ITEM-ID]]` remains display-ID text, not a composite. That is a
separate human-authored reference mechanism by design
(`docs/design/keys.md:492-497`).

### Creating items

Creation starts with type, then board/workspace where configured, fields,
links, body, and destination. The editor suggests a directory from the
project's `item_layout`, registered board/workspace paths, and neighboring
items. The project's only fixed layouts are `flat` and `workspace`
(`src/refdes/model.py:45-47`; `docs/workspaces.md:41-68`); outside those
segments, folders are author organization rather than schema
(`docs/authoring.md:340-353`). Therefore every suggestion has an explicit
relative-path override and preview.

The first version supports all three useful destinations:

- append a new mapping to an existing YAML list;
- append a fenced item and body to an existing Markdown item file; or
- create a new Markdown file.

The editor infers a default from nearby items of the same type and location,
but does not invent a schema rule that a type is intrinsically “one per file.”
The user can override it before save.

Creation plans the next display ID against the live ledger and project high
water, then mints an independent key. Today's `ids.allocate()` combines
planning, source writes, and ledger writes for every pending item
(`src/refdes/ids.py:296-416`), so implementation needs a pure single-item
allocation plan reusable inside the editor transaction. `keys.mint()` is
already pure (`src/refdes/keys.py:96-102`). The new file/item insertion,
ledger update, key, and any initial composites commit together; a failed save
burns no ID.

For a log entry, the date picker writes the project's declared `date_format`,
not the browser's locale. The setting defaults to `YYYY-MM-DD` and accepts one
each of `YYYY`, `MM`, and `DD` with a repeated separator
(`src/refdes/dates.py:9-31`); parsing is strict calendar validation
(`src/refdes/dates.py:49-58`). This repository currently declares
`date_format: YYYY-MM-DD` (`refdes-project.yaml:28-30`).

### CLI parity

The backlog's scope decision is explicit: the CLI must remain able to do
everything the form can do (`docs/design/backlog.md:183-186`). Here “able”
means semantic authoring parity, not necessarily one flag for every form
control. The plain files remain the public authoring interface:

| Editor operation | Existing non-browser path |
|---|---|
| Edit a field or body | Edit the YAML/Markdown source and run `refdes check`. |
| Add/remove a link | Edit the declared link field; a writable load expands a bare target to a composite (`src/refdes/cli.py:94-104`). |
| Create an item | Run `refdes new TYPE`, write the scaffold, then `refdes id`; writable loading mints its key and expands links (`src/refdes/scaffold.py:134-172`; `src/refdes/cli.py:403-420,82-104`). |
| Amend a sealed log | Create a new log by the same path and author its `amends:` link; never mutate the sealed entry. |

The browser adds safe source manipulation and aggregates those steps into one
transaction, but it adds no browser-only state or semantic operation. A
transactional create with initial links has no one-command CLI twin today;
the same final state is nevertheless reachable through `new`, source editing,
`id`, and a writable check/build. Likewise, “amend this log” is a pre-filled
ordinary log plus `amends`, not a new lifecycle operation.

The transaction, allocation-planning, and item-intent layers must be ordinary
Python services, not code buried in HTTP handlers. A future CLI can call them
if scripted atomic edits become a real need. The recommendation for v1 is not
to invent a large `refdes item set` flag language merely to mirror widgets;
whether parity requires an atomic one-command CLI is called out under “Where
you might disagree.”

## Server and refresh architecture

### Process boundary

The command imports refdes modules in-process; it does not shell out to a
configurable command. One process owns one project, one write lock, and one
in-memory project revision. A small stdlib HTTP server is sufficient for the
local-only first version. A framework would add installation and patching cost
without changing the single-user request model.

The browser protocol is operation-oriented rather than filesystem-oriented:

- project/editor model and revision;
- one item by stable key or provisional keyless handle;
- preview an unsaved item candidate;
- save an existing item intent;
- create an item intent; and
- current diagnostics/git status.

No endpoint accepts an arbitrary absolute path. Existing-item writes address a
loaded item. Creation accepts only a validated project-relative destination
under `items/`.

The wire model includes the project's resolved types and field/link specs,
item fields/body, raw and resolved links, inheritance/source metadata, seal
state, and a revision token. It is versioned independently from `items.json`;
`items.json` remains the public read-only export.

### Preview freshness

On launch, the server performs a Slice 0 side-effect-free load/build and
renders a per-launch preview using the current Jinja templates. Preview output
lives in an OS temporary directory outside the project—on Windows, under the
current user's `%TEMP%`—never in `_site/`. It is removed on normal exit; a
later launch may prune stale same-user preview directories left by a crash.

After a successful save, the server performs one full in-process rebuild
through that same side-effect-free path (`seal_write=False`) and refreshes the
temporary preview before reporting success. Saving or previewing an unsealed
log therefore never seals it and never writes incidental `.refdes/` state.
Only a normal, explicitly invoked write-enabled `refdes build` seals new
append-only entries. A client poll of a lightweight revision endpoint updates
open clean pages; no WebSocket dependency is needed.

For edits made outside the browser, the server polls mtimes and then confirms
content hashes for the project inputs. Polling is boring and portable on
Windows; adding a filesystem-watcher dependency is not justified for one
local user. A change invalidates the in-memory model and triggers a debounced
read-only rebuild. Clean forms reload automatically. Dirty forms remain intact
and show a conflict banner with reload/diff choices; they can no longer save
against the old revision.

Measured in this worktree, `refdes build --dry-run --keep-going` processed 20
items, rendered the site, and reported the project's expected one error/two
warnings in **1.06 seconds wall time**. That measurement includes process
startup. A full rebuild after a committed save is therefore acceptable for the
current project. Unsaved preview requests should be debounced and superseded;
optimize incrementally only after measurement on a materially larger project.

## Write-back fidelity

### Guarantee

The required guarantee is:

1. every byte outside the edited item's source span is unchanged, except other
   files/spans explicitly listed by the operation (ledger update, new item,
   or inbound composite-label refresh in a later rename operation);
2. inside the item span, comments, key order, flow/block collection style, and
   quoting of untouched fields are preserved;
3. only edited values and deliberately inserted/removed keys may be normalized;
4. the post-edit project is reparsed by PyYAML, and the edited item must parse
   to exactly the intended semantic values; and
5. every other item must parse to the same semantic projection as before,
   except changes explicitly planned by the operation.

A save that cannot prove all five is rejected and writes nothing.

“Exactly” includes Python value type and structure, not string appearance.
Refdes currently parses front matter and list files with a PyYAML loader
(`src/refdes/parse.py:476-481,628-637`). A direct probe against the installed
PyYAML showed YAML 1.1-sensitive results: `yes/no/on/off` became booleans,
`2026-01-05` became `datetime.date`, `0755` became integer 493, and `1:20`
became integer 80. The writer must quote conservatively and verify with that
same parser.

### Alternatives

**Dump the parsed object with PyYAML.** This keeps semantic parsing singular,
but destroys comments and can normalize key order, quoting, scalar style, and
flow/block layout across an entire hand-written file. Rejected.

**Add `ruamel.yaml` as a round-trip document model.** It preserves substantially
more syntax than `safe_dump`, but introduces a second YAML implementation.
Its default YAML 1.2 scalar semantics can disagree with the authoritative
PyYAML YAML 1.1 interpretation above. Keeping PyYAML as the post-write judge
reduces damage but does not remove the complexity: the editor still needs to
map ruamel nodes to refdes's multiple-item Markdown boundaries and explain any
parser disagreement. This may be worth revisiting if the source patcher grows
into a general YAML editor, but it is not recommended for the first version.

**Extend the current targeted source-rewrite posture.** Existing ID/key
write-back already inserts into Markdown front matter and block or one-line
flow mappings without dumping the file (`src/refdes/ids.py:222-293`). The
newly extended link writer bounds edits to parsed item/default spans and
handles direct values, block sequences, and one-line flow mappings while
reporting exactly what it rewrote (`src/refdes/links.py:42-194,197-330`).
Generalizing this into an item-span editor is less magical and gives the
fidelity guarantee a sharp boundary. **Recommended.**

### Source patcher

The patcher uses the existing parser's item/source metadata plus PyYAML
compose-node marks to locate the selected mapping and each direct field value.
It retains the original source as immutable slices. It never serializes an
untouched value.

For each operation:

- Replace an existing edited value's exact source range with a conservative
  scalar or collection emitter. Strings are quoted whenever PyYAML could infer
  another type or when YAML indicators make plain style unsafe.
- Preserve the existing collection and scalar style when it can represent the
  new value; otherwise normalize that edited value only. A multiline body
  added to a list entry uses a literal block scalar.
- Insert a new field using the item's indentation and dominant local style,
  near its schema-order neighbors. New links prefer the item's existing link
  list style; absent a precedent, use a block sequence for reviewable diffs.
- Delete only the field's node and its inline comment. Standalone comments
  between fields remain. If comment attachment or node extent is ambiguous,
  refuse with a source-location message rather than guess.
- For Markdown, replace body text as one raw span; front matter is patched as
  YAML. For a list-file `body:`, use the YAML node span rather than
  `Item.body_line`, which is intentionally unavailable for list bodies today
  (`src/refdes/model.py:371-376`).
- Apply edits bottom-up within each file so earlier offsets remain stable.

This is not a new YAML parser. PyYAML still decides meaning before and after;
the patcher only locates and replaces bounded source text. Fixtures must cover
comments, CRLF/LF, BOM handling, quoted YAML 1.1 traps, inline and block lists,
flow entries, multiline scalars, defaults/sections, multi-item Markdown, and
an edit adjacent to a literal `---` in body prose.

## Validation, conflicts, and transactions

### Side-effect-free loading is Slice 0

Editor GET, polling, conflict detection, and unsaved preview must never mint a
key, expand a link, refresh a manifest, or seal an entry. Current `_load()`
can mint missing keys and expand bare links while loading
(`src/refdes/cli.py:66-104`). Its own comment says the global `--no-write`
currently gates only key minting rather than all promised writes
(`src/refdes/cli.py:82-89`).

Slice 0 is therefore the independent keys-design work already named in
`docs/design/keys.md` §9: make `--no-write` cover every write under `items/`
and `.refdes/`, and expose one side-effect-free load/build path. This improves
CI, inspection, and bisects even if the browser editor is never implemented
(`docs/design/keys.md:1034-1042`). The editor must consume it, not create a
second “mostly read-only” loader.

### Revision and conflict detection

Every editor model carries a server-issued revision containing content hashes
of all semantic project inputs. Before a mutation, the server acquires its
write lock, recomputes those hashes, and requires an exact match. File content
is the conflict proof: this catches another browser tab, VS Code, a CLI write,
a checkout/reset that changes working files, or any edit outside git.

Git HEAD, branch, index identity, and dirty state are separate advisory
metadata, not part of the revision token. A commit or `git add` that leaves
working bytes unchanged shows a notice and does not invalidate a dirty form.
If a git operation also changes a semantic input, its content hash causes the
conflict. This avoids making unrelated staging in VS Code destroy editor work
while still showing that the review context moved.

A content mismatch returns a conflict, never a last-write-wins save. The UI
shows which files changed and separately reports any HEAD/index movement, with
reload plus textual-diff choices. Automatic three-way merging is deferred;
YAML merge guesses are not a first-version safety feature.

Symlink/reparse-target changes are part of path revalidation at save time, not
trusted from the earlier load.

### Diagnostic gate

The server computes full diagnostics for the before-project and candidate
project. The form shows both the current project diagnostics and candidate
changes.

The gate is delta-based:

- block every newly introduced project or item error;
- for a pre-existing error on the edited item, block only when the edit
  touches that diagnostic's attributed field, body, link, or reserved value
  and the candidate still has the error;
- allow an unrelated edit on the same item when its pre-existing error was
  caused elsewhere—for example, a body correction while a target deleted in
  another file leaves an existing dangling-link error;
- block structural invariants regardless of diagnostic diff: parse loss,
  duplicate/corrupt key or ID, illegal link target, sealed mutation, path
  escape, or unintended semantic change to another item;
- show other pre-existing errors without blocking a save that does not worsen
  them; and
- show warnings and failing engineering checks, but do not treat a computed
  check violation as source corruption.

Requiring a globally clean project would make the editor unusable when it is
most needed to repair one. `revise.apply()` makes a different, appropriate
choice for a whole-project vocabulary rewrite: it refuses pre-existing build
errors except check violations (`src/refdes/revise.py:624-646`). An item editor
needs the narrower delta rule.

Diagnostics are compared by stable structured identity—level/code, item key or
source, field/body/link path where available, and message arguments—not only
rendered English. Field-path attribution is a prerequisite for applying the
second bullet. An unattributed pre-existing error is shown but does not block
an unrelated edit; hard invariants still do. The diagnostic model must be
enriched before the delta gate ships if current diagnostics cannot make that
distinction.

### Transaction model

Reuse the invariant of `revise.apply()`, not that vocabulary-specific function.
`revise.apply()` computes rewrites, validates, writes, reloads, and restores
originals on failure (`src/refdes/revise.py:666-704,724-845`). Editor saves need
a shared transaction primitive with source overlays and crash recovery.

One save proceeds as follows:

1. Acquire the process write lock and verify the complete revision.
2. Load the before-project through the side-effect-free path.
3. Convert the form intent into candidate source buffers, key/ID allocation,
   ledger change, and any explicitly expected secondary rewrites.
4. Load and fully build a source overlay in memory with PyYAML authoritative.
5. Prove the fidelity and semantic postconditions, seal rule, and diagnostic
   delta before touching live files.
6. Write same-directory replacement files, flush them, and record originals,
   intended replacements, and their hashes in
   `.refdes/editor-transaction/`.
7. Replace each destination atomically. If any replacement fails, restore every
   destination already replaced.
8. Reload and fully validate from live disk. A mismatch restores the originals.
9. On success, remove the journal directory, issue a new revision, rebuild the
   temporary preview through the side-effect-free path, and return post-save
   diagnostics and changed paths.

The journal is inside the project so every refdes process can discover it
without a machine-global registry, and on the same volume as ordinary project
files. It is deliberately **not gitignored**: normal success removes it, while
a crash must become loud in `git status` rather than hide a directory holding
source backups. This matches the repository's existing policy that durable
`.refdes/` state is tracked unless specifically identified as disposable
(`.gitignore:19-34`). It must never be committed.

Every refdes command that loads a project checks for the journal before
parsing any source and refuses if one exists. The error names the transaction
and instructs the user to run a dedicated `refdes recover` command. Recovery
runs before normal project loading, verifies the recorded hashes, restores all
originals, and removes the journal only after the before-state is complete.
`check`, `build`, `id`, and other commands must never continue over a possibly
half-applied editor save; recovery is not deferred until the next `serve`.

A multi-file operation is not made magically atomic by the filesystem; the
journal makes it recoverable and the lock prevents this server from
interleaving saves. This matters for creation (item plus ledger), composite
label refresh (many inbound files), and future operations touching seals or
baselines.

### Sealed entries

Append-only is a type property, but an entry becomes immutable when a seal
record exists. The current verifier errors if sealed content changes and tells
the author to append a new entry with `amends` instead
(`src/refdes/seal.py:124-196`). Against the keys end state, the editor looks up
that seal by surrogate key.

A sealed item never receives enabled controls and the mutation endpoint repeats
the check under the write lock. There is no browser “reseal” escape hatch.
An append-only item not yet sealed may be edited. The UI explains that the
editor's post-save rebuild and preview are side-effect-free and do **not** seal
it; only a separately invoked, ordinary write-enabled `refdes build` does.

## Security

Local-only is a security boundary, not permission to omit checks.

- Bind only IPv4 `127.0.0.1` on an ephemeral port. IPv6 loopback (`::1`) is
  not bound, and the first version has no `--host 0.0.0.0` or remote mode.
- Accept only `Host: 127.0.0.1:<chosen-port>` or
  `Host: localhost:<chosen-port>` on every request; reject every other host
  before routing. The printed canonical URL uses `127.0.0.1`. A manually typed
  `localhost` URL works when the OS resolves it to IPv4; if it resolves only
  to `::1`, the UI cannot be reached and the printed IPv4 URL is the remedy.
  These two exact hostnames still block DNS-rebinding requests that reach
  loopback with an attacker-controlled Host header.
- Generate at least 256 random bits per launch. Print a Jupyter-style startup
  URL carrying the token, remove it from the address bar with
  `history.replaceState`, and require it in a dedicated header on every
  mutation. Compare in constant time; never persist or include it in rendered
  files/logs.
- On every mutation, require an `Origin` exactly matching the accepted Host
  and bound port (`http://127.0.0.1:<port>` or
  `http://localhost:<port>`). Reject missing, `null`, cross-origin, and
  mismatched Host/Origin combinations. Send no permissive CORS headers and
  use `SameSite=Strict` for any session cookie.
- Apply a restrictive CSP to the editor: packaged same-origin scripts/styles,
  no remote code, no inline script, no framing by other origins, and no plugin
  content. The built Markdown path already disables raw HTML
  (`src/refdes/build.py:1230-1234`), and Jinja autoescaping is explicitly on
  (`src/refdes/render.py:614-623`).
- Address loaded items by key/provisional handle. For creation, normalize and
  resolve the requested path, require it below the real `items/` root, reject
  absolute paths, `..`, alternate data streams, reserved Windows names, and
  symlinks/reparse points that leave the project. Permit only `.md`, `.yaml`,
  and `.yml` item destinations.
- Do not expose a generic file-read endpoint, command endpoint, shell, plugin
  loader, template input, or arbitrary Python expression. `serve` imports the
  installed refdes package; it never executes a project-provided command.
- Limit request and body sizes, reject unexpected content types, and escape all
  diagnostic/source text rendered into the editor.

Read APIs reveal local project content to a local browser process. Requiring
the launch token for `/api/` reads as well as writes is recommended defense in
depth; the hard requirement is that no mutation is possible without Host,
Origin, and token checks together.

## Windows behavior

Windows is the primary platform. Use `pathlib`/real-path containment rather
than slash assumptions, preserve original CRLF or LF per file, and create
temporary files in the destination directory so replacement stays on one
volume.

`os.replace` provides the desired same-volume single-file replacement, but on
Windows it can raise `PermissionError` while VS Code, antivirus, an indexer, or
OneDrive briefly holds a handle. Retry only this transient class with bounded
exponential backoff (recommended total budget: about two seconds). If it still
fails, roll back the transaction and report the exact path and likely holder
scenario. Never fall back to truncate-and-write, because that sacrifices both
atomic replacement and recoverability.

The external-change poll and revision check remain required even if a Windows
file notification API is later added; notifications are invalidation hints,
not conflict proof.

## Dependencies and distribution

The runtime currently depends on PyYAML, Jinja2, Pint, and Markdown-it-py
(`pyproject.toml:34-39`) and supports Python 3.11+
(`pyproject.toml:1-6`). The recommendation adds no runtime dependency:

- stdlib HTTP serving is sufficient for loopback-only single-user operation;
- existing Python modules own parsing, validation, rendering, IDs, and keys;
- the targeted patcher uses PyYAML node marks plus bounded source emission;
- packaged plain ES modules/CSS need no compiler; and
- portable polling avoids a filesystem-watcher package.

Node 24 and npm being available on Jared's machine is useful for optional UI
development tooling, but not a reason to make every pip user install Node or
ship generated bundles. If the browser UI later becomes complex enough to
justify TypeScript or a component framework, generated assets can still be
committed and packaged so end users retain a Python-only install. That cost
should be accepted only after the plain-JS UI becomes demonstrably harder to
maintain.

## Phasing

### Slice 0 — truly read-only loading

- Complete global `--no-write` coverage for every incidental source/metadata
  write.
- Expose one side-effect-free load/build API with source-overlay support.
- Prove reads, previews, CI checks, and bisects leave `items/` and `.refdes/`
  byte-identical.

This is standalone keys work, not editor-only plumbing.

### Slice 1 — existing fields and bodies

- Add `refdes serve`, loopback security, editor model, content-revision
  polling, advisory git status, and side-effect-free rendered preview in an
  OS temporary directory.
- Implement item-span source patches, field controls, inherited-value behavior,
  Markdown body editing, and server-side preview.
- Implement transaction journal/recovery checks across every project-loading
  command, conflict checks, attributed delta diagnostics, and sealed read-only
  enforcement.
- Keep display ID/type/key read-only.

### Slice 2 — structured links

- Add schema-filtered link pickers and composite writes.
- Revalidate target type and resolve the target key under the save lock.
- Support add/remove in scalar, flow-list, and block-list source forms without
  changing untouched syntax.
- Close or explicitly gate imported targets until import payloads carry keys.

### Slice 3 — creation

- Split pure single-item ID planning from `ids.allocate()` and include ledger
  mutation in the transaction.
- Mint a key, write initial composites, and create/append Markdown or YAML.
- Add destination suggestion plus explicit override.
- Cover log creation, project-format date output, and “amend this sealed log”
  flow.

**Slices 0–3 together are the first shippable editor.**

### Later

- Display-ID rename using the landed inbound-label refresh machinery after
  independent real-project exercise.
- Image upload/copy and binary conflict policy.
- VS Code custom-editor adapter over the same application services.
- Project/schema/defaults/section editing, only if real use shows forms need
  them.
- Incremental build/render optimization, only if measured project size makes a
  full rebuild too slow.

## Acceptance boundaries for the first version

The design is implementable when each of these outcomes can be demonstrated:

- Editing one field in a commented multi-item YAML file produces a diff only
  for that value; neighboring items and comments are byte-identical.
- YAML 1.1-sensitive strings round-trip to the intended Python values, or save
  is rejected before disk changes.
- Editing a Markdown body containing a literal horizontal rule changes the
  correct body only; preview matches the subsequent built item page.
- A picker for each verb offers only its allowed target types, and disk stores
  `CURRENT-ID@key`; add/remove survives every supported list style.
- A new ordinary item and a new log receive unique display IDs and keys; a
  failed transaction changes neither item files nor ledger.
- The log date is written in a non-default configured order/separator and
  reparses as the selected calendar date.
- A sealed log has no editable UI and a forged mutation request is rejected.
- Saving or previewing an unsealed log does not create a seal or modify
  `.refdes/`; a later ordinary write-enabled `refdes build` seals it.
- A pre-existing unrelated error, including one elsewhere on the same item,
  does not block a repair; touching its attributed field requires fixing it,
  and any newly introduced error blocks.
- External semantic-file content changes cause a conflict instead of overwrite;
  HEAD/index-only movement produces a visible notice without discarding work.
- Killing the process between two replacements leaves a visible
  `.refdes/editor-transaction/`; every project-loading command refuses until
  `refdes recover` restores it.
- Requests with a wrong Host, Origin, or token cannot mutate; a path traversal,
  absolute path, ADS path, or escaping reparse point cannot read or write.
- A transient Windows sharing violation retries; a persistent one rolls back
  and names the blocked path.
- `_site/` built without `serve` contains no editor UI, token, or write route.

## Where you might disagree

These are recommendations, not decisions. Jared should make the final calls.

- **Separate `/edit/`, not direct edit-in-place — recommended, Jared to
  decide.** Direct manipulation is attractive, but a separate privileged
  surface keeps `_site` honest and makes conflict/security state visible.
- **Targeted item-span patcher, not ruamel.yaml — recommended, Jared to
  decide.** This is more bespoke code, but it retains one semantic parser and
  makes “nothing else changed” provable. Choose ruamel if maintaining bounded
  YAML emission becomes worse than managing two parser semantics.
- **Fidelity boundary — recommended, Jared to decide.** Byte-identical outside
  planned spans; preserve comments/order/style/quoting for untouched values
  inside; edited values alone may normalize. Requiring byte-identical spelling
  for the edited value would make safe quoting and type changes needlessly
  brittle.
- **Creation destination — recommended, Jared to decide.** Suggest from
  type/board/workspace and neighboring files, always allow explicit override,
  and support appending to YAML/Markdown plus new Markdown files in v1.
- **No display-ID rename in v1 — recommended, Jared to decide.** The refresh
  path has now landed, but the editor should depend on it only after it has
  been exercised independently.
- **Delta validation — recommended, Jared to decide.** Block new errors and
  pre-existing errors whose attributed field the edit touches; permit
  unrelated repairs even on the same broken item. The stricter alternative is
  to block on every error attached to the item, but that prevents a body fix
  when a dangling link elsewhere on the item is unchanged.
- **Existing-image references only in v1 — recommended, Jared to decide.** A
  picker covers authoring syntax without silently adding binary file management
  to the source transaction.
- **No Node build step — recommended, Jared to decide.** Plain ES modules fit
  this first UI and preserve pip-only installation; reconsider after measured
  maintenance pain, not pre-emptively.
- **VS Code as a later adapter — recommended, Jared to decide.** It should reuse
  service operations, not define the editor's architecture.
- **Full rebuild after save — recommended, Jared to decide.** The measured
  1.06-second command is acceptable today. Incremental rendering adds cache
  invalidation before there is evidence it is needed.
- **CLI parity means semantic reachability, not identical atomic commands —
  recommended, Jared to decide.** All v1 results remain achievable through
  `new`, plain-text editing, `id`, and check/build; the browser merely
  aggregates them safely. If the recorded parity decision instead requires
  every browser transaction to have a one-command twin, add a CLI over the
  same intent/transaction service before shipping.
- **Git identity is advisory, content is the conflict proof — recommended,
  Jared to decide.** Blocking on HEAD/index identity is more conservative, but
  it makes an unrelated `git add` invalidate every dirty form without
  protecting any working-tree bytes.

## Open questions for Jared

1. Confirm the recommended fidelity contract, especially whether normalization
   of an edited value inside its own span is acceptable.
2. Confirm the suggested-plus-override destination model and all three v1
   destinations.
3. Confirm display-ID rename waits until after v1.
4. Confirm delta-based validation rather than a globally clean-project gate.
5. Confirm existing-image selection is enough for v1 and upload is later.
6. Confirm the editor is a standalone browser surface first, with VS Code as a
   later adapter.
7. Does “Edit this item” belong as a small server-injected toolbar over preview,
   or should preview and editor remain visually separate even while served?
8. Should read-only API routes require the launch token too? This document
   recommends yes; writes require it either way.
9. Confirm whether CLI parity means semantic reachability through existing
   commands and plain-text edits, or requires a one-command transactional twin
   for browser saves and creation.
