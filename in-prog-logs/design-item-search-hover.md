# in-prog log — speculative design: question-triggered item search (CLI + hover)

Task: a docs-only speculative design doc for a new capability. An author typing a
self-question into a refdes item body ("how many analog inputs are there?")
should get a hover with candidate answers from the project, deterministically,
no LLM. Read `docs/design/form-ingestion.md` for shape and
`docs/design/editor-vscode-adapter.md` in full for the infrastructure this plugs
into. No code changes.

---

## What I read first

- `AGENTS.md` — verify, don't recall; cite the file you verified against.
- `docs/design/form-ingestion.md` (484 lines, read in full) — the shape to match:
  a Status header that states what is *not* decided, a "current state (verified)"
  section, findings that contradict the conversation's assumptions given their own
  numbered section, "Open questions", "What is still design only", "Precedent
  this borrows from" as a table, "Not proposed".
- `docs/design/editor-vscode-adapter.md` (677 lines, read in full) — §3.2 token
  mechanics, §3.3 route table, §4 "what must NOT be reimplemented", §6 "Open
  questions for Jared" (every Q carries a *Recommendation:*), §7 "Named tests"
  (split Python-contract / extension-side), §8 phasing (V−1, V0, V1, V2; "every
  capability lands read-only first"), §9 considered-and-rejected.

---

## Findings: what exists

### F1 — The activation bug that `editor-vscode-adapter.md` §2.3 called a blocker is FIXED

§2.3 said the extension "as shipped does not activate in a current refdes
project". That is no longer true. Verified:

- `editors/vscode/extension.js:66-71` — `findRoot` now looks for
  `refdes-project.yaml`.
- `editors/vscode/package.json:27` — `"activationEvents":
  ["workspaceContains:**/refdes-project.yaml"]`.
- `editors/vscode/extension.js:306,738` — the warning text follows.

So **Slice V−1 shipped**. The doc is stale on this point and my design doc must
not inherit the staleness.

### F2 — Slice V0 shipped too. `ServeClient` is real, not speculative.

- `editors/vscode/serveClient.js` exists, 337 lines, plain CommonJS, no `vscode`
  import.
- `editors/vscode/extension.js` is 946 lines (the adapter doc recorded 536 at
  drafting, so V0 added ~400).
- `tests/test_vscode_adapter_contract.py` (10 tests, all the §7.1 names) and
  `tests/test_vscode_extension.py` (5 tests) exist.

Useful detail for scoping: `ServeClient.request(pathname)` passes `path` straight
to `http.request` (`serveClient.js:240-252`), so **a query string can ride in
`pathname` with no change to the client** — `this.request("/api/search?q=" +
encodeURIComponent(q))` works as written. That matters: a search route is a
one-method addition (`items()` next to `item()` and `revision()`), not a
plumbing change.

Still speculative (verified absent): no `webview`, no `WebviewViewProvider`, no
`Contributes.customEditors` anywhere in `editors/vscode/`. So **Slice V1 (sidebar
webview) and V2 (writes) have not landed.** Grep for them returned nothing.

### F3 — The hover provider that V0 extended

`editors/vscode/extension.js:495-507` `provideHover`. It is currently gated on
**one condition only**: `document.getWordRangeAtPosition(position, ID_RE)` with
`ID_RE = /\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6}\b/` (`extension.js:28`). No id
under the cursor, no hover. Registered on
`[{language:"markdown"},{language:"yaml"}]` (`extension.js:892-895`).

This is the single most important structural fact for my design: a `?`-triggered
hover is a *second* entry condition on a provider whose first condition is a
completely different shape (a token-shaped word at a cursor) and whose returned
range is that word. A question sentence has no such word. So this is not "add a
condition to the existing hover" — it is a second provider, or a provider that
restructures. Worth stating explicitly rather than hand-waving.

### F4 — `Item` fields, for deciding what is worth indexing

`dataclasses.fields(Item)` run live. Relevant to search: `id`, `type`, `key`,
`fields` (dict — holds `title`/`text`/`summary`/`name`, `tags`, `status`,
`limit`, `part_number`, …), `body`, `resolved_links`, `backlinks`, `source_file`,
`source_line`, `body_line`, `board`, `workspace`, `external`, `origin`,
`former_ids`.

Not search targets and should be named as excluded: `content_hash`,
`body_html` (rendered duplicate of `body`), `calcs`, `checks`, `calc_values`,
`citations`, `history`, `inherited_fields`, `id_rejected`, `prefix_hint`,
`numeric_id_hint`, `board_hint`, `workspace_hint`, `defaults_line`, `slug`.

`Item.title` is a **property, not a field** (`model.py:553-572`): it reads
`title` → `text` → `summary` → `name` from `fields`, truncates at 90 chars, and
**falls back to the first 90 chars of `body`** when none of those exist. Two
consequences: (a) an index built over "title" silently contains body text for
every item that has no title, so "index titles" and "index bodies" are not
separable by data shape, only by which field you read; (b) a `?` typed at the
start of an untitled requirement's body becomes that item's `title`, so a
question can be *the indexed string* and then match itself. Real, and worth a
line in the doc.

### F5 — Three already-divergent substring matchers. This is the biggest real finding.

There is no shared matcher. There are three, and they disagree:

| Where | What it matches | Case | Note |
|---|---|---|---|
| `cmd_ls` free-text positional, `cli.py:449,465-468` | `" ".join([item.id, item.title, *tags])` | lowered both sides | **includes the id** |
| `filters.py:144-147`, the `q` query param on `GET /api/items` | `" ".join([item.title, *item_tags(item)])` | lowered both sides | **omits the id** — the two do not agree |
| `static/links.js:134-138` | `label.toLowerCase().includes(want)` | lowered both sides | client-side, over a preloaded `/api/items?type=…` list |

`cmd_ls`'s own docstring explains why the id is in its haystack: "The id is in
the haystack too, because the natural query right after `refdes id` prints one is
the id itself" (`cli.py:437-440`).

So the instruction "don't invent a second incompatible matching convention" is
right but the situation is messier than "one convention exists" — there are
three, and they already drift. The honest framing for the doc: this is the
moment to extract one, or to consciously add a fourth and say why.

None of the three searches **body**. That is the gap this feature fills, and it
is also why "generalize `cmd_ls`" is not sufficient — `ls` never had body in its
haystack.

### F6 — Server API shape for a new read route

`serve/api.py:39-75` `handle()` is a flat if-chain over exact paths and
prefixes; every read is `method in ("GET","HEAD")`; the tail returns 405 for a
known path with the wrong verb and 404 otherwise. Token auth is *not* per-route —
it gates all `/api/` centrally (`server.py:510-511`), so a new read route is
automatically token-gated and needs no new auth code. Confirmed by reading
`handle` and cross-checking the adapter doc's §7.1 test
`test_token_gates_reads_as_well_as_writes`, which exists and passes.

`_item_view` (`api.py:227-…`) already returns `body`, `fields`, `tags`, `id`,
`type`, `board`, `workspace` — i.e. everything a search would match over is
already in one payload. Worth stating, because it makes the "just fetch and
filter client-side" option (§rejected) visibly cheap, and the reason to not do it
is not cost.

### F7 — Schema vocabulary: real, free, and small. Measured.

`refdes schema --json` run live against this repo (hardware@3). Extracted from
the `__entry` defs:

- **7 type names**: bound, component, decision, group, log, requirement, test
- **40 field names**: addresses, alternate, amends, author, blocked_by, board,
  body, checks, citations, constrained_by, date, derives_from, drop_in,
  governed_by, history, id, last_reviewed, limit, note, options, owner, part_of,
  part_number, prefix, rationale, recorded_by, records, refdes, refines,
  satisfies, selects, source, status, summary, supersedes, tags, title, type,
  verifies, workspace
- **16 enum choices**: accepted, active, blocked, candidate, draft, failing,
  in_progress, obsolete, on_hold, passing, planned, proposed, rejected, retired,
  selected, superseded

**63 domain terms, zero new dependencies, already in a JSON document the repo's
own rules tell you to verify against.** That is the strongest part of the idea
and it measured out fine. Note the field `doc:` strings are also present in that
JSON (as `description`) and are a second, richer vocabulary source that costs
nothing to use.

Caveat to state: this is *this project's* vocabulary. A project with an overlay
gets its own terms, which is the feature, not a bug — but the hit rate of a
63-term list against free prose will be modest and the term's *documented
meaning* ("`limit`: The numeric limit itself…") is better evidence of a match
than the bare token.

---

## Findings: the `?` heuristic against real content — the honest answer

This is the part I was asked to check rather than trust. I checked.

### The target surface has literally zero `?`

- `items/` — **0** question marks, across 2 files / 3,391 bytes / 6 items.
- `CHANGELOG.md` — **0** question marks, in the whole file.

So the feature's trigger has no instances in the only corpus in this repo.

### The corpus is too small to disprove it, and that has to be said plainly

6 items is not a corpus. This repository is a tool repository with a demo board,
not a real design project. Any conclusion from it is weak. I am reporting a
*measurement*, not a refutation.

### But the register analysis is real evidence, and it points the other way

I scanned `in-prog-logs/` (178 files, ~1.3 MB — the closest thing to "this person
writing notes") stripping fenced code and inline code, and separated URL/query
shaped `?` (`?type=`, `?page=`, `?token=`, `method="GET"`…) from prose.
**40 real ones remain in 1.3 MB.** Reading all of them:

| Kind | Example | Count-ish |
|---|---|---|
| Task checklist heading | `## Finished?` | several |
| Process self-talk | `Remaining: ruff (docs only — nothing to check?)` | a few |
| Quoted tool output | `Did you mean 'part_number'?` | many |
| A question **addressed to someone else** | `Do images stay out of the revision token?` (design docs, §6 lists) | most of `docs/design/`'s 150 |
| Genuine self-posed domain question | `design history trustworthy?` | **1** |

That last row is the finding. In 1.3 MB of the author's own working notes there
is **one** instance of the exact behaviour the feature is designed around, and it
is in a release-gate log about the *tool's own* design history, not in an item.

The same pattern holds in `docs/design/`: 150 prose `?` outside code, and they are
overwhelmingly §6 "Open questions" items *posed to Jared* — outward-facing. The
feature's premise assumes an inward-facing register ("how many analog inputs are
there?" written to myself), and this repo's actual `?`-using register is
outward-facing: it is the register of *asking a person a decision*, not of
*asking the project a question*.

### What that does and does not mean

It does not mean the feature is wrong. It means:

1. **The trigger is unvalidated, and the one signal available to validate it
   against is empty.** The doc should say this in plain words rather than
   presenting the `?` as a settled heuristic.
2. **It shifts the risk weighting.** The conversation's position — being wrong is
   cheap, so ship the plain version — is *strengthened*, because a trigger with
   near-zero hit rate in the observed corpus is worse than a noisy one: a noisy
   trigger at least proves the search half works. An unexercised trigger means
   the hover may be invisible in practice and the feature may be judged on a
   search nobody ever sees.
3. **A hover keyed to a `?` may be the wrong surface for the need.** The stated
   need is "I can't remember which item has this" — that need does not require
   the author to *write a question first*. A manual command (`refdes search`,
   and in VS Code a `Refdes:` command) satisfies the need without the trigger
   guess at all. That reordering is the single most useful thing this design
   should propose: **search first, trigger second.**
4. **The WH-word/adjacency refinement is not worth its cost**, and the corpus
   analysis is the reason. Refining a classifier for a signal observed once in
   1.3 MB is fitting noise. This is independent of the design's "no classifier"
   stance — it's an argument against spending effort *on this trigger at all*
   before the manual path has been used for a while.

### One structural finding the corpus check turned up

`append_only: true` is on `log` **only** (verified by reading
`src/refdes/standards/hardware/v3/base.yaml:294`; every other type omits it).
And the `log` type's own `doc:` says:

> "A dated entry in the design log — work done, **questions raised**,
> corrections. Entries are append-only: each is sealed on the first build where
> it has no errors, and after that editing it is a build error — corrections are
> new entries with `amends`."

So the one refdes type whose stated purpose includes raising questions is also
the one type that seals its body on the first clean build. A self-question typed
into a log body becomes permanent almost immediately. And `log` entries require
`date` and `summary` (base.yaml:300-301) — the `summary` field, not the body, is
what shows in log listings. A `?` in the body of a log entry is the *least*
findable place to put it. That is a genuine tension worth a paragraph, and it
suggests the trigger should exclude `log` bodies, or at least that the design
should notice that "write a question in your notes" and "refdes's notes type is
append-only" are in tension.

---

## Open questions I'm leaving for Jared (for the doc's §6)

1. **Manual command first, or trigger at all in v1?** Recommendation: search
   first, no trigger. The need does not require the trigger and the trigger is
   the unvalidated half.
2. **Body in or body out of the index?** `ls` and `q` never search body today.
   Adding it changes what an existing word means if search is ever wired into
   them; keeping search a separate command keeps it additive.
3. **Which of the three substring matchers is canonical?** Or: a fourth, on
   purpose?
4. **Is a hover the right surface, or a `Refdes:` quick-pick?** A hover over a
   sentence the author is mid-way through typing is interruptive in a way a
   hover over an id is not — the id hover shows facts about a *finished* token,
   the question hover fires *while composing*.
5. **Same-item suppression** — `Item.title` falls back to `body`, so a question
   in an untitled body is the indexed string and will match itself.

---

## Process notes

- Tree was clean at start (`git status --short` empty). No `git stash` used.
- No files outside `in-prog-logs/`, `docs/design/`, `changelog.d/` were touched.
  One scratch write: `.scratch/schema.json` (the captured `refdes schema --json`
  output used for the vocabulary counts), gitignored per AGENTS.md.
- `refdes` on PATH is broken in this environment
  (`/home/jorb/.paseo/work/venv-refdes/bin/refdes` → `ModuleNotFoundError`), so
  every CLI invocation in this log was `PYTHONPATH=src python -m refdes.cli …`.
  Noted because it changes the command string in the design doc.

## Status

Design doc written to `docs/design/item-search-hover.md`. Findings above are
verified; no code written.
