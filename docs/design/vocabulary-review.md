# Vocabulary review — duplication and clarity

**Status: findings and proposals, no code changed.** Read-only pass over the
words refdes asks an author to learn. Nothing here renames anything; §3 proposes
fixes and costs each one. The goal this review is scored against is the owner's,
in his words: the vocabulary should be **intuitive**.

## Summary

The vocabulary is mostly healthy: the link verbs are defined at their point of
use, the active-voice convention is genuinely good design, and the words that
are unfamiliar — `fold`, `tip`, `stamp`, `bound` — do not import competing
meanings. §4 records what was checked and kept, on purpose.

The damage is concentrated in three places.

1. **Words that mean something else to a hardware engineer.** `vendor:` in a
   citation entry means "keep a local copy of the bytes", and it sits in the
   same mapping as `part_number` (§2.1 S1.1). `alternate` means *not*
   interchangeable, beside `equivalent` which means interchangeable — the same
   near-synonym structure that already cost this project one rename (§S1.2).
2. **One word, several mechanisms.** `log` is a type and a change mode whose
   difference the engine does not implement (S1.4); `history` names four things
   (S1.5); `revision`/`revise`/`rev:` are four things including two adjacent
   commands (S1.3); `frozen`, `locked`, `sealed` and `pinned` are four
   mechanisms with four near-synonyms (S1.7, D1).
3. **The unshipped living-notes vocabulary is about to add five more words to
   the cluster it is simultaneously redefining** — `record`, `recorded`,
   `history`, `snapshot`, `tasks` (`living-notes-plan.md:576` reserves exactly
   this) — and `record` collides head-on with the shipped `records:` verb, a
   collision the plan itself already noticed at `:588`.

The good news is cost. Everything in the third group is unshipped and free to
change today, and most of the second group is inside `hardware@3`, which is
unreleased: a rename there touches one YAML file and this repo, not a migration.
§3.1 is free, §3.2 is cheap now and expensive after v3 ships, §3.3 is moderate,
§3.4 costs only documentation. §3.6 lists what this review recommends leaving
alone, and why.

Every term below was read in the file that defines it, and every quote is
copied from that line. Where a term exists in more than one standard version,
each version is cited separately, because the definitions differ and the
older ones are frozen.

## 1. The inventory

### 1.1 Item type names

Bundled standard `hardware@3` — `src/refdes/standards/hardware/v3/base.yaml`.
This is the version a new project gets; it is **unreleased** (see
`AGENTS.md` "Current state, briefly").

| Type | Prefix | Defined | Definition as written |
|---|---|---|---|
| `requirement` | REQ | `v3/base.yaml:128`, doc `:129` | "Something the design must achieve, stated as one prose body. Counts toward coverage while active; a draft or retired requirement is left out of coverage entirely." |
| `bound` | BND | `v3/base.yaml:146`, doc `:147` | "A numeric limit the design must respect — a voltage, a current, a tolerance. Its limit field makes it checkable by other items' checks. Counts toward coverage while active." |
| `decision` | DEC | `v3/base.yaml:165`, doc `:166` | "A design choice that was made — what was picked, why, and what it satisfies. A settled (accepted) decision closes coverage on what it satisfies; a failing check on a decision is an error." |
| `test` | TST | `v3/base.yaml:191`, doc `:192` | "A verification item that proves a requirement or bound. Its verifies links count toward coverage when the test's status is passing." |
| `component` | CMP | `v3/base.yaml:206`, doc `:207` | "A part the design uses. A selected component closes coverage on what it satisfies, and it can carry its own checks against bounds. Equivalence and alternateness between components are claims made here, not facts from a parts database." |
| `group` | GRP | `v3/base.yaml:234`, doc `:235` | "A named collection of items — 'the PCIe interface spec' — that names the collection without letting it stand in for its members. Members point here with part_of; a group never lists its members, never appears in coverage, and nothing may satisfy one." |
| `log` | LOG | `v3/base.yaml:245`, doc `:246` | "A dated entry in the design log — work done, questions raised, corrections. Entries are append-only: each is sealed on the first build where it has no errors, and after that editing it is a build error — corrections are new entries with amends." |

`hardware@2` — `src/refdes/standards/hardware/v2/base.yaml`: same seven minus
`group`; `bound` at `:100` (`prefix: BND` `:101`, `label: Bound` `:102`),
whose required content field is `text:` (`:107`), not `body:`.

`hardware@1` — `src/refdes/standards/hardware/v1/base.yaml`: `requirement`
`:40`, **`constraint`** `:55` (`prefix: CON` `:56`, `label: Constraint` `:57`,
required `title:` `:62`), `decision` `:71`, `test` `:94`, `component` `:108`,
`log` `:127`. The rename `constraint` → `bound` is recorded in
`v2/base.yaml:21-24`:

> "`constraint` is now `bound`, prefix `CON` -> `BND`. `requirement` and
> `constraint` read as near-synonyms in plain English — a constraint
> colloquially *is* a requirement — which is what produced the authoring
> mix-up this came from."

That is the project's own precedent for this review's whole thesis: a word
that reads as a near-synonym of another word in the same vocabulary produced
a real authoring error, and the fix was a rename.

Preset `design-debate` (bundled, **not enabled by default**) —
`src/refdes/standards/hardware/v3/presets/design-debate.yaml`:

| Type | Prefix | Defined | Definition as written |
|---|---|---|---|
| `debate` | DB | `:15`, doc `:16` | "An open question the design is arguing about — the argument that produces a decision, recorded alongside it. You close it by setting its status; the resolved_by link records which decision settled it." |
| `option` | OPT | `:29`, doc `:30` | "A candidate approach under debate, compared against requirements and bounds. A failed check on an option is reported as information — a finding about the candidate, not a defect in the design." |
| `claim` | CLM | `:44`, doc `:45` | "An assertion made in a debate — a fact or judgement that bears on an option, a requirement or a bound, and that others may accept or rebut." |
| `position` | POS | `:57`, doc `:58` | "One participant's stance in a debate, raising the claims they stand behind. Positions are what make the argument attributable — who said it, not just what was said." |

### 1.2 Link verbs and their inverses

`hardware@3` `link_types:` — `v3/base.yaml:106-125`. The `doc:` text on these
verbs is recent: v1 (`:25-37`) and v2 (`:70-82`) declare the same verbs with
`inverse:` and `label:` only and no `doc:` at all, so the definitions below
exist only for v3 readers.

| Verb | Inverse | Line | Definition as written |
|---|---|---|---|
| `refines` | `refined_by` | `:111` | "A narrower, more detailed version of the same kind of statement: a requirement refining a requirement, or a bound refining a bound. Same category of thing, different altitude." |
| `derives_from` | `derived_by` | `:112` | "A bound whose value follows from a requirement or another bound — where the number came from, not a restatement of it." |
| `governed_by` | `governs` | `:113` | "This requirement must comply with a general rule stated elsewhere — another requirement or a bound — without being a narrower version of it. Traceability only; it never feeds coverage." |
| `satisfies` | `satisfied_by` | `:114` | "A decision or component claims to meet a requirement or bound. This is the link that closes coverage once the claiming item reaches a satisfying status." |
| `constrained_by` | `constrains` | `:115` | "A decision or component that must respect a bound. Traceability only — it does not close coverage on the bound; satisfies does." |
| `verifies` | `verified_by` | `:116` | "A test proves a requirement or bound. Counts toward coverage when the test's status is one of the type's verifying_statuses." |
| `addresses` | `addressed_by` | `:117` | "A log entry records work done on a requirement or bound. Counts as addressed coverage — someone has worked on it and written it up — without claiming it is met." |
| `records` | `recorded_by` | `:118` | "A log entry records a decision — the design-log side of the decision's own recorded_by end of the same edge." |
| `amends` | `amended_by` | `:119` | "A log entry corrects an earlier log entry. Entries are append-only, so a correction is written as a new entry pointing back at this one rather than as an edit." |
| `supersedes` | `superseded_by` | `:120` | "This decision replaces an older one. The older decision keeps its history; moving its status to superseded is your edit, not something the link does by itself." |
| `selects` | `selected_by` | `:121` | "A decision picks a component. The component's own status marks it selected; this link records which decision made the pick." |
| `blocked_by` | `blocks` | `:122` | "Something is holding this decision up. Name only the immediate blocker; reports resolve the chain to its root. May point at an item of any type; a cycle is a build error." |
| `part_of` | `contains` | `:123` | "This item belongs to a group. Membership is always declared by the member, never by the group; contains is the computed backlink." |
| `equivalent` | `equivalent` | `:124` | "This component is a drop-in second source for that one — interchangeable as claimed, no review needed. Self-inverse, and restricted to component-to-component." |
| `alternate` | `alternate` | `:125` | "This component is functionally close to that one but not a drop-in: check before substituting. Self-inverse, component-to-component, and the rationale explaining what differs is required." |

Preset verbs — `presets/design-debate.yaml:9-12`:

| Verb | Inverse | Line | Definition as written |
|---|---|---|---|
| `raises` | `raised_by` | `:9` | "A position puts a claim on the table — someone is asserting this, and it is open to rebuttal." |
| `bears_on` | `borne_on` | `:10` | "A claim is relevant to an option, a requirement or a bound — it argues for or against it without by itself settling anything." |
| `met_by` | `meets` | `:11` | "An option claims to meet a requirement or bound. It records how a candidate measures up; it is not coverage — only a decision's or component's satisfies closes coverage." |
| `resolved_by` | `resolves` | `:12` | "A debate was settled by a decision. The debate keeps the argument; the decision keeps the outcome." |

The active/passive convention that governs which side an author writes, and
the coverage consequence attached to it, is stated in `docs/coverage.md:64-91`:

> "every link this standard authors to make a coverage claim is active voice —
> `satisfies`, `verifies`, `addresses` — and coverage is computed from *only*
> the three backlinks their inverses produce ... Every link authored in the
> passive `X_by` form instead — `constrained_by`, `governed_by`,
> `blocked_by` — is deliberately kept out of that computation."

and the same passage admits the exception:

> "Authored that way, `verified_by` — despite the `_by` suffix — *is* the
> coverage-feeding form."

### 1.3 Engine-reserved front matter keys

`src/refdes/parse.py:33` — the keys a type may never shadow:

```python
RESERVED = {"id", "type", "history", "body", "former_ids", "key"}
```

`src/refdes/parse.py:34-37` — reserved only when the type does not declare
the name itself:

```python
# Reserved, but only when the item's own type does not already declare a field of
# the same name -- so a schema that predates one of these keys keeps working
# unchanged instead of having the field silently shadowed.
OVERRIDABLE = {"prefix", "board", "workspace"}
```

Their definitions live in code, in `src/refdes/vocabulary.py:57-107`
(`RESERVED_KEYS`), because they have no YAML `doc:` slot:

| Key | Line | Definition as written |
|---|---|---|
| `id` | `vocabulary.py:58` | "The item's display identifier, minted from its type prefix and the project's id width. Stable in people's sentences, not in the engine: a rename moves it, and `former_ids:` records where it went." |
| `type` | `:63` | "The item's item type -- the entry in `types:` that gives it a prefix, fields, and links." |
| `key` | `:67` | "The item's surrogate key: opaque, immutable, and the identity the engine actually uses. Nothing rewrites it, and links resolve through it rather than through a display id." |
| `former_ids` | `:72` | "Display ids this item used to have. Written by the engine when an id is re-minted, so old citations still resolve." |
| `body` | `:76` | "The item's prose, below the front matter. Its change policy comes from the type's `body:` setting; for types whose content is the statement itself it is the required field." |
| `history` | `:81` | "This item's change-policy override, in place of the project's `history: default`." |
| `prefix` | `:85` | "On a type: the id prefix its items carry. As an item key it is the engine's own, and a type that declares a field of this name takes it over." |
| `board` | `:89` | "Which board an item belongs to -- the first path segment under `items/` unless the item says otherwise. Overridable by a type's own field." |
| `workspace` | `:93` | "Which workspace an item belongs to, when the project registers them. Overridable by a type's own field." |
| `defaults` | `:97` | "In a YAML list file: the type and field values every entry in that file inherits, before its own keys." |
| `section` | `:101` | "In a YAML list file: the section heading its entries file under on the item's page; in a Markdown marker block, the section a generated block belongs to." |

Note that `history` is *also* a project-config key with a different meaning:
`docs/schema-reference.md:78` "## `history`" — `history: { ... } # default
on_change mode` (`docs/schema-reference.md:18`), and `:652` "## Item-level
`history`" — "Not part of either config file, but the counterpart to the
`history:`" block. §2.3 comes back to this.

### 1.4 Block names in bodies

`src/refdes/blocks.py:473-489` (`_REGISTRY`) — the only three recognized
`{{name}}` block names, each with its parameters:

| Block | Line | Required / optional parameters |
|---|---|---|
| `index` | `:474` | required `by`, `type`; optional `board`, `tag` |
| `cascade` | `:477` | required `from`, `direction`; optional `depth`, `via` |
| `tree` | `:483` | optional `board`, `workspace`, `depth` |

Documented in `docs/blocks.md:32` (`## {{index}}`), `:64` (`## {{cascade}}`),
`:107` (`## {{tree}}`). Two other body-level syntaxes an author must learn:
the ```` ```calc ```` block (`docs/math.md:8` "## A calc block") and the
`[[cite:...]]` inline citation reference (`docs/markdown.md:353`).

`{{cascade}}` and `{{tree}}` are deliberately different things sharing a
walk primitive — `docs/blocks.md:95-98`:

> "`blocked_by` graph is asserted acyclic; `{{cascade}}` only renders where an"

and `docs/blocks.md:124-130`:

> "`{{tree}}` deliberately has **no `via=`.** In `{{cascade}}` it names the"
> "it would replace it with a cascade wearing a hat — so `via=` is reported"

### 1.5 Coverage vocabulary

Stage names — `docs/coverage.md:6-14` ("## The five stages"):

| Stage | Definition as written |
|---|---|
| `open` | "Nothing references it at all" |
| `addressed` | "Somebody has worked on it" |
| `claimed` | "A decision or component says it meets it, but that claim hasn't settled" |
| `satisfied` | "A settled decision or component claims to meet it" |
| `verified` | "A test proves it" |

`docs/concepts.md` documented the same subject as "## The three notions of
'done'" with **four** rows and no `claimed` — a header count of three, a row
count of four, and `coverage.md`'s five, disagreeing in the two places a new
author meets coverage. This was fixed on `main` while this review was in
flight, by `6a65cee` "docs(coverage): title the section by its five stages,
matching the code"; `docs/concepts.md:47` is now "## The five coverage stages"
with all five rows at `:56-60`. It is recorded here because it is the pattern
the rest of §2 is about — a count in a heading and a count in the code drifting
apart — and because it is the proof that the project fixes this class of thing
when it is named.

Type-level switches that produce the stages:

| Word | Where defined | Meaning as written |
|---|---|---|
| `coverable` | `v3/base.yaml:133`, `:151`, `:239`; `docs/coverage.md:46` | "`coverable: true` puts items of this type in coverage at all." |
| `coverable_statuses` | `v3/base.yaml:134`, `:152`; `docs/coverage.md:54` | "Set, it's an *inclusion* list: `coverable_statuses: [active]` means a `draft` item isn't tracked either" |
| `satisfying_statuses` | `v3/base.yaml:170` (`[accepted]`), `:211` (`[selected]`); `docs/coverage.md:229` | "Only a link whose `status` is in the list counts as satisfying; the rest count as `claimed`" |
| `verifying_statuses` | `v3/base.yaml:196` (`[passing]`); `docs/coverage.md:257` | "Only a link whose `status` is in the list counts as verifying" |
| `check_severity` | `v3/base.yaml:171` (`error`), preset `:34` (`info`); `src/refdes/model.py:231-233` | "A decision either meets its constraints or it doesn't, so ERROR is" ... "can set this to INFO so a failed criterion is a finding, not a" |

Status words each type allows (`v3/base.yaml`, `choices:` on each `status`
field), plus the preset's:

| Type | Statuses | Line |
|---|---|---|
| `requirement` | `draft`, `active`, `retired` | `:137` |
| `bound` | `draft`, `active`, `retired` | `:156` |
| `decision` | `proposed`, `in_progress`, `accepted`, `on_hold`, `rejected`, `superseded` | `:174` |
| `test` | `planned`, `passing`, `failing`, `blocked` | `:199` |
| `component` | `candidate`, `selected`, `obsolete` | `:216` |
| `group` | none — no `status` field | `:234-243` |
| `log` | none — no `status` field | `:245-261` |
| `debate` (preset) | `open`, `resolved` | preset `:22` |
| `option` (preset) | `candidate`, `eliminated` | preset `:37` |
| `claim` (preset) | `open`, `accepted`, `rebutted` | preset `:51` |

Diagnostic levels — `src/refdes/model.py:26-29`:

```python
ERROR = "error"      # blocks the build
WARNING = "warning"  # visible by default; worth a look
INFO = "info"        # default-hidden; the normal state of an incomplete project
```

### 1.6 CLI subcommand names and the nouns they print

`src/refdes/cli.py`, `add_parser` calls, with the `help=` text as written:

| Command | Line | help text |
|---|---|---|
| `build` | `:1227` | "render the HTML site and items.json" |
| `check` | `:1269` | "validate without rendering" |
| `revision <name>` | `:1306` | "stamp an internal checkpoint baseline" |
| `release <name>` | `:1319` | "run the readiness gate and stamp a baseline if it passes" |
| `index` | `:1333` | "print items.json to stdout without rendering the site" |
| `ls` | `:1341` | "list existing items: id, type, board, title -- filterable" |
| `id` | `:1354` | "allocate IDs for items that have none" |
| `fetch` | `:1358` | "fetch and pin (optionally vendor) datasheet citations" |
| `audit` | `:1376` | "list suppressed fields, resealed entries, board/workspace moves, " |
| `init` | `:1390` | "write a minimal refdes-project.yaml that points at the standard" |
| `new <type>` | `:1417` | "print a starter item for one type to stdout" |
| `schema` | `:1429` | "print the project's merged JSON Schema, or type/link graph, to stdout" |
| `standard` | `:1453` | "add or remove a preset from standard.presets:" |
| `standard add-preset` | `:1464` | "validate a preset name and add it to standard.presets:" |
| `standard remove-preset` | `:1470` | "remove a preset from standard.presets:, reporting what breaks first" |
| `standard upgrade --to N` | `:1477` | "move a pinned standard forward, rewriting item files and " |
| `keys` | `:1497` | "manage immutable surrogate-key storage" |
| `keys adopt` | `:1502` | "transactionally adopt key-keyed baselines and seals" |
| `revise` | `:1514` | "rewrite project-local vocabulary (types/fields/links/prefixes) " |
| `calc-rewrite` | `:1538` | "rewrite retired 'name : unit = expression' calc lines to the " |
| `stub-tests` | `:1558` | "generate starter test items for coverable items with no verifying test" |
| `former-ids` | `:1581` | "infer and record former_ids: mappings after a renumbering" |
| `former-ids propose` | `:1587` | "show inferred old-to-new id candidates; write none unless --confirm" |

Nouns those commands print:

- `check`/`build` print **diagnostics** at three levels — `error`, `warning`,
  `info` (`model.py:26-29`).
- `revision`/`release` print and write a **baseline**, produced by a
  **stamp**, judged by the **readiness gate** (`docs/lifecycle.md:5-11`;
  `src/refdes/lifecycle.py:1-11` "Baselines: `refdes revision <name>` and
  `refdes release <name>` ... `revision` cuts an internal checkpoint
  unconditionally ... `release` runs the full readiness gate and stamps only
  if it passes").
- `audit` prints sections named "Schema fields not tracked as 'invalidate'",
  "Item-level overrides", "Append-only entries edited after sealing",
  "Ledger entries with no live item and no former_ids", "Baselines", "Since
  last revision" (`docs/cli-reference.md:341-380`).
- `fetch` speaks **pin**, **vendor**, **re-pin**, and writes a
  **lockfile** (`.refdes/citations.yaml`) — `src/refdes/citations.py:1`
  "Datasheet citations: declared intent in items, computed provenance in a
  lockfile.", `docs/markdown.md:380-383` "**Pinning vs. vendoring.** Every
  fetched citation is pinned: its sha256 and ... `vendor: true` additionally
  keeps a local copy of the bytes".
- `index` prints "the index" meaning `items.json` — `docs/cli-reference.md:193`
  "This exists for editor tooling and scripts that need the index on every save".
- `build` writes `index.html`, the site's **index page**.

### 1.7 The living-notes vocabulary (not implemented)

Both documents are unshipped: `docs/design/living-notes.md:1` "Status:
Decided -- ready to plan implementation", and
`docs/design/living-notes-plan.md:1-2` "Status: Proposed — implementation
plan for living notes". None of these words is in `base.yaml`, in
`vocabulary.py`, or in `cli.py` today, which is what makes them free to
change.

| Word | Where introduced | Definition / use as written |
|---|---|---|
| `record` | `living-notes.md:49-50` | "The record moment is **a `follows:` edge naming that entry as its predecessor**, captured by the first writable load that resolves the edge" |
| `recorded` | `living-notes.md:270` | "recorded 2026-09-15T14:08Z when LOG-POWER-014 followed it / edited after recorded: current semantic content differs" |
| `history` | `living-notes.md:63` (store) | "Use one general, versioned `.refdes/history/` store for these snapshots and for rich baseline snapshots." |
| `snapshot` | `living-notes.md:46` | "Replace the current build-time seal with a **recorded snapshot**: an entry stays editable, but, after a record moment, refdes compares its live semantic content with the stored snapshot" |
| `redact` | `living-notes.md:329` | "`refdes history redact <object-or-item>` requires an explicit acknowledgement, removes matching current history objects/events, and writes an auditable redaction event without repeating the secret." |
| `seal` (kept, meaning changed) | `living-notes-plan.md:246-249` | "the first writable build no longer writes a hash lock, an edit is no longer a build error ... Existing seal files keep being read and become **legacy-seal markers**: 'recorded hash only; original content was not captured.'" |
| `lock` | `living-notes-plan.md:246` | "no longer writes a hash lock" — and `living-notes.md:94`, Jared's own word: "I've also been questioning the idea of 'locking' documents in the first place." |
| `task` / `tasks:` | `living-notes.md:378` | "Add an optional `tasks:` field to the merged `log` type, with stable task IDs and complete state" with `state: open # open \| done \| dropped` |
| `thread` | `threads.md:7-12` | "A **thread** is not a container and not an item: it is the connected chain of entries reachable by walking `follows:` backward and its computed inverse, `followed_by:`, forward." |
| `tip` | `threads.md:11-12`, `:448` | "answered by walking forward from any entry in the chain to its tip(s) and folding per field"; "all reachable heads contribute their tips, and a non-reconciled fork is" |
| `follows` / `followed_by` | `threads.md:6-8` | "An entry declares its predecessor with a link, `follows:`, written by the tool, not typed by the author." |
| `release` (gate sense) | `living-notes-plan.md:410-411` | "Adds. `open_tasks` (a release blocks while any thread tip carries an open author task) and `recorded_edits` (a release blocks while any item is edited after recorded). Both off by default, both enabled through the existing `release_gate:` overlay." |
| `gate` | `docs/lifecycle.md:19` "## The readiness gate"; `model.py:52-63` `RELEASE_GATE_DEFAULTS` | eight named rules, each `{release: bool, revision: bool}` |
| `work` / worklist | `living-notes.md:441` | "A proposed `refdes work` query combines hand-written tip tasks with derived rows, but preserves their origins and never writes them into `tasks:`." |
| `continuation` | `living-notes.md:74` | "a task edit is a **new continuation entry** containing a complete replacement list, not an edit of its predecessor" |
| `fold` | `threads.md:388-393` | "The per-field fold rule from the previous draft is *correct* and is kept ... declared `F`* said, walking backward from the tip." |
| `fork` / `merge` | `threads.md:671-717` | "## 6. Branching and merging ... ### Two entries claiming the same predecessor ... ### Merging" |

`follows:`/thread machinery is implemented in the engine (`chains.py:1`
"`follows:` chain walk: tips, the per-field fold, fork and cycle diagnostics",
`chains.py:29` `FOLLOWS = "follows"`) but **is not declared in the bundled
standard** — `v3/base.yaml` has no `follows` verb, and
`tests/test_chains.py:25` declares it by hand
(`follows: { inverse: followed_by, label: Follows }`). So today an author
using threads must add the verb to their own overlay; the words exist in the
engine and in `docs/design/threads.md`. `docs/links.md`, `docs/design-log.md`
and the `keys adopt` bullet in `docs/cli-reference.md` used to present
`follows:` to authors as available; `8491dd1` "docs(links): stop presenting
follows: as available in the bundled standards" corrected all three while this
review was in flight, and `docs/links.md` now says "**It is not yet available
to authors:** no bundled standard declares the verb, so writing `follows:`
today is an unknown-link error."

### 1.8 Coverage of the inventory

Every item type in all three bundled versions and the bundled preset (11
types), every link verb in all three (15 in v3, 13 in v1/v2, 4 preset), the 6
reserved plus 3 overridable front matter keys plus the 2 list-file keys, the 3
body block names plus `calc` and `[[cite:]]`, the 5 coverage stages and the 4
type-level coverage switches, the 24 CLI subcommands, the 3 diagnostic levels,
the 10 status enumerations, and the 16 living-notes/threads words named in the
brief. All were opened and read; the quotes above are copied, not recalled.

## 2. Analysis

### How this is graded

Two questions get asked of every term, and they are not the same question.

**Is it duplicated?** Either one word carrying two meanings the author must
keep apart, or one meaning wearing several names, so that the author cannot
tell whether two words are the same thing or different things.

**Is it misleading?** Whether a hardware engineer arriving with the vocabulary
of their own trade will import a meaning refdes does not intend. This is the
serious category, and the project has been bitten by it exactly once already
and paid for it with a rename:

> "`requirement` and `constraint` read as near-synonyms in plain English — a
> constraint colloquially *is* a requirement — which is what produced the
> authoring mix-up this came from." — `v2/base.yaml:21-24`

**Unfamiliar is not the same as wrong.** `fold`, `tip`, `stamp`, `pin`,
`redact`, `bound` and `cascade` are words a reader has not met before in this
position. Each is defined the first time it is used, none of them imports a
competing meaning, and none of them is a problem. Renaming unfamiliar-but-
correct words is churn that costs more than it buys, and this review does not
propose it. Findings are graded:

- **S1 — actively misleading.** A reader will get it wrong without noticing.
- **S2 — genuinely confusing.** Recoverable from the docs, but the word alone
  does not carry the distinction.
- **S3 — merely unfamiliar.** Fine as is; listed in §4.2 so the decision to
  keep it is on the record.

### 2.1 S1 — actively misleading

**S1.1 — `vendor:` in a citation entry means "keep a local copy", not
"the company that makes it".** This is the worst one in the vocabulary for a
hardware engineer, because the word already has a fixed meaning in their trade
and refdes uses it for something else in the same breath as the word that
*does* mean what they think.

`v3/base.yaml:104` — one field, two adjacent sub-keys, opposite senses:

> "Each entry needs a path — an http(s) URL or a project-root-relative file —
> and may carry rev, page, section, part_number, **vendor** and an id for
> `[[cite:]]` references."

`docs/markdown.md:297` shows a real entry, and `:380-383` explains the sense:

> "**Pinning vs. vendoring.** Every fetched citation is pinned: its sha256 and
> ... `vendor: true` additionally keeps a local copy of the bytes, content-
> addressed at `.refdes/vendor/<sha256><ext>`"

So `part_number: TPS62913` and `vendor: true` sit in the same mapping, and the
second one is a boolean about file copying. An engineer reads that pair as
"the vendor of this part number is true". Worse, the thing `vendor:` is
naming — a local copy of a datasheet — is exactly what a hardware engineer
would call a *vendor copy* in the manufacturer sense too. Both readings are
available and one of them is wrong. `src/refdes/citations.py:1` commits the
word throughout: "declared intent in items, computed provenance in a
lockfile", with `lockfile_path`, `load_lockfile`, `save_lockfile` and
`vendor:` as the vocabulary of the module.

**S1.2 — `alternate` means "not interchangeable" in a vocabulary where
`equivalent` already means "interchangeable".** `v3/base.yaml:124-125`:

> `equivalent`: "This component is a drop-in second source for that one —
> interchangeable as claimed, no review needed."
>
> `alternate`: "This component is functionally close to that one but **not a
> drop-in**: check before substituting."

Two near-synonyms in English carrying a load-bearing, safety-adjacent
distinction, both self-inverse, both component-to-component, differing only in
whether a review is needed. This is structurally identical to the
`requirement`/`constraint` pair that the project already renamed once. And the
industry usage runs against refdes: in BOM practice an "alternate part" is
generally an approved substitute — i.e. closer to what refdes calls
`equivalent` — so the default connotation a reader imports points at the
opposite meaning. The distinction is worth keeping; the word pair is not
obvious enough to carry it, and the consequence of getting it backwards is a
part swapped on a board without review.

**S1.3 — `revision`, `revise`, `rev:` and "Since last revision" are four
different things, two of them adjacent CLI commands.**

- `refdes revision <name>` — `cli.py:1306`: "stamp an internal checkpoint
  baseline".
- `refdes revise` — `cli.py:1514`: "rewrite project-local vocabulary
  (types/fields/links/prefixes)".
- `rev:` — a citation entry's datasheet revision, `docs/markdown.md:255`
  (`rev: E`), `:272` (`rev: "2"`).
- "Since last revision" — a section heading in `refdes audit` output
  (`docs/cli-reference.md:341` onward), meaning since the last stamped
  baseline of any kind, including a release.

Two commands whose names differ by two letters do unrelated jobs — one records
a point in time, the other rewrites the schema — and `rev` is simultaneously
the identity of a datasheet edition. A datasheet revision is not a project
revision and neither is a baseline name, and all three are called rev/revision
in the same tool.

**S1.4 — `log` is an item type, a change-tracking mode, and a prose name for
the notebook, and one of those three distinctions does not exist.**

- `log` the type — `v3/base.yaml:245`.
- `log` the `on_change` mode — `docs/change-tracking.md:10-14`, the middle row
  of a three-row table whose first column is the same word as an item type.
- "design log" the prose name — `v3/base.yaml:246` "A dated entry in the
  design log".

And the mode itself is not what its name promises. `docs/change-tracking.md:16-23`:

> "**The last two columns are implemented; the first is not.** ... until it
> exists, `log` and `ignore` are indistinguishable in every *other* observable
> way"

and `docs/schema-reference.md:87-89` is blunter:

> "Only `invalidate` has any effect today ... `log` is reserved for a future
> per-field history layer and currently behaves exactly like `ignore` —
> choosing between them is not yet a meaningful decision."

The bundled standard nonetheless distributes the two names across its fields as
if the choice mattered — `on_change: log` on `source` (`:97`), `note` (`:98`),
`owner` (`:101`), `date` (`:177`), `refdes` (`:215`), `title` on group (`:241`)
versus `on_change: ignore` on `tags` (`:99`) and `last_reviewed` (`:102`). An
author reading the schema reasonably concludes the engine treats them
differently. It does not. A word that names a distinction the tool does not
implement is a vocabulary item that teaches the wrong model, and `log` is the
same word as the type an author writes `type: log` five lines above it.

**S1.5 — `history` names four things.**

1. The project config key for the default change mode — `docs/schema-reference.md:18`
   `history:     { ... }   # default on_change mode`, documented at `:78`.
2. The item-level override of that mode — `vocabulary.py:81` "This item's
   change-policy override, in place of the project's `history: default`", and
   `docs/schema-reference.md:652` "## Item-level `history`".
3. The planned snapshot store — `docs/design/living-notes.md:63` "Use one
   general, versioned `.refdes/history/` store for these snapshots".
4. The parked git-reader layer — `docs/change-tracking.md:20-22` "a
   continuous, field-level history the parked git-reader layer would provide".

(1) and (2) are at least the same concept at two scopes. (3) is a completely
different object — a store of immutable events — that will be reached through a
new command family, `refdes history record` / `refdes history redact` /
`history migrate-seals` (`living-notes.md:13`, `:329`, `living-notes-plan.md:602-606`).
So `history:` in front matter and `refdes history` on the command line will
mean unrelated things in the same project, and the word already meant the
parked layer in the docs. This is the term with the most meanings in the whole
vocabulary.

**S1.6 — `records:` (shipped verb) and `record` / `recorded` (planned core
noun) collide in the same file, and the plan already noticed.**

The shipped verb, `v3/base.yaml:118`: "A log entry records a decision — the
design-log side of the decision's own `recorded_by` end of the same edge."

The planned noun, `living-notes.md:49-50` and `:270`: the record moment is "a
`follows:` edge naming that entry as its predecessor", rendered as "recorded
2026-09-15T14:08Z when LOG-POWER-014 followed it".

A log entry that carries `records: [DEC-POWER-002]` and is also "edited after
recorded" uses the same word twice for two unrelated facts, in the same item,
on adjacent lines. `living-notes-plan.md:588` names the hazard in passing while
rejecting an unrelated option:

> "(c) is the smallest diff but hides a policy in a version comparison, which
> is how the `records:` confusion happened."

That sentence is evidence the collision is already live, not hypothetical. It
is also the cheapest kind of finding this review can make: `record`, `recorded`
and `snapshot` are unshipped, and `living-notes-plan.md:576` explicitly
reserves the right to rename them — "It may rename terms this plan introduces —
`record`, `recorded`, `history`, `snapshot`, `tasks` — without reopening the
eight decisions themselves".

**S1.7 — `frozen` already means "link resolved to a surrogate key", while
living-notes uses lock/seal language for immutability.** `src/refdes/adopt.py:64`
`frozen_follows: int = 0`, `:214` "could not freeze N local follows
reference(s)", `src/refdes/build.py:421` "preserving the authoring path for
unfrozen links". Nothing to do with sealing; freezing here means a link target
has been pinned to a key instead of a display id. Meanwhile `living-notes-plan.md:246`
describes sealing's removal as "the first writable build no longer writes a
hash lock". So the codebase has freeze, lock, seal and pin as four near-
synonyms for four different mechanisms, one of which (`frozen`) is already
committed in output fields (`frozen_follows`) that users see.

**S1.8 — `claimed` (coverage stage) vs `claim` (preset item type) vs "claims
to meet" (the prose of `satisfies` and `met_by`).**

- `claimed` is a coverage stage — `docs/coverage.md:6-14`: "A decision or
  component says it meets it, but that claim hasn't settled".
- `claim` is an item type in the debate preset — `presets/design-debate.yaml:44`:
  "An assertion made in a debate".
- `satisfies` is defined as a claim — `v3/base.yaml:114`: "A decision or
  component **claims to meet** a requirement or bound." And `met_by`, preset
  `:11`: "An option **claims to meet** a requirement or bound. It records how a
  candidate measures up; it is not coverage."

So "claim" is a thing you file, a stage a requirement is in, and the standard
English verb for the coverage relation. Two of the three are unrelated to each
other and share a root with no help from the naming: an author who files a
`claim` about a requirement whose coverage stage is `claimed` has said two
unrelated things in words that look like they agree. (`docs/concepts.md` used to
compound this by omitting the `claimed` stage entirely while heading the section
"The three notions of 'done'"; `6a65cee` fixed that on `main` during this
review — see §1.5.)

**S1.9 — `supersedes`/`superseded` and `selects`/`selected`: the link and the
status both claim to do it, and neither does.** `v3/base.yaml:120`:

> "This decision replaces an older one. The older decision keeps its history;
> moving its status to superseded is your edit, not something the link does by
> itself."

and `:121`:

> "A decision picks a component. The component's own status marks it selected;
> this link records which decision made the pick."

The vocabulary offers a verb that reads like it changes the world and then
disclaims having done so, in the verb's own definition. `superseded` and
`selected` are statuses the author must set separately, so the two
representations can disagree, and the tool's own wording invites the author to
believe they cannot. Whatever the engine should do, the words should not
promise and then retract.

**S1.10 — `constrained_by` points at a type that no longer has that name, and
sits beside `governed_by` which points at the same targets.** `constraint`
as a type exists only in `hardware@1:55`; in v3 the word appears nowhere in
`v3/base.yaml` (grep: zero hits), yet the verb is still `constrained_by` —
`v3/base.yaml:115`: "A decision or component that must respect a bound."
So the vocabulary retains the fossil of the renamed type inside a verb while
the type itself is called `bound`, and the verb's doc has to use a third word
("respect") to explain it. Beside it, `governed_by` (`:113`): "This requirement
must comply with a general rule stated elsewhere — another requirement or a
bound — without being a narrower version of it. Traceability only." Both verbs
are traceability-only, both target requirement/bound, and the difference —
"must respect a bound" vs "must comply with a general rule ... elsewhere" — is
not visible in the names. `refines` (`:111`) is the third option for
requirement-to-requirement, and `derives_from` (`:112`) the fourth for
bound-to-requirement. Four verbs, one English idea ("this has to do with that
rule"), distinguished by altitude, origin, and generality that the names do not
carry.

**S1.11 — `block` is five things.** `blocked_by` the verb (`:122`) and its
inverse `blocks`; `blocked` as a `test` status (`:199`); "blocks the build" for
ERROR severity (`model.py:26`); "a release blocks while any thread tip carries
an open author task" (`living-notes-plan.md:410`); "the note type never blocks
on its own" (`living-notes.md:18`). Plus `blocked_chains` as a computed object
(`src/refdes/blocked.py:1-8`, "`blocked_by:` cycle detection, transitive root
resolution, and the stale-blocker diagnostic"). A test whose status is
`blocked` is not blocked_by anything; the two words are 6 characters apart and
unrelated.

### 2.2 Duplication clusters — one idea, several names

Ranked by how much reader work the cluster costs. Fixes are in §3.

**D1 — "this is fixed now": seal, sealed, reseal, hash lock, legacy-seal,
migrated-current, snapshot, record, recorded, baseline, stamp, revision, pin,
lockfile, frozen.** Fifteen words for "a durable record of what something was".
The mechanisms genuinely differ — `seal.py:1-6` seals append-only log entries
by content hash, `lifecycle.py` stamps baselines, `citations.py` pins fetched
bytes in a lockfile, `adopt.py` freezes link targets, and living-notes plans to
replace sealing with a snapshot store — but the words do not encode the
differences, and living-notes is about to add `record`, `recorded`,
`legacy-seal`, `migrated-current` and `history` on top of `seal`, which it is
simultaneously redefining from "editing this is a build error" to "a marker,
never fatal" (`living-notes.md:16-18`). A meaning-flip on a shipped word, in
the same release that adds five new words to the same cluster, is the highest
cost item in this review.

**D2 — "a run of connected things": thread, chain, cascade, follows,
followed_by, tip, head, fork, merge, continuation, walk.** `chains.py:1` calls
it a "`follows:` chain walk"; `docs/design/threads.md:7-12` calls the same
object a **thread** and explains it is "not a container and not an item";
`blocked.py` produces `blocked_chains`; `{{cascade}}` is a third, unrelated
"chain" that renders a walk (`docs/blocks.md:64`); and `threads.md:448` uses
**heads** and **tips** in one sentence — "all reachable heads contribute their
tips" — for what §1.4 of that document calls tips. `docs/blocks.md:124-130` is
the model for how to do this the other way: it explains, in the vocabulary
itself, why `{{tree}}` has no `via=` — "it would replace it with a cascade
wearing a hat".

**D3 — "a way to group items": board, workspace, group, section, tag, and
`{{tree}}`.** Six mechanisms, five words, no single page that says which to
reach for. `board` is "the first path segment under `items/` unless the item
says otherwise" (`vocabulary.py:89`), `workspace` is registered (`:93`),
`group` is an item type (`v3:234`), `section` is both a YAML list-file heading
and a block parameter (`vocabulary.py:101`), `tag` is free-form (`v3:99`), and
`{{tree}}` nests by path. `group` in particular is easy to reach for when the
right answer is a tag, since its own definition is "A named collection of
items".

**D4 — "no longer in play": retired, superseded, obsolete, eliminated,
rebutted, on_hold.** Six different words for the same authoring act across six
types — `retired` (requirement `:137`, bound `:156`), `superseded` (decision
`:174`), `obsolete` (component `:216`), `eliminated` (option, preset `:37`),
`rebutted` (claim, preset `:51`), and `on_hold` (decision `:174`) which
overlaps `blocked_by` (`:122`) as the way to say "stuck". Each word is right
for its type in isolation; together they mean an author cannot ask "what is
dead?" in one word, and cannot learn one type's lifecycle and transfer it.

**D5 — "index": the command, the block, items.json, and index.html.**
`refdes index` (`cli.py:1333`, "print items.json to stdout without rendering
the site"), `{{index}}` (`blocks.py:474`), "the index" meaning items.json
(`docs/cli-reference.md:193`), and the site's `index.html`. Four referents,
one word, and two of them are things a user types.

**D6 — "check": the command, the field, the severity, the gate rule, and the
citation verifier.** `refdes check` (`cli.py:1269`), `checks:` on decision
(`v3:179`) and component (`:218`), `check_severity` (`:171`, preset `:34`),
`info_check_failures` (`model.py:63`), and `citations.verify()`
(`src/refdes/citations.py:490`). "check" as a noun means a numeric assertion
inside an item; as a verb it means running the validator; `check_severity`
means the diagnostic level of the first, and `info_check_failures` means the
gate rule about it.

**D7 — "verify": the verb, the status list, the backlink, the stage, the gate
rule, and the citation verifier.** `verifies` (`v3:116`), `verifying_statuses`
(`:196`), `verified_by` (the backlink, and the one that breaks the `_by`
convention — `docs/coverage.md:91` "`verified_by` — despite the `_by` suffix —
*is* the coverage-feeding form"), `verified` (coverage stage),
`unverified_requirements` (`model.py:62`), `citations.verify()`. Six surfaces,
one root word, and one of them is a documented exception to the naming rule
the root word is supposed to express.

**D8 — "identity": id, key, former_ids, surrogate key, display id, adopt.**
`id` is "Stable in people's sentences, not in the engine" (`vocabulary.py:58`)
and `key` is "The item's surrogate key: opaque, immutable, and the identity the
engine actually uses" (`:67`) — two identities per item, named `id` and `key`,
with `key` being the word that reads as the obvious one. `refdes keys adopt`
(`cli.py:1502`) then uses **adopt** for "transactionally adopt key-keyed
baselines and seals", where adopt means "migrate to", and `former_ids`
(`:72`) is a third identity notion again.

**D9 — "make a starter item": `refdes new` and `refdes stub-tests`.**
`new <type>` (`cli.py:1417`) "print a starter item for one type to stdout";
`stub-tests` (`:1558`) "generate starter test items for coverable items with no
verifying test". Two commands, two words for the same output, and only one of
them writes.

### 2.3 S2 — unclear connotation, recoverable but not from the word alone

**S2.1 — one concept, three words across three surfaces: `bound` / `limit` /
`constrained_by`.** The type is `bound` (`v3:146`), its payload field is
`limit:` (`:155`, "The numeric limit itself ... it is what makes this bound
checkable"), and the relation to it is `constrained_by` (`:115`). `bound` is
the right call — it was a deliberate rename with a documented reason, and
"upper/lower bound" is ordinary engineering English — but the vocabulary then
uses two other words for the same thing depending on which surface you are on.

**S2.2 — the type is `component`, everything about it is a part.** `part_number`
(`:214`, "Indexed into the parts page"), `refdes` (`:215`, "Reference
designators on the board — U14, R7 — where this **part** is placed"), status
(`:216`, "Where the **part** stands in this design"), and the project-wide
parts page (`docs/design/standard-library.md:1272` "## 10. Indexing part
numbers, and the parts page"). Not misleading — nobody is confused about what a
component is — but the tool has a parts page for its components, and an author
must learn that searching for "part" and searching for "component" are the same
activity with different words.

**S2.3 — `seal` is being redefined while keeping its name and its flag.**
`seal.py:3-5` "Entries are sealed the first time they are built; after that,
changing one is a build error"; `living-notes-plan.md:246-249` "the first
writable build no longer writes a hash lock, an edit is no longer a build
error ... Existing seal files keep being read and become **legacy-seal
markers**". And `--reseal` survives as a flag that does nothing for those
types, with a message explaining why (`living-notes-plan.md:561-563` and the
Q2 decision at `:598-600`: "accepted, prints 'sealing no longer applies to this
type; nothing was rewritten'"). Keeping the word across that reversal means `sealed` in an
error message from an older build and `sealed` in a marker from a newer one
mean different things, and the flag in users' muscle memory is the one that
means "make the bad thing go away".

**S2.4 — `audit` promises more than it reports.** `cli.py:1376` "list
suppressed fields, resealed entries, board/workspace moves," — five unrelated
sections including "Baselines" and "Since last revision" (`docs/cli-reference.md:341`
 onward). "Audit" is a fine word for a compliance pass, so readers expect a
verdict; what they get is a drift report. Compare `check`, which does give a
verdict.

**S2.5 — `refdes index` does not say what it is for.** Its help text is a
subtraction: "print items.json to stdout without rendering the site". The name
says index, the doc says "not build", and the actual purpose is stated only in
prose: "This exists for editor tooling and scripts that need the index on every
save" (`docs/cli-reference.md:193`).

**S2.6 — `init` and `new` are near-synonyms doing different things.** `init`
(`cli.py:1390`) "write a minimal refdes-project.yaml that points at the
standard"; `new <type>` (`:1417`) "print a starter item". One bootstraps a
project, the other prints an item to stdout. Neither name says which.

### 2.4 What is not a finding

Short, on purpose. `fold`, `tip`, `stamp`, `pin`, `redact`, `cascade`,
`{{tree}}`, `refines`, `derives_from`, `part_of`, `amends`, `addresses`,
`bound`, `calc`, `[[cite:]]`, `board`, `workspace`, `coverable` and the
active-voice link convention are all either defined at first use, or ordinary
engineering English, or both. Several are unfamiliar; none imports a competing
meaning; none is duplicated by a sibling word. §4 records them as checked.

## 3. Proposals

Each proposal is one line of old to new, what has to change, and what breaks.
They are grouped by cost, not by severity, because the cheapest fixes are the
ones worth doing first.

### 3.0 Cost tiers

- **T0 — free.** The word exists only in `docs/design/living-notes.md`,
  `living-notes-plan.md` or `threads.md`. No item file, no output, no code.
  `living-notes-plan.md:576` says so explicitly: a rename "touches the names on
disk and in output, not what was decided about them", and the eight ratified
  decisions stay intact.
- **T1 — cheap now, expensive later.** The word is in `hardware@3`, which is
  unreleased (`AGENTS.md` "Current state, briefly"). A rename touches
  `v3/base.yaml`, this repo's own items, tests and docs. The moment v3 ships,
  the same rename needs `refdes standard upgrade` and a migration for other
  people's projects. `hardware@1` and `hardware@2` are frozen either way —
  `constraint` stays `constraint` in v1 forever, which is correct.
- **T2 — moderate.** The word is in engine code and in output users read, so a
  rename touches function names, output fields and docs, but not the item-file
  format.
- **T3 — documentation only.** The word is fine or the fix is a table; no
  rename.

### 3.1 T0 — free today: the living-notes words

**P1 — `record` / `recorded` → `capture` / `captured`.** The event, the marker
and the command: "captured 2026-09-15T14:08Z when LOG-POWER-014 followed it",
"edited after captured", `refdes history capture <item>`.
*Why*: kills the head-on collision with the shipped `records:` verb
(`v3/base.yaml:118`) that `living-notes-plan.md:588` already names as a
confusion, and keeps every ratified decision about what the mechanism does.
*Alternatives considered*: `settle`/`settled` — already the coverage prose for a
satisfying decision (`v3:166` "A settled (accepted) decision"), so it moves the
collision instead of removing it; `freeze` — taken by key-freezing
(`adopt.py:64`), and P4 is renaming that anyway; `fix`/`fixed` — reads as
*repaired*; `seal` — reusing the word H5 is retiring is precisely the
meaning-flip S2.3 warns about.
*Cost*: T0. Two design docs and the names H1 through H9 will use. Nothing on
disk, because nothing is written yet.

**P2 — move the config key, not the store: project `history:` → `on_change:`.**
The key's own comment already says what it is — `docs/schema-reference.md:18`
`history:     { ... }   # default on_change mode` — and the item-level override
(`vocabulary.py:81`) is the same thing at item scope. Renaming both to
`on_change:` leaves `history` to mean exactly one thing: the store and its
command family, `refdes history capture` / `redact` / `migrate-seals`.
*Cost*: T1, small. `refdes-project.yaml` in this repo, the config parse and
default in `model.py`, `parse.py`'s reserved-key handling for the item-level
override, `schema-reference.md`, `change-tracking.md`, and tests. No item body
changes. Doing it before H1 means no project ever has to migrate.

**P3 — keep `snapshot`, and say what distinguishes it from `baseline`.**
`snapshot` is uncollided and names the stored object, which `capture` (the
event) does not. The pair that needs a sentence, not a rename, is
snapshot/baseline: a snapshot is one item's payload at a moment, a baseline is
the whole project's content hash at a stamped moment (`lifecycle.py`).
*Cost*: T3, one line in the H-plan glossary.

**P4 — `frozen` (key-freezing) → `anchored` / `anchor`.** Today `adopt.py:64`
reports `frozen_follows`, `:214` says "could not freeze N local follows
reference(s)", `build.py:421` discusses "unfrozen links", and `links.md` tells
authors a bare `follows:` "freezes" to its tip. None of it has anything to do
with immutability: it means the link stopped floating on a display id and now
names a key. *Anchor* says exactly that, is uncollided, and reads correctly in
the sentence the docs already have: "the first writable load anchors it to the
thread's current tip".
*Cost*: T2. Function names `plan_follows_freeze` / `freeze_follows`, the
`frozen_follows` output field, `links.md`, `cli-reference.md`, tests. The
composite `DISPLAY-ID@key` form itself does not change, so no item file and no
baseline format changes. Worth doing before the threads work ships, because
that work will add more uses of the word to the immutability cluster.

**P5 — a naming rule for H1 through H9, at zero cost.** `sealed` may only ever
refer to the pre-H5 mechanism and the `legacy-seal` markers; the new state is
`captured` and `edited after captured`. The decided behaviour of Q2 stays
exactly as ratified (`living-notes-plan.md:598-600`), including the `--reseal`
message; this constrains the *word*, not the mechanism. Without the rule, an
older build's error message and a newer build's marker will both say `sealed`
and mean opposite things (S2.3).

**P6 — keep `tasks:`, and make the noun always `task`.** `tasks:` on the merged
`log` type, `open_tasks` as the gate rule (`living-notes-plan.md:410-411`), and
`refdes work` as the query are three consistent derivations of one noun, not a
duplication. The one thing to avoid is letting `work`, `work item`, `to-do` and
`task` all appear for the same object; pick `task` for the data and `work` only
for the command that lists them.

### 3.2 T1 — cheap while `hardware@3` is unreleased

**P7 — citation sub-key `vendor:` → `keep:`.** "keep a copy of the bytes" is
what the boolean does (`docs/markdown.md:380-383`), and `keep` does not already
mean the manufacturer to the person writing a BOM. *Alternatives considered*:
`local:` — collides with "local citation", which is what the docs already call a
path-on-disk citation (`markdown.md:280`); `cache:` — implies disposable, and
these bytes are provenance; `copy:` — acceptable, vaguer. Also update
`refdes fetch` help ("optionally vendor") and the `fetch` description's
"vendors the bytes into `.refdes/vendor/`". The `.refdes/vendor/` directory name
can stay — it is not author-facing prose — or move with it; either is fine.
*Cost*: T1. `v3/base.yaml:104`, `citations.py` key parsing, `markdown.md`
examples, this repo's items that set `vendor: true`, tests. Any future project
gets `refdes revise` coverage for free, since that command already renames
fields from a mapping file.

**P8 — `equivalent` → `drop_in`, keep `alternate`.** The pair is the problem
(S1.2), and the fix is to put the unambiguous industry phrase on the safe side:
`drop_in` means interchangeable, full stop, and `alternate` keeps its weaker
meaning of "functionally close, check before substituting" (`v3:124-125`).
Self-inverse stays. The `required_when: {links: alternate}` rule on
`component.rationale` (`:217`) is unaffected.
*Cost*: T1. One link verb in `v3/base.yaml`, the parts-page rendering, `docs/links.md`,
tests. No shipped project. If v3 ships first, this becomes a standard upgrade
with a mapping, and every `equivalent:` line in someone's items needs rewriting.

**P9 — `on_change: log` → `on_change: timeline`.** The mode's whole meaning is
"this change belongs in the field-level timeline we have not built yet"
(`change-tracking.md:10-23`), and `timeline` names that without borrowing the
name of an item type. It also makes the current no-op honest: a reader can see
that `timeline` is the unimplemented one, rather than reading `log` and
assuming the `log` type is involved.
*Cost*: T1. Six field annotations in `v3/base.yaml` (`:97`, `:98`, `:101`,
`:177`, `:215`, `:241`), the mode constant in `model.py`, the tables in
`schema-reference.md:275` and `change-tracking.md:10-14`, tests. *Alternative*:
collapse `log` and `ignore` into one mode until the timeline exists — honest,
but it throws away authoring intent already recorded in six fields, and the
rename is smaller.

**P10 — preset type `claim` → `assertion`.** Removes the `claimed` stage /
`claim` type collision (S1.8) at its cheapest point: the debate preset is
opt-in, bundled with an unreleased standard, and nothing outside this repo can
be using it. `raises`, `bears_on`, `met_by`, `resolved_by` stay; the coverage
stage `claimed` stays, because stage names appear in computed output and gate
language.
*Cost*: T1. `presets/design-debate.yaml`, its tests, `docs/links.md` and
whatever preset prose exists.

**P11 — a question, not a rename: should `superseded` and `selected` exist as
statuses at all?** Both are facts the `supersedes` and `selects` links already
assert, and both verb definitions have to disclaim any effect (S1.9) precisely
because the state is stored twice and can disagree. The vocabulary-level fix is
to have one representation: compute "superseded" from `supersedes` and
"selected" from `selected_by`, and drop both from the enums. That is a design
change, not a word change, and it interacts with coverage — `selected` is
component's `satisfying_statuses` value (`v3:211`) — so it needs Jared's call.
The fallback if he says no: keep both, and add a build warning when a link and
a status disagree, so the vocabulary stops being the only thing telling the
author they mean the same thing.

### 3.3 T2 — engine and CLI words

**P12 — `refdes revise` → `refdes rename`, keeping `revise` as an alias.**
`revise` and `revision` are two letters apart and do unrelated things (S1.3),
and the command's own description is a rename: "Apply an explicit old->new
vocabulary mapping (type names, field names scoped per type, link verb names, id
prefixes) to every item file in one operation" (`cli.py:1514-1527`).
*Cost*: T2. Parser name, `cmd_revise`, `docs/cli-reference.md`, shell
completions, muscle memory — hence the alias, kept until the next minor.

**P13 — `refdes index` → `refdes items`, keeping `index` as an alias.** Four
referents for `index` (D5), and this is the one users type. The command prints
items; call it that. *Cost*: T2, same shape as P12, plus any editor tooling
built on it — `docs/cli-reference.md:193` says that is precisely who it is for,
so the alias matters more here than for P12.

**P14 — leave `audit`, `init`, `new`, `check`, `build`, `fetch`, `stub-tests`,
`keys adopt`, `calc-rewrite`, `former-ids`, `standard`, `schema`, `ls`, `id`,
`release`, `revision` alone.** Renaming CLI verbs is the most expensive
category of vocabulary change and buys the least. The two that are genuinely
vague — `audit` (S2.4) and `index` (S2.5) — get fixed by their help text and
first doc line, not by a new name. `release` and `revision` are load-bearing in
user habits and their definitions are already precise (`docs/lifecycle.md:5-11`).

### 3.4 T3 — the fixes renaming cannot make

Most of §2.2 is not misnaming; it is the absence of a page that says which word
to reach for. Five tables and one mechanism:

**P15 — a "which grouping?" table** for `board`, `workspace`, `group`,
`section`, `tag` and `{{tree}}` (D3), in `docs/concepts.md`, one row each: what
it is for, whether it is data or path, and whether it appears in coverage.

**P16 — a "which compliance verb?" table** for `refines`, `derives_from`,
`governed_by`, `constrained_by`, `satisfies` and preset `met_by` (S1.10) in
`docs/links.md`, with the two columns that actually decide it: does it feed
coverage, and does it change the thing or just point at it. `constrained_by`
is worth keeping despite the fossil — a new author never met `constraint`, so
the word only confuses people who read v1 — but the doc string should say
"must respect a bound" and nothing that sounds like `governed_by`.

**P17 — a "what does this word mean when a thing is finished with?" table** for
`retired`, `superseded`, `obsolete`, `eliminated`, `rebutted` and `on_hold`
(D4). Do not unify them: each is right for its type, and a single `retired`
across six types would lose the difference between a part that was never chosen
and a decision that was reversed. Document them as a set instead, and note that
`on_hold` and `blocked_by` are two ways to say stuck.

**P18 — one sentence for component versus part** (S2.2): the type is
`component`, the world calls it a part, and the parts page is the components
page. Put it in `docs/concepts.md` where `component` first appears.

**P19 — restate the `_by` rule so it has no exception.** `docs/coverage.md:64-91`
makes a good rule and then flags `verified_by` as breaking it. The rule authors
can actually use is: *the suffix never tells you whether a link feeds coverage;
the type's `satisfying_statuses` and `verifying_statuses` do.* That is true for
every verb including `verified_by`, and it removes the one exception from a rule
whose whole value is being automatic.

**P20 — put disambiguation in the standard, not in prose.** `vocabulary.py`
already renders every type, field and verb onto a generated vocabulary page
(`vocabulary.py:12-14`: `vocabulary.html` and `docs/vocabulary.md`), from the
same `doc:` strings quoted throughout §1. Add one optional sibling key — say
`not_to_be_confused_with:` — rendered as a fact line by `_facts()`
(`vocabulary.py:387`) and `_term_html()` (`:365`), and use it for exactly the
pairs in this review: `alternate`/`drop_in`, `records:`/`capture`,
`log`-the-type/`timeline`, `claimed`/`assertion`, `bound`/`limit`.
*Cost*: small engine change, no format change for projects that do not use it.
The value is structural: a rename proposed later has one place to look for what
the word was for, and the page stops being a list of definitions that happen to
sit next to each other.

**P21 — a three-question rule for any new word entering a standard.** (1) Does
this word already mean something else in refdes? grep the standards, `parse.py`,
`vocabulary.py`, `cli.py`. (2) Does it mean something else to a hardware
engineer, in a BOM, or in a datasheet? (3) If two words name adjacent ideas, is
the difference visible in the names, or only in the doc strings? The
`constraint`/`requirement` rename, the `records:` confusion at
`living-notes-plan.md:588`, and S1.1 through S1.5 in this review are all
failures of question one or two, caught after the fact each time.

### 3.5 Order of work

1. P1, P5, P6 — free, and they must happen before H1 writes any of these names
   to disk.
2. P2 — free-ish now, a migration later; it also unblocks P1's `refdes history`
   naming.
3. P7, P8, P9, P10 — do them in the same pass as any other v3 change, before
   v3 ships. After that they are standard upgrades.
4. P4, P12, P13 — engine and CLI, with aliases; schedule whenever, but P4 gets
   more expensive the more threads work lands.
5. P15 through P20 — documentation, useful immediately, no dependencies.
6. P11 — needs a decision from Jared before anyone writes code.

### 3.6 Explicitly not proposed

- **Renaming `bound`.** It was a deliberate, documented rename with a working
  reason (`v2/base.yaml:21-24`), and upper/lower bound is ordinary engineering
  English. The `limit`/`constrained_by` drift around it is fixed by P16, not by
  another rename.
- **Unifying the six dead-words** (D4). See P17.
- **Renaming `fold`, `tip`, `thread`, `cascade`, `{{tree}}`, `stamp`, `pin`,
  `redact`, `refines`, `derives_from`, `part_of`, `amends`, `addresses`,
  `board`, `workspace`, `coverable`, `calc`, `[[cite:]]`.** Unfamiliar, not
  wrong; each is defined where it is used; none imports a competing meaning.
- **Renaming `seal` to something new.** H5 already retires the mechanism; the
  word stays only as the name of the legacy files, which is what P5 pins down.
- **Renaming `constrained_by`.** See P16 — the fossil costs a doc line, a rename
costs every item file that uses the verb.

## 4. Checked and fine

Terms that were read, examined against the two questions in §2, and found
sound. This list is the other half of the review: it is what tells the next
person that the absence of a finding here was a decision and not an oversight.

### 4.1 Terms checked and kept

**Link verbs.** `satisfies`, `verifies`, `addresses`, `refines`,
`derives_from`, `part_of`, `amends` — each names one action, the doc string
says who may author it and what it does to coverage, and none has a sibling
word for the same job. `governed_by` is the weakest of them only because it
shares a page with three near-neighbours, which is P16's problem rather than
its own.

**The active-voice convention** (`docs/coverage.md:64-91`) — a semantic
property readable from the shape of the word, which is rare and worth keeping.
P19 removes its one exception from the prose.

**Coverage machinery.** `coverable`, `coverable_statuses`,
`satisfying_statuses`, `verifying_statuses`, `check_severity` — four switches
that say exactly what they include, and `check_severity`'s comment
(`model.py:230-235`) explains why `option` is INFO and `decision` is ERROR.
The five stage names are good; `claimed` is the only one with a naming problem,
and that is its collision with the preset type (S1.8, P10), not the word.

**Nouns a hardware engineer already owns, used correctly.** `refdes` as
reference designator (`v3:215` "U14, R7"), `part_number`, `calc`,
`[[cite:]]`, `board`, `limit`, `pin` (a hash-pinned reference — the right word,
and `docs/markdown.md:380-383` draws the pin/vendor line cleanly even though
`vendor` itself is P7's problem).

**Words that are unfamiliar and better than the obvious alternative.** `fold`
for combining a thread's per-field values by walking back from the tip —
precise, and `threads.md:388-393` defends it as correct. `tip` for the live end
of a thread. `stamp` for writing a baseline. `redact` for the destructive,
acknowledged removal in `living-notes.md:329`, which is exactly the word for it.
`{{tree}}` and `{{cascade}}` — two words for two different walks, and
`docs/blocks.md:124-130` explains in the vocabulary itself why the tree has no
`via=`: "it would replace it with a cascade wearing a hat". That is the tone
the rest of this vocabulary should aim for.

**Already renamed, correctly.** `constraint` → `bound` in v2, with the reason
recorded in the standard's own header (`v2/base.yaml:21-24`), and v1 left
frozen at `constraint` forever. That is the model for every rename proposed
above: change the name where it is cheap, keep the old name where it is honest,
and write down why both times.

### 4.2 What this review did not cover

- **Config vocabulary from the other design docs.** `extends.md` and
  `calc-sources.md` are coining words for layering and value sources
  (`extends`, overlay, source) and their decisions were ratified on 2026-09-19
  as this review was running. They deserve the same two questions, and they are
  still unshipped, so the answer is cheap to get.
- **Error and diagnostic message wording.** The vocabulary of what the tool
  says when it fails is a large surface and none of it was examined here.
- **Rendered site strings** — template headings, page titles, the parts page.
  Only `docs/` and `src/refdes/` definitions were read.
- **`hardware@1` and `hardware@2` names as candidates for change.** They were
  read for the inventory and compared against v3; they are frozen and nothing
  here proposes touching them.
- **`docs/design/backlog.md`.** It is a large term-coining document in its own
  right and was read only where §1 cited it.

The one structural thing worth saying about the healthy part of the vocabulary
is `docs/coverage.md:64-91`: the rule that coverage claims are authored in
active voice and everything else is `*_by` is a genuinely good piece of
vocabulary design — it makes a semantic property readable from the word — and
it has exactly one exception, `verified_by`, which the doc itself flags as an
exception (`:91`). A rule with one exception is a rule authors will not learn.
