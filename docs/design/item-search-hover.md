Status: **proposed**; **no slices scoped, no code written**. Nothing in this
document is a commitment to build it. It records a conversation about a way for
an author who cannot remember whether a fact is already in the project to ask
the project instead — and it records, more load-bearingly, that when the
conversation's central heuristic was checked against this repository's own
content, **the evidence came back against it** (§4). The recommendation that
follows from that is to build the *search* and defer the *trigger*, which is the
opposite of the order the conversation arrived at. Every §5 direction is a
direction under discussion. Every §6 question carries a recommendation, and each
recommendation is the default if Jared lets it stand unanswered.

Verified while writing: `Item`'s dataclass fields and its `title` property, the
three existing substring matchers, `serve/api.py`'s dispatch and `_item_view`,
`ServeClient.request`, the live hover provider, the live `refdes schema --json`
output, `append_only` across hardware@3, and the `?`-frequency of this
repository's real prose. Commands run are named inline; note that `refdes` on
`PATH` is broken in the environment this was written in, so every CLI invocation
was `PYTHONPATH=src python -m refdes.cli …`, which is why those strings appear
instead of the bare command.

# Item search: find the fact you cannot remember, from inside the item you are writing

## 1. Problem

Someone is authoring hardware requirements in refdes items. They are writing
prose, they are partway through a sentence or a decision, and they cannot
remember which item — or which file — already holds the information they are
about to duplicate or contradict. The example the asker gave:

> "how many analog inputs are there?"

is the shape. It is not a request to look something up in a reference manual. It
is a request to the *project*: does this design already say how many analog
inputs it has, and where.

What was asked for is that the editor notice that, search the project, and
surface candidates — as a hover, not an intrusive popup — with no generative
model anywhere in the loop. §2 records which parts of that is load-bearing.

The need itself is real and does not depend on any of the design below: someone
who cannot remember which item holds a fact needs a way to find it. §4 argues
the *trigger* is the weakest link in the idea and should be the last thing built,
not the first.

## 2. What has to be true

Four premises. They constrain every direction in §5, and the first is the reason
this is not "add search to the editor".

1. **No model.** No classifier, no generative model, no embedding search. The
   reason is not ideology and not capability — it is the risk this repo names
   in its own first line: "verify claims instead of recalling them.
   Confident-but-wrong output has happened here before — treat that as the
   default risk, not the exception" (`AGENTS.md`). A search feature that
   sometimes fabricates a plausible-sounding answer about how many analog inputs
   the design has is worse than no search feature, because the author has no way
   to tell the fabrication from the hit. Deterministic substring and
   token-frequency matching over the built project is the whole of it. §9.1
   records the classifier alternative and why it is rejected rather than deferred
   for its own sake.
2. **Wrong has to be cheap.** This is the premise that does the most work in
   this document, and §4 leans on it hard. In the conversation's framing, a
   false-positive trigger is "just an unwanted hover, not a wrong answer", so the
   bar for the trigger heuristic is **"not annoying", not "accurate."** That
   sentence is load-bearing in two directions — it argues against over-investing
   in a classifier, and (once §4's measurement lands) it argues against
   over-investing in the trigger at all. §4.3 is the honest consequence of
   applying this premise consistently rather than only where it is convenient.
3. **The project schema is a free, domain-specific signal.** Type names, field
   names, and enum choices are a domain vocabulary that a generic search tool
   does not have, and they are already in a JSON document the repo's own rules
   tell you to read before claiming anything about the schema. Measured at 63
   terms for hardware@3 — §5.2.
4. **Python remains the only implementation.** Quoted rather than paraphrased
   from the constraint the whole editor family works under: "Python remains the
   only implementation of the schema, parser, validator, ID ledger, surrogate
   keys, link resolver, Markdown renderer, figures, seals, and writes"
   (`docs/design/browser-editor.md:13-16`). Search is a semantics question —
   what counts as a match, what is ranked higher — and it belongs on the same
   side of that line as everything else. §5.1 is scoped accordingly.

## 3. Current state (verified 2026-09-29)

### 3.1 There is no search in this repository. None.

Checked before this was handed to me, and checked again while writing it,
because the answer changes what has to be built:

- **No `refdes search` command.** No `cmd_search`, no `search` subparser
  anywhere in `src/refdes/cli.py`.
- **No full-text index.** Nothing in `src/refdes/render.py` builds one; the
  `index` there is a page slug, a link-fold key index (`render.py:362-363`),
  and a history capture index (`render.py:630`).
- **No design doc on this ground.** The 23 other files in `docs/design/` include
  `editor-source-picker.md` and `editor-pdf-picker.md`, which are about *picking
  a source file*, not about searching content.
- **No mention of `refdes search` in any user-facing doc.** Zero hits across
  `docs/`, `CHANGELOG.md`, and `README.md`.
- **No search-adjacent dependency.** No SQLite, no inverted index, no
  full-text library. `difflib` is used in 23 places in `src/refdes` but only for
  did-you-mean and title similarity (`form-ingestion.md` §3.4 catalogues this),
  never for search.

The one genuinely adjacent thing is `docs/design/backlog.md` finding 36, a
declared **asset search path** — "Resolve `<img>` references by filename against
a declared search path, not by relative path" (`backlog.md:2090+`). That is name
resolution over a *declared list of image directories*, explicitly contrasted
there with "`#include <foo.h>` does not search the whole project tree; it
searches a small, explicitly declared list of locations." It shares the word and
nothing else: no content matching, no items, no ranking. It is named here only
so a reader does not mistake it for prior art.

### 3.2 What a matcher already has to agree with: three, not one

The instruction this design was handed — do not invent a second incompatible
matching convention — is right, and the situation is worse than "one convention
exists". There are three substring matchers in the repository today and **they
already disagree**:

| Where | Haystack | Case | Source |
|---|---|---|---|
| `refdes ls` free-text positional | `" ".join([item.id, item.title, *tags])` | lowered both sides | `cli.py:449,465-468` |
| `GET /api/items?q=` | `" ".join([item.title, *item_tags(item)])` | lowered both sides | `serve/filters.py:144-147` |
| link-candidate filter in the browser editor | `label.toLowerCase().includes(want)` | lowered both sides | `serve/static/links.js:134-138` |

The first two are the interesting disagreement: `ls` matches the **id**, `q`
does not. `cmd_ls`'s own docstring says why it does — "The id is in the haystack
too, because the natural query right after `refdes id` prints one is the id
itself" (`cli.py:437-440`) — and `filters.py`'s module docstring claims its
semantics "follow `refdes ls` where that command already has an equivalent"
(`filters.py:11-14`), which is true of every other filter and not of `q`.

Two consequences:

- **None of the three searches item bodies.** That is the gap this feature
  fills, and it is why "just generalize `cmd_ls`" is not sufficient: `ls` never
  had body in its haystack, and adding it would change what an existing query
  means.
- **A new matcher is a third data point on an existing inconsistency.** The
  honest options are to extract one shared matcher that all three call, or to
  add a fourth on purpose and say which of the three it follows. §6 Q3.

### 3.3 What is available to search over

`Item`'s dataclass fields, enumerated live rather than from memory:

**Searchable.** `id`, `type`, `fields` (a dict that carries `title`/`text`/
`summary`/`name`, `tags`, `status`, `limit`, `part_number`, and whatever else the
type declares), `body`, `board`, `workspace`, `source_file`, plus resolved link
targets for a "linked to something that says X" query if that is ever wanted.

**Not searchable, and named here so nobody indexes them.** `content_hash` (a
hash — nobody searches for a hash), `body_html` (a rendered duplicate of `body`;
two copies of the same prose would double every body's apparent weight), `key`,
`calcs`, `calc_values`, `checks`, `citations`, `history`, `inherited_fields`,
`id_rejected`, `prefix_hint`, `numeric_id_hint`, `board_hint`, `workspace_hint`,
`defaults_line`, `slug`.

**One trap.** `Item.title` is a *property*, not a field
(`src/refdes/model.py:553-572`): it reads `title` → `text` → `summary` → `name`
out of `fields`, truncates at 90 characters, and **falls back to the first 90
characters of `body`** when none of those exist. So "index the title" silently
means "index the title, or the opening of the body" — the two are not separable
by data shape, only by which field you chose to read. It also means a question
typed at the start of an untitled requirement's body *becomes that item's title*
and will match itself. §6 Q5.

### 3.4 The server side, and how a new read route would fit

`serve/api.py:39-75` `handle()` is a flat if-chain over exact paths and
prefixes. Every read is `method in ("GET", "HEAD")`; the tail answers 405 for a
known path with the wrong verb and 404 otherwise.

**A new read route needs no new auth code.** Token auth is not per-route — it
gates every `/api/` request centrally, reads included, which is a deliberate
decision recorded at `docs/design/browser-editor.md:982` and pinned by a
test that already exists (`test_token_gates_reads_as_well_as_writes`,
`tests/test_vscode_adapter_contract.py:353`). A `GET /api/search` branch in the
chain is automatically token-gated, loopback-bound, and `Host`-checked.

**The client side needs almost nothing either.** `ServeClient.request(pathname)`
passes `pathname` straight through to `http.request`'s `path`
(`editors/vscode/serveClient.js:240-252`), so a query string rides along in the
pathname as written — `client.request("/api/search?q=" + encodeURIComponent(q))`
is already valid. A `search(q)` method next to the existing `revision()` and
`item()` (`serveClient.js:277-284`) is the whole client change.

**And the data a search needs is already in one payload.** `_item_view`
(`serve/api.py:227`ff) returns `id`, `type`, `title`, `tags`, `fields`, `body`,
`board`, `workspace`, `source_file`. This is worth stating plainly because it
makes "fetch everything and filter in the client" visibly cheap — and §9.2
explains why the answer is still no.

### 3.5 The VS Code side: what is shipped, and the one fact that matters most

The adapter design (`docs/design/editor-vscode-adapter.md`) was written as a
spec. Checking it against the source, **Slice V−1 and Slice V0 have both
landed**:

- The §2.3 blocker is fixed. `findRoot` looks for `refdes-project.yaml`
  (`extension.js:66-71`) and `activationEvents` matches (`package.json:27`).
  The adapter doc's claim that the extension "does not activate in a current
  refdes project" is **stale**; this document does not inherit it.
- `editors/vscode/serveClient.js` exists — 337 lines, plain CommonJS, no
  `vscode` import, exactly as §7.2 wanted.
- `extension.js` is 946 lines (the adapter doc recorded 536 at drafting, so V0
  added roughly 400 of live server, status bar, and CodeLens).
- The ten Python contract tests of §7.1 and five extension-side tests exist
  (`tests/test_vscode_adapter_contract.py`, `tests/test_vscode_extension.py`).

**Slice V1 and V2 have not.** No `webview`, no `WebviewViewProvider`, no
`contributes.customEditors` anywhere in `editors/vscode/`. So a search surface
would be an addition to shipped V0, and the sidebar-panel route is not on the
table.

**The one fact that decides the shape of any hover work.** The live hover
provider has exactly one entry condition (`extension.js:495-507`):

    const range = document.getWordRangeAtPosition(position, ID_RE);
    if (!range) return null;

with `ID_RE = /\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6}\b/` (`extension.js:28`).
No id-shaped token under the cursor, no hover at all.

So a question-triggered hover is **not** "add a condition to the existing
hover." The existing provider's whole contract is a token-shaped range that it
returns as the hover's range, and a sentence of prose has no such range. This is
a second provider, or a restructuring of the first into a dispatcher, and it
should be scoped as one. §6 Q4 asks whether a hover is even the right surface.

## 4. The trigger heuristic, checked against real content

This is the load-bearing part of the document, and it does not go the way the
conversation went.

### 4.1 The target surface has zero instances of the signal

- `items/` — **0** question marks, across 2 files, 3,391 bytes, 6 items.
- `CHANGELOG.md` — **0** question marks, in the entire file.

The feature's trigger does not occur once in the only content corpus this
repository has.

### 4.2 The register analysis, and it points the other way

6 items is not a corpus, so this cannot refute anything, and §4.5 says so
plainly. But `in-prog-logs/` is 178 files and 1,299,159 bytes of the author's
own working notes — the closest thing this repository has to "a person writing
notes". Stripping fenced code blocks and inline code spans leaves **38** `?`
characters; removing the ones that are URL or query syntax (`?type=`, `?page=`,
`?token=`, `method="GET"`, and anything with a path segment or a `key=value`
shape) leaves **32**. All 32 were read, and they fall into five groups:

| Kind | Example | Where | ~n |
|---|---|---|---|
| Task-list heading | `## Finished?`, `## 4. Regression check: did the predicted −40-45% model-build win materialize?` | `in-prog-logs/finding-25.md:69`, `perf-rebaseline-opp3.md:76` | 4 |
| Quoted tool output, or a table column header | `Did you mean 'part_number'?`, `\| site \| line \| pointer? \|` | `scalar-typo-error-f3.md:101`, `config-error-doc-pointer-f8.md:58` | 11 |
| Process self-talk | `Remaining: ruff (docs only — nothing to check?)`, `standard "is the tree clean?" step` | `finding-37-decisions-links-part-of-row.md:33`, `user-sim-release-gate-run2.md:105,269` | 3 |
| A question about the *tool's own implementation*, asked in prose to whoever reads next | `dependent, and is the fix small and clear?`, `Which ending does a *new* line wear?` | `micro-sign-linux.md:5`, `windows-line-endings.md:138` | 13 |
| A self-posed question about content | `design history trustworthy?` | `user-sim-release-gate-run1.md:167` | **1** |

**One.** In 1.3 MB of the author's own notes there is one instance of the exact
behaviour this feature is built around, and it is about the *tool's own* design
history, not about a design fact.

The pattern holds across the repository. `docs/design/` carries 162 `?`
characters outside code, 156 after the same URL/query filter, and they are
overwhelmingly §6 "Open questions" items *posed to Jared*. The register that
uses `?` in this repository is the register of **asking a person for a
decision**. The feature's premise assumes a different register: writing a
question to yourself, aimed at the project. That register does not appear in the
observed prose.

**One entry does argue for the need, and it is worth quoting verbatim** — the
same release-gate log, `in-prog-logs/user-sim-release-gate-run2.md:295`:

> question ("what's in product-a?") has no answer through the listing command

That is the §1 problem stated independently, in this repository's own words,
against `refdes ls` rather than against a hover: a question about what the
project contains, with no way to ask it. It is evidence for **§1** and evidence
about the **gap** §3.1 confirms — and, pointedly, it is phrased as a thing a
*command* could not answer, which is §4.3's recommendation arriving from a
direction this document did not go looking in.

This does not mean nobody does it. It means the idea's core premise — "someone
typing a self-question into their notes is a recognizable event" — is, on this
repository's evidence, **an assumption and not an observation**. §2.2's premise
was reached on the grounds that a false trigger costs an unwanted hover. It is
worth noticing that the risk here is *worse* than a false positive: it is a
**false negative that makes the feature invisible**, and an invisible feature is
not cheap to discover.

### 4.3 What follows, and it is a reordering

Applying §2.2 honestly rather than only where it is convenient:

1. **Build the search; defer the trigger.** The stated need — "I cannot remember
   which item has this" — is fully served by a query the author types. It does
   not require them to *write a question first*, and requiring that stacks a
   detection problem on top of a retrieval problem to serve one need. A
   standalone `refdes search` that never has to guess when it should fire serves
   all of the need and none of the guessing.
2. **In VS Code, the honest first surface is a command, not a hover.** The id
   hover shows facts about a *finished* token. A question hover fires *while the
   author is mid-sentence*, which is the opposite of finished, and hovers are
   transient by nature — the results scroll away, and re-typing the sentence to
   see them again is a worse loop than re-running a command. A `Refdes: Search
   items` quick-pick is the same feature with none of those problems. §6 Q4.
3. **The WH-word / adjacency refinement should not be built at all.** The
   conversation's instinct was reasonable on its own terms — "how many / where /
   which" reads as a lookup, "is this / should this" next to a number reads as a
   self-check. The measurement is why it is not worth the effort: refining a
   classifier for a signal observed **once in 1.3 MB** is fitting noise, and
   even a perfect refinement of a near-unused trigger stays near-unused. This
   argument is independent of §2.1's no-classifier stance — it is about the
   signal, not the method.
4. **The known failure modes of the WH-word idea are real, and are recorded here
   as the conversation left them**, because if the trigger is ever revived these
   are the first things to be wrong: some genuine lookups begin with "is" ("is
   the ADC count already decided?" is a lookup); some genuine self-checks begin
   with "how" ("how much headroom is left?" next to a number you just computed
   is a self-check); and an adjacency rule keyed to "a number or unit you just
   typed" is a rule about *cursor history* rather than about the sentence, which
   means it is untestable without a cursor and is a different feature with a
   different failure surface.

### 4.4 A structural finding the corpus check turned up

`append_only: true` is on `log` **only** — verified by reading
`src/refdes/standards/hardware/v3/base.yaml:294` against every type in the
resolved schema; the other six types omit it entirely.

And the `log` type's own `doc:`, at `base.yaml:290`, says:

> "A dated entry in the design log — work done, **questions raised**,
> corrections. Entries are append-only: each is sealed on the first build where
> it has no errors, and after that editing it is a build error — corrections are
> new entries with `amends`."

So the one refdes type whose stated purpose includes raising questions is also
the one type that seals its body on the first clean build, and it requires `date`
and `summary` (`base.yaml:297-298`) — `summary` being what shows in log
listings, not the body. **A self-question typed into a log entry's body is the
least findable place to put one:** it is invisible in every log listing, and it
becomes uneditable almost immediately. If the trigger is ever built, `log`
bodies are the case to think hardest about, and probably the case to exclude.

### 4.5 What this measurement is, and is not

It is a measurement of a 6-item corpus, of an author with a demonstrably
low-question-mark register, in a repository that is a tool rather than a design
project. It is **weak evidence against a strong intuition, not proof the
behaviour does not happen.** A real user's `items/` might be full of them. The
honest claim is narrower than "the trigger is wrong": it is **"the trigger is
unvalidated, and the only evidence available is negative"** — which is exactly
the failure mode `AGENTS.md` opens by warning about, and which applies to a
design idea just as much as to a schema.

The practical consequence is a sequencing change, not a cancellation. Build the
retrieval half, which is useful on its own terms and testable, and let real
authoring accumulate the evidence about the trigger half that this repository
does not have.

## 5. Direction (all of it speculative)

### 5.1 The backend, standalone, before anything calls it

**A `refdes search` command, usable with no editor running.** It follows
`cmd_ls`'s shape exactly: `_load(args, require_ids=False)`, print
`project.errors` to stderr, `build_mod.build(project, seal_write=False,
reseal=False)` (`cli.py:441-447`) — the same three lines every read command
runs, for the same reason: an answer computed from an unbuilt project is not an
answer.

The haystack is `item.id`, `item.title`, the item's `body`, and its tags. The
first three settle the §3.2 disagreement in favour of `ls` (id included), plus
body; §6 Q2.

**Output shape is the question's own open problem, not the search's.** `ls`
prints a fixed-width table; a search wants id, type, board, title, **and a
matching snippet with the match marked**, because a ranked list of titles still
makes the author open every file to find out why anything matched. Snippet
extraction is a few lines of context around the first match and is worth more
than any ranking refinement.

**Ranking is the smallest useful thing that could work**, not a scoring system.
An id hit outranks a title hit, which outranks a body hit; ties break on type
then id, the order `apply_filters` already uses (`filters.py:207-208`). Anything
smarter should be measured against real queries first, which is the posture
`form-ingestion.md` §3.4 takes about `difflib` cutoffs and for the same reason: a
threshold chosen once and shipped is a threshold nobody revisited.

### 5.2 Keyword extraction weighted by the project's own schema vocabulary

This part measured out well and is the strongest idea in the conversation.

`refdes schema --json`, run live against this repository, yields a domain
vocabulary for free — 7 type names, 40 field names, 16 enum choices:

- **types** — bound, component, decision, group, log, requirement, test
- **fields** — addresses, alternate, amends, author, blocked_by, board, body,
  checks, citations, constrained_by, date, derives_from, drop_in, governed_by,
  history, id, last_reviewed, limit, note, options, owner, part_of, part_number,
  prefix, rationale, recorded_by, records, refdes, refines, satisfies, selects,
  source, status, summary, supersedes, tags, title, type, verifies, workspace
- **enum choices** — accepted, active, blocked, candidate, draft, failing,
  in_progress, obsolete, on_hold, passing, planned, proposed, rejected, retired,
  selected, superseded

**63 domain terms, no new dependency, already in a document this repo's own
rules say to check before making a claim about the schema.** A generic search
tool does not have this and cannot cheaply get it.

Two refinements worth more than they look:

- **The field `doc:` strings are in that same JSON**, as `description`
  (`schema_json.py:117-125`). A body containing "the numeric limit itself" is
  evidence about the `limit` field that the bare token "limit" is not. Token plus
  its documented meaning is a strictly better match signal, and it costs one
  more field read.
- **A project overlay gets its own vocabulary**, which is the feature rather than
  a limitation: a project declaring `family:` gets "family" weighted like any
  standard term.

What it will not do is carry a query on its own. 63 terms against free prose is a
modest hit rate, and the honest expectation is that vocabulary weighting
*reorders* results substring matching already found, rather than finding things
substring matching missed.

### 5.3 The server route, when the editor wants it

`GET /api/search?q=…`, accepting the same `FILTER_PARAMS` the item list already
accepts, so `?q=analog&type=bound&board=board-a` composes rather than
reimplementing. It fits the existing conventions without inventing new ones:

- one more branch in `handle()`'s if-chain, `method in ("GET", "HEAD")`
  (`api.py:39-75`);
- token auth for free — it gates all `/api/`, reads included (§3.4);
- a payload shaped like `items_payload` (`filters.py:357-368`):
  `{query, total, items: [{key, handle, id, type, title, board, tags,
  source_file, source_line, snippet, score}]}`, reusing `filters.row()` for the
  per-item fields so a search row and a list row cannot drift;
- a bad query is a 400 with a message, never a silently-empty list — the rule
  `filters.parse_filters` already states (`filters.py:22`).

Reusing `filters.row()` rather than writing a search-specific row serializer is
the whole argument for putting the matching logic in `serve/filters.py` rather
than in `serve/api.py`: the matching semantics and the row shape stay in the one
module that already owns the editor's query.

### 5.4 The editor surface, read-only, in the adapter's own spirit

`docs/design/editor-vscode-adapter.md` §8 states the phasing philosophy this
follows: every editor capability in this repo went read-first, and "Slice V0 is
deliberately smaller than anything above." A search surface is read-only, so it
fits — but §4.3 recommends the **command** shape first, not the hover:

- **A `Refdes: Search items` command**, quick-pick over `GET /api/search`, with
  the snippet in the detail line and the item's deep link
  (`ServeClient.deepLink`, already shipped at `serveClient.js:297-300`) as the
  action. No new provider, no trigger, no cursor logic, nothing that can fire
  while someone is typing a sentence.
- **A hover, only if §4.3's reasoning is answered against.** It is a second
  provider rather than a new condition on the first (§3.5), it needs a
  sentence-shaped range where `ID_RE` gives none, and it needs a trigger whose
  only evidence is negative. All three are reasons to sequence it last, and none
  of them is "hard."
- **No writes, no new server flags, no webview** — the same three exclusions V0
  shipped with.

## 6. Open questions for Jared

**Q1 — Search first, or trigger and search together?**
*Recommendation:* `refdes search` first, standalone, no trigger (§4.3). The need
in §1 does not require the trigger; the trigger is the unvalidated half, and
building it first means the feature is judged on the half with negative
evidence. Cost of this order: the feature is invisible unless invoked, which is a
real cost, and is why the VS Code command (§5.4) should land close behind.

**Q2 — Does search index bodies, and does that change what `ls` and `q` mean?**
`ls`'s haystack is `id + title + tags`; `q`'s is `title + tags`; neither has body
(§3.2). *Recommendation:* **search indexes bodies; `ls` and `q` do not change.**
Two names for two different questions, both documented. The alternative —
teaching `ls` to search bodies — changes the meaning of every existing alias and
script, and `ls` is a listing, not a search.

**Q3 — Which matcher is canonical?**
Three exist and two already disagree about the id (§3.2). *Recommendation:*
extract **one** substring matcher and have all three call it, with `ls`'s
behaviour (id included) as the definition, and have `q` gain the id as a
**documented** narrowing rather than silently keeping its difference. This is
adjacent scope — it is not this feature — but shipping a fourth matcher without
doing it makes the drift permanent.

**Q4 — Hover, command, or both?**
*Recommendation:* **command first** (§5.4), for the reasons in §4.3: a hover
fires while a sentence is unfinished, and its result is transient in a way a
re-runnable command's is not. The hover is the version that would feel magical if
it worked, and §4 says the evidence for it is not there yet.

**Q5 — Does a question in a body match itself?**
`Item.title` falls back to the first 90 characters of `body` when a type has no
title field value (`model.py:553-572`, §3.3), so an untitled requirement whose
body opens "how many analog inputs are there?" has that sentence **as its
indexed title**. *Recommendation:* suppress the item the cursor is currently in,
unconditionally and before ranking, so the author is never shown the thing they
just typed as if it were a finding elsewhere in the project.

**Q6 — Is there a `log` exception?**
§4.4: `log` is the one type whose own `doc:` says it holds "questions raised",
and it is also `append_only`, sealed on the first clean build, with `summary`
rather than body in listings. *Recommendation:* if a trigger is ever built, log
bodies are excluded from it, and that exclusion is stated in the user-facing docs
rather than left to be discovered.

**Q7 — Does this belong in `docs/index.md`'s nav?**
*Recommendation:* no, and the other 23 files in `docs/design/` set the precedent
— `docs/index.md` contains no `design/` path at all (verified; its one `design`
hit is a link to the user-facing `design-log.md`). Same answer as
`form-ingestion.md` §9.

## 7. Named tests

Not written, and deliberately named rather than sketched, in the convention
`docs/design/editor-vscode-adapter.md` §7 established: **the facts the client
depends on are pinned in Python, where CI runs them**, and the extension's own
logic is driven from pytest through Node rather than by adding a JS test runner
CI does not run. §7.1 there is a Python contract suite; §7.2 is the Node-driven
half with a loud skip when Node is absent.

**Python contract tests** (the search backend, in the same file's spirit):

- `test_search_finds_a_term_that_only_appears_in_an_item_body` — the gap both
  existing matchers have (§3.2), pinned as closed.
- `test_search_matches_ids_as_ls_does` — pins §6 Q3's definition of canonical, so
  `q` and `ls` cannot keep silently diverging.
- `test_search_route_is_token_gated_on_reads` — no token, 403. This is the
  decision already pinned by `test_token_gates_reads_as_well_as_writes`
  (`tests/test_vscode_adapter_contract.py:353`); named separately because a new
  route is exactly where someone would assume reads are open.
- `test_search_row_shape_matches_the_item_list_row` — a search row and
  `filters.row()`'s output agree field for field, so the two cannot drift.
- `test_bad_search_query_is_a_400_not_an_empty_list` — the rule `filters.py:22`
  already states, pinned on the new route.
- `test_search_suppresses_the_item_the_cursor_is_in` — pins §6 Q5: an item whose
  `title` fell back to its own body does not match its own body.
- `test_schema_vocabulary_covers_declared_type_and_field_names` — the 63-term
  claim in §5.2, asserted against a fixture project so an overlay that breaks the
  extraction fails in CI rather than at query time.

**Extension-side tests** (pytest driving Node against a live `EditorApp`, per
§7.2, with `@pytest.mark.skipif(not shutil.which("node"))` and a loud skip
reason):

- `test_search_command_fetches_through_the_serve_client` — the command reaches
  `GET /api/search` with the header, and the query string rides in the pathname
  exactly as `ServeClient.request` already permits (`serveClient.js:240-252`).
- `test_search_offers_the_server_deep_link` — the quick-pick's action is the
  server's own `/edit/#/items/<key>`, never a URL the extension assembles. This
  is §4 of the adapter design's drift rule, already pinned for the CodeLens by
  `test_deep_link_shape_matches_server_toolbar`.
- `test_search_command_says_so_when_no_server_is_running` — a dead server never
  presents as "no results found." This is the quiet-failure bug class named at
  `serveClient.js:136-140` and it is the most important test in this list.

**One test that exists specifically to keep §4 honest:** if a trigger is ever
built, `test_no_search_surface_fires_without_an_explicit_invocation` pins §4.3's
conclusion in shipped behaviour rather than in prose — a search result appears in
the editor only because the author asked for it. A test that fails when someone
adds a speculative trigger is cheap, and it is the only durable form of "don't
build the trigger yet."

## 8. What is still design only

Everything. Explicitly, with no slices scoped:

- **No search command exists.** `refdes search` is a name in this document.
- **No search route exists.** `GET /api/search` is proposed in §5.3 and is not in
  `serve/api.py`'s dispatch chain.
- **No `ServeClient.search()` method** exists; `serveClient.js:276-284` has
  `revision()` and `item()` only.
- **No keyword extraction exists.** The 63-term vocabulary in §5.2 is a
  measurement taken from `refdes schema --json` output, not an implementation.
- **No ranking exists.** "id beats title beats body" is a sentence in §5.1, not a
  function. No score, no threshold, no snippet extractor.
- **No trigger exists**, and §4 argues against building one for now. No WH-word
  table, no adjacency rule, no cursor-history tracking.
- **No hover provider for questions exists.** §3.5 establishes that the current
  one cannot host it, which is a statement about shipped code, not a proposal.
- **No help text, no user-facing docs page, and no changelog entry** for the
  feature, because there is no feature.

## 9. Considered and rejected

**9.1 A classifier — tiny model or otherwise.**
Rejected for now, and the reasoning is that the mechanical version has not been
tried. §2.1's no-model stance is the constraint; the *sequence* is the argument. A
classifier drifts from deterministic, adds a dependency, needs training examples
that do not exist (§4.1: zero instances in `items/`, one in 1.3 MB of notes), and
would be introduced to solve a problem the mechanical version might not have. If
it is ever reopened, it should be reopened with real queries collected from a
shipped §5.1 command — that is, after the thing that would tell you whether a
classifier is needed has existed for a while.

**9.2 Client-side search: fetch the items, filter in the extension.**
`/api/items` already returns everything needed, capped at `DEFAULT_LIMIT = 500`
(`filters.py:52,392-402`), and the browser editor already does exactly this shape
for link targets — preload `/api/items?type=…`, filter with
`toLowerCase().includes()` (`static/links.js:28-36, 134-138`). So it is
available, it is precedented, and it is still the wrong answer here: it caps at
500 rows, it cannot see bodies for items past the cap, it would put a third
matcher in JavaScript (§3.2 already has two that disagree), and it makes search
wrong silently on a large project. The link picker is fine with a preloaded list
because its list is *per declared target type*; a search is project-wide by
definition.

**9.3 An embedding or vector search.**
Rejected with §2.1. Named only so it is not proposed again as a
"deterministic-sounding" improvement: it is the same fabrication risk with a
dependency attached, and §5.2's vocabulary is a better use of the same insight.

**9.4 Wiring search into `ls` and `q` rather than beside them.**
`cmd_ls`'s own docstring calls it "the CLI-native answer to 'what already exists
here'" (`cli.py:425-432`) — a listing. Making it a body-searching tool changes
what every existing alias and script means, to serve a feature whose trigger is
unvalidated. §6 Q2's recommendation is to leave both alone.

**9.5 A popup, a panel, or any intrusive suggestion.**
Named in the ask and declined. A panel is the V1 sidebar webview that has not
been built; a popup interrupts. The hover is deferred by §4.3 and the command is
what §5.4 proposes instead.

## 10. Precedent this borrows from

| Precedent | Where | What it is precedent for |
|---|---|---|
| `cmd_ls` free-text matching | `cli.py:437-468` | the closest thing to a matcher, including why the id is in the haystack |
| `ls` / `q` divergence | `cli.py:465-468` vs `filters.py:144-147` | why §6 Q3 exists |
| `filters` owns the editor's query | `filters.py:1-27` | where matching semantics and the row shape should live |
| `row()` / `items_payload()` | `filters.py:357-389` | the search row shape, reused not rewritten |
| bad filter is a 400 | `filters.py:22, 186-199` | what a bad search query does |
| token gates all `/api/`, reads included | `browser-editor.md:982`; `test_vscode_adapter_contract.py:353` | a new read route needs no new auth |
| `handle()`'s if-chain and its 404/405 tail | `api.py:39-75` | where a new read route goes |
| `ServeClient.request` passes pathname through | `serveClient.js:240-252` | a query string needs no client plumbing change |
| `ServeClient.deepLink` | `serveClient.js:297-300` | what a search result's action is — the server's own URL |
| the hover provider's `ID_RE` entry condition | `extension.js:28, 495-507` | why a question hover is a second provider |
| read-only first, smallest slice first | `editor-vscode-adapter.md` §8 | §5.4's exclusions |
| Python contract tests + Node-driven extension tests | `editor-vscode-adapter.md` §7; `tests/test_vscode_adapter_contract.py`, `tests/test_vscode_extension.py` | §7's whole shape |
| `Item.title` fallback chain | `model.py:553-572` | §3.3's trap and §6 Q5 |
| `append_only` on `log`, and its `doc:` |  `base.yaml:290, 294, 297-298` | §4.4's tension and §6 Q6 |
| `refdes schema --json` as the vocabulary source | `schema_json.py:117-148` | §5.2's 63 terms, and its `doc:` strings |
| the asset search path (a different thing) | `backlog.md:2090+` | §3.1's note that the word "search" already means something else here |

## 11. Not proposed

- **Not an LLM, a classifier, an embedding model, or any generated summary of
  what the matches mean.** §2.1 and §9.1. A hit list is shown; nothing
  summarises it.
- **Not a change to item shape, the schema, the id ledger, or key minting.**
  Search reads the built project and writes nothing.
- **Not a second implementation of any project rule in JavaScript.** §9.2 is the
  rejection; the shape of that rejection is the same one
  `editor-source-picker.md` §5 states — if it needs a JS re-implementation of a
  project rule, that rule should not exist yet.
- **Not a change to `ls`'s or `q`'s matching.** §6 Q2 and §9.4.
- **Not a new auth pattern, a new server flag, or a route outside the existing
  `/api/` chain.** §3.4.
- **Not a webview panel, and not a writable custom editor.** §5.4; the
  two-write-path problem of `editor-vscode-adapter.md` §3.5 is not reopened here.
- **Not a new page in `docs/index.md`'s nav.** §6 Q7.
