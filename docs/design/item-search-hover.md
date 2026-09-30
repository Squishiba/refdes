Status: **proposed**; **no slices scoped, no code written**. Nothing in this
document is a commitment to build it. It records a way for an author who cannot
remember whether a fact is already in the project to ask the project instead.
The earlier §4 conclusion against the trigger was based on the wrong evidence:
this repository's tiny dogfood items and AI-agent task logs do not represent
Jared's private hardware-spec authoring. Jared has now described three real
signals, and named a literal `?` as the deliberate, precise invocation that
makes this a tool. This revision treats that character trigger as the
load-bearing, ship-first anchor; pauses and suspected duplicates are future
directions, not equal alternatives. Every §5 direction remains under
discussion, and each §6 recommendation is the default if Jared lets it stand.

Verified while writing: the trigger-related claims about the current VS Code
hover provider and extension event surface against `editors/vscode/extension.js`
and `editors/vscode/package.json`. Earlier verified search infrastructure,
schema vocabulary, and matcher findings are retained; this revision does not
rely on the old corpus analysis as evidence about Jared.

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

The need itself is real and does not depend on any of the design below. Jared
has now identified the literal `?` as the deliberate invocation: its specificity
is what makes the search a tool rather than ambient guessing. §4 develops that
trigger first and records two broader signals as possible later work.

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
2. **Wrong has to be cheap.** This constrains how search results are presented;
   it does not erase the value of a precise invocation. A literal `?` is
   deliberate and unambiguous as a character match, while broader pause-based
   triggers have much more noise. §4 distinguishes those costs instead of
   treating every trigger as the same heuristic.
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

## 4. The trigger: `?` first, broader signals later

The previous version treated a count of question marks in repository text as
evidence against the trigger. That conclusion was a real evidence-gathering
mistake: the corpus was wrong for the question being asked. Jared has now
described what actually happens while authoring, and specifically explained why
the `?` is the right anchor: **"using a '?' as the trigger for the search is
what gives it specificity; it turns it into a tool."** He named three related
experiences, with the first deliberately serving a different design role from
the other two:

1. He types a literal `?` mid-sentence when genuinely unsure (for example,
   `...runs at 3.3V?`). This is the primary, deliberate invocation.
2. He pauses without punctuation because he wonders whether he already said
   something somewhere. This is a real experience, but an ambient and much
   noisier possible future signal.
3. He is about to write a number, rating, or part choice with a nagging sense it
   may duplicate or contradict something already in the project. This describes
   the need for retrieval, but recognizing it at the right moment is the hardest
   trigger problem.

### 4.1 Why the earlier corpus counts do not answer this question

The measured counts remain valid only as descriptions of those files:
`items/` had 0 literal question marks across its six dogfood items, and
`in-prog-logs/` had 32 after the previous analysis's filtering, with only one
matching its narrow self-posed-content-question pattern. But `items/` is this
repository's tiny example project, not Jared's real hardware work. The progress
logs are AI-agent task documentation (and `AGENTS.md` explicitly requires them),
not a human engineer's private notes while writing specs. Neither corpus is a
sample of Jared's authoring behavior. The counts therefore neither disprove nor
meaningfully estimate how often his `?` trigger occurs. The prior inference
that the trigger should be deferred was unsupported and is withdrawn.

### 4.2 Primary trigger mechanics: literal `?` insertion

A character match is deterministic and cheap. It has low recall by design: it
fires only when Jared deliberately types the marker. That precision is the
feature. The proposed first slice should make this a distinct, explicit search
invocation and measure its usefulness before considering ambient triggers.

Mechanics to settle in implementation, while preserving that contract:

- Observe `workspace.onDidChangeTextDocument` and inspect each inserted change.
  Trigger only when a change inserts exactly one `?` character with no replaced
  text (`text === "?"`, `rangeLength === 0`). This avoids treating an arbitrary
  pasted sentence containing question marks as an invocation. VS Code's change
  event identifies inserted text, not its physical source, so a paste consisting
  of exactly `?` is indistinguishable from a keystroke; the design is character
  insertion, not keyboard-layout-specific key interception.
- Use a short settling delay (proposed 150 ms) to let the editor apply the
  change and place the caret before requesting results. Take the query from the
  current prose clause ending at that marker; this is deterministic text
  extraction, not a claim to understand the question. This is event
  coordination, not a pause/idle heuristic: the `?` event itself is required.
  Cancel a pending invocation if the document closes or the marker is removed
  before it runs. Do not wait for a longer idle interval or infer intent from
  subsequent prose.
- Search the current item's Markdown body only. Ignore front matter, fenced code
  blocks, and inline code, where `?` commonly belongs to syntax or examples.
  Within prose, allow the marker anywhere, including mid-sentence or after a
  number/unit; do not require it at line end or require a WH-word. Resolve the
  item from the current document using the existing index/source mapping.
- Keep the marker in the document. The search is read-only and must not consume,
  rewrite, or normalize the user's text. Results should exclude the current
  item, since the marker is part of the text being authored and must not make
  that item appear as its own discovery.
- Treat the existing ID hover as a separate provider contract. It is entered
  only when `ID_RE` finds an item id under the hover position
  (`extension.js:28, 494-508`). A `?` in prose does not satisfy that condition.
  A search result surfaced as a hover therefore needs a second provider (or an
  explicit dispatcher refactor), with a `?`-range and its own result rendering;
  it must not broaden the ID provider and change ID hover behavior.
- A document-change event alone cannot make VS Code's passive hover appear at
  the caret. The first slice must explicitly invoke a surface after detecting
  `?`—for example, request the editor's hover at the marker and let the
  question-specific provider render there. Because the caret normally lands
  immediately after an inserted `?`, that provider must recognize the marker at
  the recorded insertion range or immediately to the left of the caret; it must
  not depend on `getWordRangeAtPosition` treating punctuation as a word. Use a
  focused search result surface if hover invocation proves unreliable. Keep it
  tied to the exact insertion event, avoid repeated display while the same marker remains, and
  ensure another provider's hover over an ID continues to work unchanged.
  Validate the chosen editor API behavior in an extension-host spike before
  locking the interaction; current `extension.js` has no such trigger path.

The last point is a real integration question, not a reason to demote the
trigger. The character condition is deterministic; VS Code's ability to invoke a
hover at the just-edited marker is the implementation detail to prove. If the
hover API cannot reliably show there, retain `?` as the invocation and choose a
small explicit result surface rather than adding a semantic classifier.

### 4.3 Future signals, not co-equal triggers

A typing pause can be measured with a deterministic debounce timer; a timer is
not a model. Its meaning is still ambiguous: the author may be choosing words,
distracted, or finished. The current extension has no idle-triggered hover.
Its hover provider is called through VS Code's hover mechanism and gates on an
ID-shaped word; the adapter design documents no suppression or noise-control
logic beyond that entry condition (`editors/vscode/extension.js:494-508`,
`docs/design/editor-vscode-adapter.md` §2.2). A timer that opens search after
ordinary pauses would bypass that narrow, user-positioned hover behavior and
could repeatedly interrupt typing. Any future pause experiment needs concrete
noise controls—at minimum a substantial idle threshold, one invocation per
pause episode, suppression while selection/composition or another popup is
active, and an easy disable—and evidence from real use. It is not part of the
ship-first trigger.

The "about to state a possibly duplicated fact" moment is harder still. A
number, rating, or part choice can be detected lexically, but deciding that this
particular fact feels familiar requires context or semantic understanding. A
rule keyed to digits/units would produce many unrelated matches and still miss
textual facts. Under §2.1's no-classifier/no-model constraint, a dependable
per-keystroke detector for this signal is not realistically specified yet. The
need it points to is better served by explicit on-demand search and perhaps a
passive result surface that the author can open while composing, not by claiming
that software can recognize the nagging sense itself. Keep it as future
exploration, not a trigger commitment.

### 4.4 Recommendation

Build deterministic search and the literal `?` invocation together in the first
editor-facing slice, after or alongside the search backend needed to answer it.
The marker supplies the deliberate moment; search supplies the retrieval. A
standalone command remains useful for queries that do not arise as a typed
question, but it is complementary and should not replace or postpone the
primary trigger. Do not build the pause heuristic or duplicate-suspicion detector
in that slice. Revisit either only with real authoring evidence and a concrete
noise budget. This keeps §2.1 intact: deterministic matching and ranking may
return imperfect candidates, but no system guesses what the author meant.

### 4.5 Structural finding retained

`append_only: true` is on `log` only — verified in
`src/refdes/standards/hardware/v3/base.yaml:290-298`. The `log` type's own
`doc:` says it records "questions raised" and its entries seal on the first
clean build. This affects where a future implementation may observe editable
prose, but it does not undermine the `?` trigger. The search invocation should
work in editable item prose; any exclusion for sealed log bodies should follow
what the editor can actually edit and should be specified separately.

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
body; §6 Q2. For the `?` invocation, use the current prose clause ending at the
inserted marker as the query text, then apply deterministic token and schema
vocabulary weighting from §5.2. Do not ask a model to rewrite the question.

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
fits — §4.4 recommends a deliberate `?` invocation as the anchor, with a
command as a complementary explicit route:

- **A `Refdes: Search items` command**, quick-pick over `GET /api/search`, with
  the snippet in the detail line and the item's deep link
  (`ServeClient.deepLink`, already shipped at `serveClient.js:297-300`) as the
  action. This complements the primary `?` trigger and supports queries that
  are not being typed into item prose.
- **A question-specific hover/result surface for `?`.** It is a second provider
  rather than a new condition on the ID provider (§3.5), and must be validated
  against the editor API as §4.2 describes. The exact character event remains
  the trigger even if the result surface needs adjustment.
- **No writes, no new server flags, no webview** — the same three exclusions V0
  shipped with.

## 6. Open questions for Jared

**Q1 — Search backend and `?` trigger: which lands first?**
*Recommendation:* build the deterministic search backend and literal `?`
invocation as one first editor-facing feature (§4.4). The backend can be
implemented first internally, but the feature should ship with its deliberate
trigger. Keep a command as a complementary route for queries outside prose.

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
*Recommendation:* the `?`-invoked result surface is part of the first feature
(§4.2); validate whether the existing VS Code hover mechanism can reliably show
it at the marker. Keep the search command as a complementary invocation. The
ID hover remains unchanged.

**Q5 — Does a question in a body match itself?**
`Item.title` falls back to the first 90 characters of `body` when a type has no
title field value (`model.py:553-572`, §3.3), so an untitled requirement whose
body opens "how many analog inputs are there?" has that sentence **as its
indexed title**. *Recommendation:* suppress the item the cursor is currently in,
unconditionally and before ranking, so the author is never shown the thing they
just typed as if it were a finding elsewhere in the project.

**Q6 — Is there a `log` exception?**
§4.5: `log` is the one type whose own `doc:` says it holds "questions raised"
and it is also `append_only`. *Recommendation:* the trigger observes editable
prose only; specify any sealed-body handling against actual editor behavior.

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

**Tests for the deliberate trigger:** pin that a single inserted `?` in item
prose invokes search once after the settling delay; replacement, unrelated
characters, fenced/inline code, front matter, and ordinary typing pauses do not.
Also pin that ID hovers retain their existing range and content. These tests
protect the intended specificity while leaving future ambient triggers out of
scope.

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
- **No search trigger exists yet.** The proposed first trigger is the literal
  `?` character insertion (§4.2); pause and duplicate-suspicion signals remain
  future directions, with no WH-word table or semantic detector.
- **No hover provider for questions exists.** §3.5 establishes that the current
  one cannot host it, which is a statement about shipped code, not a proposal.
- **No help text, no user-facing docs page, and no changelog entry** for the
  feature, because there is no feature.

## 9. Considered and rejected

**9.1 A classifier — tiny model or otherwise.**
Rejected for now, and the reasoning is that the mechanical version has not been
tried. §2.1's no-model stance is the constraint; the *sequence* is the argument. A
classifier drifts from deterministic, adds a dependency, and would need training
examples that are not present in this repository. The `items/` and
`in-prog-logs/` counts described in §4.1 are not evidence about
Jared's real authoring. The classifier remains rejected by §2.1 regardless of
trigger frequency; collect real queries through the `?` feature and command if
future matching changes need evaluation.

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
deliberately limited to a typed `?`. §6 Q2 recommends leaving both alone.

**9.5 A popup, a panel, or any intrusive suggestion.**
A panel is the V1 sidebar webview that has not been built. An automatically
opening popup on ordinary typing is declined; a result surface opened only by
the deliberate `?` is bounded by the user's invocation. The command in §5.4
remains available for explicit searches outside that moment.

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
| `append_only` on `log`, and its `doc:` |  `base.yaml:290, 294, 297-298` | §4.5 context for §6 Q6 |
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
