# Vocabulary

Every term a refdes schema resolves to, defined in one place: **item types**,
**link verbs**, **sets**, and the **engine-reserved keys** — the ones
an item carries whether the project declared them or not.

The page below is generated from the standard this repo pins, and a built
site carries the same page as its own `vocabulary.html`, generated from its
own resolved schema: base standard, then any presets, then the project's
overlay. So the page always says what *this* project's vocabulary actually
is — a preset that is not enabled is not on the page, and a type a project
adds of its own is.

Each entry gives the term's definition (its `doc:` key), its scope, where it
points and what points at it, its fields with their definitions, and a
worked example of how it is actually written. Three conventions are worth
knowing:

- **A term with no definition says so.** `doc:` is optional on project
  terms — nothing is required to define itself — so an overlay type that
  skips it appears with "No definition" rather than being left off the page.
  The bundled standard defines its terms; a project's own types are the
  project's business.
- **Engine-reserved keys are defined in code, not YAML.** `id`, `type`,
  `key`, `body`, `history` and the rest are not author-declared, so their
  definitions live in `refdes/vocabulary.py` — the one place they can be
  written once and cited from the page.
- **Every example is schema-true.** The bundled standard's terms carry
  hand-written examples in `refdes/vocabulary.py` — real values from the
  standard and this repo's `items/` tree, never invented fields. A term
  the table does not cover (your overlay's type, a preset's verb) gets a
  minimal example generated from its own resolved facts, placeholders and
  all, so no entry is ever example-less.

The syntax for declaring any of it is in the
[schema reference](schema-reference.md); what the built site does with the
vocabulary is in [output](output.md#the-vocabulary-page).

<!-- BEGIN GENERATED vocabulary -->
Every term below is what the resolved **hardware@3** schema in this repo's `refdes-project.yaml` means today, written here by `python docs-site/gen_examples.py`. A built site renders the same structure as its own `vocabulary.html`, from its own resolved schema -- base standard, presets, and the project's overlay. Do not hand-edit this block: `tests/test_vocabulary_page.py` fails if it differs from what the generator produces today.

## Item types

### `bound`

A numeric limit the design must respect — a voltage, a current, a tolerance. Its limit field makes it checkable by other items' checks. Counts toward coverage while active.

- **Id prefix:** `BND`
- **Pointed at by:** `addresses` from `log`; `constrained_by` from `component`, `log`; `derives_from` from `bound`; `governed_by` from `requirement`; `refines` from `bound`; `satisfies` from `component`, `log`; `verifies` from `test`

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

**Example:**

```yaml
defaults:
  type: bound
  prefix: BND-THM
  status: active
items:
  - id: BND-THM-001
    body: Board power density
    limit: "<= 0.15 W/in^2"  # required -- what makes it checkable
    rationale: Natural convection only; the enclosure is sealed.
```

### `component`

A part the design uses. A selected component closes coverage on what it satisfies, and it can carry its own checks against bounds. Drop-in and alternate claims between components are made here, not facts from a parts database.

- **Id prefix:** `CMP`
- **Pointed at by:** `alternate` from `component`; `drop_in` from `component`; `selects` from `log`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `citations` | Sources this item relies on. Each entry names a path (an http(s) URL or project-root-relative file) or item (another item's id); document entries may carry rev, page, section, part_number, keep_copy and an id for [[cite:]] references. | citations | no |
| `title` | What the component is, in one line. Required. | text | yes |
| `part_number` | The manufacturer part number. Indexed into the parts page, alongside part numbers cited inside citations entries. | text | no |
| `refdes` | Reference designators on the board — U14, R7 — where this part is placed. Kept out of the content hash. | list | no |
| `status` | Where the part stands in this design. Only a selected component counts as settled and closes coverage on what it satisfies; a rejected one was considered and not chosen, and never satisfies. | enum | no |
| `rationale` | Why this part, or — when an alternate link is present — what makes that alternate not a drop-in. Required whenever an alternate link exists. | text | no |
| `checks` | Numeric checks: each entry compares a value from this item's calc block against a bound's limit, so a component can demonstrate compliance with a bound directly. | checks | no |

**Example:**

```yaml
defaults:
  type: component
  prefix: CMP-PWR
items:
  - id: CMP-PWR-001
    title: TPS62913 synchronous buck converter
    part_number: TPS62913
    status: selected
```

### `group`

A named collection of items — 'the PCIe interface spec' — that names the collection without letting it stand in for its members. Members point here with part_of; a group never lists its members, never appears in coverage, and nothing may satisfy one.

- **Id prefix:** `GRP`
- **Pointed at by:** `part_of` from `bound`, `component`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |
| `title` | The name of the collection. Required — an unnamed group names nothing. Kept out of the content hash, so renaming a group never marks its members suspect. | text | yes |

**Example:**

```yaml
defaults:
  type: group
  prefix: GRP-IO
items:
  - id: GRP-IO-001
    title: The digital IO interface spec
# A group never lists members: each member declares part_of: [GRP-IO-001].
```

### `log`

A design-log entry — narrative work or a verdict. Entries are append-only in the authoring sense: corrections are new entries. Captured history records earlier content; an edit after capture is a warning.

- **Id prefix:** `LOG`
- **Pointed at by:** `amends` from `log`; `follows` from `log`; `supersedes` from `log`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |
| `citations` | Sources this item relies on. Each entry names a path (an http(s) URL or project-root-relative file) or item (another item's id); document entries may carry rev, page, section, part_number, keep_copy and an id for [[cite:]] references. | citations | no |
| `date` | When this entry was written, if known. Older decisions may not have a date. | date | no |
| `summary` | One-line account of what happened, shown in log listings above the body. | text | yes |
| `author` | Who wrote the entry. | person | no |
| `status` | A verdict when this entry declares one. Accepted entries can close coverage on what they satisfy. | enum | no |
| `rationale` | Why this verdict was reached; required for a rejected verdict. | text | no |
| `options` | Alternatives considered for this verdict. | options | no |
| `checks` | Numeric checks against bounds; a failed check is an error. | checks | no |

**Example:**

```yaml
defaults:
  type: log
  prefix: LOG-A
items:
  - id: LOG-A-001
    date: 2026-02-18
    summary: Took delivery of the customer spec rev D.
    addresses: [REQ-PWR-001, REQ-PWR-002]
  - id: LOG-A-002
    summary: Chose the 3V3 rail regulator.
    status: accepted
    follows: [LOG-A-001]
    satisfies: [REQ-PWR-002]
```

### `requirement`

Something the design must achieve, stated as one prose body. Counts toward coverage while active; a draft or retired requirement is left out of coverage entirely.

- **Id prefix:** `REQ`
- **Pointed at by:** `addresses` from `log`; `derives_from` from `bound`; `governed_by` from `requirement`; `refines` from `requirement`; `satisfies` from `component`, `log`; `verifies` from `test`

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

**Example:**

```yaml
# items/requirements/power.yaml -- shared fields go in defaults:,
# and the statement itself is the body.
defaults:
  type: requirement
  prefix: REQ-PWR
  status: active
items:
  - id: REQ-PWR-001
    body: The unit shall operate from an input supply of 9 V to 36 V.
    source: Customer spec rev D, §3.1
```

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

**Example:**

```yaml
defaults:
  type: test
  prefix: TST-PWR
items:
  - id: TST-PWR-001
    title: Input range sweep
    status: passing  # only a passing test counts toward coverage
    body: Sweep the bench supply 9 V to 36 V in 1 V steps at full load.
    verifies: [REQ-PWR-001]
```

## Link verbs

### `addresses`

A log entry records work done on a requirement or bound. Counts as addressed coverage — someone has worked on it and written it up — without claiming it is met.

- **Points at:** `bound`, `requirement`
- **Inverse:** `addressed_by`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-A-001
  addresses: [REQ-PWR-001, REQ-PWR-002]
# Addressed coverage: worked on and written up, without claiming it is met.
```

### `alternate`

This component is functionally close to that one but not a drop-in: check before substituting. Self-inverse, component-to-component, and the rationale explaining what differs is required.

- **Points at:** `component`
- **Inverse:** `alternate`
- **Declared on:** `component`

**Example:**

```yaml
- id: CMP-PWR-002
  alternate: [CMP-PWR-001]
  rationale: Higher ESR at the output cap; verify ripple before swapping.
  # rationale is required whenever an alternate link is present
```

### `amends`

A log entry corrects an earlier log entry. Entries are append-only, so a correction is written as a new entry pointing back at this one rather than as an edit.

- **Points at:** `log`
- **Inverse:** `amended_by`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-A-006
  amends: [LOG-A-003]  # a correction is a new entry pointing back,
                       # never an edit to the sealed original
```

### `blocked_by`

Something is holding this entry up. Name only the immediate blocker; reports resolve the chain to its root. May point at an item of any type; a cycle is a build error.

- **Points at:** any type
- **Inverse:** `blocks`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-IO-005
  blocked_by: [LOG-IO-001]
# May point at an item of any type; name only the immediate blocker --
# reports resolve the chain to its root, and a cycle is a build error.
```

### `constrained_by`

A verdict log entry or component that must respect a bound. Traceability only — it does not close coverage on the bound; satisfies does.

- **Points at:** `bound`
- **Inverse:** `constrains`
- **Declared on:** `component`, `log`

**Example:**

```yaml
- id: LOG-PWR-001
  constrained_by: [BND-THM-001]
# Traceability only -- it does not close coverage on the bound; satisfies does.
```

### `derives_from`

A bound whose value follows from a requirement or another bound — where the number came from, not a restatement of it.

- **Points at:** `bound`, `requirement`
- **Inverse:** `derived_by`
- **Declared on:** `bound`

**Example:**

```yaml
- id: BND-THM-002
  body: Minimum converter efficiency
  limit: ">= 0.90"
  derives_from: [BND-THM-001]  # the number follows from the density bound
```

### `drop_in`

This component is a drop-in second source for that one — interchangeable as claimed, no review needed. Self-inverse, and restricted to component-to-component. For a part that is close but needs checking before it goes in a design, use alternate.

- **Points at:** `component`
- **Inverse:** `drop_in`
- **Declared on:** `component`

**Example:**

```yaml
- id: CMP-PWR-001
  drop_in: [CMP-PWR-002]  # self-inverse: CMP-PWR-002 gains the same edge,
                          # and no rationale is required
```

### `follows`

This log entry continues an earlier entry in the same thread.

- **Points at:** `log`
- **Inverse:** `followed_by`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-A-004
  summary: Recorded the release outcome.
  follows: [LOG-A-003]  # the earlier entry freezes here
```

### `governed_by`

This requirement must comply with a general rule stated elsewhere — another requirement or a bound — without being a narrower version of it. Traceability only; it never feeds coverage.

- **Points at:** `bound`, `requirement`
- **Inverse:** `governs`
- **Declared on:** `requirement`

**Example:**

```yaml
- id: REQ-DIO-003
  body: The main IO board shall provide isolated discrete inputs.
  governed_by: [REQ-DIO-001]  # must comply with its 26 V TVS rule
# Not a narrower version of REQ-DIO-001 -- a different fact that has
# to obey it. governs, the backlink, is computed.
```

### `part_of`

This item belongs to a group. Membership is always declared by the member, never by the group; contains is the computed backlink.

- **Points at:** `group`
- **Inverse:** `contains`
- **Declared on:** `bound`, `component`, `requirement`, `test`

**Example:**

```yaml
# Membership is always declared by the member, never by the group:
- id: REQ-DIO-003
  part_of: [GRP-IO-001]
# GRP-IO-001 shows contains: [REQ-DIO-003] as the computed backlink.
```

### `refines`

A narrower, more detailed version of the same kind of statement: a requirement refining a requirement, or a bound refining a bound. Same category of thing, different altitude.

- **Points at:** `bound`, `requirement`
- **Inverse:** `refined_by`
- **Declared on:** `bound`, `requirement`

**Example:**

```yaml
# REQ-PWR-003 is a narrower statement of the same kind as REQ-PWR-002.
- id: REQ-PWR-003
  body: Converter efficiency shall exceed 90 % at half load.
  refines: [REQ-PWR-002]
# REQ-PWR-002 shows refined_by: [REQ-PWR-003] without saying so itself.
```

### `satisfies`

A verdict log entry or component claims to meet a requirement or bound. This closes coverage once the claiming item reaches a satisfying status.

- **Points at:** `bound`, `requirement`
- **Inverse:** `satisfied_by`
- **Declared on:** `component`, `log`

**Example:**

```yaml
# Declared from the verdict log entry (or component):
- id: LOG-PWR-001
  satisfies: [REQ-PWR-002, REQ-PWR-003]
# The requirements gain satisfied_by: [LOG-PWR-001]; once the entry
# reaches status: accepted, that closes their coverage.
```

### `selects`

A verdict selects a component. The component's own status marks it selected; this link records which entry made the pick. A build warns when either half is missing and the other is not.

- **Points at:** `component`
- **Inverse:** `selected_by`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-PWR-001
  selects: [CMP-PWR-001]
# The part's own status: selected is the other half of the same claim;
# the build warns when one exists and the other does not.
```

### `supersedes`

This verdict replaces an older one. The older entry keeps its history; moving its status to superseded is your edit, not something the link does by itself. A build warns when the link and target status disagree.

- **Points at:** `log`
- **Inverse:** `superseded_by`
- **Declared on:** `log`

**Example:**

```yaml
- id: LOG-PWR-002
  supersedes: [LOG-PWR-001]
# The link does not move LOG-PWR-001's status -- set status: superseded
# there yourself, or the build warns that the two halves disagree.
```

### `verifies`

A test proves a requirement or bound. Counts toward coverage when the test's status is one of the type's verifying_statuses.

- **Points at:** `bound`, `requirement`
- **Inverse:** `verified_by`
- **Declared on:** `test`

**Example:**

```yaml
# Declared from the test:
- id: TST-PWR-001
  verifies: [REQ-PWR-001]
# Or from the requirement, under the inverse name -- same edge either way:
- id: REQ-PWR-001
  verified_by: [TST-PWR-001]
```

## Sets

### `citations`

_No definition._

- **Included by:** `component`, `log`

| Field | Definition | Type | Required |
|---|---|---|---|
| `citations` | Sources this item relies on. Each entry names a path (an http(s) URL or project-root-relative file) or item (another item's id); document entries may carry rev, page, section, part_number, keep_copy and an id for [[cite:]] references. | citations | no |

**Example:**

```yaml
types:
  component:
    include: [citations]
- id: CMP-PWR-001
  citations:
    - path: https://www.ti.com/lit/ds/symlink/tps62913.pdf
      rev: E
      page: "14"
      keep_copy: false
```

### `claims`

_No definition._

- **Included by:** `component`, `log`

**Example:**

```yaml
types:
  log:
    include: [claims]
- id: LOG-PWR-001
  satisfies: [REQ-PWR-001]
  constrained_by: [BND-PWR-001]
```

### `grouped`

_No definition._

- **Included by:** `bound`, `component`, `requirement`, `test`

**Example:**

```yaml
types:
  requirement:
    include: [grouped]
- id: REQ-IO-001
  part_of: [GRP-IO-001]
  # membership is declared by the member, never by the group
```

### `invalidate_body`

_No definition._

- **Included by:** `component`, `log`, `test`

**Example:**

```yaml
types:
  log:
    include: [invalidate_body]
# editing such a body marks downstream items suspect
```

### `named_title`

_No definition._

- **Included by:** `component`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `title` | What this item is, in one line. Required. | text | yes |

**Example:**

```yaml
types:
  test:
    include: [named_title]
- id: TST-PWR-001
  title: Regulator choice
  # title is required on test and component
```

### `provenance`

_No definition._

- **Included by:** `bound`, `component`, `group`, `log`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `source` | Where the item's content came from — a spec section, a datasheet, a conversation. Kept out of the content hash, so correcting it never marks downstream items suspect. | text | no |
| `note` | A free-text remark about the item's provenance, kept beside the item instead of inside its body. Kept out of the content hash. | text | no |
| `tags` | Free-form labels for grouping and finding items; free-text search matches tags as well as titles. Kept out of the content hash. | list | no |

**Example:**

```yaml
# A type pulls the set in, and its items then carry its fields:
types:
  requirement:
    include: [provenance]
# An item of that type:
- id: REQ-PWR-001
  source: Customer spec rev D, §3.1
  tags: [power]
```

### `statement_title`

_No definition._

- **Included by:** `bound`, `requirement`

| Field | Definition | Type | Required |
|---|---|---|---|
| `title` | An optional short label for tables and previews. The item's content is the body, not this. | text | no |

**Example:**

```yaml
types:
  requirement:
    include: [statement_title]
    fields:
      # a doc-only patch keeps the type's own wording for the field
      title: { doc: "An optional short label for tables and previews." }
- id: REQ-PWR-001
  title: 12 V rail tolerance
  body: The 12 V rail must stay within 5% under load.
```

### `stewardship`

_No definition._

- **Included by:** `bound`, `component`, `group`, `requirement`, `test`

| Field | Definition | Type | Required |
|---|---|---|---|
| `owner` | The person responsible for this item — who a question about it goes to. Kept out of the content hash, so ownership changes never invalidate downstream work. | person | no |
| `last_reviewed` | The date this item was last reviewed. Bookkeeping only: kept out of the content hash. | date | no |

**Example:**

```yaml
types:
  requirement:
    include: [stewardship]
- id: REQ-PWR-001
  owner: J. Bin
  last_reviewed: 2026-03-02
```

## Engine-reserved keys

### `id`

The item's display identifier, minted from its type prefix and the project's id width. Stable in people's sentences, not in the engine: a rename moves it, and `former_ids:` records where it went.

- **Scope:** every item; a type may not shadow it

**Example:**

```yaml
- id: REQ-PWR-001  # minted from the type prefix and the id width;
                   # leave it out and `refdes id` writes one back
```

### `type`

The item's item type -- the entry in `types:` that gives it a prefix, fields, and links.

- **Scope:** every item; a type may not shadow it

**Example:**

```yaml
# Usually stated once per file, under defaults:
defaults:
  type: requirement
# An item may also state its own, or a Markdown item carries it in
# the front matter:
---
id: LOG-PWR-001
type: log
---
```

### `key`

The item's surrogate key: opaque, immutable, and the identity the engine actually uses. Nothing rewrites it, and links resolve through it rather than through a display id.

- **Scope:** every item; a type may not shadow it

**Example:**

```yaml
- key: 1zn5skrv6k3  # written back by the tool on the first writable
  id: REQ-PWR-001   # load; never hand-edit it, and links resolve through it
```

### `former_ids`

Display ids this item used to have. Written by the engine when an id is re-minted, so old citations still resolve.

- **Scope:** every item; a type may not shadow it

**Example:**

```yaml
- id: BND-THM-001
  former_ids: [CON-THM-001]  # written when an id is re-minted, so old
                             # CON-THM-001 citations keep resolving
```

### `body`

The item's prose, below the front matter. Its change policy comes from the type's `body:` setting; for types whose content is the statement itself it is the required field.

- **Scope:** every item; a type may not shadow it

**Example:**

```yaml
- id: REQ-PWR-001
  body: The unit shall operate from an input supply of 9 V to 36 V.
# In a Markdown item, body is the prose below the front matter instead.
```

### `on_change`

This item's change-policy override, in place of the project's `on_change: default`. A type that declares a field of this name takes it over.

- **Scope:** every item, unless its type declares a field of that name

**Example:**

```yaml
- id: REQ-PWR-004
  on_change:
    fields:
      owner: ignore
    reason: Owner rotates weekly during bring-up; not a meaningful change.
```

### `prefix`

On a type: the id prefix its items carry. As an item key it is the engine's own, and a type that declares a field of this name takes it over.

- **Scope:** every item, unless its type declares a field of that name

**Example:**

```yaml
defaults:
  type: requirement
  prefix: REQ-PWR  # items in this file mint ids like REQ-PWR-001;
                   # a type declaring a field of this name takes it over
```

### `board`

Which board an item belongs to -- the first path segment under `items/` unless the item says otherwise. Overridable by a type's own field.

- **Scope:** every item, unless its type declares a field of that name

**Example:**

```yaml
# The first path segment under items/ is the board; state it only
# when the folder is not a registered board:
defaults:
  board: board-a  # folder predates the boards: registry
```

### `workspace`

Which workspace an item belongs to, when the project registers them. Overridable by a type's own field.

- **Scope:** every item, unless its type declares a field of that name

**Example:**

```yaml
# Only when the project registers workspaces: in its settings file:
items:
  - id: IFC-CAN-001
    workspace: platform  # lives in a folder that predates the registry
```

### `defaults`

In a YAML list file: the type and field values every entry in that file inherits, before its own keys.

- **Scope:** a YAML list file, not an item

**Example:**

```yaml
defaults:
  type: requirement
  status: active
items:
  - id: REQ-PWR-001  # inherits type and status, then its own keys apply
    body: The unit shall operate from an input supply of 9 V to 36 V.
```

### `section`

In a YAML list file: the section heading its entries file under on the item's page; in a Markdown marker block, the section a generated block belongs to.

- **Scope:** a YAML list file, not an item

**Example:**

```yaml
items:
  - section: requirement  # every item after it is a requirement,
  - id: REQ-IO-AI-001     # until the next section marker
    body: The AI accelerator rail shall regulate to 0.85 V ±3%.
```
<!-- END GENERATED vocabulary -->
