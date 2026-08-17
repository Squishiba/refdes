# Schema reference

Every key in `refdes.yaml`. A project is any folder containing this file;
commands search upward from the current directory to find it.

## Top level

```yaml
site:        { ... }   # title, output directory, version
id:          { ... }   # ID width and ledger location
history:     { ... }   # default on_change mode
units:       { ... }   # preferred display units
link_types:  { ... }   # relationships and their inverses
types:       { ... }   # item types
imports:     [ ... ]   # other projects to read
boards:      { ... }   # opt-in board registry
```

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
| `nav` | *(empty)* | Explicit page order in the nav bar, by slug |
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

Either end resolves to the same edge, so a type may declare `verifies` even though
`verified_by` is the name in `link_types`. See [links](links.md).

---

## `types`

```yaml
types:
  constraint:
    prefix: CON
    label: Constraint
    append_only: false
    preview: [status, limit, rationale]
    fields:
      title:  { type: text,  required: true, on_change: invalidate }
      limit:  { type: limit, required: true, on_change: invalidate }
      status: { type: enum, choices: [draft, open, accepted, retired],
                default: draft, on_change: invalidate }
      owner:  { type: person, on_change: log }
    links:
      derives_from: [requirement, constraint]
    body: { on_change: invalidate }
```

| Key | Default | Purpose |
|---|---|---|
| `prefix` | first 3 letters, uppercased | ID prefix when a list file gives none |
| `label` | title-cased name | Display name |
| `append_only` | `false` | Seal items of this type after first build |
| `preview` | `[]` | Fields shown in hover previews and index columns |
| `fields` | `{}` | Legal fields |
| `links` | `{}` | Legal links, mapped to allowed target types |
| `body` | project default | `on_change` mode for the markdown body |
| `satisfying_statuses` | not set — every `satisfies:` link counts | `status` values that count as settled; see [coverage](coverage.md#which-statuses-count-as-satisfying) |
| `check_severity` | `error` | Diagnostic level for a failing `checks:` entry on items of this type; see [checks](checks.md#candidates-vs-decisions) |

`satisfying_statuses` requires the type to declare a `status` field — the project
fails to load if it doesn't.

`check_severity` must be `error`, `warning`, or `info`. It only changes how a
*failing* check is reported — the check still runs, and `item.checks` (and the
rendered Checks table) still shows pass/fail exactly the same way regardless of
the setting.

### Field options

| Key | Purpose |
|---|---|
| `type` | `text`, `enum`, `limit`, `person`, `date`, `list`, `options`, `checks`, `citations`, `quantity` |
| `required` | Missing or empty is a build error |
| `choices` | Allowed values, for `type: enum` |
| `default` | Applied when the item omits the field |
| `on_change` | `invalidate`, `log`, or `ignore` |

**`enum`, `limit`, and `citations` are enforced today.** `enum` is checked
against `choices`; `limit` is parsed as a quantity; `citations` is checked to
be a list of entries that each have at least a `url`. The rest are
declarative — they document intent and are where future validation will hook
in.

Three field *names* have behaviour attached regardless of declared type:

| Field | Behaviour |
|---|---|
| `limit` | Parsed as a quantity; makes the item checkable. One scalar bound per field — see [one `limit`, one bound](checks.md#one-limit-one-bound) |
| `options` | Rendered as the options-considered panel (`name`, `verdict`, `because`) |
| `checks` | Evaluated as [checks](checks.md) (`value`, `against`) |

`citations` is different: it is keyed off the declared **type**, not a fixed
field name, so a project can call the field `datasheets`, `references`,
anything. Any field declared `type: citations` gets a `url` (required), plus
`rev`, `page`, `part_number`, and `vendor` per entry, its own table on the
item page, and an entry in `references.html` — see [citing a
datasheet](markdown.md#citing-a-datasheet), [CLI
reference](cli-reference.md#refdes-fetch), and [output
formats](output.md#items.json).

### Starter types

`requirement`, `constraint`, `decision`, `component`, `test`, `log`. Add, remove,
or rename them freely — nothing in the code depends on these names except
`coverage`, which looks for `requirement` and `constraint`.

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
