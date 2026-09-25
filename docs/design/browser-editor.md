Status: architecture decided (2026-09-16) — remaining work is v1 scope, not
shape. See “Decisions” near the end.

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
build step, and operation with JavaScript disabled (`README.md:342-346`). No
editor control, token, or write API is emitted into `_site/`.

**Decided.** This shape — Option B below — is the architecture, chosen 2026-09-16.
Options A, C, D, and E stay in this document as considered-and-rejected for v1,
not as live alternatives.

The first released editor comprises Slices 0–3 below. Internal slices may land
separately, but Slice 1 alone is not the promised first version: creating all
item types including log entries, editing fields and Markdown bodies, and
adding/removing valid links must all work before the browser editor is called
shippable.

## Goals and non-goals

### First-version goals

- Browse and search local items using their current rendered context.
- Filter the item list as a first-class surface, not a search box bolted onto a
  table: type, board, workspace, tag, source file, coverage stage, check state,
  link relationships, and free text over title and tags. See “Filtering” below.
- Handle identity so the author never types an identifier. Display IDs are
  allocated from the ledger, surrogate keys are minted, and link targets are
  picked from a filtered list rather than spelled. See “Identity” below.
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
  `DISPLAY-ID@surrogate-key` composite, including for imported targets whose
  artifact carries a key.
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
- Automatic three-way merging of a conflicting save. Conflicts refuse and show a
  diff; see “Drafts” below.
- Accounts, roles, per-item permissions, and drafts kept across browser
  sessions. See “Permissions are out of scope for v1”.
- A VS Code custom editor. VS Code may later host the same application model,
  but it is not the primary product.
- Remote or multi-user service operation, and the GitHub-API editor shape that
  would imply it (Option E).

## What exists today

### Data and authoring model

Refdes has one semantic item model and two source representations. Markdown
files may contain multiple fenced items plus a leading defaults block and
section markers; the text after each closing fence is that item's body
(`src/refdes/parse.py:565-664`). YAML files contain an `items:` sequence and
may also apply defaults and section markers (`src/refdes/parse.py:665-732`).
`id`, `type`, `history`, `body`, `former_ids`, and `key` are engine-reserved
(`src/refdes/parse.py:33`); `prefix`, `board`, and `workspace` are
conditionally overridable (`src/refdes/parse.py:37`).

The parsed `Item` deliberately carries raw link spellings separately from
resolved, current display IDs. Writes and hashing need the raw value, while
graph traversal must use `resolved_links` (`src/refdes/model.py:378-396`). An
editor DTO therefore cannot flatten these two views.

The existing `items_json()` is useful but insufficient as the editor protocol.
It exports type field/link definitions (`src/refdes/render.py:543-561`), item
source locations, keys, fields, links, backlinks, citations, calc and check
results (`src/refdes/render.py:563-613`), project coverage stages with their
per-stage link sets (`src/refdes/render.py:533-542`), next-ID data
(`src/refdes/render.py:615-627`), and diagnostics
(`src/refdes/render.py:628-642`). Its surrogate key is now present but
nullable — `null` marks a `--no-write` load that could not persist a minted key
(`src/refdes/render.py:566-570`) — and item records still carry no raw body
text, which is the one thing an editor cannot reconstruct. Blocked chains are
likewise absent from the payload: they are computed for templates only
(`src/refdes/render.py:782`). The editor API should
be generated from the same `Project`, `ItemType`, and `Item` objects, not by
parsing `items.json` back into a second model.

`refdes new TYPE` already generates required/defaulted fields and link hints
from the resolved `ItemType`, rather than per-type templates
(`src/refdes/scaffold.py:135-180`). Creation should reuse that resolved schema
logic, not parse the command's textual scaffold.

### Site and editor support

The current item page already puts fields, body, links, backlinks, source
location, and content hash in one review surface
(`src/refdes/templates/item.html.j2:5-276`). That makes the rendered
site the right preview and navigation context, but not the right place to hide
a write-capable application in static output.

The VS Code extension establishes the correct ownership boundary. It is plain
JavaScript and obtains items, schema-derived data, source locations, and
diagnostics by invoking `refdes index --compact`; it has no parser of its own
(`editors/vscode/extension.js:1-9,72-126`). It already publishes diagnostics,
completion, hover, and definition support, but registers no webview or custom
editor (`editors/vscode/extension.js:493-526`).

### Surrogate-key end state

This proposal targets the specified end state in `docs/design/keys.md`, not
only the code present while this document was written:

- Each item has an opaque immutable key; storage remains readable plain text
  (`docs/design/keys.md:3-15`).
- A structured link is stored as `DISPLAY-ID@key`; only the key resolves and
  the display half is tool-maintained (`docs/design/keys.md:427-451`).
- A renamed target refreshes inbound composite labels, with an ambiguous stale
  label reported rather than silently changed (`docs/design/keys.md:515-537`).
- Seals and baselines ultimately key records by surrogate key, with display ID
  retained only for readability (`docs/design/keys.md:726-780`).

At the baseline inspected for this proposal, composite expansion, display-half
refresh, corruption lint Layers 1–5, and `refdes keys adopt` are all
implemented (`docs/design/keys.md:17-30`; `src/refdes/adopt.py`); this
repository is itself adopted. What remains design only is the §4 simplification
of `revise.py` and `former_ids.py`, which the editor does not depend on. Rename
is still deferred from v1 so the newly landed refresh path can be exercised
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

**Verdict (decided):** reject direct edit-in-place. Keep the site as preview,
and allow a server-only “Edit this item” link or toolbar to navigate to
`/edit/items/<key>`. That link is injected into the HTTP response or server
preview wrapper; it is never written by `render_site()`.

The affordance exists **only while `refdes serve` is running**. A published
static site — `_site/` copied to any host — never shows an “Edit this item”
control, because there is nothing behind it there and a dead edit link on a
reviewed artifact is worse than no link. This is a decided boundary, not a
polish item: the affordance belongs to the server, not to the page.

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
named this shape (`docs/design/backlog.md:297-330`).

It is not a general browser editor; it requires VS Code and makes a multi-item
source file's ownership awkward because one custom editor normally owns one
text document while this UI edits one semantic item. Webview CSP, extension
packaging, and host message plumbing are additional constraints. It also
makes the authoring surface unavailable to someone reviewing the local site in
an ordinary browser.

**Verdict (decided):** later adapter, not the primary product. Share application
services and DTOs, not an HTTP server requirement: a future extension can invoke
the same Python operations through a narrow CLI/RPC bridge. The standalone
browser surface comes first.

### D. Serverless browser application

The File System Access API could let a static page open a project directory.
It removes the local server, but replaces it with Chromium-specific permission
behavior and cannot directly reuse the pip-installed Python parser, checker,
renderer, ledger, keys, or seals. Reimplementing them in JavaScript would create
a second refdes.

The honest version of this shape is Pyodide: ship CPython plus the real refdes
wheel and run the same Python in the browser. Its download cost is not the
objection — six to ten megabytes, cached after first load, against a feature the
author uses every day. Three things are:

- **The file handle is Chromium-only.** File System Access API write access is
  a Chrome/Edge feature; Firefox and Safari do not grant it. A browser editor
  that can save is therefore not a browser editor on two of the three browsers
  a reviewer is likely to be using.
- **A second runtime doubles the test surface for the write path.** Every
  fidelity, transaction, journal, and recovery guarantee in this document has
  to hold inside WASM too, with a virtual filesystem whose `os.replace`,
  durability, and locking semantics differ from NTFS.
- **A cached browser build can silently differ from the CLI version.** For most
  tools that is staleness. For key minting, ID allocation, and seal hashing it
  is corruption: two runtimes minting against the same ledger, or hashing with
  different field rules, produce artifacts the other cannot reproduce.

**Verdict (decided):** reject for editing the author's real project. Note it
separately as a plausible path for a **zero-install demo** — a read-only
browser tour of a checked-in example project, where nothing is saved, no ledger
is touched, and no seal is computed against a runtime the author did not choose.
That is a different product with a much smaller contract, and this rejection is
not a rejection of it.

### E. GitHub-backed editor

A static page with no local server at all: read the repository through the
GitHub API, edit in the browser, and save by committing to a branch and opening
a pull request. Validation is not local either — a CI run of `refdes check` on
the pushed branch is the authoritative verdict, and the review happens where the
review already happens.

This is genuinely attractive for the last-mile case: fixing a typo, correcting
an MPN, or updating a status from a phone, with no clone, no Python, and no
machine that has the toolchain. The commit-per-save model is also an honest one
— it never pretends to be an in-place edit of a working tree.

It is rejected as the v1 primary editor for the same reason Option A is: the
boundary. The write path stops being refdes's own — no item-span patcher, no
transaction journal, no content-hash revision check, no sealed-entry rule
enforced at the point of mutation — and gets delegated to whatever the GitHub
API and a CI job happen to accept after the fact. A save that a local server can
refuse before touching a file becomes a merged commit that a human has to notice.
Filtering, link picking, and ID allocation all need project-wide data the API
does not have, which means either shipping the whole tree to the browser or
running a server: the argument for the local server returns.

It is also worth being blunt about the CI half. This repository has test CI
today: `.github/workflows/tests.yml` runs pytest and the E9,F ruff gate on
ubuntu and windows.
“CI validates the save” is currently a promise with nothing behind it, and it
would have to be built before this shape could be trusted — work that is worth
doing regardless of which editor wins.

**Verdict (decided):** reject for the v1 primary editor; keep as a possible
later “fix a typo from anywhere” path, contingent on real test CI existing.


### Comparison

| Shape | Semantic reuse | Source safety | Browser-independent | Static site stays static | Packaging cost |
|---|---|---|---|---|---|
| Edit-in-place site | High | Mixed boundary | Yes | At risk | Low |
| Separate `/edit/` shell | High | Explicit boundary | Yes | Yes | Moderate |
| VS Code custom editor | High | Good host primitives | No | Yes | Moderate |
| File System Access / Pyodide app | Low | Browser-dependent, Chromium-only writes | No | Yes | High semantic duplication |
| GitHub API editor | Low | Deferred to CI, no local transaction | Yes | Yes | High: needs project-wide data over HTTP |

## User experience

### Launch and navigation

`refdes serve` loads exactly one project and prints a launch URL containing a
per-launch random token. The browser opens to the rendered project dashboard.
A server-only toolbar opens `/edit/`; an item page can open that item's form.
The editor shows the current git branch/HEAD when available and whether the
working tree or index is dirty. It never stages or commits. Git remains the
undo and review mechanism.

The item list is the editor's front door, and “Filtering” below treats it as a
surface in its own right rather than a search box over a table. Imported items
are visible but read-only. Sealed items are visible and read-only, with an
action to start a new log entry whose `amends` link targets the sealed entry.

### Filtering

Filtering is a v1 requirement because finding the thing is most of what authoring
a traceable project costs. The pieces largely exist; what is missing is one
surface that combines them.

What the existing tooling already provides:

- `refdes ls` filters by `--type`, `--board`, `--file`, `--tag`, and free text
  matched against title and tags (`src/refdes/cli.py:441-494`, the filter loop
  at `src/refdes/cli.py:468-482`). It has no workspace, coverage, check-state,
  or link-relationship filter.
- `refdes index` builds the whole project and emits it as one JSON document
  (`src/refdes/cli.py:405-431`), which is what the VS Code extension consumes.
  Because it runs a full build first, the payload carries the derived facts a
  file scan cannot produce: coverage stage with its per-stage link sets
  (`src/refdes/render.py:533-542`), resolved links and backlinks per item, calc
  and check results, board/workspace registries, and diagnostics.
- Coverage is a five-stage ladder — open, addressed, claimed, satisfied,
  verified (`src/refdes/render.py:115`) — already rendered as a strip on the item
  page (`src/refdes/templates/item.html.j2:25-34`) and as a sorted report.

What the editor needs on top of that:

- **Workspace**, **coverage stage**, and **check state** filters. The data is in
  the payload; `refdes ls` simply has no flag for them.
- **Link-relationship** filters: items linking to a given target, items reachable
  from it by one verb, and — the one that actually hurts — items of a type whose
  required link verb is empty. Backlinks are already per item; the empty-verb
  query is a scan over `ItemType.links` and the item's raw links.
- **Blocked / under-repair** filters. Blocked chains are computed today, but only
  as a template global (`src/refdes/render.py:782`, `src/refdes/blocked.py:135`);
  they are not in the index payload, so the editor API must expose them.
- **Combination and state.** All filters AND together, counts per facet, and the
  whole filter held in the URL so a view is deep-linkable and survives reload.

The constraint that follows: the list endpoint answers from the **built** project
through the side-effect-free path, exactly as `refdes index` does — never from a
file scan. Coverage stage, blocked state, resolved links, and check verdicts only
exist after `build()`, and a list that disagreed with the report page about which
requirements are open would be worse than no list.

### Identity

The second v1 requirement is that the author never types an identifier, and the
editor never guesses one.

- **Creating:** the display ID is allocated from the ledger and the surrogate key
  minted, in the same transaction as the file write. The index already publishes
  the next ID per prefix (`src/refdes/render.py:615-627`), so a creation form can
  show the ID an item is about to receive. That number is advisory: it is a
  snapshot, and another process can allocate between load and save, so the
  authoritative allocation happens under the save lock and the form displays
  whatever it returns.
- **Linking:** targets are picked from the filtered list, never typed. The
  selection carries the target's key, and Python writes the composite — see “Link
  picker.”
- **Referring in prose:** `[[REQ-PWR-002]]` is the one place an author types an
  ID by hand, deliberately (`docs/design/keys.md:539-546`). The editor should
  complete it, but it stays display-ID text and inherits `former_ids` as its
  safety net.
- **Reading an ID:** `ids.split_id` (`src/refdes/ids.py:39-48`) is the existing
  parse of an ID into prefix and number, and is what a filter or a creation form
  should use rather than a hand-rolled split.
- **`--no-write` interacts with all of this.** A key read during a read-only load
  can legitimately be `null` (`src/refdes/render.py:566-570`), meaning the load
  could not persist a minted key — not that the item never had one. The editor
  must never write a link composite from such a load, and must say so instead of
  silently emitting a bare ID that the next writable command would have to
  expand.

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
and reference linkification (`src/refdes/build.py:1741-1789`). Figure numbering
and `[[fig:id]]` resolution remain document-dependent
(`src/refdes/build.py:1654-1740`); the preview labels which context it is
showing, defaulting to the standalone item page.

Existing images resolve relative to the item's source file and are
content-hashed into site assets (`docs/markdown.md:86-112`). Figure attributes
and references use the existing syntax (`docs/markdown.md:113-152`). The
recommended first-version boundary is an assisted picker for existing files,
not upload: upload introduces destination choice, overwrite handling, binary
conflicts, extension/MIME policy, and git status changes unrelated to the item
transaction.

### Source-value picker

`docs/design/calc-sources.md` §1 records a requirement from the project owner
(2026-09-19): importing data from an outside file should have some form of
picker in this editor, provided that is not terribly difficult to implement. His
reason, in his terms: he is not fond of adding more places where a user has to
manually type the things they want out of a file, and intuition and ease of use
are key. It is a requirement on the editor work, not a decided implementation —
this document has not settled what the picker lists, how a named key is chosen
from it, or where the resulting `source("path", "key")` text is emitted.

#### PDF datasheet values

**Raised by Jared on 2026-09-21. Status: NOT DECIDED IMPLEMENTATION / later
slice** — the CSV/xlsx picker above is unchanged. Recorded in full in
`docs/design/calc-sources.md` §1.

Jared's proposal: the picker **tries** to extract the number from a pinned PDF
datasheet, then asks the author to verify it is correct before accepting.
Agreed shape and safety rules:

- Show the extracted value with its unit **in context** — the highlighted
  cell/line on the rendered page — not the bare number.
- When a table row has several candidates (min/typ/max columns), list all of
  them and let the author choose.
- Nothing is pre-selected: accepting is a deliberate step, never automatic.
- On accept, record a `citations:` entry holding the file, the page or
  `section:`, the quoted text, and the value the author confirmed, so a
  reviewer can re-verify.
- The calc-sources lockfile pins the number, so a changed PDF raises the loud
  drift warning (calc-sources Q2: warns loudly, `fetch --update` accepts).
- If the page is scanned/image-only, or extraction is ambiguous, fail visibly —
  “could not read this page” — never guess.

The failure this guards against is a silent plausible-but-wrong number: mA vs A
(the 1000x trap), or the wrong min/typ/max column.

Costs, stated plainly: this needs a PDF text-and-coordinates library as a new
dependency (an optional dependency, like openpyxl for xlsx), and rendering
pages in the browser means vendoring pdf.js (large) or rendering images
server-side; both fit “no Node build step”, but it would be the heaviest
dependency the editor has.

Sequencing: build after the CSV/xlsx picker, as its own later slice — the PDF
reader is one more source type behind the same picker UI and the same
confirm-before-accept step.

### Link picker

For each link verb, the API supplies its allowed target types from
`ItemType.links`. An empty allowed list means unrestricted; the server remains
authoritative. This is the same rule `resolve_links()` validates today
(`src/refdes/build.py:448-510`).

The picker searches current display IDs and titles, filters by allowed type,
and displays board/workspace/source context. Selecting a target stores its key
in form state. Saving emits `CURRENT-DISPLAY-ID@key`; the browser never
constructs the composite from stale text. Removing a chip deletes that target
from the link field.

Imported targets are writable. `items.json` exports every item's key as a
nullable field, `imports._absorb` stores a keyed import under that key, and a
writable load expands a bare cross-project link to the same composite a local
target gets (`docs/design/keys.md:1195-1210`; `src/refdes/imports.py:60-73`;
`src/refdes/cli.py:99-111`). Two cases stay unavailable, each with an explicit
reason rather than a silent bare ID: an artifact produced by an older refdes, or
by a `--no-write` load, whose `key` is `null`; and any target whose key does not
resolve, which keys treats as an error rather than falling back to the display
half (`docs/design/keys.md:535-537`).

Prose `[[ITEM-ID]]` remains display-ID text, not a composite. That is a
separate human-authored reference mechanism by design
(`docs/design/keys.md:539-546`).

### Creating items

Creation starts with type, then board/workspace where configured, fields,
links, body, and destination. The editor suggests a directory from the
project's `item_layout`, registered board/workspace paths, and neighboring
items. The project's only fixed layouts are `flat` and `workspace`
(`src/refdes/model.py:42-46`; `docs/workspaces.md:41-56`); outside those
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
(`src/refdes/ids.py:321-450`), so implementation needs a pure single-item
allocation plan reusable inside the editor transaction. `keys.mint()` is
already pure (`src/refdes/keys.py:107-114`). The new file/item insertion,
ledger update, key, and any initial composites commit together; a failed save
burns no ID.

For a log entry, the date picker writes the project's declared `date_format`,
not the browser's locale. The setting defaults to `YYYY-MM-DD` and accepts one
each of `YYYY`, `MM`, and `DD` with a repeated separator
(`src/refdes/dates.py:9-30`); parsing is strict calendar validation
(`src/refdes/dates.py:49-58`). This repository currently declares
`date_format: YYYY-MM-DD` (`refdes-project.yaml:28-30`).

### CLI parity

The backlog's scope decision is explicit: the CLI must remain able to do
everything the form can do (`docs/design/backlog.md:308-311`).

**Decided:** parity means **semantic reachability**, not a twin command per form
action. The reason is not convenience — it is that a second command surface
would be a second implementation, and the whole value of this design is that one
Python service sits behind both surfaces. A flag language that mirrors every
widget would drift from the form within a release and be maintained by nobody.
The plain files remain the public authoring interface:

| Editor operation | Existing non-browser path |
|---|---|
| Edit a field or body | Edit the YAML/Markdown source and run `refdes check`. |
| Add/remove a link | Edit the declared link field; a writable load expands a bare target to a composite (`src/refdes/cli.py:105-118`). |
| Create an item | Run `refdes new TYPE`, put the scaffold in the file you want (it prints to stdout: `src/refdes/cli.py:812-824`), then `refdes id`; writable loading mints its key and expands links (`src/refdes/scaffold.py:135-180`; `src/refdes/cli.py:69-135`). |
| Filter or list items | `refdes ls` for the narrow question, `refdes index` for everything a script needs (`src/refdes/cli.py:441-494`, `src/refdes/cli.py:405-431`). |
| Amend a sealed log | Create a new log by the same path and author its `amends:` link; never mutate the sealed entry. |

The browser adds safe source manipulation and aggregates those steps into one
transaction, but it adds no browser-only state and no semantic operation the
files cannot express. A transactional create with initial links has no
one-command CLI twin today; the same final state is nevertheless reachable
through `new`, source editing, `id`, and a writable check/build. Likewise,
“amend this log” is a pre-filled ordinary log plus `amends`, not a new lifecycle
operation.

The transaction, allocation-planning, and item-intent layers must therefore be
ordinary Python services, not code buried in HTTP handlers. That is what makes
this parity definition safe rather than a loophole: if an atomic one-command CLI
ever becomes a real need, it is a thin caller of the service that already exists,
not a reimplementation. v1 does not invent a large `refdes item set` flag
language to mirror widgets.

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

Measured in an earlier pass of this document, on this repository's own project
(two dozen items), `refdes build --dry-run --keep-going` rendered the site and
reported the project's expected one error/two warnings in **1.06 seconds wall
time**, process startup included. Treat that as a baseline rather than a live
reading: it was not re-measured while revising this document, and the rebuild
policy below rests on it. `--dry-run` is the right proxy for the editor's
post-save rebuild — it renders real browsable HTML and skips only seal recording
(`src/refdes/cli.py:1203-1210`), which is the `seal_write=False` posture the
editor needs. A full rebuild after a committed save is therefore acceptable for a
project of this size. Unsaved preview requests should be debounced and superseded;
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
(`src/refdes/parse.py:502-510,665-680`). A direct probe against the installed
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
flow mappings without dumping the file (`src/refdes/ids.py:220-320`). The
newly extended link writer bounds edits to parsed item/default spans and
handles direct values, block sequences, and one-line flow mappings while
reporting exactly what it rewrote (`src/refdes/links.py:44-197,252-300`), with
the plan/apply split in `plan_expansion()` and `expand_missing()`
(`src/refdes/links.py:353-490`).
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
  (`src/refdes/model.py:400-406`).
- Apply edits bottom-up within each file so earlier offsets remain stable.

This is not a new YAML parser. PyYAML still decides meaning before and after;
the patcher only locates and replaces bounded source text. Fixtures must cover
comments, CRLF/LF, BOM handling, quoted YAML 1.1 traps, inline and block lists,
flow entries, multiline scalars, defaults/sections, multi-item Markdown, and
an edit adjacent to a literal `---` in body prose.

## Validation, conflicts, and transactions

### Side-effect-free loading is Slice 0 — and its hard half has landed

Editor GET, polling, conflict detection, and unsaved preview must never mint a
key, expand a link, refresh a manifest, or seal an entry. `_load()` does mint
keys and expand bare links while loading (`src/refdes/cli.py:69-135`) — but
every one of those writes is now gated by the global `--no-write`, and the code
says so outright: minting, link expansion, `.refdes/schema.json` regeneration,
and, through `build(seal_write=...)`, the seal files and the membership manifest
(`src/refdes/cli.py:87-95`). `docs/design/keys.md` §9 item 4 records the same
conclusion, and `tests/test_no_write.py` pins it by asserting a byte-identical
`items/`, `.refdes/`, and config tree across commands.

What remains for Slice 0 is the editor-specific half: one load/build entry point
that accepts in-memory source overlays, so a candidate form can be built and
validated before anything is written. The editor must consume that path, not
create a second “mostly read-only” loader.

### Drafts: what the editor holds before it saves

An edit is not a file write with extra steps. While a form is open the author's
work is a **draft**: the intent to change one item, held against the revision the
form was opened on. Nothing about a draft touches disk — no scratch file in the
project, no shadow copy under `.refdes/`, no autosave into the source. The file
stays the file until a save is explicitly requested.

Where a draft lives, stated plainly, because “the browser” is not an answer that
survives a crash:

- the live copy is in the open page's memory;
- a mirror is kept in that page's `sessionStorage`, so reloading the tab recovers
  it and closing the tab destroys it;
- nothing survives a browser restart, and nothing is kept in the project.

Closing the tab is therefore a **discard**, and the UI must say so before it
happens: an unsaved draft raises a `beforeunload` prompt, and the editor's
reconnect banner offers to reopen the item rather than dropping the author back
at the list. Keeping drafts across sessions is not a v1 feature, and pretending
otherwise would mean building a second, worse autosave next to git.

On save, three versions meet: the revision the form opened on, the draft, and
what is on disk right now.

- Disk still matches the revision the form opened on: the draft is the only
  change, and the transaction proceeds.
- Disk has moved — another tab, VS Code, a `git checkout`, a CLI write: the save
  is **refused**, and the author sees their draft against the current file side
  by side, with three outcomes offered: keep mine (overwrite, having seen exactly
  what is lost), keep theirs (discard the draft and reload), or copy my draft out
  by hand.

There is no fourth option that merges. Automatic merging is explicitly out of v1,
and not because it is hard to wire up: a YAML merge that guesses which of two
edits to a hand-authored item wins produces a file that parses cleanly and means
something neither author wrote — the exact failure class this project keeps
finding and fixing. Refusing loudly is the feature.

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

A content mismatch returns a conflict, never a last-write-wins save. “Drafts”
above is the UI contract for that moment; this section is the mechanism behind
it. The UI shows which files changed and separately reports any HEAD/index
movement, so the author can tell “someone edited my item” from “I switched
branches.”

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
errors except check violations (`src/refdes/revise.py:818-841`). An item editor
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
originals on failure (`src/refdes/revise.py:1065-1347`), and already keeps the
reusable pieces as their own functions: `write_rewrites_verified()` re-checks a
rewritten file before it counts as written, and `restore_rewrites()` puts the
original bytes back (`src/refdes/revise.py:581-590,628-661`). Editor saves need
that same posture, generalized with source overlays and crash recovery.

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
(`src/refdes/seal.py:222-342`, message at 311-320). `is_sealed()` is already the
predicate for exactly this question (`src/refdes/seal.py:199-216`), and in the
keys end state the lookup runs on the surrogate key.

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
  (`src/refdes/build.py:1741-1746`), and Jinja autoescaping is explicitly on
  (`src/refdes/render.py:769-775`).
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
the launch token for `/api/` reads as well as writes is **decided: yes** — reads
carry it too. The cost is one header on a fetch the same page already makes, and
the benefit is that a page that failed the token check reveals nothing at all
rather than a project's full item list.

### Permissions are out of scope for v1 — with one seam

`refdes serve` serves one local author on loopback. There is no account model,
no roles, no per-item ACL, and no shared-service mode, and designing one now
would mean speculating about users who do not exist while the real design goes
untested. The launch token is not an identity system: it proves only that a
request came from the browser this server opened.

The seam worth paying for now is cheap, and it is the difference between a later
feature and a later rewrite:

- **One entry point applies every mutation.** No handler writes a file on the
  side; every change goes through a single apply-operation call.
- **Every operation carries who asked.** Today that is always the same local
  author, recorded as such — the field exists before anyone needs it.
- **A refusal is a first-class result, not an exception.** “Not allowed”,
  “sealed”, “conflict”, and “would introduce an error” share one shape: a
  reason, the operation it applies to, and the statement that nothing changed.

With those three, adding authentication or a second writer later is one more
check in one place plus a new caller identity — not an audit of every handler
that might have forgotten.

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

**Status: the `--no-write` coverage is done** (keys.md §9 item 4), and the
byte-identical-tree proof is pinned by `tests/test_no_write.py`. What remains is
the editor-facing half.

- ~~Complete global `--no-write` coverage for every incidental source/metadata
  write.~~ Done: minting, expansion, `schema.json`, seals, and the membership
  manifest are all gated (`src/refdes/cli.py:87-95`).
- Expose one side-effect-free load/build API with source-overlay support.
- Prove reads, previews, CI checks, and bisects leave `items/` and `.refdes/`
  byte-identical — already pinned for the CLI surface by
  `tests/test_no_write.py`; extend it to the editor's own GET/preview paths.

This started as standalone keys work and landed as such; the remainder is
editor-only plumbing.

### Slice 1 — existing fields and bodies

- Add `refdes serve`, loopback security, editor model, content-revision
  polling, advisory git status, and side-effect-free rendered preview in an
  OS temporary directory.
- Build the filtered item list — type, board, workspace, tag, file, coverage
  stage, check state, blocked state, and free text — answered from the built
  project and held in the URL.
- Implement item-span source patches, field controls, inherited-value behavior,
  Markdown body editing, server-side preview, and the draft/conflict flow
  (refuse and diff, never merge).
- Implement transaction journal/recovery checks across every project-loading
  command, conflict checks, attributed delta diagnostics, and sealed read-only
  enforcement.
- Keep display ID/type/key read-only.

### Slice 2 — structured links

- Add schema-filtered link pickers and composite writes.
- Revalidate target type and resolve the target key under the save lock.
- Support add/remove in scalar, flow-list, and block-list source forms without
  changing untouched syntax.
- Support imported targets whose artifact carries a key, and refuse with a
  reason the ones whose `key` is `null` (an artifact from an older refdes, or
  from a `--no-write` load) rather than writing a bare ID.

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
- A zero-install read-only browser demo (Pyodide over a checked-in example
  project) as its own small product, if a demo is ever worth building.
- A GitHub-API “fix a typo from anywhere” path, contingent on this repository
  having real test CI — which it does not have today.

## What v1 must deliver

In scope order. This is the checklist the first shippable editor is judged
against; the two items marked with a dagger are the author's own stated pain
points and are not polish.

1. **`refdes serve`, loopback only.** One project, one process, ephemeral
   `127.0.0.1` port, launch token on reads and writes, Host and Origin checks,
   CSP, and a rendered preview in an OS temp directory that never touches
   `_site/`.
2. **† Filtering as a first-class surface.** Type, board, workspace, tag,
   source file, coverage stage, check state, blocked state, link relationships,
   and free text over title and tags; combinable, counted, and held in the URL.
   Answered from the built project, not a file scan.
3. **† Identity handled for the author.** No hand-typed IDs anywhere in the
   editor's own operations: IDs offered at creation from `next_ids` and
   allocated authoritatively under the save lock; keys minted by Python; link
   targets picked from the filtered list and written as composites; a null key
   from a read-only load refused rather than silently degraded to a bare ID.
4. **Editing every field shape.** Text, person, limit, enum, date, scalar
   lists, and the structured row editors (options, checks, citations), with
   inherited values labelled and overridden per item rather than edited in the
   shared default.
5. **Editing Markdown bodies with an authoritative preview.** Source-text
   editing of both body forms, insertion helpers for `[[ID]]`, `[[fig:id]]`,
   images, and calc fences, and a preview produced by the real build pipeline
   with the document context labelled. Existing images by picker; no upload.
6. **Structured links, add and remove.** Per-verb pickers filtered to the
   allowed target types, composite writes from a selected key, imported keyed
   targets supported, and every supported list style preserved on disk.
7. **Creating every item type, including log entries.** Destination suggested
   with explicit override, all three destinations supported, ID and key minted
   in the same transaction as the file write, and a failed save burning no ID.
   Log dates in the project's `date_format`.
8. **Drafts and conflict refusal.** Edits live in the draft, not the file; a
   save against moved disk is refused with a side-by-side diff and the three
   offered outcomes; no automatic merging.
9. **Fidelity and transaction guarantees.** Byte-identical outside planned
   spans, PyYAML-authoritative post-conditions, journal plus `refdes recover`,
   and refusal when the proof cannot be made.
10. **Delta-based diagnostics.** New errors block; a pre-existing error blocks
    only the edit that touches its attributed field; unrelated repairs on a
    broken item are allowed.
11. **Sealed entries stay sealed.** No controls, mutation endpoint repeats the
    check, and the post-save rebuild never seals anything.
12. **The seam for permissions, not permissions.** One apply-operation entry
    point, every operation carrying who asked, refusals as first-class results.

Everything else in “Later” is explicitly not v1.

## Acceptance boundaries for the first version

The design is implementable when each of these outcomes can be demonstrated:

- A filter combining type, coverage stage, and a link relationship returns the
  same set the coverage report and item pages agree with, and the URL alone
  reproduces it in a fresh tab.
- Creating an item requires typing no identifier; the ID shown before saving is
  the ID the item gets, and a concurrent allocation cannot silently reuse one.
- Closing the tab with an unsaved draft warns; reopening the tab recovers the
  draft; a browser restart does not, and nothing about the draft ever appears in
  `git status`.
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

## Decisions

Recorded 2026-09-16. These were recommendations; they are calls now, with the
reasoning that settled each one.

- **Architecture: Option B.** `refdes serve` with the rendered site as preview
  and a separate `/edit/` application over the same plain files. A, C, D, and E
  are recorded above as considered and rejected for v1.
- **Separate `/edit/`, not edit-in-place.** Direct manipulation is attractive,
  but a separate privileged surface keeps `_site` honest and makes conflict and
  security state visible instead of ambient.
- **“Edit this item” belongs to the server, not the page.** The affordance
  appears only while `refdes serve` is running and never in a published static
  site. A dead edit link on a reviewed artifact is worse than no link.
- **Targeted item-span patcher, not ruamel.yaml.** More bespoke code, but one
  semantic parser and a provable “nothing else changed”. Switch to ruamel if
  maintaining bounded YAML emission turns out to cost more than carrying two
  parser semantics.
- **Fidelity boundary.** Byte-identical outside planned spans; comments, order,
  style, and quoting preserved for untouched values inside; edited values alone
  may normalize. Requiring byte-identical spelling of the edited value would
  make safe quoting and type changes needlessly brittle.
- **Creation destination: suggest plus override.** Suggested from type,
  board/workspace, and neighboring files; explicit relative-path override always
  available; all three destinations (append YAML, append Markdown, new Markdown
  file) in v1.
- **No display-ID rename in v1.** The refresh machinery has landed, but the
  editor starts depending on it after it has been exercised independently on
  real projects.
- **Delta-based validation.** Block newly introduced errors and a pre-existing
  error whose attributed field the edit touches; allow unrelated repairs on an
  already-broken item. A globally clean-project gate would disable the editor
  precisely when it is needed to fix something.
- **Existing images only in v1.** A picker covers the authoring syntax without
  quietly adding binary file management — destination, overwrite, MIME policy,
  and binary conflicts — to the source transaction.
- **No Node build step.** Plain ES modules and CSS, packaged in the wheel, so a
  pip install stays a pip install. Reconsider after measured maintenance pain,
  not pre-emptively.
- **VS Code is a later adapter.** It reuses the service operations; it does not
  define the editor's architecture. The standalone browser surface comes first.
- **Full rebuild after save.** Acceptable at the measured baseline. Incremental
  rendering would add cache invalidation before there is evidence for it.
- **CLI parity means semantic reachability, not a twin command per action.** The
  point of the rule is that one implementation sits behind both surfaces; a flag
  language mirroring every widget would be a second implementation that drifts.
  Every v1 result stays reachable through `new`, plain-text editing, `id`,
  `ls`/`index`, and check/build, and the intent/transaction layers stay ordinary
  Python services so a real CLI can be added later as a thin caller.
- **Git identity is advisory; content is the conflict proof.** Blocking on
  HEAD/index identity would let an unrelated `git add` invalidate every open
  form while protecting no working-tree bytes.
- **Concurrency: draft, refuse, diff — never merge.** Edits live in a draft, not
  the file. On save, unchanged disk saves; moved disk refuses and shows the
  draft against the current file with keep-mine, keep-theirs, or copy-by-hand.
  Automatic merging would guess which edit wins and produce a file that parses
  cleanly while meaning something neither author wrote.
- **Permissions are out of v1, with a seam.** One apply-operation entry point,
  every operation carrying who requested it, refusals as first-class results.
- **Pyodide: rejected for the author's project, kept for a demo.** The objection
  is Chromium-only write access, a doubled test surface for the write path, and
  a cached browser runtime that can disagree with the CLI on keys and seals —
  not its download size. A read-only zero-install demo is a different, smaller
  product.
- **GitHub API: rejected for v1.** Commit-per-save is a fine model for fixing a
  typo from a phone and a poor one for the primary editor, because the write
  path stops being refdes's own. It also depends on CI that does not exist yet:
  `.github/workflows/` holds only `docs.yml`, which currently fails at
  `configure-pages` because Pages is disabled.
- **Read APIs require the launch token.** One header on a request the page
  already makes, in exchange for a failed check revealing nothing rather than the
  whole item list.

## Open questions

All nine questions this document originally posed are answered above; none blocks
the design. What is genuinely still unknown is empirical, and each has a cheap
way to find out:

- **Re-measure the rebuild.** The 1.06-second figure predates this revision and
  describes a project of two dozen items. Re-measure on the largest real project
  before assuming a full rebuild stays acceptable.
- **Do diagnostics carry enough attribution?** The delta gate needs a diagnostic
  to name the field, body, or link it is about. If today's diagnostics cannot,
  enriching them is a prerequisite for the gate, not part of it.
- **How much source does the patcher have to bound?** The fidelity fixtures will
  find the shapes — comment attachment, ambiguous node extents, a literal `---`
  in prose — where the honest answer is “refuse and say why”. The interesting
  number is how often that happens on real files.
