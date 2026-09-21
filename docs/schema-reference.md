# Schema reference

Every key in `refdes-project.yaml` — the project marker, and the home of
every project setting. The three schema keys (`types:`, `link_types:`,
`sets:`) are the one exception: they are the project's own schema
overlay, and they live in the optional `refdes-schema.yaml`, which most
projects never have — a project taking its whole vocabulary from a bundled
standard needs only the settings file. A project is any folder containing
`refdes-project.yaml`; commands search upward from the current directory to
find it. Each section below says which file its key belongs in.

## Top level

```yaml
# refdes-project.yaml — every project setting
site:        { ... }   # title, output directory, version
id:          { ... }   # ID width and ledger location
history:     { ... }   # default on_change mode
coverage:    { ... }   # coverage presentation (grouping subtypes under their parent)
date_format:  YYYY-MM-DD  # log-date order; default shown
units:       { ... }   # preferred display units
standard:    { ... }   # the bundled standard dictionary, or "none"
imports:     [ ... ]   # other projects to read
boards:      { ... }   # opt-in board registry
workspaces:  { ... }   # opt-in workspace registry, one level above boards

# refdes-schema.yaml — optional, only when the project declares its own schema
sets:  { ... }   # reusable type-spec fragments (fields, links, body), include:d by a type
link_types:  { ... }   # relationships and their inverses
types:       { ... }   # item types
```

`standard:` (or its absence) determines where `link_types:`/`types:` start
from before the project's own `refdes-schema.yaml` blocks are applied on top —
see [the standard library](standard-library.md) for the full picture.
Everything below describes the merged result, regardless of which file each
piece came from.

---

## `site`

```yaml
site:
  title: "Example Board — Design Reference"
  out: _site
  version: "2026.3"
```

| Key | Default | Purpose |
|---|---|---|
| `title` | `Design Reference` | Site title and nav brand |
| `out` | `_site` | Output directory, relative to the project root |
| `pages` | `pages` | Directory of narrative [pages](pages.md) |
| `nav` | *(empty)* | Explicit page order in the sidebar, by slug |
| `version` | *(empty)* | Written into `items.json`; checked by downstream [imports](multi-board.md) |
| `assets` | *(empty)* | Directories copied verbatim into `assets/`, no reference needed — see [images and other local files](markdown.md#images-and-other-local-files) |
| `theme` | `default` | Built-in theme by name. An unknown name is a build error naming the themes that exist, never a silent fallback |
| `tokens` | *(empty)* | `--token: value` overrides merged over the theme — see [theming](output.md#theming) |

### `site.theme` and `site.tokens`

```yaml
site:
  theme: default
  tokens:
    --accent: "#b3541e"
    --sans: Georgia, serif
    --radius-pill: 999px
```

A theme is a flat list of design-token pairs and nothing else. Every name must
be a token the built-in stylesheet declares (`--bg`, `--fg`, `--accent`,
`--text-base`, `--space-4`, `--radius-md`, …); a mistyped name is an error with
a *Did you mean* hint, because CSS's own answer to an undefined custom property
is silence and a half-themed site. Values must be plain CSS values: `;`, `{`,
`}`, `<`, `@import`, `url(`, a comment opener, or an escape is refused, so a
theme can never become a rule, a stylesheet, or a network fetch.

`site.tokens:` is **merged over** the theme, and the theme over the built-in
default: a token you do not mention keeps its default value rather than going
unset. `--good`, `--bad`, `--warn` and `--claim` cannot be set at all yet —
they are verdict colours, and the check that a reassignment keeps that meaning
is finding 34 step 2b.

The overrides are emitted as a generated `assets/theme.css` linked after
`assets/style.css`; see [theming](output.md#theming).

---

## `id`

```yaml
id:
  width: 3
  ledger: .refdes/ids.yaml
```

| Key | Default | Purpose |
|---|---|---|
| `width` | `3` | Zero-padding: `3` gives `REQ-PWR-004` |
| `ledger` | `.refdes/ids.yaml` | Where burned numbers are recorded |

Set `width` generously at the start; changing it later breaks IDs or leaves them
inconsistent. See [IDs](ids.md).

---

## `history`

```yaml
history:
  default: invalidate
```

The `on_change` mode for any field that does not declare its own. One of
`invalidate`, `log`, `ignore`. See [change tracking](change-tracking.md).

Only `invalidate` has any effect today: it is the sole mode the content hash
checks for. `log` is reserved for a future per-field history layer and currently
behaves exactly like `ignore` -- choosing between them is not yet a meaningful
decision.

This entire surface only matters to a project under version control. Without a
VCS there is no history layer to feed, and `history:` reduces to nothing more
than a hash-exclusion list.

---

## `coverage`

```yaml
coverage:
  group_inherited: true   # the default
```

`group_inherited` (default `true`, for every project) controls how a subtype
of an [`extends:`](#extends) parent is presented: the coverage page badges its
rows with the subtype's name (`(bound)`) and sorts them with the parent's, the
summary counts them in the parent's row, and `{{index type=<parent>}}` lists them
under the parent. `false` keeps each type separate. Presentation only -- it
never changes which items take part in coverage.

---

## `date_format`

```yaml
date_format: MM/DD/YYYY
```

Sets the project-wide order of the `YYYY`, `MM`, and `DD` placeholders used by
fields whose schema type is `date`. The default is strict ISO order,
`YYYY-MM-DD`. Each placeholder must appear exactly once.

The separator written here is canonical in build errors, but input may use
`-`, `/`, or `.` interchangeably: with `MM/DD/YYYY`, the values `01/25/2026`,
`01-25-2026`, and `01.25.2026` are equivalent. A value with the wrong
placeholder order, missing or extra separators, or an impossible calendar date
is a build error naming the expected format.

---

## `units`

```yaml
units:
  preferred: [W, V, A, ohm, F, H, Hz, J, N, Pa, K, s, m, g]
```

Named units that derived results may collapse into, so `volt*ampere` displays as
`W`. **Only single-symbol units belong here** — compound entries like `W/m**2` are
ignored. A unit you write yourself is never rewritten. See [math](math.md).

---

## `standard`

```yaml
standard:
  base: hardware
  version: 1
  presets: []
```

Points at the bundled standard dictionary instead of hand-declaring
`link_types:`/`types:`/`sets:` from scratch. Resolved fresh, from the
installed `refdes` package, on every load — `refdes-project.yaml` never
contains a copy of what the standard declares, only the pointer to it. Absent
entirely, or the string `standard: none`, means no standard: every type,
link, and set comes only from the project's own `refdes-schema.yaml`,
exactly like every project before this existed.

| Key | Required | Purpose |
|---|---|---|
| `base` | yes | Which bundled dictionary — `hardware` today |
| `version` | yes | A pinned integer, e.g. `1` — never the string `"latest"` |
| `presets` | no, defaults to `[]` | Optional bundled extensions layered on top, e.g. `[design-debate]` |

The project's own `link_types:`/`types:`/`sets:` — written in
`refdes-schema.yaml` — are merged on top of the
resolved standard, not replacing it — see [the standard
library](standard-library.md#overriding-and-extending) for the merge rules
(add a field, remove one, redeclare an enum, add or remove a whole type).

---

## `sets`

```yaml
# refdes-schema.yaml
sets:
  provenance:
    fields:
      source: { type: text, on_change: log }
      tags:   { type: list, on_change: ignore }
  tracked:
    links:
      part_of: [group]
    body: { required: true }
```

Named, reusable fragments of a type's own spec, `include:`d by one or more
types instead of being retyped on each. A set carries exactly three keys —
`fields:`, `links:` and `body:` — and nothing else: `include:`, `coverable:`,
`prefix:` and the rest are a type's declarations, not a set's. Including a
set merges in list order (a later set wins on a name collision), and the
type's own declaration merges last and wins over everything it includes.
Two included sets declaring the same link verb or `body:` with different
specs is a load error naming both sets. An include whose every contribution
is shadowed warns in the build output.

A type may override an included field with a spec whose **only** key is
`doc:` — a patch that keeps the set's `type`, `required`, `choices`,
`default` and `on_change` while replacing just the definition. Any other
override must be a full field spec carrying `type:`. The standard is
authored this way internally (`provenance`, `stewardship`, `citations`);
a project declares its own in `refdes-schema.yaml` for structure repeated
across its own custom types. See [the standard
library](standard-library.md#sets-and-include) and
[docs/design/composition.md](design/composition.md) for the full merge rule.

---

## `link_types`

```yaml
# refdes-schema.yaml
link_types:
  satisfies:   { inverse: satisfied_by, label: "Satisfies" }
  verified_by: { inverse: verifies,     label: "Verified by" }
```

| Key | Default | Purpose |
|---|---|---|
| `inverse` | `<name>_by` | Name of the computed back-link |
| `label` | the link name | Heading shown on item pages |
| `trace` | `true` | Whether this link type participates in a `{{cascade}}` block's default walk (see [generated blocks](blocks.md)) |
| `doc` | not set | The verb's own definition — see [`doc`](#doc) |

Either end resolves to the same edge, so a type may declare `verifies` even though
`verified_by` is the name in `link_types`. See [links](links.md).

`trace: false` marks a link as describing process rather than "this item's
correctness rests on that one" — the bundled standard sets it on `amends`,
`records`, `supersedes`, and `addresses`. A `{{cascade}}` block with no
explicit `via=` follows every link type where `trace` is still `true`.

---

## `types`

```yaml
# refdes-schema.yaml
types:
  bound:
    prefix: BND
    label: Bound
    append_only: false
    preview: [status, title, limit]
    coverable: true
    coverable_statuses: [active]
    fields:
      title:  { type: text, on_change: invalidate }
      limit:  { type: limit, required: true, on_change: invalidate }
      status: { type: enum, choices: [draft, active, retired],
                default: draft, on_change: invalidate }
      owner:  { type: person, on_change: log }
    include: [provenance]
    links:
      refines:      [bound]
      derives_from: [requirement, bound]
    body: { on_change: invalidate, required: true }
```

| Key | Default | Purpose |
|---|---|---|
| `prefix` | first 3 letters, uppercased | ID prefix when a list file gives none |
| `label` | title-cased name | Display name |
| `append_only` | `false` | Seal items of this type after first build |
| `preview` | `[]` | Fields shown in hover previews and index columns |
| `fields` | `{}` | Legal fields |
| `extends` | not set | The one type this specializes; the type then writes only its delta. See [`extends`](#extends) |
| `include` | not set | Names of `sets:` entries merged into `fields:` before this type's own fields are applied |
| `links` | `{}` | Legal links, mapped to allowed target types |
| `body` | `on_change`: project default; `required`: `false` | `on_change` mode for the markdown body, and whether it must be non-empty (`required: true` — the bundled standard sets this on `requirement`/`bound`, hardware@3). Enforced as a **warning**, not a build-blocking error the way `required: true` is on an ordinary field — a stub can still exist while it's being drafted. |
| `satisfying_statuses` | not set — every `satisfies:` link counts | `status` values that count as settled; see [coverage](coverage.md#which-statuses-count-as-satisfying) |
| `check_severity` | `error` | Diagnostic level for a failing `checks:` entry on items of this type; see [checks](checks.md#candidates-vs-decisions) |
| `coverable` | not set — falls back to name-based detection, see below | Whether items of this type get a `Coverage` object at all |
| `coverable_statuses` | not set — excludes `status: retired` if a `status` field exists, nothing otherwise | `status` values that keep an item in coverage; unlisted statuses (e.g. `draft`) are excluded entirely, not just "open" |
| `verifying_statuses` | not set — every `verifies:` link counts | `status` values on a verifier (a type declaring a `verifies`-family link) that actually count as having verified, as opposed to merely linked; mirrors `satisfying_statuses` |
| `doc` | not set | The type's own definition — see [`doc`](#doc) |

`satisfying_statuses` requires the type to declare a `status` field — the project
fails to load if it doesn't.

`check_severity` must be `error`, `warning`, or `info`. It only changes how a
*failing* check is reported — the check still runs, and `item.checks` (and the
rendered Checks table) still shows pass/fail exactly the same way regardless of
the setting.

`coverable`, `coverable_statuses`, and `verifying_statuses` are engine
capabilities, not standard-specific plumbing — available on any type in any
project, `standard: none` included. A type that never declares `coverable:`
falls back to the pre-existing convention (`requirement`/`constraint` are
coverable by name) with a one-time warning naming the fix; that fallback, and
the requirement-only restriction on the per-item coverage warnings it
preserves, is removed in refdes 1.0. See
[coverage](coverage.md#what-gets-coverage) for the full behavior.

### `extends`

```yaml
types:
  thermal_bound:
    extends: bound
    prefix: THB
    label: Thermal bound
    plural: Thermal bounds
```

A type may name one parent and declare only what differs
(`docs/design/extends.md`). It inherits `fields:`, `links:` (merged by key --
an override replaces the whole field definition or target list), `body:`,
`preview:`, `coverable:`, `coverable_statuses:`, `satisfying_statuses:`,
`verifying_statuses:`, `check_severity:` and `append_only:`. It never inherits
`prefix:`, `label:`, `plural:` (declaring all three is required) or `doc:`.

A subtype is accepted anywhere a link's target list names its parent -- no
per-link marker. That holds one way only: a list naming the subtype still
refuses the parent. Inheritance is one level: extending a type that itself
extends is a load error, as are extending a set, making a parent-required field
optional, and turning `append_only` off under an append-only parent.

### Field options

| Key | Purpose |
|---|---|
| `type` | `text`, `enum`, `limit`, `person`, `date`, `list`, `options`, `checks`, `citations`, `quantity` |
| `required` | Missing or empty is a build error |
| `required_when` | Required only when a sibling condition currently holds — see below |
| `choices` | Allowed values, for `type: enum` |
| `default` | Applied when the item omits the field |
| `on_change` | `invalidate`, `log`, or `ignore` |
| `doc` | The field's own definition — see [`doc`](#doc) |

### `doc`

```yaml
# refdes-schema.yaml
types:
  thermal_budget:
    prefix: THB
    doc: A statement of the heat a board is allowed to produce, and where.
    fields:
      watts: { type: quantity, required: true, doc: Total dissipation this budget allows. }
sets:
  stewardship:
    fields:
      owner: { type: person, doc: The person a question about this item goes to. }
link_types:
  governed_by: { inverse: governs, doc: The bound or requirement this item must respect. }
```

One prose definition, written next to the declaration it defines. It is accepted
on a type, a field, a field-set entry (a field spec like any other, so the
definition is written once and rides along into every type that `include:`s the
set), and a link type — in the bundled standard and in a project's
`refdes-schema.yaml` alike.

The value must be a non-empty string; `doc: 42`, `doc: [a, b]` and a bare
`doc:` are configuration errors naming the block path, the same way any other
wrong-typed config value is. A misspelling (`docs:`) is the unknown-key error
the rest of the config already raises, did-you-mean included.

Nothing is rendered and nothing changes for a project that declares none: a
term without `doc:` exports exactly what it exported before the key existed.
Where a definition *is* declared it reaches the editor through the two exports
that already exist — `.refdes/schema.json` carries it as the JSON Schema
`description` (so vscode-yaml shows it on hover and in completions, and the
refdes extension shows it on field-name completion in `.md` front matter), and
`items.json`'s `types` payload carries it as `doc` on the type and on each
field. A link type's definition joins the `target: …` line already in its
editor description.

The generated vocabulary reference and diagram that will read these definitions
is [design finding 38](design/backlog.md); this is chunk 1 of it — the key, not
the dictionary.

### `required_when`

A field required only when a sibling field currently holds a particular value,
or a particular link is present — instead of being unconditionally `required`:

```yaml
fields:
  rationale:
    type: text
    on_change: invalidate
    required_when: { status: rejected }
```

- Each key names another field on the *same* type (which must be `type: enum`
  — its declared `choices:` is what lets this be validated) or the reserved
  key `links`, whose value names one or more link names on the type.
- Each value is a scalar or a list of scalars (a list is "any of these").
  Multiple keys are ANDed: every named condition must currently hold.
- A field declares `required: true` or `required_when:`, never both — that
  combination is a `SchemaError` at load.
- Validated against the fully merged schema (after any `standard:` and
  overrides are applied): a `required_when:` naming a field that doesn't
  exist, isn't an `enum`, or names a value outside that enum's resolved
  `choices:` fails the build at load time, not silently.

The standard's own `decision.rationale` uses this
(`required_when: {status: rejected}`), toggled by
`require_rejection_rationale:` in `refdes-project.yaml`. `component.rationale`
uses the `links` form (`required_when: {links: alternate}`) — see
[`alternate`'s required rationale](links.md#part-equivalence-drop_in-and-alternate).

**`enum`, `limit`, and `citations` are enforced today.** `enum` is checked
against `choices`; `limit` is parsed as a quantity; `citations` is checked to
be a list of entries that each have at least a `path`. The rest are
declarative — they document intent and are where future validation will hook
in.

Four field *names* have behaviour attached regardless of declared type:

| Field | Behaviour |
|---|---|
| `limit` | Parsed as a quantity; makes the item checkable. One scalar bound per field — see [one `limit`, one bound](checks.md#one-limit-one-bound) |
| `options` | Rendered as the options-considered panel (`name`, `verdict`, `because`) |
| `checks` | Evaluated as [checks](checks.md) (`value`, `against`) |
| `part_number` | Indexed into [the parts page](parts.md), on any type that declares it, alongside the nested `part_number` inside any `citations:` entry |

`citations` is different: it is keyed off the declared **type**, not a fixed
field name, so a project can call the field `references`, `sources`,
anything — the hardware standard calls it `citations`. Any field declared `type: citations` gets a `path` (required — `http`/`https` for a remote document, a project-root-relative file path for a local one), plus
`rev`, `page`, `section`, `part_number`, `keep_copy`, and an optional `id` per entry, its
own table on the item page, and an entry in `references.html` — see [citing a
datasheet](markdown.md#citing-a-datasheet), [CLI
reference](cli-reference.md#refdes-fetch), and [output
formats](output.md#items-json). A citation's `id`, when given, is what
`[[cite:id]]` in prose resolves to — a project-wide-unique namespace, the
same posture a figure's `id=` already has.

### Starter types

`requirement`, `bound`, `decision`, `component`, `test`, `log` — the
[standard library](standard-library.md) ships these by default, so most
projects never declare `types:` at all — and have no `refdes-schema.yaml`
either. A project may still add, remove, or
override any of them under `standard:`'s merge rules, or declare its own from
scratch under `standard: none`. Nothing in the code depends on these
particular names — `coverable:`/`coverable_statuses:`/`verifying_statuses:`
(above) are what makes a type participate in coverage, not its name; the
fallback that still checks for `requirement`/`constraint` by name only fires
when a type declares no `coverable:` at all. It keeps those two literal names,
deliberately unchanged by the `hardware@2` rename, because its whole job is to
reproduce what projects did before `coverable:` existed; it is removed in
refdes 1.0.

### Filled-in examples

Field tables describe a type abstractly; the fastest way to see one is the
front matter a new item of that type actually starts life with. Each example
below is what `refdes new <type>` generates — the required fields with their
placeholders, defaulted fields with their defaults, optional fields and links
commented out with their type/choices hints — for every type the pinned
standard resolves.

<!-- BEGIN GENERATED per-type-examples -->
Every example below is live `refdes new <type>` output -- the same
`scaffold.new_item_text()` the CLI calls, run against the resolved
**hardware@3** schema pinned in this repo's `refdes-project.yaml`, and
written here by `python docs-site/gen_examples.py`. Do not hand-edit
this block: `tests/test_docs_examples.py` fails if it differs from
what the generator produces today.

#### `requirement` — hardware@3

```yaml
---
id:
type: requirement
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
# title:  # text
status: draft  # choices: draft, active, retired
# rationale:  # text
# part_of: []  # target: group
# refines: []  # target: requirement
# governed_by: []  # target: requirement, bound
---

<!-- required: the content itself goes here. -->
```

#### `bound` — hardware@3

```yaml
---
id:
type: bound
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
# title:  # text
limit:  # required -- limit
status: draft  # choices: draft, active, retired
# rationale:  # text
# part_of: []  # target: group
# refines: []  # target: bound
# derives_from: []  # target: requirement, bound
---

<!-- required: the content itself goes here. -->
```

#### `decision` — hardware@3

```yaml
---
id:
type: decision
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
# citations:  # citations
title:  # required -- text
status: proposed  # choices: proposed, in_progress, accepted, on_hold, rejected, superseded
# rationale:  # text; required when status is 'rejected'
# date:  # date
# options:  # options
# checks:  # checks
# part_of: []  # target: group
# satisfies: []  # target: requirement, bound
# constrained_by: []  # target: bound
# supersedes: []  # target: decision
# selects: []  # target: component
# blocked_by: []  # target: any
# recorded_by: []  # target: log
---

<!-- optional body. -->
```

#### `test` — hardware@3

```yaml
---
id:
type: test
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
title:  # required -- text
status: planned  # choices: planned, passing, failing, blocked
# part_of: []  # target: group
# verifies: []  # target: requirement, bound
---

<!-- optional body. -->
```

#### `component` — hardware@3

```yaml
---
id:
type: component
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
# citations:  # citations
title:  # required -- text
# part_number:  # text
# refdes:  # list
status: candidate  # choices: candidate, selected, obsolete
# rationale:  # text; required when it has a link under 'alternate'
# checks:  # checks
# part_of: []  # target: group
# satisfies: []  # target: requirement, bound
# constrained_by: []  # target: bound
# drop_in: []  # target: component
# alternate: []  # target: component
---

<!-- optional body. -->
```

#### `group` — hardware@3

```yaml
---
id:
type: group
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
title:  # required -- text
---

<!-- optional body. -->
```

#### `log` — hardware@3

```yaml
---
id:
type: log
# source:  # text
# note:  # text
# tags:  # list
date:  # required -- date
summary:  # required -- text
# author:  # person
# addresses: []  # target: requirement, bound
# amends: []  # target: log
# records: []  # target: decision
---

<!-- optional body. -->
```
<!-- END GENERATED per-type-examples -->

---

## `imports`

```yaml
imports:
  - name: platform
    items: ../platform-interfaces/_site/items.json
    version: "2026.3"
```

| Key | Required | Purpose |
|---|---|---|
| `name` | yes | Label shown on imported items |
| `items` | yes | Path to the upstream `items.json`, relative to the project root |
| `version` | no | Asserted against the artifact's `site.version` |

See [multiple boards](multi-board.md).

---

## `boards`

```yaml
boards:
  board-a:
    label: "Board A"
    token: A
    path: brd-a
    conforms_to: [GRP-DBG]   # group items whose members this board owes
```

| Key | Required | Purpose |
|---|---|---|
| `label` | no, defaults to the key | Display name on board-scoped pages |
| `token` | no | Checked against item id prefixes; unset means no check |
| `path` | no, defaults to the key | The `items/` path segment, if different from the key |
| `conforms_to` | no | A list of group ids whose members get a per-(item, board) coverage result; anything but a list of strings, or a target that is not an existing group, is a build error ([multiple boards](multi-board.md#conforming-to-a-shared-contract)) |

Absent entirely, this key does nothing: no item gets a board, and the site is
unaffected. With it, a board is the first path segment under `items/` matched
against this registry, overridable per item with the reserved `board:` key. See
[multiple boards](multi-board.md).

Two boards resolving to the same `items/` path segment — either the same `path:`
given twice, or a `path:` colliding with another board's key — is a hard error
at project-load time, printed as `configuration error: boards.board-b and
boards.board-a both map to items/board-a/ — path segments must be unique`, and
fails before any item is parsed.

---

## `workspaces`

```yaml
workspaces:
  platform:
    label: "Shared Platform"
    shared: true
  product-a:
    label: "Product A"
```

| Key | Required | Purpose |
|---|---|---|
| `label` | no, defaults to the key | Display name on workspace-scoped pages |
| `shared` | no, defaults to `false` | Other workspaces may link into this one without tripping the cross-workspace lint |
| `path` | no, defaults to the key | The `items/` path segment, if different from the key |

Absent entirely, this key does nothing. With it, a workspace is one level
above a board — read from the first `items/` path segment when
`item_layout: workspace` (`refdes-project.yaml`), overridable per item with
the reserved `workspace:` key regardless of layout. See
[workspaces](workspaces.md).

A board key and a workspace key must never collide — they share one
generated-filename namespace (`coverage-<key>.html`); doing so is a hard
error at project-load time naming both sides.

---

## Item-level `history`

Not part of either config file, but the counterpart to the `history:`
setting in `refdes-project.yaml`. In an item's
front-matter:

```yaml
history:
  fields:
    owner: ignore
  reason: "Owner rotates weekly during bring-up; not a meaningful change."
```

Or as a scalar for the whole item:

```yaml
history: ignore
```

Precedence: item field override → whole-item mode → schema field → project
default.
