Status: Decided -- ready to plan implementation

# Living notes, captured history, and task lists

## Decisions (2026-09-16)

Jared answered all eight open questions. They are decisions, not options under
continued review; §9 records each answer with the reasoning and the alternatives
considered and rejected.

1. **Capture moment.** A `follows:` edge appearing in a successor is the capture
   event for its predecessor, whether the edge was hand-authored or written by a
   continuation command. Manual `refdes history capture <item>` covers terminal
   and unthreaded notes, and `revision`/`release` capture baseline events for
   their own purpose. Git hooks are never correctness machinery.
2. **A captured edit is visible, never fatal.** It is a marker on the item and a
   diagnostic, never a build failure. A project may opt into a release-gate rule
   for it; the note type never blocks on its own.
3. **Snapshot fidelity.** A canonical semantic item payload plus body. Git stays
   the exact-text layer for comments and whitespace.
4. **Redaction.** Any author may run an explicit `refdes history redact`, with an
   unmistakable warning that Git, clones, and published copies keep the data.
5. **First task list.** The first task creates an ordinary `log` head, optionally
   board-scoped. There is no separate per-board notes format.
6. **Task representation.** Complete-list snapshots per task-changing
   continuation. No `tasks_add:`/`tasks_done:` deltas. The editor absorbs the
   rewrite friction.
7. **Worklist breadth.** Every derived row in §5's table, under five binding
   rules (§5). One of them is an optional, off-by-default release-gate rule.
8. **Hand-authored `follows:` captures history automatically.** This reverses the
   draft's recommendation: writing the edge *is* the explicit act. §2 states the
   five cases this commits the design to handling and says plainly which of them
   cannot be handled well.

## The model in one page

**Treat source files as the product; treat the site as one projection.** The
proposed framing is sound, with one qualification: a derived result need not be
printed by every interface, but it must be available through a non-rendering
command or editor protocol using the same Python model. `refdes index` already
shows the useful direction: it calls the build pipeline without rendering HTML
and exports coverage, calculated values, checks, links, and diagnostics
(`src/refdes/cli.py:405-433`, `src/refdes/render.py:511-643`).

Do not make an entry permanently uneditable. Replace the current build-time
seal with a **captured snapshot**: an entry stays editable, but, after a capture
moment, refdes compares its live semantic content with the stored snapshot and
shows **edited after captured** with the captured content available to inspect.
The capture moment is **a `follows:` edge naming that entry as its predecessor**,
captured by the first writable load that resolves the edge — the same load that
already rewrites the edge's own spelling (`src/refdes/links.py:592-693`, called
from `_load()` at `src/refdes/cli.py:125`). Writing the edge is the authoring
act; there is no second command to remember. A terminal or unthreaded note is
captured by `refdes history capture <item>`, and `revision`/`release` capture
baseline events. Rendering never captures: no snapshot is created by
`render_site()`, a `--dry-run`, or any `--no-write` run.

A non-locking stale-tip prompt — "is this tip still in progress?" after a
configured interval — is deferred out of this model. If it returns it is useful
self-checking, never evidence and never a history trigger, and its clock must be
explicit to keep static output reproducible (§2).

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
tip rather than inventing a merged list. The generated worklist shows every
derived gap it can, under five binding rules (§5): the author's tasks and the
derived rows are two structurally separate groups, derived rows close themselves
when their condition clears, every open task shows its age, a verdict never
prints while its own tasks are still open, and one optional off-by-default
release-gate rule covers open tasks.

The sequence is now: adjust threads phase 4a before it lands, implement the
history store and non-rendering query surfaces, then add a browser editor as an
optional client. Landing phase 4a unchanged would make `log` append-only in
precisely the build-triggered, edit-preventing sense this document rejects.

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
and rendered bodies/pages (`src/refdes/build.py:1855-1894`). `cmd_build()` then
calls `render_site()`; that call is what writes `_site/` (`src/refdes/cli.py:259-296`).
The distinction matters: many facts appear only as HTML today but are already
computed by `check`, `index`, or `ls`.

### Views

| Derived view currently on the built site | Current computation | Available without rendering? | Gap and recommendation |
| --- | --- | --- | --- |
| Per-item fields, body, links, backlinks, source location, content hash, citation state, calc results, and checks | `render.items_json()` exports those values (`src/refdes/render.py:563-642`). | **Yes.** `refdes index` emits it without `render_site()` (`src/refdes/cli.py:405-433`); VS Code consumes it on refresh. | Keep this as the editor/CLI data source, never scrape HTML. |
| Coverage stages and their address/claim/satisfy/verify evidence | `compute_coverage()` populates `project.coverage` (`src/refdes/build.py:759-886`); the index exports it (`src/refdes/render.py:533-542`). | **Yes**, via `index`; the extension status bar also counts non-verified rows (`editors/vscode/extension.js:128-141`). | Add a concise human CLI worklist, not another coverage algorithm. |
| Calculated values and failed checks | `run_checks()` builds `item.checks` (`src/refdes/build.py:927-1046`); index exports `calcs` and `checks` (`src/refdes/render.py:588-610`). | **Yes**, structured through `index`; check diagnostics are also available from `refdes check`. VS Code hovers show failed checks and calc decorations use the index (`editors/vscode/extension.js:180-207,355-412`). | Add targeted CLI rendering of the same data. |
| Thread timeline and the "currently concludes" panel | `thread_view()` folds fields/links and identifies forks (`src/refdes/render.py:260-350`); the item template renders it (`src/refdes/templates/item.html.j2:36-80`). | **Partly.** `chains.resolve_current*()` and `thread_entries()` exist, but neither `index` nor a human CLI exposes the assembled panel. | Add `refdes thread <ref>` and an index `threads` projection; do not require a site build. |
| Open thread tips/fork diagnostic | Chain resolution emits fork information (`src/refdes/chains.py:726-782`). | **Yes** as diagnostics from `check`/`index`; **no** concise tip listing. | The same `refdes thread` command should show all tips. |
| Blocked-by cascade and stale blockers | `blocked.resolve()` creates `project.blocked_chains`; `blocked.by_item()` groups them (`src/refdes/blocked.py:68-141`). | **Partly.** The item/coverage templates display the derived paths; `index` currently omits them. | Add them to the worklist/index protocol rather than making the site canonical. |
| Coverage, log, document, summary, references, and parts reports, including board/workspace variants | `render_site()` writes these reports and scoped copies (`src/refdes/render.py:756-1119`). | **No equivalent human report** today, though most inputs are computed before rendering. | Keep static reports as a useful reader view; add only the authoring queries that serve a real write-time decision. |
| Rendered Markdown, figures, linkification, copied assets, and preview JavaScript | `render_site()` writes HTML/assets and prunes its manifest (`src/refdes/render.py:756-1119`). | **No full equivalent.** The proposed editor preview would call the existing Python rendering pipeline, but `refdes serve` does not exist (`docs/design/browser-editor.md:1-23`). | This is genuinely a preview/site concern; it need not block a text/CLI worklist. |

### Side effects

| Write associated with a normal build | Where it happens now | Available without a site build? | Decision |
| --- | --- | --- | --- |
| `_site/` HTML, `items.json`, copied assets, and the output manifest | `cmd_build()` calls `render_site()`; the renderer writes/prunes its manifest (`src/refdes/cli.py:288-290`, `src/refdes/render.py:641-655,723-738,1109`). | This is build's declared output, not incidental state. `--no-write` intentionally still writes it (`docs/design/keys.md:374-382`). | Keep it as output; never use it as an event that changes source/history state. |
| New append-only seals; reseals; board-split seal migration | `build()` calls `seal.verify(... write=seal_write)` (`src/refdes/build.py:1859-1861`); new entries are written only when `write` is true (`src/refdes/seal.py:222-342`). | **No:** `check`/`index` verify only. | Replace "build seals new entry" with explicit captured-snapshot events. Preserve current files during migration (§8). |
| Board/workspace membership manifest, including accepted moves and stale-entry pruning | `build()` calls `boards.verify()` (`src/refdes/build.py:1860-1862`); it writes only when changed and write-enabled (`src/refdes/boards.py:486-521`). | **No:** checks discover drift, but do not record it. | Keep a deliberate acceptance action; it already has one (`build --accept-board-move`). Do not make it dependent on HTML rendering. |
| Schema cache, key minting, composite-link/check expansion, and `follows` freezing | These occur in `_load()` for **any writable loading command**, before build (`src/refdes/cli.py:69-136`). | **Yes, but with writes**: `check`, `index`, `ls`, and others load this way; `--no-write` gates it. | This is the strongest counterexample to "only build writes," and the reason §2 puts history capture here rather than inventing a new write path. |
| Citation lockfile/vendor cache | Not a build side effect: `citations.verify()` is hermetic (`src/refdes/citations.py:483-547`); only `refdes fetch` writes pins/vendor bytes (`src/refdes/citations.py:360-372,806-1001`). | **Yes**, via explicit fetch. | Leave it separate. Citation pinning is a different intentional record. |
| Revision/release baseline | Not a build side effect: revision/release run a read-only build then write only a passing baseline (`src/refdes/cli.py:318-380`, `src/refdes/lifecycle.py:642-735`). | **Yes**, through explicit lifecycle commands. | Extend this moment with a rich history event (§4), not a generic build write. |

**Decision.** The premise is right about discoverability: thread state,
coverage, checks, calcs, citations, and diagnostics should be queryable without
HTML. It is not right to call every write "build-only": writable loading
already changes project files (`src/refdes/cli.py:69-136`), and the design uses
that rather than fighting it. The rule that survives is about *rendering*, not
about load: **no render, `--dry-run`, or `--no-write` pass may create an
author-history event.** A writable load that resolves a new `follows:` edge may,
and does (§2).

## 2. When does an entry become captured history?

Today an append-only type is sealed the first write-enabled build sees it.
A later hash mismatch is an error unless `--reseal` accepts the changed hash
(`src/refdes/seal.py:304-322`); deletion is likewise an error
(`src/refdes/seal.py:343-410`).
That detects edits rather than physically preventing them, but it makes
ordinary work-in-progress edits build failures.

Decided: **the capture moment is a `follows:` edge, captured by the first
writable load that resolves it**, plus `refdes history capture` for notes a
thread will never supply a successor for, plus the baseline events `revision`
and `release` already write. The table below is the option set that was weighed;
the verdict on each is now part of the row.

| Option | Benefit | Failure mode / cost |
| --- | --- | --- |
| **Seal on write-enabled build (today)** -- *rejected; replaced by captured snapshots* | Existing code; a first build records every new append-only item. | Rendering/validation has an invisible authoring consequence. A note can become immutable because someone opened a preview. `index` avoids seal writes, but its regular save refresh demonstrates why that is fragile. |
| **Capture on Git commit via pre-commit hook** -- *rejected* | A commit is a recognizable checkpoint and Git already preserves review history. | A hook must be installed and kept current; a clone without it captures nothing. A hook that writes snapshots after files are staged must either restage unexpectedly or require a second commit. CI normally must verify, not invent history. It also excludes non-Git projects, contradicting the baseline design's VCS independence (`docs/lifecycle.md:266-277`). |
| **Capture when followed** -- *chosen, as the authoring act; no separate command* | The current tip stays editable; making a successor is a meaningful "what did I know then?" moment. It gives the next work session its prior list. | Forks create two captured parents; a terminal note may never be followed; id-less entries need their surrogate key; standalone logs have no successor. |
| **Capture predecessor on first writable load that sees a new `follows:` edge** -- *chosen, as the capture mechanism for the row above* | Hand-authored YAML/Markdown needs no second command: once a valid successor names a predecessor, write one idempotent `followed` event keyed by predecessor/successor. The successor may still be half typed, but the snapshot is of the untouched predecessor. | This makes generic load an author-history writer. VS Code runs writable `index` after every save (`editors/vscode/extension.js:91-126,510-526`), so a partial save can capture a later-corrected `follows:` typo. CI must consistently use `--no-write`; checking out an old branch can replay an edge absent from that checkout's history store. Idempotence prevents duplicate events, not a misleading one for a typo or branch replay. |
| **Seal at day rollover** -- *rejected* | A daily cutoff is easy to explain and may fit a diary-like log. | An unfinished note is stamped merely because midnight passed — the exact friction Jared identified. A build that compares entry date with "today" gives the same commit different seal outcomes on different days, breaking reproducible builds and bisects. It also needs a timezone rule and mistakes deliberately backdated entries for stale notes. |
| **N-day stale-tip prompt (no seal)** -- *deferred; not part of this model* | Preserves the self-checking value of "is this still in progress?" without blocking edits or creating history. | Current source has no reliable "last touched" time: a log `date:` may be backdated, and filesystem mtimes change across clone/export. A wall-clock site build would still produce different HTML on different days unless it uses an explicit as-of date. |
| **Explicit finalize/status field** -- *rejected* | Clear intent; works for single notes and standalone logs. | Adds a state authors must remember and encourages premature stamps; "final" is usually false for design work. |
| **Never capture; detect only** -- *rejected* | Maximum fluidity and no new store. | Cannot show the original content Jared wants, and a later edit is indistinguishable from an ordinary revision. |

**Decided — the `follows:` edge is the capture moment, and a writable load
captures it.** Writing `follows: LOG-A-011` into a new entry is itself the
explicit act of saying "what that entry said is now history." There is no second
command to remember, and no uncaptured-continuation state a hand author has to
be nagged about.

1. A continuation operation (a future CLI command or editor action) resolves the
   intended current tip, writes the new entry, and writes the `followed` history
   event containing the predecessor's snapshot. It must be one transaction:
   neither the successor nor the event survives a partial write.
2. A hand-authored `follows:` edge captures the same event. Capture happens in
   the writable-load path that already rewrites a bare edge's spelling —
   `links.plan_follows_freeze()`/`freeze_follows()` (`src/refdes/links.py:592-693`,
   called from `_load()` at `src/refdes/cli.py:125` with `write=not args.no_write`)
   — so the edge and its event come from one write pass and no new command or
   hook is introduced. `freeze_follows()` keeps what it does today; capture is
   added alongside it, not substituted for it.
3. A manual `refdes history capture <item>` captures an unthreaded or terminal
   note without falsely calling it final. A revision/release captures baseline
   history for its own purpose (§4). These remain explicit author moments.
4. A fork captures the predecessor snapshot once for each branch event. A merge
   captures each parent as appropriate but never selects one branch's task state
   by accident. An id-less entry is addressed by its already-required key, not
   its absent display ID.
5. The capture is announced, never silent. A writable command prints a line
   naming it (`captured LOG-A-011: LOG-A-012 now follows it`) and the editor
   surfaces the same fact on the predecessor (§6). An author who runs no
   writable command sees nothing written — which is the point of the next rule.

### The five cases this commits the design to handling

Automatic capture buys the authoring ergonomics and inherits five failure modes.
Each gets a stated rule; the last two are stated as only partly solvable,
because they are.

| Case | Rule |
| --- | --- |
| **A typo corrected on the next save.** The first save's edge resolves to the wrong predecessor and captures an event for it. | Events are keyed to the (predecessor, successor) pair. When a later writable load resolves that successor's edge to a *different* predecessor, refdes writes a compensating `followed-corrected` event naming both and treats the original as superseded — it never deletes or rewrites the first event. The snapshot was still an accurate picture of the predecessor; only the relationship was wrong, and the correction is auditable. |
| **VS Code's save refresh runs a writable `index`.** `refdes index --compact` runs 250 ms after every save (`editors/vscode/extension.js:91-126,510-526`), so a mid-thought save can be the load that captures. | Accepted deliberately: the save is the author moment, and the announced capture line plus the editor marker make the write visible instead of hidden. This is the explicit price of decision 8, paid against the draft's objection. A project that would rather not pay it configures the extension to pass `--no-write` and captures explicitly. |
| **CI must never capture.** | `--no-write` gates capture exactly as it gates every other incidental write in `_load()` (`src/refdes/cli.py:69-136`), and an explicit `refdes history capture` under `--no-write` refuses through `_refuse_no_write()` (`src/refdes/cli.py:137-149`) rather than pretending to have captured. CI is inert by construction, not by convention. |
| **Checking out an old branch replays an edge that branch never captured.** | Events are content-addressed per (predecessor key, successor key) pair, so a replay regenerates the same object and the same event id and is a no-op. Where that branch's history store genuinely lacks the event, the replay is the repair rather than the corruption: the edge exists there, so the event belongs there. |
| **Idempotence.** | One event per (predecessor key, successor key) pair, enforced by the event's content address, so repeated writable loads — the common case, since every save runs one — cannot accumulate duplicates. |

**Stated plainly, because two of these are not fully fixable.** A typo leaves a
real event in history that is only ever *corrected*, never erased. A replayed
event on an old branch carries the replay clock in `occurred_at`, not the
original authoring time. An append-only content-addressed store cannot do better
at either, and the design does not claim otherwise; both residuals are visible,
and `refdes history redact` (§3) is the way an author clears them from the
working store. `occurred_at` is therefore display metadata only — never used for
ordering, comparison, or any gate decision.

The rejected alternative was to require a separate explicit command after a
hand-edited edge, with automatic capture as an opt-in. It was rejected because
the extra step is the friction this document exists to remove: the edge already
means what the command would have meant. Every safety property the draft wanted
from the explicit form — idempotence per edge, capture only after the edge
resolves, `--no-write` inertness, explicit CI and checkout behavior — is carried
by the chosen design above.

**Deferred companion — stale-tip prompt, not a seal.** Defer this until the
capture model exists, then expose it in `refdes thread`/`refdes work`, VS
Code/editor hover, and, where useful, the site as `still in progress?` after
`N` days. It needs an explicit `last_touched_at` written only by an explicit
continuation/touch operation — never a filesystem mtime or the author-editable
`date:` field. The query takes `--as-of YYYY-MM-DD` (CI/static rendering must
supply it); an interactive CLI may default that flag from the local clock and
print the date used. A static site generated without `--as-of` omits the prompt
rather than quietly making its bytes depend on the wall clock. This companion
creates no snapshot, lock, or build failure.

VS Code runs `refdes index --compact` on each save after a 250 ms debounce
(`editors/vscode/extension.js:91-126,510-526`). Under this decision that is the
intended capture path rather than an obstacle to route around, so the hard
constraint narrows to one that must be enforced in code: **rendering, `--dry-run`,
and `--no-write` never capture, and no snapshot or seal write may happen inside
`render_site()`.**

## 3. Editing after it was captured

### Options

| Policy | Trade-off |
| --- | --- |
| **Prevent/require amendment (today)** -- *rejected* | The build error is loud and corrections are explicit, but the existing item cannot remain a living note. `amends:` preserves a correction relationship but cannot show source content once `--reseal` overwrites the hash. |
| **Allow and detect/show** -- *chosen* | Better matches notes. Requires durable snapshot content, a visible marker, and an intentional redaction story. |

**Decided — allow and detect/show.** A captured item may be edited. `check`,
`index`, the proposed `thread` CLI query, and the site all expose:

```text
captured 2026-09-15T14:08Z when LOG-POWER-014 followed it
edited after captured: current semantic content differs
original: view / diff / restore-as-new-entry
```

This is a signal, never a failed build. A project that needs the evidence
requirement enforced turns it on as a release-gate rule — the same mechanism §7
adds for open tasks: one entry in `RELEASE_GATE_DEFAULTS`
(`src/refdes/model.py:52-63`), one `_rule_*` function in the `_RULES` dispatch
(`src/refdes/lifecycle.py:575-586`), off by default like
`unverified_requirements` and `info_check_failures`, enabled per project through
the `release_gate:` overlay (`src/refdes/schema.py:174-209`, and the defaults
printed in `docs/lifecycle.md:31-43`). A requirement to amend a formal decision
stays project policy; it is not implicit in the note type.

### Snapshot storage

| Storage choice | Trade-off |
| --- | --- |
| Extend current seal records | Smallest migration, but seals contain only identity/hash (`src/refdes/seal.py:51-123`), need frequent shared-file rewrites, and conflate enforcement with viewable history. |
| Read Git history at build time | No duplicate data where full Git exists. It fails silently or expensively with shallow clones, source exports, vendored directories, non-Git projects, and missing `.git`; it also makes site rendering depend on repository topology. |
| **Dedicated `.refdes/history/` store** -- *chosen* | New state and file count, but explicit, VCS-independent, inspectable, and usable by CLI/editor/site alike. |

**Decided — dedicated, content-addressed history.** This is a proposed format,
not existing behavior:

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
`ignore` fields (`docs/design/keys.md:649-657`; `Item.on_change_for()` resolves
that policy in `src/refdes/model.py:477-489`). A task change must be visible in
history even though it must not churn a baseline.

**Fidelity is decided as the canonical semantic payload plus body**, not an
exact source span and not a hash with Git as the only content. Storing parsed
semantic content is the chosen representation.
A raw span would preserve comments and whitespace but must also capture
surrounding defaults, sections, and the split Markdown front matter/body
representation. It makes equivalent source shapes look changed. A canonical
payload is enough to render the former item and diff meaningful fields;
source-path/line still points to where it was captured. The cost is that it is
not a byte-for-byte archival copy. Git remains the tool for whitespace and
comment archaeology.

Object content addressing makes repeated baseline snapshots cheap: storage
increases with distinct item states, plus small event records. It also avoids
a global mutable index that would turn ordinary branch work into one recurring
merge conflict. The site may hide this machinery behind a history disclosure,
but the files remain ordinary committed project state.

**Decided — redaction is available to any author, through one explicit
command.** `refdes history redact <object-or-item>` requires an explicit
acknowledgement, removes matching current history objects/events, and writes an
auditable redaction event without repeating the secret. It cannot remove data
already committed to Git, clones, or published sites; the command says that
plainly in its own output and points to normal Git history rewrite/revocation
procedures. A "reseal"-style overwrite is not enough because it loses the fact
and value of the original silently. A configured project policy or second
approver was considered and rejected: access control belongs to the repository
host, and a redaction path that only some authors can take leaves the fastest
path to a leak unpoliced anyway.

**`HASH_FORMAT` and `--no-write`.** Existing seal/baseline hash readers carry
hash-format migration to avoid false edit reports (`src/refdes/seal.py:150-186`,
`src/refdes/lifecycle.py:344-406,804-888`). History objects must instead have
their own `history_format`, migrated only by an explicit history migration that
proves semantic equivalence. A new `HASH_FORMAT` must never rewrite an object or
make an item look edited. `--no-write` prohibits history writes just as it
prohibits source-tree incidental writes (the global flag is declared at
`src/refdes/cli.py:1167-1178` and gates `_load()` at `src/refdes/cli.py:69-136`):
an explicit capture/continue command refuses through `_refuse_no_write()`
(`src/refdes/cli.py:137-149`) rather than pretending it captured something.

## 4. Baseline snapshots: "what did this item say at rev-B?"

Current baselines intentionally store only per-item hash, type, title,
identity metadata, and two narrow probes; `diff_against()` is explicitly
item-scoped, hash-only, not field-level history (`src/refdes/lifecycle.py:265-325,804-888`).
So the requested item page cannot currently reconstruct "what did it say at
rev-B?" from a baseline.

| Choice | Trade-off |
| --- | --- |
| Keep hash-only baselines and tell users to use Git -- *rejected* | No new storage, but fails the same non-Git/shallow/export cases and does not meet the requested built-site view. |
| Separate full baseline archive -- *rejected* | Clear purpose but duplicates snapshot formats, serializers, migrations, and redaction policy. |
| **Use the same history object store with baseline events** -- *chosen* | One canonical former-item representation; events distinguish `followed`, `manual`, `revision`, and `release`. |

**Decided — same store, separate event kind.** A successful
`revision rev-B` captures one `baseline: revision/rev-B` event per local item,
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
   `chains._fold_from_tip()` does (`src/refdes/chains.py:515-551`). The nearest
   own `tasks:` declaration supplies the complete list. Inherited defaults do
   not declare it, matching the existing field fold (`src/refdes/chains.py:440-451`).
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

**Decided — complete-list snapshots; the editor does the rewriting.** The
full-list form is awkward in raw YAML: ticking one task rewrites the list. That
cost is accepted and assigned to the tooling, not to the author or to the data
model, because each entry stays self-contained and its state reads without
replaying a command stream. The browser editor described in
`docs/design/browser-editor.md` is a proposal, not an implementation; if built,
its checkbox action appends a continuation with the copied-and-updated list and
never mutates the current tip. Direct YAML editing stays an ordinary list
rewrite, and that is the honest description of what it is.

The delta alternative — `tasks_add:` and `tasks_done:` — was considered and
rejected. Its precise rule would have to apply deltas from oldest ancestor to
tip; IDs must be unique, `done` must target an existing open task, full `tasks:`
must reset the state, and a merge needs an explicit ordering/reconciliation
rule. That saves typing but makes hand editing, forks, restoration, and
snapshots harder. It stays out unless a measured case shows full-list UI
generation is insufficient.

### Tasks before there is a thread

**Decided — an ordinary log head, and nothing else.** The first task creation
writes a deliberately named ordinary `log` head (for example, "Power work
list"), optionally scoped to a board. It is a note, not a verdict, and later
work follows it. A project-wide task list is the same shape without a board.
A separate per-board notes file was considered and rejected: it would be a third
worklist format with no thread fold, no source identity, and no answer to "what
starts a task list?" The formality of "your scratch list is a note like every
other note" is accepted as the price of one representation.

### Generated worklist

A proposed `refdes work` query combines hand-written tip tasks with derived
rows, but preserves their origins and never writes them into `tasks:`.

| Derived gap | Existing producer / required projection |
| --- | --- |
| Uncovered active requirements | `lifecycle._rule_uncovered_requirements()` delegates to coverage stages (`src/refdes/lifecycle.py:530-551`). |
| Unverified active requirements | `lifecycle._rule_unverified_requirements()` (`src/refdes/lifecycle.py:552-555`). |
| Proposed/on-hold verdicts | Not currently enumerated as a worklist. A new projection must enumerate log threads and call the existing `chains.resolve_current(..., "status")` (`src/refdes/chains.py:552-580`); forked values remain branch-local. |
| Blocked-by cascades and stale blockers | `blocked.resolve()` computes `project.blocked_chains` and stale-blocker info; `blocked.by_item()` groups it (`src/refdes/blocked.py:68-141`). |
| Failing checks | `build.run_checks()` produces `item.checks` and sets `ok` (`src/refdes/build.py:927-1046`). |
| Unpinned citations / missing vendored copies | `citations.verify()` assigns status, and lifecycle's `_rule_unpinned_citations()` / `_rule_missing_vendored_copies()` select it (`src/refdes/citations.py:483-547`, `src/refdes/lifecycle.py:508-529`). |
| Remote citation drift | `citations.refresh()` computes drift only for `check --refresh`; it is read-only and networked (`src/refdes/citations.py:1009-1055`). |
| Forked threads | `chains.resolve()` diagnoses open forks; `thread_tips()` identifies their tips (`src/refdes/chains.py:726-782`, `chains.py:361-389`, consumed by `render.py:295-297`). |

### Binding rules for the worklist

Decided as option B — every row above appears — under five rules that are part
of the design, not implementation polish:

1. **Two structurally separate groups.** The output is the author's own tasks at
   the thread tip, then a clearly labelled derived section. A derived row never
   sorts into the author's list, never shares numbering with it, and is never
   written back into `tasks:`.
2. **Derived rows are self-closing.** A derived row exists exactly while its
   condition does and disappears when the underlying gap closes. It has no
   author-settable state, cannot be ticked, and produces no "done" event. Only
   the author's own tasks carry `open`/`done`/`dropped`.
3. **Every open task shows its age.** An open task prints the entry that
   declared it and that entry's date — `open since LOG-A-004, 2026-08-30` —
   measured from the declaring entry rather than a filesystem mtime or the
   tip's date, using the source entry the fold already reports
   (`chains.resolve_current_with_source()`, `src/refdes/chains.py:581-608`).
   Age is rendered relative to an explicit `--as-of` date; a command with no
   `--as-of` prints the absolute declaring date and no relative span, so
   generated bytes never depend on the wall clock.
4. **A verdict never prints alone.** When a thread's folded verdict is
   concluding — a status in the type's `satisfying_statuses:`, which is
   `[accepted]` on `decision` today
   (`src/refdes/standards/hardware/v3/base.yaml:167`) and carries over to the
   merged `log` type on the phase 4a branch — while open tasks remain at its
   tip, the surface prints the
   verdict and the open tasks together, with the open tasks visually attached to
   the verdict. This is the same "is it really settled?" question
   `blocked._is_settled()` already asks for `blocked_by` edges
   (`src/refdes/blocked.py:23-42`), pointed at the thread instead of an edge.
   It is a display rule and a diagnostic, not a new state.
5. **One optional release-gate rule, off by default.** A new rule —
   `open_tasks` — blocks a release while any thread tip carries an open task.
   It is declared exactly like the existing eight: an entry in
   `RELEASE_GATE_DEFAULTS` (`src/refdes/model.py:52-63`) with
   `{release: false, revision: false}`, a `_rule_open_tasks()` function added to
   the `_RULES` dispatch (`src/refdes/lifecycle.py:575-586`), which makes it a
   member of `RULE_NAMES` (`src/refdes/lifecycle.py:588`) and of the
   `release_gate:` overlay validation
   (`src/refdes/schema.py:174-209)`; `evaluate_gate()`
   (`src/refdes/lifecycle.py:604-621`) then applies it with no further change,
   and `stamp()` refuses on `enabled and offenders`
   (`src/refdes/lifecycle.py:696-698`). Off by default means notes stay fluid
   by default and a project that wants task discipline asks for it.

## 6. Surfaces without building

**Decided:** build one read-only query service first, then expose it through
CLI, `index`, VS Code, the eventual `serve` editor, and the static site. The
static page remains a reader's rich rendering; it must not be the only way to
learn the thread tip or task list. None of `refdes thread`, `refdes work`, or
`refdes history` exists today — the subcommands on `main` are `build`, `check`,
`revision`, `release`, `index`, `ls`, `id`, `fetch`, `audit`, `init`, `new`,
`schema`, `standard`, `keys`, `revise`, `stub-tests`, and `former-ids` — so
everything in this section is a proposal.

Proposed CLI, explicitly a sketch rather than current behavior:

```console
$ refdes thread LOG-POWER-002
Thread: LOG-POWER-001 → LOG-POWER-002  (one tip)
Tip: LOG-POWER-002  2026-09-15  Buck thermal follow-up
Captured: LOG-POWER-001 at 2026-09-15T14:08:00Z (followed)

Tasks at tip:
  [ ] T-thermal-model  Model worst-case copper temperature.  (open since LOG-POWER-001, 2026-08-30)
  [x] T-input-range    Check the 36 V input case.

Derived (self-closing):
  coverage  REQ-PWR-003  unverified
  check     LOG-POWER-002  P_diss violates BND-THERM-001
  citation  CMP-PWR-004  unpinned
```

The two groups are separate blocks with separate headings, per §5's binding
rules: the derived block is labelled as self-closing and its rows carry no
checkbox. A thread whose folded verdict is concluding while tasks stay open
prints the verdict line and the open tasks together rather than the verdict
alone. For a fork the header lists both tips and prints one `Tasks at <tip>`
block per branch; it never reports a single current status or list.

VS Code shows the same tip, tasks, capture marker, and fork state in the hover
for a thread entry. Today its hover is a compact item preview built from
`index` (`editors/vscode/extension.js:180-207`, registered at
`editors/vscode/extension.js:507`), and the current index payload has no thread
projection (`src/refdes/render.py:511-643` exports `boards`, `workspaces`,
`coverage`, `types`, `items`, `next_ids`, and `diagnostics` — no threads). The extension must not reconstruct the
chain itself; extend the Python index payload, as it already uses Python for
schema, diagnostics, completions, and calculated values.

`refdes serve` remains an optional client proposal, not a prerequisite.
`docs/design/browser-editor.md` already recommends a separate `/edit/` app
over the plain files and says Python remains authoritative (`docs/design/browser-editor.md:5-23,154-182`). It should call the same query/continue/history APIs as
CLI and VS Code. It must not make a site render create a snapshot.

## 7. Effect on threads phase 4a/4b

Phase 4a is not on `main`: branch `ao/refdes-64/root`, beginning at `0737950`
with three follow-ups (tip `941c975`), changes `hardware@3` so `decision` merges
into the append-only `log` type and gains `follows:` (`log` declares
`follows: [log]` and the `follows`/`followed_by` link verb, and carries
`legacy_prefixes: [DEC]`). This was checked from that branch's `base.yaml` and
`migration.yaml`, not inferred from the current main schema — `main`'s v3
`base.yaml` still has a separate `decision` type
(`src/refdes/standards/hardware/v3/base.yaml:163`) and declares no `follows:`
verb at all. The engine chain model already treats an entry as an ordinary item
and folds from the sole tip; non-declaring entries do not clear fields, and an
unmerged fork is undefined (`src/refdes/chains.py:452-551`).

| Phase 4 work | Under the recommended model |
| --- | --- |
| Retire `decision`, merge its fields/links into `log`, and migrate `title` to `summary` | **Keep.** One entry type is still the correct home for a narrative note and a verdict. |
| `follows:` chain, fold, forks/merges, id-less continuations | **Keep.** It is exactly the topology needed to locate the editable tip and carry the task list. |
| `append_only: true` meaning build seals every new log | **Change.** It would reintroduce the behavior this document rejects. `append_only` keeps its meaning for authoring (an entry is not rewritten in place; corrections are new entries) and loses the build-time hash lock. Log entries are capturable without being build-locked. |
| `_load()` freezes hand-authored bare `follows:` on any writable command | **Keep, and extend.** The same writable-load path that freezes the edge (`src/refdes/links.py:592-693` via `src/refdes/cli.py:125`) is where the predecessor snapshot is captured (§2). Rendering and `--no-write` stay out. |
| Phase 4b static thread panel | **Keep, but make it a client.** It should display task/history data from the shared projection, not own its computation or trigger writes. |
| `amends:` | **Keep as an annotation.** It identifies a specific correction; it is not a replacement for a history snapshot or chain position. |

**Decided — settle this model before landing phase 4a.** The
type merge is compatible; the current seal timing is not. Landing first would
make a later reversal more expensive: migrated decisions and fresh logs would
already be sealed under the policy being rejected. The low-risk work is to
retain the branch for its merge/migration evidence while changing the
capture contract before integration.

## 8. Migration and compatibility

| Existing project state | Migration posture |
| --- | --- |
| `.refdes/log-seal.yaml` and board-specific seal files | Continue to read/verify them during a compatibility period. Each valid legacy seal becomes a `legacy-seal` marker. It can show "recorded hash only; original content was not captured" rather than pretending a hash is a viewable snapshot. |
| A legacy sealed item whose live content still matches | A migration command may capture its *current* semantic snapshot as a clearly dated `migrated-current` event. It must not label that as the original seal-time text. |
| A resealed legacy item | Keep the existing audit drift evidence (`seal.resealed_ids()` is read-only, `src/refdes/seal.py:411-438`); no old content can be recovered unless Git has it. |
| Existing baselines | Leave their compact schema and hash-format handling intact. New baselines gain history events; old baseline item pages say rich content is unavailable. |
| Existing standalone logs | They remain valid ordinary entries. An explicit history-capture command supports them; no retroactive `follows:` inference. |
| Projects with no Git or an exported tree | Fully supported by `.refdes/history/`; no Git fallback or silent absence. |
| `--no-write` / CI | Validate and report mismatches, but create no events, objects, redactions, or migration files — including the automatic capture of §2, which sits behind the same `write=not args.no_write` gate as `freeze_follows()` (`src/refdes/cli.py:125`). A capture/continue request fails loudly under `--no-write` via `_refuse_no_write()` (`src/refdes/cli.py:137-149`). |

The new store must key records by surrogate key where available, as seals and
baselines now do after adoption. Display ID remains stored for readability but
is never the identity. Do not delete legacy seal support until a documented,
transactional migration has run and old project versions are deliberately
out of support.

## 9. Decision record

These were the open questions put to Jared; all eight are now answered
(2026-09-16). Each entry keeps the options that were on the table, states the
answer, and marks what was considered and rejected. Answer 8 reverses the
draft's recommendation.

1. **What is the minimum explicit capture moment?**
   - A. Only "continue thread."
   - B. Continue plus manual `history capture` and baseline/release events.
   - C. Git commits through a required hook.

   **Decided: B.** The natural next-entry moment is preserved without
   abandoning terminal and non-thread notes. Git hooks were rejected outright:
   they are optional integrations at most, never correctness machinery. See §2.

2. **Should a captured edit merely be visible, or ever block a release?**
   - A. Always visible, never blocking.
   - B. A project release-gate rule may block it.
   - C. Restore today's build error.

   **Decided: B, with the non-blocking half stated first.** A captured edit is
   always visible and never a build failure; the project *may* add a
   release-gate rule for it. Restoring today's build error was rejected. See §3
   and the gate mechanism in §5.

3. **What fidelity is required of a viewable former note?**
   - A. Exact source span, comments and whitespace included.
   - B. Canonical semantic item payload plus body.
   - C. Hash only; rely on Git for content.

   **Decided: B.** It renders and diffs the design meaning reliably across
   Markdown/YAML/defaults; Git remains the exact-text layer for comments and
   whitespace. An exact source span was rejected as requiring capture of
   surrounding defaults, sections, and front-matter shape. See §3.

4. **Who may redact historical content, and what acknowledgement is enough?**
   - A. Any author can run an explicit redaction command.
   - B. Require a configured project policy/second approver.
   - C. Never support redaction.

   **Decided: A**, with an unmistakable warning about Git, clones, and
   published copies. The tool must provide a path for pasted secrets;
   access-control policy belongs to the repository host. A configured
   policy/second-approver gate was rejected. See §3.

5. **Does creating the first task deserve an automatic root log entry?**
   - A. Yes: task lists always live on ordinary log threads.
   - B. Add a separate per-board/project notes file.
   - C. Require the author to create a thread first.

   **Decided: A.** One representation, and an unthreaded worklist gets a durable
   place without an extra configuration language. A separate per-board notes
   format was rejected, as was making the author create a thread first. See §5.

6. **Must tasks be complete-list snapshots, or are deltas worth the syntax?**
   - A. Full `tasks:` list per task-changing continuation.
   - B. `tasks_add:` / `tasks_done:` deltas.

   **Decided: A.** The editor absorbs the rewrite friction; complete values make
   snapshot, fork, merge, and manual-file semantics boring. `tasks_add:` /
   `tasks_done:` deltas were rejected. See §5.

7. **How broad should the generated worklist be?**
   - A. Only manual tasks and coverage gaps.
   - B. All rows in §5, including checks/citations/forks.
   - C. Make every diagnostic a task.

   **Decided: B** — every derived row in §5's table — under the five binding
   rules added there: two structurally separate groups, self-closing derived
   rows, task age, verdict-with-open-tasks surfacing, and one optional
   off-by-default release-gate rule. Making every diagnostic an author-owned
   task (C) was rejected.

8. **Should hand-authored `follows:` capture history automatically?**
   - A. Require `refdes thread continue` / explicit history capture after
     editing the edge by hand.
   - B. On the first writable load that observes a valid new edge, snapshot its
     predecessor once per predecessor/successor pair.
   - C. Offer B as an opt-in project policy while keeping A as the default.

   **Decided: B — this reverses the draft, which recommended A.** Writing the
   `follows:` line *is* the explicit act; requiring a second command to declare
   an intention the author already expressed is the friction this document
   exists to remove. The five cases A was meant to protect against — a typo
   corrected on the next save, VS Code's writable save refresh, CI, an old-branch
   checkout replaying an edge, and duplicate events — each have a stated rule in
   §2, and §2 says plainly which two of them cannot be fully fixed: a typo is
   corrected rather than erased, and a replayed event carries the replay clock.
   The opt-in variant (C) was rejected as a second mode with no consumer.
