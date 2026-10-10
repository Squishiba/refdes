Status: **proposed**; **no slices scoped, no code written**. Nothing in this
document is decided, and nothing here is a commitment to build it. It
records a conversation about a possible way for someone who does not know
refdes to contribute requirements and bounds, and the shape that conversation
landed on — plus the parts where the current code answers a question the
conversation assumed it did, and does not. There is no phase list, because
there is no agreed first phase. Every §3 heading is a direction under
discussion, not a spec.

Verified while writing: the live shape of `GET /api/create/schema`, the live
request/response of `POST /api/items/create` including its `links` support,
the `refdes schema --json` output, the `difflib` call sites, the conflict-diff
UI, and the existing "propose, then a human applies it" commands. Commands
run are named inline. The two places where the conversation's assumption was
wrong — that the create API accepts a `body:`, and that the create-schema
endpoint advertises link verbs — are §4, and they are the most load-bearing
thing in this document.

# Form ingestion: schema-generated intake for people who don't know refdes

## 1. Problem

Jared uses refdes for real hardware design work. The expectation is that at
some point the work needs contributions from people who are neither versed in
refdes nor in hardware design conventions — people who know *what the design
has to do* and nothing about how the tool records that. His framing, lightly
summarized from the conversation that produced this document:

> a way for people not versed in refdes or hardware design to be able to
> specify these things. Thinking something like an HTML file you give someone,
> they do their thing and then you can add it back to refdes.

He flagged two problems with the idea before any of it was designed, and both
survive into this document unchanged because neither has a clean answer: how
editing/staying in sync with the schema works over time, and how duplicate
submissions get handled — flagged explicitly *given* that this is not a cloud
multi-user form. refdes is local-first and git-based; there is no server
coordinating concurrent edits, and this design does not propose one.

The concrete version of the problem is a string grammar. A `bound` in the
bundled standard has one required field, and its own `doc:` says what it wants
(`src/refdes/standards/hardware/v3/base.yaml:209`):

    limit:  { type: limit, required: true, ..., doc: "The numeric limit
             itself, parsed as a quantity with a comparison — '>= 9 V',
             '<= 600 mA'. Required, and it is what makes this bound checkable
             by other items' checks." }

`calc.parse_limit` accepts a comparison against a quantity, or a `low .. high`
range, and raises on anything else (`src/refdes/calc.py:834-861`):

    could not read limit '3.3V +/- 5%'; expected a comparison such as
    '<= 2 W/in^2' or a range such as '9 V .. 36 V'

Someone who has never opened refdes, told only "the rail has to hold 3.3 V
plus or minus 5 percent", is being asked to produce `">= 3.15 V"`. That is
the gap, and it is not a nice-to-have: the error is correct and the value is
unusable, and the person who hit it has no way to guess the fix.

The linked half is the same problem in a different costume. On `bound`, the
standard declares `refines: [bound]`, `derives_from: [requirement, bound]`
and `governed_by: null` (`base.yaml:213-216`) — the `null` is a deliberate
refusal, commented in place. A submitter who wants to say "this sharpens that
bound" has to know the display id of the other bound, and the display id is
minted by the tool.

## 2. What has to be true

Three premises, because they constrain every direction in §3 and are the
reason this is not simply "add a form to the editor".

1. **A human applies it.** The submitter never writes to the repository.
   Every existing mutation path in this tool is already "propose, then a
   person decides": `refdes former-ids propose` computes candidates, prints
   all of them, writes **none**, and requires `--confirm OLD_ID[,OLD_ID...]`
   naming the ones to accept — "Nothing written. Re-run with --confirm ...
   to record the ones you accept" (`src/refdes/cli.py:1214-1280`, message at
   `cli.py:1259-1263`; the parser help states the policy outright at
   `cli.py:1894`). `refdes new` prints generated front matter to stdout and
   tells you to redirect it where you want it (`refdes new --help`, run
   against a scratch project). The same posture is what
   `docs/design/browser-editor.md:999` calls the editor's invariant: *"No
   handler writes a file on the side; every change goes through a single
   apply-operation call."*
2. **The form cannot drift from the schema.** A hand-authored HTML form
   against a schema that evolves is a form that submits fields the loader
   refuses and misses fields the type requires. The existing New Item form is
   already generated from the live schema and says so in its own header:
   *"the schema comes from `/api/create/schema`, so nothing here re-implements
   a project fact"* (`src/refdes/serve/static/create.js:1-9`).
3. **The form goes offline immediately.** It is handed to someone as a file.
   There is no server at the far end. Everything the form needs — the schema
   snapshot, the control logic, the export — is in the one HTML document at
   generation time. This is the constraint that decides §6 Q3 and §6 Q5, and
   it is the reason the link-target picker question is as hard as it is.

## 3. Direction (all of it speculative)

### 3.1 Generate the form from the live schema

One input per declared field, typed by the field's declared type, from
`GET /api/create/schema`. Verified live against three projects — the
`tests/serve_support.py:make_project` fixture, this repository's own
`refdes-project.yaml` (hardware@3), and a scratch project with hand-declared
link verbs — the endpoint returns exactly:

    {"types": [{"name", "prefix", "label", "append_only", "amends",
                "fields": {fname: {"type", "required", "choices"|None,
                                   "default", "creatable"}}}],
     "boards": [...], "workspaces": [...], "date_format": "YYYY-MM-DD"}

Field types observed live on hardware@3: `text`, `person`, `date`, `limit`,
`enum` (with `choices` and `default`), `list`, `options`, `checks`,
`citations`, `refdes`. `creatable` is `false` for the collection types and
`true` otherwise — it is literally
`fspec.type not in NON_SCALAR_FIELD_TYPES` (`api.py:590`), and
`NON_SCALAR_FIELD_TYPES` is `{"list", "checks", "citations", "options"}`
(`src/refdes/model.py:148`).

The existing renderer is a near-exact match for what a generated form needs
and is the natural thing to start from rather than a greenfield generator:
`create.js` renders one control per `creatable` field, maps `enum` with
choices to a `<select>` and everything else to a text input
(`create.js:105-114`, via `controls.js:9-16`). A generated intake form differs
in three places, and only the third is interesting:

- `date` should be a real date input and `limit` should **not** be a text
  input. The `limit` case is the one with a payoff: `_FIELD_TYPE_MAP` already
  carries `examples: [">= 9 V", "<= 600 mA"]` for that type
  (`src/refdes/schema_json.py:43`), and the grammar is small enough
  (`<op> <quantity>` or `low .. high`, `calc.py:834-861`) that a comparison
  dropdown plus a quantity field would make the §1 example un-failable for a
  submitter who has the number in the right units. Whether to go that far, or
  to ship the free text and show the examples, is not decided.
- `enum` needs its `default` shown, and `required` needs to be enforced
  client-side enough to avoid a pointless round trip of a known failure.
- It needs **link-verb inputs**, which the shipped New Item form does not
  have at all — verified by reading `create.js` in full: it posts
  `{type, fields, id?, destination?, amends?}` and sends no `links`
  (`create.js:154-157`). So a generated intake form would be the first
  consumer of the create API's link support, which landed as
  `9d9b549 feat(serve): create writes any declared link verb, not just amends
  (F1) (#100)`.

What a link-verb input has to produce, read from `serve/edit.py` and confirmed
by exercising it live against a scratch project declaring `refines` and
`governed_by`:

| A link input must produce | Verified behaviour |
|---|---|
| `{verb: [ref, ...]}` — a non-empty list per verb | `links must be an object mapping link verbs to lists of target refs`; a bare string, an empty list, or a non-string entry is a 400 (`api.py:654-663`; `edit.py:1219-1229`) |
| one of three target spellings | display id, surrogate key, or `DISPLAY@key` — all three live-tested and all three land as the same composite (`edit.py:1176-1201`) |
| the composite is *re-derived*, never taken from the request | a bare key `m6p4r95v2zp` and a full `REQ-001@m6p4r95v2zp` both wrote `refines: [REQ-001@m6p4r95v2zp]`; the output is always `links.composite_for` (`src/refdes/links.py:311-319`) |
| one flow-sequence line per verb | `governed_by: [REQ-002@s9vdx3ac1d6, DEC-001@yn5vsd2s7m5]` — one target and five targets are spelled identically (`edit.py:1253`) |
| a target of an allowed type | otherwise 422, `'refines' accepts targets of type requirement; LOG-001 is a log` (`edit.py:1191-1193`, live) |
| a target that exists | otherwise 422, `no item 'REQ-999' in this project to link to with 'refines'` (`edit.py:1190`, live) |
| a target that carries a key | a keyless target is refused: no composite can be written and a bare id "would drop the identity the link is for" (`edit.py:1195-1200`) |
| no duplicate target inside one verb | `links 'refines' names REQ-001 twice; one creation links each target once` (`edit.py:1247-1251`) |
| only verbs the type declares | otherwise 422, `requirement does not declare the link 'refines'; it declares no links at all` (`edit.py:1230-1232`, live) |

### 3.2 Export a portable snippet, not a direct write

The filled-out form produces a downloadable file; someone reviews it and
imports it. Two candidate shapes, and the choice is genuinely open — see §6
Q2. What is not open is that the write is a human's, for §2.1.

The two shapes the code supports today:

- **A `POST /api/items/create` request body.** The endpoint takes
  `{type, fields, id?, destination?, amends?, links?}` — verified by reading
  `api.py:628-677` and `CreateRequest` (`edit.py:771-794`) — and answers
  `200` with `{kind: "created", ok, message, id, key, type, path, revision}`,
  `422` for a refusal or a diagnostic, `400` for a malformed request
  (`api.py:687-696`; the docstring at `api.py:629-631` states the mapping).
  Live response from a scratch project:

      {"kind": "created", "ok": true,
       "message": "created: REQ-003 (requirement) in items/reqs.yaml",
       "id": "REQ-003", "key": "5h675sv470h", "type": "requirement",
       "path": "items/reqs.yaml", "revision": "0a42a1d1…"}

- **Item YAML, the shape `refdes new` already prints.** Run against a scratch
  project, `refdes new requirement` emits front matter with the required field
  marked, the enum choices in a comment, each link verb with its target types,
  and a placeholder body:

      ---
      id:
      type: requirement
      text:  # required -- text
      # status:  # choices: draft, approved
      # refines: []  # target: requirement
      # governed_by: []  # target: requirement, bound
      ---

      <!-- optional body. -->

Neither shape round-trips a `body:` today — §4.2.

### 3.3 A per-form-instance key, for idempotency and not for identity

Each generated form embeds a random key at generation time. It is stamped
into the exported snippet. An importer can then answer "have I already
imported this exact submission?" by comparison alone, and choose to skip or
overwrite, without ever needing to establish who the submitter is.

The submitter's name and email are ordinary free-text fields in the form, at
the same trust level as the rest of the intake content: self-reported,
unverified, and reviewed by a human before anything reaches the repository.
That is not a weakening of refdes's posture, it is the posture — nothing a
form collects is authoritative, and the gate is the person applying it.

**What this explicitly does not solve** is content-level duplicate detection.
Two people independently describing the same real requirement in two separate
form instances produce two snippets with two distinct keys, and the key check
passes on both. Refdes is local-first with no server coordinating concurrent
edits, so there is no place where two submissions could have been caught
against each other at the moment they arrived; the only moment at which they
can be compared is the moment a human is looking at a batch. That is §3.4.

### 3.4 Similarity highlighting, as a curation aid

For the problem §3.3 does not solve: when a batch of candidate submissions is
imported, run each candidate's title and body against existing items of the
same type — and against each other within the batch — and surface likely
duplicate pairs for a human to glance at before anything is created.

The fuzzy-matching machinery is not new and does not need inventing. There are
23 `difflib.get_close_matches` call sites in `src/refdes`; the load-bearing
precedents for this design are:

- `configcheck.py:159-164` `_hint` — `get_close_matches(str(key), sorted(known),
  n=1, cutoff=0.6)`. Its comment is the best statement of threshold policy in
  the repo, and it is the reason this section refuses to pick a number:
  *"0.6, not difflib's 0.5: at 0.5 `unit` is 'close' to `note`, and a wrong
  suggestion is worse than none — every real typo this has to catch (`titel`,
  `labl`, `requird`, `trac`, …) scores 0.8 or above."*
- `parse.py:207-209` `_suggest` (cutoff 0.6) and `parse.py:583-584`, which
  runs link-verb and field-name did-you-mean with the same 0.6 and is what
  makes a confidently-misspelled field name a build error.
- `citations.py:340-352` — the closest existing precedent for matching
  *human-written titles*: `get_close_matches(want, [_norm(t) for t, _p in
  titles], n=5)`, no cutoff, against a normalized title, in a "no outline
  entry titled X" error. `_norm` is `" ".join((title or "").split())` and is
  deliberately case-sensitive (`citations.py:272-277`) — a decision this
  design inherits rather than reopens, though §6 Q6 asks whether it should.

The behaviour is a **soft nudge, never a block**, and both failure directions
are expected rather than merely tolerated:

- false positives — two genuinely different requirements that share
  vocabulary ("the 3.3 V rail shall…") will score high against each other;
- false negatives — the same requirement phrased two different ways will score
  low.

Which means the threshold is a tuning question against real submissions, not
a constant to pick once and ship. `configcheck.py`'s own reasoning is the
precedent for treating it that way.

**UI precedent.** The editor already renders a "here is yours, here is
what's there now" comparison, and renders it twice for two different payload
kinds. Server-side it is the `Conflict` dataclass (`edit.py:163-187`) carrying
`current_text` and a `diff` built by `difflib.unified_diff` with
`fromfile="<rel> (on disk)"` / `tofile="<rel> (your edit)"`
(`edit.py:598-607`). Client-side it is `showConflict` in
`static/editor.js:294-330`: an `h3`, two muted `p`s, then
`el('pre', 'conflict-diff', payload.diff)`, a read-only textarea, and
Keep mine / Keep theirs / Copy my draft. The second precedent is the one to
follow for a similarity panel, because its payload is *not* a text diff:
`static/images.js:118-160` is "the binary variant of the conflict dialog, in
the convention already used by editor.js `showConflict`" — a `.conflict` box
with an `h3`, muted facts, a pre block, and `.conflict-actions`. A
side-by-side "here's the existing item, here's the submission" comparison is
structurally that, not a unified diff.

## 4. Two places the current code does not do what this design assumed

These are the load-bearing findings. Both were found by running the code, and
both change what is buildable.

### 4.1 `/api/create/schema` does not advertise link verbs

Verified live against a scratch project whose `refdes-schema.yaml` declares
`refines` and `governed_by`: the response contains no key named `links` or
`verbs` anywhere. `_create_schema` emits only

    "amends": "amends" in spec.links

as a **boolean** (`api.py:598`) — enough to render the "amends a sealed
entry" note `create.js:49-55` shows, and not enough to render a link input.

So §3.1's link inputs **cannot** be generated from the endpoint the design
started from. `refdes schema --json` does carry them, as an array-of-strings
property with the target list in the description
(`schema_json.link_json_schema`, `schema_json.py:128-148`); run live against
the scratch project:

    "refines": {"type": "array", "items": {"type": "string"},
                "description": "target: requirement"}

That route also carries a thing `/api/create/schema` does not: field `doc:`
strings. `schema_json.py:117-125` copies `fspec.doc` into `description`, and
`refdes schema --json` on this repository returns the `bound.limit` field with

    "description": "The numeric limit itself, parsed as a quantity with a
    comparison — '>= 9 V', '<= 600 mA'. Required, and it is what makes this
    bound checkable by other items' checks."

The `/api/create/schema` payload has no such key — checked directly against
the live hardware@3 response: `'doc' in json.dumps(payload)` is `False`. The
single most useful sentence to show a non-expert is in the route the design
did not originally name. Whether to widen `/api/create/schema`, to generate
from the JSON Schema route instead, or to merge the two is §6 Q1 and is not
decided.

### 4.2 `POST /api/items/create` silently ignores a `body:` field

`CreateRequest` has `who`, `type`, `fields`, `id`, `destination`, `amends`,
`links` — no body (`edit.py:771-794`) — and `_create_item` reads only those
keys (`api.py:628-677`). Verified live: a create request carrying
`"body": "## Why\nBecause."` alongside a valid `fields` and `links` body
returned `kind: created` and the written item had **no markdown body at all**.
The field is ignored, not refused.

The only body write is a *second* request: `POST /api/item/<ref>/edit` with
`op: "set_body"` and a `text` string (`api.py:487-491`), against an item that
must already exist and with an `expected_revision` to check. So a `body:` in
an intake form cannot be a create-time field at all; it is either a
follow-up edit or the reason the exported snippet is not a create request.
That is §6 Q4, and it is the reason "the YAML the create API already accepts
as `fields`/`links`/`body`" is not available as stated.

## 5. Accepted limitation: a distributed form goes stale, and that is fine

A generated form is a snapshot. If the project's schema changes after
generation, the distributed form is wrong — it will offer a field that no
longer exists and miss one that now does. There is no mechanism to fix this
and none is proposed: an HTML file that has been emailed to someone cannot be
updated, and the whole point of the design is that it works with no server
round-trip and no refdes access at the far end.

Stated as an accepted limitation rather than a problem to solve, because the
alternative is not "keep the form fresh" — it is "require the submitter to
have a live project", which is the thing this design exists to avoid. The
mitigation that is available is mundane: the form can state the project and
schema it was generated from, so a stale submission is *recognizable* as
stale rather than silently wrong. Whether that is enough is a question for
whoever uses it.

## 6. Open questions

None of these is resolved here. They are named because each one changes what
would be built, and picking an answer without Jared is how a design doc
becomes a spec nobody agreed to.

1. **Which schema route generates the form?**
   - A. Widen `GET /api/create/schema` to carry the declared link verbs and
     the field `doc:` strings, and keep generating from it.
   - B. Generate from `refdes schema --json`'s resolved output, which already
     has both.
   - *Why it is still a question:* A keeps one endpoint as the single answer
     to "what does a create form need", which is what `_create_schema`'s own
     docstring claims it is (`api.py:575-579`) and what `create.js` relies on.
     B changes no service but couples the generator to a JSON Schema shape
     that is documented as a different contract (validator-facing, with
     `oneOf` over `__bare`/`__entry` variants) rather than a form-facing one.
2. **Is the exported snippet a `POST /api/items/create` body, or hand-editable
   YAML/JSON?**
   - A. Literally the request body. Import is replay; a curator can edit the
     JSON, but the field names are the API's, not the schema's.
   - B. Human-readable YAML a curator hand-edits before import, in the shape
     `refdes new` already prints.
   - *Why it is still a question:* A is unambiguous and reuses the endpoint's
     own validation; B is reviewable by someone who does not know the API and
     diffable in a PR, and the trust model here is a human reviewing
     everything anyway. They also differ on what "import" means, and B is the
     only one that survives §4.2.
3. **Fully offline, or is a server round-trip acceptable?**
   - A. Fully offline: the schema snapshot, the control logic, the export, and
     any client-side validation are all embedded in the single HTML file at
     generation time. The file is self-contained and the submitter needs
     nothing.
   - B. The form talks to a running `refdes serve`.
   - *Why it is still a question:* §2.3 says A, but the question has a cost
     that has not been measured — file size, and a validation layer that
     duplicates the server's and can disagree with it. `browser-editor.md`
     already draws the line that B is the wrong side of it ("Python remains
     the only implementation"); if the answer turns out to need a JS re-
     implementation of any project rule, that rule should not exist yet.
4. **How does a `body:` (markdown) get authored in a plain HTML form?**
   Nothing discussed so far resolves this, and §4.2 makes it sharper rather
   than softer: a body cannot travel in the create request at all. A
   multi-line textarea producing raw markdown that nobody but the submitter
   ever sees is one option; restricting intake to scalar fields and letting
   the curator write the body is another; a markdown preview is a third. This
   is unresolved, not merely undecided between good options.
5. **What happens to link targets a submitter cannot know?**
   The editor's own answer does not port. `links.js:28-36` `candidatesFor`
   fetches `/api/items?type=…` once per declared target type and merges the
   lists; the picker is then a **client-side substring filter** over that
   preloaded list (`links.js:120-149`). So it is not a server search — it is
   the whole candidate list in the page, filtered locally. Embedding that in
   an offline form means embedding the list: a privacy question (whose item
   titles leave the project?) and a size question, on a file handed to
   someone outside the team. Dropping link inputs from generated forms
   entirely is a third option and may well be the right first one. Not
   resolved.
6. **Should the title similarity reuse `citations._norm`'s case-sensitive
   normalization?** It is the existing precedent and it is deliberately
   case-sensitive because datasheet outlines capitalise section titles
   (`citations.py:272-277`). Two people independently typing the same
   requirement title in different case would score as different. The precedent
   argues for inheriting it; the use case arguably does not.

## 7. What is still design only

Everything. Explicitly, and with no slices scoped:

- **No form generator exists.** Not a template, not a schema-to-HTML path, not
  a route. `create.js` is the closest existing code and it renders into the
  editor's own page, from a live fetch, into a `<div>` — it is not a portable
  document and was not written to be one.
- **No export, no snippet format, no importer.** No download step, no
  round-trip, no `refdes` command that takes a submission file. §3.2's two
  shapes are candidates.
- **No form-instance key is minted anywhere.** §3.3 is a description of where
  a key would live, not a spec for one. There is no store of keys, no
  comparison, no skip-or-overwrite behavior.
- **No similarity matching for submissions.** §3.4 names existing machinery
  it would reuse; no threshold has been chosen, no candidate set defined, and
  §3.3's gap — two different form instances describing the same requirement —
  is acknowledged and unsolved.
- **No offline embedding, no client-side validation, no file-size answer.**
  §6 Q3.
- **No markdown authoring story.** §6 Q4, and §4.2 says the create API cannot
  carry one even if there were.
- **No privacy posture for embedding project data in a distributed file.**
  This is the question §6 Q5 raises and the reason that question is listed
  first among the blockers rather than last.
- **`/api/create/schema` is unchanged.** §4.1 is a finding about it, not a
  proposal to widen it. Widening it is option A of §6 Q1 and is a decision
  that has not been made.

## 8. Precedent this borrows from

Each of these already exists and is load-bearing for a specific claim above;
they are collected so a reader does not have to re-derive them.

| Precedent | Where | What it is precedent for |
|---|---|---|
| `former-ids propose --confirm` | `cli.py:1214-1280` | propose-then-human-applies; write nothing without `--confirm` |
| `refdes new` scaffold | `refdes new --help`, `scaffold.py` | generate from `refdes schema --json`, print to stdout, human places it |
| schema-driven New Item form | `static/create.js:1-9, 101-138` | generate inputs from the live schema; never re-implement a project fact in the client |
| one mutation entry point | `browser-editor.md:999` | the export is the only thing that carries a write; the apply stays a human's |
| `create` writes any declared link verb (F1) | `9d9b549`, `edit.py:1176-1254` | what a generated link input must produce |
| `links.composite_for` | `links.py:311-319` | the one `DISPLAY-ID@key` spelling, re-derived server-side |
| `_hint` cutoff policy | `configcheck.py:159-164` | why the similarity threshold is tuned, not chosen |
| outline-title fuzzy match | `citations.py:340-352`, `_norm` at `272-277` | the closest existing title-similarity behavior |
| `Conflict` + `showConflict` | `edit.py:163-187`, `598-607`; `editor.js:294-330` | rendering "yours vs what's there" side by side |
| binary conflict dialog | `static/images.js:118-160` | the same comparison UI for a payload that is not a text diff |
| link candidate list + local filter | `static/links.js:28-36, 120-149` | why a link picker in an offline form is hard |
| `limit` grammar and its error | `calc.py:834-861` | the §1 problem, and what a generated `limit` control would have to enforce |
| `_FIELD_TYPE_MAP` and `doc:` → `description` | `schema_json.py:32-125` | the field-type catalog, and where the human-readable text lives |
| `link_json_schema` | `schema_json.py:128-148` | link verbs and their allowed targets in `refdes schema --json` |

## 9. Not proposed

- **Not a server, an account system, an inbox, or any multi-user
  coordination.** refdes is local-first and git-based. The two problems this
  design started from — schema drift and duplicate submissions — are both
  consequences of that, and neither is answered by adding a service.
- **Not a direct write from the form.** The submitter has no write path and
  no credentials, by §2.1.
- **Not a second implementation of any project rule in JavaScript.** If
  client-side validation is needed for §6 Q3, it is validation the server
  would not have to re-derive — not a second parser, not a second limit
  grammar, not a second link resolver. `editor-source-picker.md` §5 is the
  statement of why that line is where it is.
- **Not a change to item shape, the id ledger, key minting, or composite
  expansion.** A submission becomes an ordinary item through ordinary means.
- **Not a new docs page in `docs/index.md`'s nav.** The other 22 files in
  `docs/design/` do not appear there today (verified: `docs/index.md` contains
  no `design/` path at all — its one `design` hit is a link to the
  user-facing `design-log.md`), and this one does not either.
