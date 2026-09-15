Status: Draft -- exploring, nothing decided

# Living notes, recorded history, and task lists

## Recommended model in one page

**Treat source files as the product; treat the site as one projection.** The
proposed framing is sound, with one qualification: a derived result need not be
printed by every interface, but it must be available through a non-rendering
command or editor protocol using the same Python model. `refdes index` already
shows the useful direction: it calls the build pipeline without rendering HTML
and exports coverage, calculated values, checks, links, and diagnostics
(`src/refdes/cli.py:390-416`, `src/refdes/render.py:510-637`).

Do not make an entry permanently uneditable. Replace the current build-time
seal with a **recorded snapshot**: an entry stays editable, but, after a record
moment, refdes compares its live semantic content with the stored snapshot and
shows **edited after recorded** with the recorded content available to inspect.
A later entry should record the previous tip as part of the explicit
"continue this thread" write operation. That fits the working rhythm: the tip
is a living note, and starting the next entry is the moment the prior state
becomes worth remembering. It must not happen during `build`, `index`, or a VS
Code save refresh.

Use one general, versioned `.refdes/history/` store for these snapshots and
for rich baseline snapshots. Store normalized semantic item content (own
fields, raw structured links, body, identity, and source location), not an
HTML page and not only a content hash. Content-address the payloads and let
small event records refer to them. This makes the original viewable without
Git, deduplicates repeated baseline content, and works in exports and shallow
clones. It does not promise to erase historical data from Git: a deliberate
`refdes history redact` operation must remove current snapshot objects and
name the remaining Git-history responsibility.

Make `tasks:` a folded, non-invalidating field on a log thread. The sole tip
has one current list; a task edit is a **new continuation entry** containing a
complete replacement list, not an edit of its predecessor. A browser editor
can make ticking feel like a checkbox while appending that entry; direct YAML
editing remains an ordinary list rewrite. Forks deliberately show one list per
tip rather than inventing a merged list. A generated worklist should put these
hand-written tasks beside existing derived gaps, but must never silently add a
derived gap to an author's list.

The necessary sequence is: decide the recording and task semantics; adjust
threads phase 4a before it lands; implement non-rendering query surfaces; then
add a browser editor as an optional client. Landing phase 4a unchanged would
make `log` append-only in precisely the build-triggered, edit-preventing sense
this draft is reconsidering.

## Jared's problem statement

> "you usually have a rough *idea* of what tasks to do, but never the complete list. It's an evolving thing, and mostly exists as a form of self checking."
>
> "I've also been questioning the idea of 'locking' documents in the first place. Notes are dynamic, and that's part of what this system is meant to help."
>
> "a task list should be something that automatically stays with the thread tip; i.e. every time you start working, you get your task list"
>
> "Is there some way to explicitly *keep* history of previous data that was entered, as a hidden state? When something is locked it takes a snapshot of what was present when that snapshot happened, and you can mouse over or see the history yourself somehow in the built site?"
>
> "some functionality of refdes is locked behind the website being built... that's also sort of contrary to how notes behave. It requires an explicit step for extra behavior, and that feels weird."
>
> "Sealing in progress notes feels strange, like putting a stamp on something that ... is still a work in progress"

The framing to evaluate is: **files are the product and the site is one view**;
every derived fact is reachable where an author writes, without building; and a
side effect belongs to an author-recognizable moment such as committing or
starting the next entry, never to rendering HTML. The inventory below supports
that framing for read surfaces, but rejects Git commit hooks and rendering as
the canonical snapshot trigger.

## 1. Current inventory: what build uniquely exposes or changes

`build.build()` computes the project model before rendering: links, chains,
blocker chains, calcs, checks, hashes, seals, board drift, coverage, citations,
and rendered bodies/pages (`src/refdes/build.py:1831-1870`). `cmd_build()` then
calls `render_site()`; that call is what writes `_site/` (`src/refdes/cli.py:259-294`).
The distinction matters: many facts appear only as HTML today but are already
computed by `check`, `index`, or `ls`.

### Views

| Derived view currently on the built site | Current computation | Available without rendering? | Gap and recommendation |
| --- | --- | --- | --- |
| Per-item fields, body, links, backlinks, source location, content hash, citation state, calc results, and checks | `render.items_json()` exports those values (`src/refdes/render.py:562-637`). | **Yes.** `refdes index` emits it without `render_site()` (`src/refdes/cli.py:390-416`); VS Code consumes it on refresh. | Keep this as the editor/CLI data source, never scrape HTML. |
| Coverage stages and their address/claim/satisfy/verify evidence | `compute_coverage()` populates `project.coverage` (`src/refdes/build.py:735-796`); the index exports it (`src/refdes/render.py:532-540`). | **Yes**, via `index`; the extension status bar also counts non-verified rows (`editors/vscode/extension.js:128-140`). | Add a concise human CLI worklist, not another coverage algorithm. |
| Calculated values and failed checks | `run_checks()` builds `item.checks` (`src/refdes/build.py:903-1005`); index exports `calcs` and `checks` (`src/refdes/render.py:587-610`). | **Yes**, structured through `index`; check diagnostics are also available from `refdes check`. VS Code hovers show failed checks and calc decorations use the index (`editors/vscode/extension.js:180-208,322-413`). | Add targeted CLI rendering of the same data. |
| Thread timeline and the "currently concludes" panel | `thread_view()` folds fields/links and identifies forks (`src/refdes/render.py:260-348`); the item template renders it (`src/refdes/templates/item.html.j2:36-73`). | **Partly.** `chains.resolve_current*()` and `thread_entries()` exist, but neither `index` nor a human CLI exposes the assembled panel. | Add `refdes thread <ref>` and an index `threads` projection; do not require a site build. |
| Open thread tips/fork diagnostic | Chain resolution emits fork information (`src/refdes/chains.py:726-782`). | **Yes** as diagnostics from `check`/`index`; **no** concise tip listing. | The same `refdes thread` command should show all tips. |
| Blocked-by cascade and stale blockers | `blocked.resolve()` creates `project.blocked_chains`; `blocked.by_item()` groups them (`src/refdes/blocked.py:68-140`). | **Partly.** The item/coverage templates display the derived paths; `index` currently omits them. | Add them to the worklist/index protocol rather than making the site canonical. |
| Coverage, log, document, summary, references, and parts reports, including board/workspace variants | `render_site()` writes these reports and scoped copies (`src/refdes/render.py:887-1108`). | **No equivalent human report** today, though most inputs are computed before rendering. | Keep static reports as a useful reader view; add only the authoring queries that serve a real write-time decision. |
| Rendered Markdown, figures, linkification, copied assets, and preview JavaScript | `render_site()` writes HTML/assets and prunes its manifest (`src/refdes/render.py:755-1118`). | **No full equivalent.** The proposed editor preview would call the existing Python rendering pipeline, but `refdes serve` does not exist (`docs/design/browser-editor.md:1-23`). | This is genuinely a preview/site concern; it need not block a text/CLI worklist. |

### Side effects

| Write associated with a normal build | Where it happens now | Available without a site build? | Recommendation |
| --- | --- | --- | --- |
| `_site/` HTML, `items.json`, copied assets, and the output manifest | `cmd_build()` calls `render_site()`; the renderer writes/prunes its manifest (`src/refdes/cli.py:288-290`, `src/refdes/render.py:722-752,1107-1118`). | This is build's declared output, not incidental state. `--no-write` intentionally still writes it (`docs/design/keys.md:374-382`). | Keep it as output; never use it as an event that changes source/history state. |
| New append-only seals; reseals; board-split seal migration | `build()` calls `seal.verify(... write=seal_write)` (`src/refdes/build.py:1859-1861`); new entries are written only when `write` is true (`src/refdes/seal.py:222-340`). | **No:** `check`/`index` verify only. | Replace "build seals new entry" with explicit recorded-snapshot events. Preserve current files during migration (§8). |
| Board/workspace membership manifest, including accepted moves and stale-entry pruning | `build()` calls `boards.verify()` (`src/refdes/build.py:1860-1862`); it writes only when changed and write-enabled (`src/refdes/boards.py:486-521`). | **No:** checks discover drift, but do not record it. | Keep a deliberate acceptance action; it already has one (`build --accept-board-move`). Do not make it dependent on HTML rendering. |
| Schema cache, key minting, composite-link/check expansion, and `follows` freezing | These occur in `_load()` for **any writable loading command**, before build (`src/refdes/cli.py:76-134`). | **Yes, but with writes**: `check`, `index`, `ls`, and others load this way; `--no-write` gates it. | This is the strongest counterexample to "only build writes." It is also why recording must not piggyback on generic load or editor save. |
| Citation lockfile/vendor cache | Not a build side effect: `citations.verify()` is hermetic (`src/refdes/citations.py:289-316`); only `refdes fetch` writes pins/vendor bytes (`src/refdes/citations.py:496-589`). | **Yes**, via explicit fetch. | Leave it separate. Citation pinning is a different intentional record. |
| Revision/release baseline | Not a build side effect: revision/release run a read-only build then write only a passing baseline (`src/refdes/cli.py:318-335`, `src/refdes/lifecycle.py:634-717`). | **Yes**, through explicit lifecycle commands. | Extend this moment with a rich history event (§4), not a generic build write. |

**Recommendation.** The premise is right about discoverability: thread state,
coverage, checks, calcs, citations, and diagnostics should be queryable without
HTML. It is not right to call every write "build-only": writable loading
already changes project files. The design rule should instead be stricter:
**no generic load, render, or save refresh may create an author-history event.**

## 2. When does an entry become recorded history?

Today an append-only type is sealed the first write-enabled build sees it.
A later hash mismatch is an error unless `--reseal` accepts the changed hash
(`src/refdes/seal.py:264-322`); deletion is likewise an error (`src/refdes/seal.py:343-408`).
That detects edits rather than physically preventing them, but it makes
ordinary work-in-progress edits build failures.

| Option | Benefit | Failure mode / cost |
| --- | --- | --- |
| **Seal on write-enabled build (today)** | Existing code; a first build records every new append-only item. | Rendering/validation has an invisible authoring consequence. A note can become immutable because someone opened a preview. `index` avoids seal writes, but its regular save refresh demonstrates why that is fragile. |
| **Record on Git commit via pre-commit hook** | A commit is a recognizable checkpoint and Git already preserves review history. | A hook must be installed and kept current; a clone without it records nothing. A hook that writes snapshots after files are staged must either restage unexpectedly or require a second commit. CI normally must verify, not invent history. It also excludes non-Git projects, contradicting the baseline design's VCS independence (`docs/lifecycle.md:262-277`). |
| **Record when followed** | The current tip stays editable; making a successor is a meaningful "what did I know then?" moment. It gives the next work session its prior list. | Forks create two recorded parents; a terminal note may never be followed; id-less entries need their surrogate key; standalone logs have no successor. |
| **Explicit finalize/status field** | Clear intent; works for single notes and standalone logs. | Adds a state authors must remember and encourages premature stamps; "final" is usually false for design work. |
| **Never record; detect only** | Maximum fluidity and no new store. | Cannot show the original content Jared wants, and a later edit is indistinguishable from an ordinary revision. |

**Recommendation — record when followed, with explicit escape hatches.**

1. A new explicit continuation operation (CLI or future editor) first resolves
   the intended current tip, writes the new entry, and writes a `followed`
   history event containing the predecessor's snapshot. It must be one
   transaction: neither the successor nor the event survives a partial write.
2. A manual `refdes history record <item>` records an unthreaded or terminal
   note without falsely calling it final. A revision/release records baseline
   history for its own purpose (§4). These are explicit author moments.
3. A fork records the predecessor snapshot once for each branch event. A merge
   records each parent as appropriate but never selects one branch's task state
   by accident. An id-less entry is addressed by its already-required key, not
   its absent display ID.
4. Existing direct text editing remains valid. If an author creates a
   `follows:` edge by hand, a non-writing command reports it as an unrecorded
   continuation; only the explicit continuation writer makes the record. That
   deliberately changes the current writable-load `freeze_follows()` behavior
   (`src/refdes/cli.py:120-132`).

VS Code currently runs `refdes index --compact` on each save after a 250 ms
debounce (`editors/vscode/extension.js:91-126,510-526`). Therefore neither
sealing nor snapshotting may happen in `_load()`, `index`, or save-time
validation. This is a hard constraint, not a preference.

## 3. Editing after it was recorded

### Options

| Policy | Trade-off |
| --- | --- |
| **Prevent/require amendment (today)** | The build error is loud and corrections are explicit, but the existing item cannot remain a living note. `amends:` preserves a correction relationship but cannot show source content once `--reseal` overwrites the hash. |
| **Allow and detect/show** | Better matches notes. Requires durable snapshot content, a visible marker, and an intentional redaction story. |

**Recommendation — allow and detect/show.** A recorded item may be edited.
`check`, `index`, a proposed `thread` CLI query, and the site should expose:

```text
recorded 2026-09-15T14:08Z when LOG-POWER-014 followed it
edited after recorded: current semantic content differs
original: view / diff / restore-as-new-entry
```

This remains a signal, not a failed build, unless a project independently
chooses a release-gate rule for recorded edits. A requirement to amend a
formal decision can remain a project policy; it should not be implicit in the
basic note type.

### Snapshot storage

| Storage choice | Trade-off |
| --- | --- |
| Extend current seal records | Smallest migration, but seals contain only identity/hash (`src/refdes/seal.py:51-121`), need frequent shared-file rewrites, and conflate enforcement with viewable history. |
| Read Git history at build time | No duplicate data where full Git exists. It fails silently or expensively with shallow clones, source exports, vendored directories, non-Git projects, and missing `.git`; it also makes site rendering depend on repository topology. |
| **Dedicated `.refdes/history/` store** | New state and file count, but explicit, VCS-independent, inspectable, and usable by CLI/editor/site alike. |

**Recommendation — dedicated, content-addressed history.** This is a proposed
format, not existing behavior:

```text
.refdes/history/
  objects/<semantic-sha256>.yaml   # canonical snapshot payload
  events/<uuid>.yaml               # {kind, occurred_at, item_key, object, reason, successor_key?}
```

An object contains the item's key, display ID, type, own declared fields,
raw links, body, source file/line, and a `history_format` version. It excludes
rendered HTML, diagnostics, backlinks, and other rebuildable data. Snapshot
comparison uses a separately versioned full semantic payload digest, **not**
`item.content_hash`: the latter intentionally excludes `on_change: log` and
`ignore` fields (`docs/design/keys.md:653-657`; `Item.on_change_for()` resolves
that policy in `src/refdes/model.py:466-477`). A task change must be visible in
history even though it must not churn a baseline.

Storing parsed semantic content is recommended over a raw YAML/Markdown span.
A raw span would preserve comments and whitespace but must also capture
surrounding defaults, sections, and the split Markdown front matter/body
representation. It makes equivalent source shapes look changed. A canonical
payload is enough to render the former item and diff meaningful fields;
source-path/line still points to where it was recorded. The cost is that it is
not a byte-for-byte archival copy. Git remains the tool for whitespace and
comment archaeology.

Object content addressing makes repeated baseline snapshots cheap: storage
increases with distinct item states, plus small event records. It also avoids
a global mutable index that would turn ordinary branch work into one recurring
merge conflict. The site may hide this machinery behind a history disclosure,
but the files remain ordinary committed project state.

**Redaction.** `refdes history redact <object-or-item>` must require an
explicit acknowledgement, remove matching current history objects/events, and
write an auditable redaction event without repeating the secret. It cannot
remove data already committed to Git, clones, or published sites; the command
must say that plainly and point to normal Git history rewrite/revocation
procedures. A "reseal"-style overwrite is not enough because it loses the
fact and value of the original silently.

**`HASH_FORMAT` and `--no-write`.** Existing seal/baseline hash readers carry
hash-format migration to avoid false edit reports (`src/refdes/seal.py:150-184`,
`src/refdes/lifecycle.py:784-849`). History objects must instead have their own
`history_format`, migrated only by an explicit history migration that proves
semantic equivalence. A new `HASH_FORMAT` must never rewrite an object or make
an item look edited. `--no-write` must prohibit history writes just as it
prohibits source-tree incidental writes (`src/refdes/cli.py:1136-1149`): an
explicit record/continue command should refuse under that flag rather than
pretend it recorded something.

## 4. Baseline snapshots: "what did this item say at rev-B?"

Current baselines intentionally store only per-item hash, type, title,
identity metadata, and two narrow probes; `diff_against()` is explicitly
item-scoped, hash-only, not field-level history (`src/refdes/lifecycle.py:265-325,784-849`).
So the requested item page cannot currently reconstruct "what did it say at
rev-B?" from a baseline.

| Choice | Trade-off |
| --- | --- |
| Keep hash-only baselines and tell users to use Git | No new storage, but fails the same non-Git/shallow/export cases and does not meet the requested built-site view. |
| Separate full baseline archive | Clear purpose but duplicates snapshot formats, serializers, migrations, and redaction policy. |
| **Use the same history object store with baseline events** | One canonical former-item representation; events distinguish `followed`, `manual`, `revision`, and `release`. |

**Recommendation — same store, separate event kind.** A successful
`revision rev-B` records one `baseline: revision/rev-B` event per local item,
referencing the same semantic object format. The existing
`.refdes/baselines/rev-B.yaml` remains the compact gate/diff artifact; history
adds a view layer rather than changing its contract. The item page can then
show a baseline selector and resolve the event by current surrogate key. A
baseline created before this feature remains hash-only and says so, rather
than inventing historical text from current files.

## 5. Tasks at the thread tip

### Proposed field and fold

Add an optional `tasks:` field to the merged `log` type, with stable task IDs
and complete state:

```yaml
tasks:
  - id: T-thermal-model
    text: Model worst-case copper temperature.
    state: open                 # open | done | dropped
```

`tasks:` is **not** a requirement, status, link, or release claim. Set its
schema `on_change: log`, so updating it does not change `content_hash`, seals,
or baseline/audit diffs. This uses the project's existing change-policy split,
rather than special-casing a task type.

Fold semantics are deliberately stricter than a vague "latest list":

1. On a component with exactly one tip, walk backward breadth-first exactly as
   `chains._fold_from_tip()` does (`src/refdes/chains.py:515-549`). The nearest
   own `tasks:` declaration supplies the complete list. Inherited defaults do
   not declare it, matching the existing field fold (`src/refdes/chains.py:440-449`).
2. An omitted `tasks:` preserves the nearest prior list. An explicitly empty
   `tasks: []` clears it. A declared list replaces the entire prior list.
3. If equally-near declarations differ, the task result is ambiguous and the
   continuation must declare an explicit complete `tasks:` list. Equal lists
   are agreement.
4. On an unmerged fork, do **not** return one undefined global list and do
   not union tasks. Show a labeled effective list for every open tip. A merge
   with no `tasks:` declaration is likewise reported as "task reconciliation
   required" whenever its parent lists differ; a merge carrying a list is the
   explicit reconciliation.

The full-list form is slightly awkward in raw YAML: ticking one task rewrites
the list. It is nevertheless the recommended base representation because each
entry is self-contained and its state can be read without replaying a command
stream. The browser editor described in `docs/design/browser-editor.md` is a
proposal, not an implementation; if built, its checkbox action should append
a continuation with the copied-and-updated list, never mutate the current tip.

A delta alternative would add `tasks_add:` and `tasks_done:`. Its precise rule
would have to apply deltas from oldest ancestor to tip; IDs must be unique,
`done` must target an existing open task, full `tasks:` must reset the state,
and a merge needs an explicit ordering/reconciliation rule. That saves typing
but makes hand editing, forks, restoration, and snapshots harder. **Reject it
for the first model.** It can be introduced later only with a measured case
where full-list UI generation is insufficient.

### Tasks before there is a thread

A separate per-board notes file would be a third worklist format with no
thread fold, no source identity, and no answer to "what starts a task list?"
**Recommendation:** the first task creation creates a deliberately named
ordinary log head (for example, "Power work list"), optionally scoped to a
board. It is a note, not a verdict, and later work follows it. This keeps
unattached tasks in the same model from the first line. A project-wide work
list is the same shape without a board. Whether this feels too formal is an
open question in §9.

### Generated worklist

A proposed `refdes work` query combines hand-written tip tasks with derived
rows, but preserves their origins and never writes them into `tasks:`.

| Derived gap | Existing producer / required projection |
| --- | --- |
| Uncovered active requirements | `lifecycle._rule_uncovered_requirements()` delegates to coverage stages (`src/refdes/lifecycle.py:530-553`). |
| Unverified active requirements | `lifecycle._rule_unverified_requirements()` (`src/refdes/lifecycle.py:552-553`). |
| Proposed/on-hold verdicts | Not currently enumerated as a worklist. A new projection must enumerate log threads and call the existing `chains.resolve_current(..., "status")` (`src/refdes/chains.py:552-605`); forked values remain branch-local. |
| Blocked-by cascades and stale blockers | `blocked.resolve()` computes `project.blocked_chains` and stale-blocker info; `blocked.by_item()` groups it (`src/refdes/blocked.py:68-140`). |
| Failing checks | `build.run_checks()` produces `item.checks` and sets `ok` (`src/refdes/build.py:903-1005`). |
| Unpinned citations / missing vendored copies | `citations.verify()` assigns status, and lifecycle's `_rule_unpinned_citations()` / `_rule_missing_vendored_copies()` select it (`src/refdes/citations.py:289-414`, `src/refdes/lifecycle.py:508-527`). |
| Remote citation drift | `citations.refresh()` computes drift only for `check --refresh`; it is read-only and networked (`src/refdes/citations.py:603-649`). |
| Forked threads | `chains.resolve()` diagnoses open forks; `thread_tips()` identifies their tips (`src/refdes/chains.py:726-782`, `src/refdes/render.py:292-297`). |

## 6. Surfaces without building

**Recommendation:** build one read-only query service first, then expose it
through CLI, `index`, VS Code, the eventual `serve` editor, and the static
site. The static page remains a reader's rich rendering; it must not be the
only way to learn the thread tip or task list.

Proposed CLI, explicitly a sketch rather than current behavior:

```console
$ refdes thread LOG-POWER-002
Thread: LOG-POWER-001 → LOG-POWER-002  (one tip)
Tip: LOG-POWER-002  2026-09-15  Buck thermal follow-up
Recorded: LOG-POWER-001 at 2026-09-15T14:08:00Z (followed)

Tasks at tip:
  [ ] T-thermal-model  Model worst-case copper temperature.
  [x] T-input-range    Check the 36 V input case.

Derived work:
  coverage  REQ-PWR-003  unverified
  check     LOG-POWER-002  P_diss violates BND-THERM-001
  citation  CMP-PWR-004  unpinned
```

For a fork the header would list both tips and print one `Tasks at <tip>` block
per branch. It would not report a single current status/list.

VS Code can show the same tip, tasks, record marker, and fork state in the
hover for a thread entry. Today its hover is restricted to a compact item
preview based on `index` (`editors/vscode/extension.js:180-220`), and the
current index has no thread projection. The extension must not reconstruct the
chain itself; extend the Python index payload, as it already uses Python for
schema, diagnostics, completions, and calculated values.

`refdes serve` remains an optional client proposal, not a prerequisite.
`docs/design/browser-editor.md` already recommends a separate `/edit/` app
over the plain files and says Python remains authoritative (`docs/design/browser-editor.md:5-23,154-182`). It should call the same query/continue/history APIs as
CLI and VS Code. It must not make a site render create a snapshot.

## 7. Effect on threads phase 4a/4b

Phase 4a is not on `main`: branch `ao/refdes-64/root`, beginning at
`b7fc5ee`, with follow-ups, changes `hardware@3` so `decision` merges into the
append-only `log` type and gains `follows:`. This was checked from that branch's
`base.yaml` and `migration.yaml` diff, not inferred from the current main
schema. The engine chain model already treats an entry as an ordinary item and
folds from the sole tip; non-declaring entries do not clear fields, and an
unmerged fork is undefined (`src/refdes/chains.py:452-549`).

| Phase 4 work | Under the recommended model |
| --- | --- |
| Retire `decision`, merge its fields/links into `log`, and migrate `title` to `summary` | **Keep.** One entry type is still the correct home for a narrative note and a verdict. |
| `follows:` chain, fold, forks/merges, id-less continuations | **Keep.** It is exactly the topology needed to locate the editable tip and carry the task list. |
| `append_only: true` meaning build seals every new log | **Change.** It would reintroduce the behavior this document questions. Log entries can be recordable without being build-locked. |
| `_load()` freezes hand-authored bare `follows:` on any writable command | **Change.** The explicit continue writer resolves/freezes and records its parent atomically; generic load/index cannot. |
| Phase 4b static thread panel | **Keep, but make it a client.** It should display task/history data from the shared projection, not own its computation or trigger writes. |
| `amends:` | **Keep as an annotation.** It identifies a specific correction; it is not a replacement for a history snapshot or chain position. |

**Recommendation — decide this document's model before landing phase 4a.** The
type merge is compatible; the current seal timing is not. Landing first would
make a later reversal more expensive: migrated decisions and fresh logs would
already be sealed under the policy being rejected. The low-risk work is to
retain the branch for its merge/migration evidence while changing the
recording contract before integration.

## 8. Migration and compatibility

| Existing project state | Migration posture |
| --- | --- |
| `.refdes/log-seal.yaml` and board-specific seal files | Continue to read/verify them during a compatibility period. Each valid legacy seal becomes a `legacy-seal` marker. It can show "recorded hash only; original content was not captured" rather than pretending a hash is a viewable snapshot. |
| A legacy sealed item whose live content still matches | A migration command may capture its *current* semantic snapshot as a clearly dated `migrated-current` event. It must not label that as the original seal-time text. |
| A resealed legacy item | Keep the existing audit drift evidence (`seal.resealed_ids()` is read-only, `src/refdes/seal.py:411-438`); no old content can be recovered unless Git has it. |
| Existing baselines | Leave their compact schema and hash-format handling intact. New baselines gain history events; old baseline item pages say rich content is unavailable. |
| Existing standalone logs | They remain valid ordinary entries. An explicit history-record command supports them; no retroactive `follows:` inference. |
| Projects with no Git or an exported tree | Fully supported by `.refdes/history/`; no Git fallback or silent absence. |
| `--no-write` / CI | Validate and report mismatches, but do not create events, objects, redactions, or migration files. A record/continue request must fail loudly under `--no-write`. |

The new store must key records by surrogate key where available, as seals and
baselines now do after adoption. Display ID remains stored for readability but
is never the identity. Do not delete legacy seal support until a documented,
transactional migration has run and old project versions are deliberately
out of support.

## 9. Open questions for Jared

1. **What is the minimum explicit record moment?**
   - A. Only "continue thread."
   - B. Continue plus manual `history record` and baseline/release events.
   - C. Git commits through a required hook.

   **Recommendation: B.** It preserves the natural next-entry moment without
   abandoning terminal and non-thread notes; hooks are optional integrations,
   not correctness machinery.

2. **Should a recorded edit merely be visible, or ever block a release?**
   - A. Always visible, never blocking.
   - B. A project release-gate rule may block it.
   - C. Restore today's build error.

   **Recommendation: B.** Notes stay fluid by default while regulated projects
   can make the evidence requirement explicit at release time.

3. **What fidelity is required of a viewable former note?**
   - A. Exact source span, comments and whitespace included.
   - B. Canonical semantic item payload plus body.
   - C. Hash only; rely on Git for content.

   **Recommendation: B.** It renders and diffs the design meaning reliably
   across Markdown/YAML/defaults; Git remains the exact-text layer.

4. **Who may redact historical content, and what acknowledgement is enough?**
   - A. Any author can run an explicit redaction command.
   - B. Require a configured project policy/second approver.
   - C. Never support redaction.

   **Recommendation: A initially, with an unmistakable warning about Git,
   clones, and published copies.** The tool must provide a path for pasted
   secrets; access-control policy belongs to the repository host until there
   is a demonstrated refdes need.

5. **Does creating the first task deserve an automatic root log entry?**
   - A. Yes: task lists always live on ordinary log threads.
   - B. Add a separate per-board/project notes file.
   - C. Require the author to create a thread first.

   **Recommendation: A.** It has one representation and gives an unthreaded
   worklist a durable place without an extra configuration language.

6. **Must tasks be complete-list snapshots, or are deltas worth the syntax?**
   - A. Full `tasks:` list per task-changing continuation.
   - B. `tasks_add:` / `tasks_done:` deltas.

   **Recommendation: A.** The editor can hide rewrite friction; complete
   values make snapshot, fork, merge, and manual-file semantics boring.

7. **How broad should the generated worklist be?**
   - A. Only manual tasks and coverage gaps.
   - B. All rows in §5, including checks/citations/forks.
   - C. Make every diagnostic a task.

   **Recommendation: B.** It surfaces existing derived evidence without
   claiming that every warning or diagnostic is an author-owned task.
