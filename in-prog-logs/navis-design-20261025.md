Status: Design proposal. Owner decisions of 2026-10-25 are recorded as binding
(§2). Nothing is implemented; every claim about current behavior below names
the file (and command, where run) it was verified against.

# Navis — project-wide flying notes

## 1. Concept (owner's note, 2026-10-20, verbatim)

> Task: capture Jared's Navi idea for later feature design.
> 2026-10-20: Requested project-wide "flying" notes that follow the reader in
> any file, like reminders related to information learned while writing. Notes
> should be removable one by one, with a Show all view that includes removed
> notes. Name: Navis (Ocarina of Time reference).
>
> Initial design thought: a small panel available from every file; each Navi
> has text and may link to its source. Treat removal as archival so Show all
> can reveal and restore it. Keep this separate from authored document bodies.
>
> Status: concept only. No schema, storage, UI, or behavior implemented.
> Resume after the current AgentCoder priority and confirm detailed behavior
> with Jared before implementation.

## 2. Owner decisions (Jared, 2026-10-25, binding)

1. **Project-wide.** A Navi is available from every file (editor and
   published site) through a small panel that follows the reader; Navis are
   reminders related to things learned while writing.
2. **Removal is archival.** A Navi is removable one by one; removal archives
   it. A "Show all" view reveals archived Navis and can restore them.
3. **Archiving never removes or edits text in a body.** The Navi's text stays
   exactly where it was written. Archiving archives the *pointer*: the Navi
   stops linking to its source and drops out of the active list; restore
   re-creates the link and puts it back. Archive state therefore lives outside
   the body, keyed by the Navi's stable identity; the body marker stays as
   inert text; archive/restore change no body, hash, seal, or history content.
4. **Archive records are compressed.**
5. **Every Navi links to its source** (the note/file/location it is about).
6. **Navis live in note bodies.** They are hand-authored inside the body text
   of the note or file they are about; the panel gathers them project-wide.
   This supersedes the concept note's "keep separate from authored bodies".
7. **Navis are separate from derivation.** Hand-authored, never computed by
   refdes, never mixed with derived worklist rows. `docs/design/living-notes.md`
   §5 binding rule 1 (lines 461-467: "Two structurally separate groups … A
   derived row never sorts into the author's list") is the structural rule a
   Navi list must follow in reverse: a Navi is never a derived row, never
   appears inside the task pane, and shares no surface that sorts the two
   together.

## 3. The model

- A **Navi** is one hand-authored marker in an item body: a stable key, a
  line of text, and — implicitly — the item that contains it (its source).
- The **active list** is every marker whose key has no archive record.
- **Archiving** writes one compressed record keyed by the Navi's key; the
  marker in the body is untouched and becomes inert (not in the active list).
- **Restoring** deletes/neutralizes that record; the marker becomes active
  again. Neither operation writes the body.
- The **panel** (editor/preview and published site) shows the active list
  project-wide, each row linking to its source item, with a Show-all view
  including archived Navis and a restore action where writes are allowed.
- **Show all** = active + archived, labelled.

## 4. Marker syntax (§2.3: inert, §6: in the body)

Inventory of inline syntax a marker must not collide with (all verified in
`src/refdes/build.py`, `src/refdes/calc.py`, `src/refdes/inline_calc.py`,
`src/refdes/blocks.py`; author-facing docs `docs/markdown.md`):

| Syntax | Definition |
| --- | --- |
| `[[ID]]`, `[[ID#field]]`, `[[ID#calc:name]]`, `[[ID\|label]]` | `EXPLICIT_REF_RE` `build.py:69-72`; `CALC_FRAGMENT_PREFIX` `build.py:76` |
| `[[fig:…]]`, `[[cite:…]]` | `build.py:3280-3311`, `CITATION_ID_RE` `build.py:189` |
| bare ids `REQ-PWR-002` | `BARE_REF_RE` `build.py:78` |
| `{{name}}`, `{{name \| unit}}` (item bodies) | `INLINE_VALUE_RE` `build.py:82-84` |
| `{{index}}`… block directives (**pages only**, not items) | `blocks.py:1-63` |
| inline calc span: single backtick with unquoted `:=`, outside fences **and outside HTML comments** | `inline_calc.py:1-4,48-59,519` |
| ` ```calc ` fences | `CALC_BLOCK_RE` `calc.py:993` |
| images/figures with `{width=…}` attrs | `FIGURE_RE` `build.py:155-168` |

Rendering facts, verified:

- The Markdown engine is `MarkdownIt("gfm-like", {"html": False,
  "linkify": False})` — **html off** (`build.py:2694`), and markdown-it with
  `html:false` *escapes*
  HTML comments to visible text (`<!--x-->` renders as
  `&lt;!--x--&gt;`) — checked by running
  `MarkdownIt("commonmark", {"html": False}).render(...)` with
  markdown-it-py 4.2.0 in `.scratch/navis-design-20261025/` (output recorded
  in the task log). So a comment marker is inert in GitHub/VS Code preview
  (real renderers consume comments) but is **visible on the refdes site
  unless the pipeline consumes it** — and the pipeline must scan bodies for
  markers anyway, so the design makes consumption part of the scan.
- Inline calc deliberately skips HTML comments (`inline_calc.py:1-4,48-53`)
  and warns on unclosed ones (`build.py:1797-1803`).

**Options for the marker form:**

| Option | Trade-offs |
| --- | --- |
| A. Single-backtick code span, e.g. `` `navi: text` `` | Visible in rendered output (not inert); collides with inline calc whenever the Navi text contains `:=` (triggered span → hard error, `docs/design/inline-calc.md` §1); multi-backtick author escape hatch gets confusing. |
| B. `[[navi: text]]` link-style | Text containing `|`, `]]`, `#`, or `:` breaks the closed link grammar; unknown `a:b` namespaces are reported typos today, so this is a grammar extension with a collision surface. |
| C. **HTML comment marker** `<!--navi:KEY text-->` | Invisible in every standard Markdown renderer; cannot trigger inline calc (comments suppress spans, verified above); no collision with any syntax in the table; fenced code contains it as literal text (scan must skip fences — same scan `inline_calc.triggered_spans` already does); on the refdes site it needs an explicit consuming pass (without it, escaped text shows) — accepted, since the build must scan bodies for Navis regardless; `-->` is forbidden in Navi text (it terminates the comment) and unclosed-comment diagnostics already exist (`build.py:1797-1803`). |

**Recommendation: C.** Concrete grammar (a closed family, reported on typo —
the codebase's stated policy that silently-ignored author intent is the
failure, `build.py:66-68`):

```text
navi_marker = "<!--navi:" [ key wsp ] text "-->"      # one line only
key         = 11 chars from "0123456789abcdefghjkmnpqrstvwxyz"
text        = any text, single line, not containing "-->"
```

- **One line, always.** Single-line keeps the marker safe under CRLF
  (`src/refdes/textio.py:7-27,218,237-247` preserves per-file line endings on
  write; a multi-line construct spanning a line boundary in a CRLF file is
  the kind of byte-equality trap `textio` exists to avoid), keeps line
  reporting exact (a marker line is `item.body_line + offset`, the
  `inline_calc` line-reporting pattern), and keeps the panel row a sentence.
- Author writes `<!--navi: remember X-->`; the tool mints the key into the
  marker on the next writable load (§5, §7.2). Malformed `navi:` comment
  (bad key length/alphabet, empty text) is a warning diagnostic at the line
  (model.Diagnostic, `src/refdes/model.py:144-156`), never swallowed.
- Consumption: the body scan strips markers before `md.render` (exactly the
  way calc fences are swapped for pass-through placeholder tokens before
  render, `build.py:3155-3157,3955`); published HTML therefore contains no
  marker bytes.

## 5. Stable identity

Keys exist (`docs/design/keys.md`, `src/refdes/keys.py`): an item key is 11
characters of Crockford base32 (10 data + 1 Damm check character,
`keys.py:35-37,117-128`), minted on writable load, stored in the reserved
front-matter `key:` field, and composite display ids `DISPLAY-ID@key`
already exist for link targets (`docs/design/keys.md:84,136`).

**Options for the Navi's identity:**

| Option | Trade-offs |
| --- | --- |
| A. `item-key#ordinal` (N-th marker in the body) | Zero body cost; identity shifts when an earlier marker is inserted/deleted — archive records mis-point on every local edit. |
| B. Content hash of the Navi text | Stable only while text is unchanged; the owner's model has text edited by hand (§9), so identity must outlive text edits. |
| C. **Minted per-marker key inside the marker** — `<!--navi:k7f3q2x8d0m text-->` | Survives renames, moves, and text edits (it *is* the identity); reuses `keys.mint()` verbatim (`keys.py:117`); cost: writing the key into the marker is a body write (handled, §7.2 — it is the same class of writable-load rewrite as `anchor_follows()`), and the key is visible noise (11 chars, one line per Navi). |

**Recommendation: C.** Navi keys are a fresh namespace (minted like item
keys, validated with `keys.malformed_key_message()` for the corruption lint,
`keys.py:131`); CLI and panel show the 6-char prefix, full key in
`refdes navis show`. The **source link** is the containing item's identity
(item key, `Item.resolved_links` rules do not apply — the source is the
containing item, so `item.key` from the scan is exact, no composite needed
in the archive record; display uses the composite precedent when a label is
shown).

## 6. Where archived-pointer records live (§2.3, §2.4)

The body is never touched, so records are sidecar state. All project state
today lives under `.refdes/` as plain YAML, zero compression in `src/` (grep
for gzip/zlib/bz2/lzma in `src/` is empty); writes go through
`src/refdes/textio.py` (atomic, perms) under the per-project lock
(`src/refdes/write_lock.py`) — precedents: `.refdes/history/`
(`src/refdes/history.py:8-31`), `.refdes/baselines/`
(`src/refdes/lifecycle.py:41`), `.refdes/keys-adopted.yaml`
(`src/refdes/keys.py:32`).

| Option | Trade-offs |
| --- | --- |
| A. One compressed file per project, `.refdes/navis.yaml.gz` | One file, trivial reads; every archive edits the same file → binary git diff for the whole set, and two authors archiving Navis concurrently *always* conflict (gzip defeats merge tooling entirely). |
| B. **One gzip file per Navi: `.refdes/navis/<navi-key>.yaml.gz`** | Conflicts require editing the same Navi's record (vanishingly rare, same posture as today's one-file-per-event `.refdes/history/events/`); a record is small so gzip size is the format floor; binary diff per record — accepted, the owner mandated compression (§2.4). |
| C. Plain YAML per Navi | Human-readable diffs — **rejected by the owner's compression decision (§2.4)**, listed only to mark the trade paid. |

**Recommendation: B.** Record content (versioned, `archive_format: 1`):

```yaml
archive_format: 1
navi_key: k7f3q2x8d0m        # the marker's key — the identity (§5)
item_key: 8tqf4m2z0bh        # source item identity at archive time
source: {file: notes/power.md, line: 42}  # snapshot, display/advisory
text: Model worst-case copper temperature.  # text snapshot at archive time
archived_at: "2026-10-25T12:00:00Z"        # display metadata only, never
                                           # ordered/gated on (living-notes
                                           # §2 occurred_at rule)
```

Restore removes the record (an atomic delete under the write lock); the
marker becomes active again with its *current* body text (the live text wins
for the active list; the record's snapshot is the archive).

## 7. Seals, hashes, history — precise interaction

Verified against the code:

- The content hash includes the **body only when the body's `on_change`
  mode is `invalidate`** (`src/refdes/build.py:2309-2313`,
  `item.on_change_for("body", spec, spec.body_on_change)`; current
  `HASH_FORMAT = 6`, `build.py:2260`).
- A `log`-family item is `append_only` with `sealing == SEALING_HISTORY`
  under the capture model (`src/refdes/seal.py:384,621`); build-sealed
  append-only items exist for `SEALING_BUILD` types (`seal.py:418,476`).
- The history semantic digest covers `{history_format, type, fields, links,
  body}` (`src/refdes/history.py:26-31`); `capture_index()` maps item key →
  `(representative capture event, edited_after_captured)`
  (`src/refdes/history.py:799-807`).

### 7.1 Adding a marker is a body edit — it must be said plainly

Typing `<!--navi: text-->` into a body changes the body bytes. Consequences,
by item kind (all verified as above):

- Body mode `invalidate`: the content hash changes. For a `SEALING_BUILD`
  append-only item this is a seal mismatch → the build errors and the fix is
  the one documented hint `refdes build --reseal <board>`
  (`src/refdes/seal.py:69-74`).
- Body mode `log`/`ignore`: hash-neutral (hash includes body only under
  `invalidate`, `build.py:2309`).
- A history-captured item: the digest no longer matches the capture →
  "edited after captured" — **visible, never fatal** (decided,
  `docs/design/living-notes.md` §3 decision 2;
  `warn_edited_after_captured`, `src/refdes/history.py:799+`).

### 7.2 Minting the key into a marker is also a body edit — by design

The author writes the marker keyless; the first **writable load** mints the
key into the marker — the same class of write as hand-authored `follows:`
anchoring in the writable-load path (`links.plan_follows_anchor()` /
`anchor_follows()`, `src/refdes/links.py:685,822`, called from `load_tree()`
at `src/refdes/loader.py:149`, reached from `_load()` at `src/refdes/cli.py:58` with
`write=not (args.no_write or dry_run)`, `docs/design/living-notes.md` §2).
It is announced, never silent (same rule as capture, living-notes §2.5: a
writable command prints a line naming the write). Consequence stated
plainly: the mint write lands under the same §7.1 rules as the author's own
edit — an author adding a Navi to a sealed entry should add the key the same
way they add any text, in an edit they intend to reseal/accept.

### 7.3 Archive/restore touch no body, ever — the hard invariant

Archive/restore write only under `.refdes/navis/`: no item file byte changes
→ no content hash change (`build.py:2263`), no seal mismatch (`seal.py:432`
compares hashes of append-only items), no history event and no
edited-after-captured flip (`history.py:799`, read-only under
`capture_index`), no editor file-revision bump (the editor's
`expected_revision` tracks the item file). A test suite must pin this
invariant (archive a Navi, assert item bytes/hashes byte-identical).
`--no-write` refuses archive/restore through `_refuse_no_write()`
(`src/refdes/cli.py:94-101`); in `refdes serve`, the API layer already
returns 403 on writes under `--no-write` (`src/refdes/serve/api.py:1082-1083`).

## 8. Compression format

`src/` compresses nothing today (grep empty), so this is a free choice; the
owner mandates compression of archive records (§2.4).

| Format | Trade-offs |
| --- | --- |
| **gzip (`gzip` module)** | Stdlib, best tooling (`gunzip -c`, git filters); adequate ratio; the universal default. |
| zlib raw | Slightly smaller; no magic bytes, worse tooling. |
| lzma | Best ratio on small text, slower, less common tooling. |

**Recommendation: gzip**, one gzip stream per record (one Navi per file, §6).
The cost is binary git diffs — inherent to the compression decision; the
mitigation is `refdes navis show` / `show --archived` as the text reader.

## 9. Edits, deletes, and the four states (owner's §2.3 checklist)

The marker carries the identity, so the scan (not the record) is the live
truth. The record's `item_key`/`source` are a snapshot for display and
diagnostics; the live link follows the marker.

| State | Meaning | Panel | Diagnostic / restore |
| --- | --- | --- | --- |
| Marker, no record | Active Navi (normal) | In active list, links to containing item | — |
| Marker + record | Archived (normal) | Not in active list; in Show-all with snapshot text, marked archived | Restore: delete record → marker active again, showing its **current** text. |
| Record, no marker | Archived, then marker hand-deleted/moved out of scope | Show-all reveals it (snapshot text; source labelled "marker not found") | `navis.archived_orphan` warning at the record's stored file. Restore **refuses** (there is no marker to reactivate; writing a marker would edit a body — §2.3 forbids). Restoring the marker by hand re-pairs them by key. |
| Marker edited after archive | Text changed by hand while archived | Show-all shows the snapshot, plus "marker text has changed since archived" note when the marker's current text differs | Informational; snapshot is the archive (the live text is what a future restore shows). |

Marker moved (cut/paste to another item): the scan re-anchors by key — the
live location wins (source link follows the marker; a moved marker changes
the panel link with no record write). Text edited while **active** is simply
an edited Navi (active rows read live text).

## 10. Source-link form

The source is the containing item: panel row links to the item's site page
(today's item pages are per item, `src/refdes/templates/item.html.j2`).
Identity resolution is by item key (the `index` payload already carries
`key` and `source: {file, line}` per item, `src/refdes/render.py:734,756`),
never by display id (renames: `DISPLAY-ID@key` precedent,
`docs/design/keys.md:84`). CLI rows print
`DISPLAY-ID (file:line)`. A fragment anchor to the marker line is deferred:
markers are consumed at render, so there is no in-page anchor target in v1.

## 11. Project-wide index, panel placement, CLI parity

**Build path.** Markers are discovered in the body scan (regex over item
bodies outside fences — `inline_calc.triggered_spans` precedent,
`src/refdes/inline_calc.py:519`; linear in body size, the same cost class
inline calc already pays). The projection is computed **once per build /
once per render** — the standing rule for task-pane data
(`render.py:1136-1148`, "one projection per render", PR #197 review P4) —
and merged with the `.refdes/navis/` record set (active = markers minus
archived keys; archived = records). `refdes index` gains a `navis` key
following the "absent key, not null" convention (`render.py:640-642`).

**Panels.**
- *Published site:* the `taskpane_assets` pattern is the template —
  per-project asset pair written only when the render has Navis, so a
  project without Navis publishes byte-identical output
  (`src/refdes/render.py:1026-1050`); assets included from `base.html.j2`
  (as taskpane css/js are, `base.html.j2:10,66`); the panel data is embedded
  server-side (no fetch — the task pane "fetches nothing" contract,
  `templates/taskpane/taskpane.js:1-13`). The site panel is **read-only**
  (a static site cannot write): active list + Show-all of archived, restore
  shown disabled with a "run `refdes navis restore`" hint.
- *Serve preview + browser editor:* live state is serve's surface —
  server-side decoration of preview responses
  (`src/refdes/serve/server.py:741-779`), `/api/*` token-gated
  (`server.py:783-786`). New `GET /api/navis` (panel data incl. archived)
  and `POST /api/navis/archive` / `POST /api/navis/restore` (writes; 403
  under `--no-write`, `api.py:1082-1083`). The panel refreshes on the
  save-then-rebuild refresh the editor already runs
  (`api.py:1144-1148`).
- *Placement vs. the task pane:* a second fixed panel stacked above the
  task pane toggle (toggle `z-index: 63`, pane `62`,
  `templates/taskpane/taskpane.css:21,36`; the serve bar already solves the
  offset problem by overriding pane offsets, `serve/static/bar.css:41-42`)
  — Navis toggle above, e.g. `z-index: 65`. One toggle each; **no merged
  pane** (§2.7: a Navi never sorts into the task pane; the two lists share
  no DOM). Progressive enhancement like the task pane: no JS → no panel;
  escape-to-close; no localStorage (the task pane persists nothing today —
  only `serve/static/drafts.js` uses storage, keys `refdes.draft.v1.<handle>`,
  `drafts.js:9`).

**CLI parity (semantic reachability — AGENTS.md rule).** New
`refdes navis` family, noun-verb style matching `keys adopt` /
`history capture` (`src/refdes/cli.py:3424-3441,3573-3625`):

```console
refdes navis ls             # active Navis project-wide
refdes navis all            # active + archived, labelled
refdes navis show <navi>    # full text + source + (archived: snapshot)
refdes navis archive <navi> # writes record (§6); --no-write refuses
refdes navis restore <navi> # removes record; refuses on archived_orphan (§9)
```

Every panel fact and action is reachable from the CLI; the panel is a client
of the same projection, never a second implementation (the task pane's
"computes nothing" rule, `docs/design/thread-workbench.md` §7a,
`src/refdes/task_pane.py:1-30`).

## 12. Conflicts: editor drafts and the journal

- The draft is page memory + a sessionStorage mirror and never touches disk
  (`docs/design/browser-editor.md:796-826`; `drafts.js:9,14`), so a
  sidecar record write is invisible to an open draft — by design, because
  the record is not in the drafted file. The save path's revision check
  (three versions meet; disk-moved → 409 + diff, "draft, refuse, diff —
  never merge", `src/refdes/serve/edit.py:1-30`) protects the body: any
  write to the item's **file** outside the draft yields a 409, never a
  silent merge. Archive/restore write only `.refdes/navis/`, so they never
  bump an item's file revision and never 409 a draft.
- Precedent for sidecar state edited next to drafts: the citations accept
  lands lockfile+body as one pair under the per-project write lock
  (`edit.py:776-828`). Navis archive is the simpler case: one file, one
  atomic `textio.write_text` under `write_lock.py`'s per-project lock.
- The transaction journal (PR #367, `src/refdes/editor_journal.py`) is a
  library, not wired (`serve/edit.py:13-14` "minus the journal, which is a
  later slice"); its rule is "a journal dir on disk means the project may
  be half-applied and every consumer must refuse until `recover` runs"
  (`editor_journal.py:1-30`). Navis writers follow that rule: refuse while
  `.refdes/editor-transaction/` exists; Navis writers never begin a journal
  (single-file atomic writes need none — the journal exists for editor
  multi-file transactions).
- Concurrent writable CLI + serve: the mint write (§7.2) is in the load path
  both share (`loader.py:149`), so it is as concurrent-safe as
  `anchor_follows()` already is (write lock + idempotent-by-construction:
  a keyless marker mints once; a keyed marker is inert).

## 13. PR slice plan (each lands green, independently)

0. **This design doc.** Docs only.
1. **Grammar + scan + model + read-only CLI.** Marker regex
   (`navi:`-prefixed comment, one line), body scan producing
   `Item.navis`, malformed-marker diagnostics
   (`model.Diagnostic`, `model.py:144-156`), `refdes navis ls/show/all`,
   `index` payload `navis` key (absent-key convention). Site output
   byte-identical (markers consumed, panel not yet emitted).
2. **Key minting on writable load.** `<!--navi:` → `<!--navi:key …` in
   `_load(write=True)` (`cli.py:58` gate), announced line
   (`anchor_follows` precedent, `links.py:685,822`); short-key resolution
   (6-char prefix) in CLI; corruption lint via
   `keys.malformed_key_message()`-style validation (`keys.py:131`).
3. **Archive store + archive/restore.** gzip records under
   `.refdes/navis/`, per-project lock, `--no-write` refusal
   (`cli.py:94-101`), §9 state table incl. `navis.archived_orphan`,
   journal-dir refusal (§12), byte-identity invariant tests (§7.3).
4. **Site panel.** Projection once-per-render (`render.py:1136-1148`
   pattern), `navis_assets` gate byte-identical for Navis-free projects
   (`render.py:1026-1050` pattern), `base.html.j2` include, read-only panel
   + Show-all, z-index stack above task pane.
5. **Serve.** `GET /api/navis`, `POST …/archive`, `POST …/restore`
   (token-gated `server.py:783-786`, 403 under `--no-write`
   `api.py:1082-1083`), preview/editor panel, `bar.css` offset.
6. **(Deferred, see §14)** VS Code panel from the `index` payload.

## 14. Open questions for Jared

1. **Narrative pages:** pages are prose with no ids
   (`src/refdes/pages.py:1-8`) and carry no item key — are Navis in pages
   v1 (needs a page-level identity), or items-only in v1? (Recommend
   items-only.)
2. **One line per Navi** (grammar, §4): confirm the Navi text is always a
   single line.
3. **Text edited after archive:** Show-all shows the archive *snapshot* +
   a "marker text has changed" note (recommendation), not a re-snapshot.
4. **Published site is read-only** (archive/restore live in CLI/serve/
   editor; the site shows Show-all with restore disabled): confirm.
5. **VS Code:** the extension consumes `refdes index`
   (`editors/vscode/extension.js`; panel data lands in `index` in slice 1) —
   is a VS Code panel wanted, and is it v1 or later?
