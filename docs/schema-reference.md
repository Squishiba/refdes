# Schema reference

Every key in `refdes.yaml`. A project is any folder containing this file;
commands search upward from the current directory to find it.

## Top level

```yaml
site:        { ... }   # title, output directory, version
id:          { ... }   # ID width and ledger location
history:     { ... }   # default on_change mode
units:       { ... }   # preferred display units
standard:    { ... }   # the bundled standard dictionary, or "none"
field_sets:  { ... }   # reusable field groups, include:d by a type
link_types:  { ... }   # relationships and their inverses
types:       { ... }   # item types
imports:     [ ... ]   # other projects to read
boards:      { ... }   # opt-in board registry
workspaces:  { ... }   # opt-in workspace registry, one level above boards
```

`standard:` (or its absence) determines where `link_types:`/`types:` start
from before this file's own blocks are applied on top — see [the standard
library](standard-library.md) for the full picture. Everything below describes
the merged result, regardless of where each piece came from.

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
`link_types:`/`types:`/`field_sets:` from scratch. Resolved fresh, from the
installed `refdes` package, on every load — this file never contains a copy of
what the standard declares, only the pointer to it. Absent entirely, or the
string `standard: none`, means no standard: every type, link, and field set
comes only from this file, exactly like every project before this existed.

| Key | Required | Purpose |
|---|---|---|
| `base` | yes | Which bundled dictionary — `hardware` today |
| `version` | yes | A pinned integer, e.g. `1` — never the string `"latest"` |
| `presets` | no, defaults to `[]` | Optional bundled extensions layered on top, e.g. `[design-debate]` |

This file's own `link_types:`/`types:`/`field_sets:` are merged on top of the
resolved standard, not replacing it — see [the standard
library](standard-library.md#overriding-and-extending) for the merge rules
(add a field, remove one, redeclare an enum, add or remove a whole type).

---

## `field_sets`

```yaml
field_sets:
  provenance:
    source: { type: text, on_change: log }
    tags:   { type: list, on_change: ignore }
```

Named, reusable groups of field definitions, `include:`d by one or more types
instead of being retyped on each. The standard is authored this way internally
(`provenance`, `stewardship`); a project can declare its own for fields
repeated across its own custom types. See [the standard
library](standard-library.md#field-sets-and-include) for `include:`'s merge
order against a type's own fields.

---

## `link_types`

```yaml
link_types:
  satisfies:   { inverse: satisfied_by, label: "Satisfies" }
  verified_by: { inverse: verifies,     label: "Verified by" }
```

| Key | Default | Purpose |
|---|---|---|
| `inverse` | `<name>_by` | Name of the computed back-link |
| `label` | the link name | Heading shown on item pages |
| `trace` | `true` | Whether this link type participates in a `{{cascade}}` block's default walk (see [generated blocks](blocks.md)) |

Either end resolves to the same edge, so a type may declare `verifies` even though
`verified_by` is the name in `link_types`. See [links](links.md).

`trace: false` marks a link as describing process rather than "this item's
correctness rests on that one" — the bundled standard sets it on `amends`,
`records`, `supersedes`, and `addresses`. A `{{cascade}}` block with no
explicit `via=` follows every link type where `trace` is still `true`.

---

## `types`

```yaml
types:
  bound:
    prefix: BND
    label: Bound
    append_only: false
    preview: [status, text, limit]
    coverable: true
    coverable_statuses: [active]
    fields:
      text:   { type: text,  required: true, on_change: invalidate }
      limit:  { type: limit, required: true, on_change: invalidate }
      status: { type: enum, choices: [draft, active, retired],
                default: draft, on_change: invalidate }
      owner:  { type: person, on_change: log }
    include: [provenance]
    links:
      refines:      [bound]
      derives_from: [requirement, bound]
    body: { on_change: invalidate }
```

| Key | Default | Purpose |
|---|---|---|
| `prefix` | first 3 letters, uppercased | ID prefix when a list file gives none |
| `label` | title-cased name | Display name |
| `append_only` | `false` | Seal items of this type after first build |
| `preview` | `[]` | Fields shown in hover previews and index columns |
| `fields` | `{}` | Legal fields |
| `include` | not set | Names of `field_sets:` entries merged into `fields:` before this type's own fields are applied |
| `links` | `{}` | Legal links, mapped to allowed target types |
| `body` | project default | `on_change` mode for the markdown body |
| `satisfying_statuses` | not set — every `satisfies:` link counts | `status` values that count as settled; see [coverage](coverage.md#which-statuses-count-as-satisfying) |
| `check_severity` | `error` | Diagnostic level for a failing `checks:` entry on items of this type; see [checks](checks.md#candidates-vs-decisions) |
| `coverable` | not set — falls back to name-based detection, see below | Whether items of this type get a `Coverage` object at all |
| `coverable_statuses` | not set — excludes `status: retired` if a `status` field exists, nothing otherwise | `status` values that keep an item in coverage; unlisted statuses (e.g. `draft`) are excluded entirely, not just "open" |
| `verifying_statuses` | not set — every `verifies:` link counts | `status` values on a verifier (a type declaring a `verifies`-family link) that actually count as having verified, as opposed to merely linked; mirrors `satisfying_statuses` |

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

### Field options

| Key | Purpose |
|---|---|
| `type` | `text`, `enum`, `limit`, `person`, `date`, `list`, `options`, `checks`, `citations`, `quantity` |
| `required` | Missing or empty is a build error |
| `required_when` | Required only when a sibling condition currently holds — see below |
| `choices` | Allowed values, for `type: enum` |
| `default` | Applied when the item omits the field |
| `on_change` | `invalidate`, `log`, or `ignore` |

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
[`alternate`'s required rationale](links.md#part-equivalence-equivalent-and-alternate).

**`enum`, `limit`, and `citations` are enforced today.** `enum` is checked
against `choices`; `limit` is parsed as a quantity; `citations` is checked to
be a list of entries that each have at least a `url`. The rest are
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
field name, so a project can call the field `datasheets`, `references`,
anything. Any field declared `type: citations` gets a `url` (required), plus
`rev`, `page`, `part_number`, and `vendor` per entry, its own table on the
item page, and an entry in `references.html` — see [citing a
datasheet](markdown.md#citing-a-datasheet), [CLI
reference](cli-reference.md#refdes-fetch), and [output
formats](output.md#items-json).

### Starter types

`requirement`, `bound`, `decision`, `component`, `test`, `log` — the
[standard library](standard-library.md) ships these by default, so most
projects never declare `types:` at all. A project may still add, remove, or
override any of them under `standard:`'s merge rules, or declare its own from
scratch under `standard: none`. Nothing in the code depends on these
particular names — `coverable:`/`coverable_statuses:`/`verifying_statuses:`
(above) are what makes a type participate in coverage, not its name; the
fallback that still checks for `requirement`/`constraint` by name only fires
when a type declares no `coverable:` at all. It keeps those two literal names,
deliberately unchanged by the `hardware@2` rename, because its whole job is to
reproduce what projects did before `coverable:` existed; it is removed in
refdes 1.0.

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
```

| Key | Required | Purpose |
|---|---|---|
| `label` | no, defaults to the key | Display name on board-scoped pages |
| `token` | no | Checked against item id prefixes; unset means no check |
| `path` | no, defaults to the key | The `items/` path segment, if different from the key |

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

Not part of `refdes.yaml`, but the counterpart to it. In an item's
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
