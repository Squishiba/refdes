# Vocabulary

Every term a refdes schema resolves to, defined in one place: **item types**,
**link verbs**, **field sets**, and the **engine-reserved keys** — the ones
an item carries whether the project declared them or not.

The page below is generated from the standard this repo pins, and a built
site carries the same page as its own `vocabulary.html`, generated from its
own resolved schema: base standard, then any presets, then the project's
overlay. So the page always says what *this* project's vocabulary actually
is — a preset that is not enabled is not on the page, and a type a project
adds of its own is.

Each entry gives the term's definition (its `doc:` key), its scope, where it
points and what points at it, and its fields with their definitions. Two
conventions are worth knowing:

- **A term with no definition says so.** `doc:` is optional on project
  terms — nothing is required to define itself — so an overlay type that
  skips it appears with "No definition" rather than being left off the page.
  The bundled standard defines its terms; a project's own types are the
  project's business.
- **Engine-reserved keys are defined in code, not YAML.** `id`, `type`,
  `key`, `body`, `history` and the rest are not author-declared, so their
  definitions live in `refdes/vocabulary.py` — the one place they can be
  written once and cited from the page.

The syntax for declaring any of it is in the
[schema reference](schema-reference.md); what the built site does with the
vocabulary is in [output](output.md#the-vocabulary-page).

<!-- BEGIN GENERATED vocabulary -->
Every term below is what the resolved **hardware@3** schema in this repo's `refdes-project.yaml` means today, written here by `python docs-site/gen_examples.py`. A built site renders the same structure as its own `vocabulary.html`, from its own resolved schema -- base standard, presets, and the project's overlay. Do not hand-edit this block: `tests/test_vocabulary_page.py` fails if it differs from what the generator produces today.

## Item types

### `bound`

A numeric limit the design must respect — a voltage, a current, a tolerance. Its limit field makes it checkable by other items' checks. Counts toward coverage while active.

- **Id prefix:** `BND`
- **Pointed at by:** `addresses` from `log`; `constrained_by` from `component`, `decision`; `derives_from` from `bound`; `governed_by` from `requirement`; `refines` from `bound`; `satisfies` from `component`, `decision`; `verifies` from `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `title` | An optional short label for tables and previews. The bound's content is the body, not this. | text | no |
| `limit` | The numeric limit itself, parsed as a quantity with a comparison — '>= 9 V', '<= 600 mA'. Required, and it is what makes this bound checkable by other items' checks. | limit | yes |
| `status` | Lifecycle of the bound. Only active bounds count toward coverage; draft and retired ones are excluded. | enum | no |
| `rationale` | Why this limit is what it is — the reasoning behind the number. | text | no |

### `component`

A part the design uses. A selected component closes coverage on what it satisfies, and it can carry its own checks against bounds. Equivalence and alternateness between components are claims made here, not facts from a parts database.

- **Id prefix:** `CMP`
- **Pointed at by:** `alternate` from `component`; `equivalent` from `component`; `selects` from `decision`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `citations` | External documents this item relies on. Each entry needs a path — an http(s) URL or a project-root-relative file — and may carry rev, page, section, part_number, vendor and an id for [[cite:]] references. | citations | no |
| `title` | What the component is, in one line. Required. | text | yes |
| `part_number` | The manufacturer part number. Indexed into the parts page, alongside part numbers cited inside citations entries. | text | no |
| `refdes` | Reference designators on the board — U14, R7 — where this part is placed. Kept out of the content hash. | list | no |
| `status` | Where the part stands in this design. Only a selected component counts as settled and closes coverage on what it satisfies. | enum | no |
| `rationale` | Why this part, or — when an alternate link is present — what makes that alternate not a drop-in. Required whenever an alternate link exists. | text | no |
| `checks` | Numeric checks: each entry compares a value from this item's calc block against a bound's limit, so a component can demonstrate compliance with a bound directly. | checks | no |

### `decision`

A design choice that was made — what was picked, why, and what it satisfies. A settled (accepted) decision closes coverage on what it satisfies; a failing check on a decision is an error.

- **Id prefix:** `DEC`
- **Pointed at by:** `records` from `log`; `supersedes` from `decision`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `citations` | External documents this item relies on. Each entry needs a path — an http(s) URL or a project-root-relative file — and may carry rev, page, section, part_number, vendor and an id for [[cite:]] references. | citations | no |
| `title` | What was decided, in one line. Required — every decision needs a label. | text | yes |
| `status` | Where the decision stands. Only an accepted decision counts as settled and closes coverage on what it satisfies. | enum | no |
| `rationale` | Why this decision, and why not the alternatives. Required when the decision is rejected — the reason a rejection happened is the point of recording it. | text | no |
| `date` | When the decision was made. Kept out of the content hash, so fixing a date never marks downstream items suspect. | date | no |
| `options` | The alternatives considered, as name / verdict / because entries. Rendered as the options-considered panel on the decision's page. | options | no |
| `checks` | Numeric checks: each entry compares a value from this item's calc block against a bound's limit. A failed check here is reported as an error. | checks | no |

### `group`

A named collection of items — 'the PCIe interface spec' — that names the collection without letting it stand in for its members. Members point here with part_of; a group never lists its members, never appears in coverage, and nothing may satisfy one.

- **Id prefix:** `GRP`
- **Pointed at by:** `part_of` from `bound`, `component`, `decision`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `title` | The name of the collection. Required — an unnamed group names nothing. Kept out of the content hash, so renaming a group never marks its members suspect. | text | yes |

### `log`

A dated entry in the design log — work done, questions raised, corrections. Entries are append-only: each is sealed on the first build where it has no errors, and after that editing it is a build error — corrections are new entries with amends.

- **Id prefix:** `LOG`
- **Pointed at by:** `amends` from `log`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `date` | When this entry was written. Required — an undated log entry cannot be ordered in time. | date | yes |
| `summary` | One-line account of what happened, shown in log listings above the body. | text | yes |
| `author` | Who wrote the entry. | person | no |

### `requirement`

Something the design must achieve, stated as one prose body. Counts toward coverage while active; a draft or retired requirement is left out of coverage entirely.

- **Id prefix:** `REQ`
- **Pointed at by:** `addresses` from `log`; `derives_from` from `bound`; `governed_by` from `requirement`; `refines` from `requirement`; `satisfies` from `component`, `decision`; `verifies` from `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `title` | An optional short label for tables and previews. The requirement's content is the body, not this. | text | no |
| `status` | Lifecycle of the requirement. Only active requirements count toward coverage; draft and retired ones are excluded. | enum | no |
| `rationale` | Why this requirement exists — the reasoning behind the statement, kept separate from the statement itself. | text | no |

### `test`

A verification item that proves a requirement or bound. Its verifies links count toward coverage when the test's status is passing.

- **Id prefix:** `TST`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `title` | What the test proves, in one line. Required. | text | yes |
| `status` | Result of the test. Only a passing test counts as having verified what it points at. | enum | no |

## Link verbs

### `addresses`

A log entry records work done on a requirement or bound. Counts as addressed coverage — someone has worked on it and written it up — without claiming it is met.

- **Points at:** `bound`, `requirement`
- **Inverse:** `addressed_by`
- **Declared on:** `log`

### `alternate`

This component is functionally close to that one but not a drop-in: check before substituting. Self-inverse, component-to-component, and the rationale explaining what differs is required.

- **Points at:** `component`
- **Inverse:** `alternate`
- **Declared on:** `component`

### `amends`

A log entry corrects an earlier log entry. Entries are append-only, so a correction is written as a new entry pointing back at this one rather than as an edit.

- **Points at:** `log`
- **Inverse:** `amended_by`
- **Declared on:** `log`

### `blocked_by`

Something is holding this decision up. Name only the immediate blocker; reports resolve the chain to its root. May point at an item of any type; a cycle is a build error.

- **Points at:** any type
- **Inverse:** `blocks`
- **Declared on:** `decision`

### `constrained_by`

A decision or component that must respect a bound. Traceability only — it does not close coverage on the bound; satisfies does.

- **Points at:** `bound`
- **Inverse:** `constrains`
- **Declared on:** `component`, `decision`

### `derives_from`

A bound whose value follows from a requirement or another bound — where the number came from, not a restatement of it.

- **Points at:** `bound`, `requirement`
- **Inverse:** `derived_by`
- **Declared on:** `bound`

### `equivalent`

This component is a drop-in second source for that one — interchangeable as claimed, no review needed. Self-inverse, and restricted to component-to-component.

- **Points at:** `component`
- **Inverse:** `equivalent`
- **Declared on:** `component`

### `governed_by`

This requirement must comply with a general rule stated elsewhere — another requirement or a bound — without being a narrower version of it. Traceability only; it never feeds coverage.

- **Points at:** `bound`, `requirement`
- **Inverse:** `governs`
- **Declared on:** `requirement`

### `part_of`

This item belongs to a group. Membership is always declared by the member, never by the group; contains is the computed backlink.

- **Points at:** `group`
- **Inverse:** `contains`
- **Declared on:** `bound`, `component`, `decision`, `requirement`, `test`

### `records`

A log entry records a decision — the design-log side of the decision's own recorded_by end of the same edge.

- **Points at:** `decision`
- **Inverse:** `recorded_by`
- **Declared on:** `decision`, `log`

### `refines`

A narrower, more detailed version of the same kind of statement: a requirement refining a requirement, or a bound refining a bound. Same category of thing, different altitude.

- **Points at:** `bound`, `requirement`
- **Inverse:** `refined_by`
- **Declared on:** `bound`, `requirement`

### `satisfies`

A decision or component claims to meet a requirement or bound. This is the link that closes coverage once the claiming item reaches a satisfying status.

- **Points at:** `bound`, `requirement`
- **Inverse:** `satisfied_by`
- **Declared on:** `component`, `decision`

### `selects`

A decision picks a component. The component's own status marks it selected; this link records which decision made the pick.

- **Points at:** `component`
- **Inverse:** `selected_by`
- **Declared on:** `decision`

### `supersedes`

This decision replaces an older one. The older decision keeps its history; moving its status to superseded is your edit, not something the link does by itself.

- **Points at:** `decision`
- **Inverse:** `superseded_by`
- **Declared on:** `decision`

### `verifies`

A test proves a requirement or bound. Counts toward coverage when the test's status is one of the type's verifying_statuses.

- **Points at:** `bound`, `requirement`
- **Inverse:** `verified_by`
- **Declared on:** `test`

## Field sets

### `citations`

_No definition._

- **Included by:** `component`, `decision`

| Field | Definition | Type | Required |
|---|---|---|---|
| `citations` | External documents this item relies on. Each entry needs a path — an http(s) URL or a project-root-relative file — and may carry rev, page, section, part_number, vendor and an id for [[cite:]] references. | citations | no |

### `provenance`

_No definition._

- **Included by:** `bound`, `component`, `decision`, `group`, `log`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |

### `stewardship`

_No definition._

- **Included by:** `bound`, `component`, `decision`, `group`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |

## Engine-reserved keys

### `id`

The item's display identifier, minted from its type prefix and the project's id width. Stable in people's sentences, not in the engine: a rename moves it, and `former_ids:` records where it went.

- **Scope:** every item; a type may not shadow it

### `type`

The item's item type -- the entry in `types:` that gives it a prefix, fields, and links.

- **Scope:** every item; a type may not shadow it

### `key`

The item's surrogate key: opaque, immutable, and the identity the engine actually uses. Nothing rewrites it, and links resolve through it rather than through a display id.

- **Scope:** every item; a type may not shadow it

### `former_ids`

Display ids this item used to have. Written by the engine when an id is re-minted, so old citations still resolve.

- **Scope:** every item; a type may not shadow it

### `body`

The item's prose, below the front matter. Its change policy comes from the type's `body:` setting; for types whose content is the statement itself it is the required field.

- **Scope:** every item; a type may not shadow it

### `history`

This item's change-policy override, in place of the project's `history: default`.

- **Scope:** every item; a type may not shadow it

### `prefix`

On a type: the id prefix its items carry. As an item key it is the engine's own, and a type that declares a field of this name takes it over.

- **Scope:** every item, unless its type declares a field of that name

### `board`

Which board an item belongs to -- the first path segment under `items/` unless the item says otherwise. Overridable by a type's own field.

- **Scope:** every item, unless its type declares a field of that name

### `workspace`

Which workspace an item belongs to, when the project registers them. Overridable by a type's own field.

- **Scope:** every item, unless its type declares a field of that name

### `defaults`

In a YAML list file: the type and field values every entry in that file inherits, before its own keys.

- **Scope:** a YAML list file, not an item

### `section`

In a YAML list file: the section heading its entries file under on the item's page; in a Markdown marker block, the section a generated block belongs to.

- **Scope:** a YAML list file, not an item
<!-- END GENERATED vocabulary -->
