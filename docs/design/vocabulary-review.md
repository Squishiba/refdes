# Vocabulary review — duplication and clarity

**Status: findings, no code changed.** Read-only pass over the words refdes
asks an author to learn. Nothing here renames anything; §4 proposes fixes and
names the migration cost of each. The goal this review is scored against is
the owner's, in his words: the vocabulary should be **intuitive**.

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

`docs/concepts.md:47-57` documents the same subject as "## The three notions
of 'done'" and lists **four** stages — `open`, `addressed`, `satisfied`,
`verified` — with no `claimed` row:

> "| `satisfied` | A decision claims to meet it | a **decision** `satisfies` it |"

The header count ("three"), the row count (four), and `coverage.md`'s five
disagree with each other in the two places a new author meets coverage.

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
| `seal` (kept, meaning changed) | `living-notes-plan.md:243-247` | "the first writable build no longer writes a hash lock, an edit is no longer a build error ... Existing seal files keep being read and become **legacy-seal markers**: 'recorded hash only; original content was not captured.'" |
| `lock` | `living-notes-plan.md:243` | "no longer writes a hash lock" — and `living-notes.md:94`, Jared's own word: "I've also been questioning the idea of 'locking' documents in the first place." |
| `task` / `tasks:` | `living-notes.md:378` | "Add an optional `tasks:` field to the merged `log` type, with stable task IDs and complete state" with `state: open # open \| done \| dropped` |
| `thread` | `threads.md:7-12` | "A **thread** is not a container and not an item: it is the connected chain of entries reachable by walking `follows:` backward and its computed inverse, `followed_by:`, forward." |
| `tip` | `threads.md:11-12`, `:448` | "answered by walking forward from any entry in the chain to its tip(s) and folding per field"; "all reachable heads contribute their tips, and a non-reconciled fork is" |
| `follows` / `followed_by` | `threads.md:6-8` | "An entry declares its predecessor with a link, `follows:`, written by the tool, not typed by the author." |
| `release` (gate sense) | `living-notes-plan.md:407` | "Adds. `open_tasks` (a release blocks while any thread tip carries an open author task) and `recorded_edits` (a release blocks while any item is edited after recorded). Both off by default, both enabled through the existing `release_gate:` overlay." |
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
engine and in `docs/design/threads.md`, and `docs/design-log.md:177` and
`docs/links.md:66` already describe them to users as if they were standard.

### 1.8 Coverage of the inventory

Every item type in all three bundled versions and the bundled preset (11
types), every link verb in all three (15 in v3, 13 in v1/v2, 4 preset), the 6
reserved plus 3 overridable front matter keys plus the 2 list-file keys, the 3
body block names plus `calc` and `[[cite:]]`, the 5 coverage stages and the 4
type-level coverage switches, the 24 CLI subcommands, the 3 diagnostic levels,
the 10 status enumerations, and the 16 living-notes/threads words named in the
brief. All were opened and read; the quotes above are copied, not recalled.
