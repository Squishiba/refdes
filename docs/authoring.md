# Authoring items

Two file formats, one object model. Which you use is a matter of how much the item
has to say, not what kind of item it is.

## List files — `items/**/*.yaml`

For items that are mostly one sentence: requirements, constraints, tests, log
entries. `defaults:` applies to every entry in the file.

```yaml
defaults:
  type: requirement
  prefix: REQ-PWR
  owner: J. Bin
  tags: [power]
  status: accepted

items:
  - id: REQ-PWR-001
    text: The unit shall operate from an input supply of 9 V to 36 V.
    source: Customer spec rev D, §3.1

  - id: REQ-PWR-002
    text: The 3V3 rail shall supply 1.2 A continuous.
    status: draft          # overrides the default
```

- `defaults:` is merged into every entry; an entry's own keys win.
- `prefix:` is consumed by the [ID allocator](ids.md), not stored as a field.
- Entries may omit `id:` — run `refdes id` to fill them in.

### Bodies in list files

Use a `body:` key with a YAML block scalar. This is what makes a running log
practical without one file per entry:

```yaml
items:
  - id: LOG-005
    date: 2026-03-16
    summary: Thermal check fails at the current power-stage allocation.
    addresses: [CON-THM-001]
    body: |
      Three ways out, none chosen yet:

      1. Widen the allocation to about 2.0 × 1.0 inches.
      2. Improve efficiency — little headroom at this current.
      3. Renegotiate CON-THM-001; the 55 °C ambient may not be real.
```

The body is markdown, and supports everything a `.md` file's body does, including
`calc` blocks and `{{value}}` references.

## Markdown files — `items/**/*.md`

For items with substantial prose, math, or structured fields like `options`. YAML
front-matter, then the body.

````markdown
---
id: DEC-PWR-001
type: decision
title: 3V3 rail regulator topology
status: accepted
date: 2026-03-14
satisfies: [REQ-PWR-002]
options:
  - name: LDO (TPS7A4700)
    verdict: rejected
    because: Dissipates 10.4 W at full load.
  - name: Synchronous buck (TPS62913)
    verdict: chosen
    because: 93 % efficiency at half load.
---

Prose goes here, and may reference REQ-PWR-002 inline.

```calc
P : W = 3.3 V * 1.2 A
```
````

The filename does not matter — the ID is the identity.

### Several items in one file

A `.md` file is not limited to one item. A further `---` starts a new item's
front-matter as long as the line right after it looks like a YAML key, a closing
`---` exists later, and the text between actually parses as YAML — otherwise it is
left alone as a literal horizontal rule in the body, exactly as it always was. This
is what makes a today-style single-item file valid unmigrated: nothing after its
one closing `---` looks like a fresh front-matter block, so the whole rest of the
file stays its body.

An optional leading block whose only key is `defaults:` applies to every item that
follows, the same way `defaults:` works in a list file:

````markdown
---
defaults:
  type: decision
  prefix: DEC-PWR
---
id: DEC-PWR-001
title: 3V3 rail regulator topology
---

Body of the first decision.

---
title: LDO thermal fallback, rejected
---

Body of the second decision. Each item keeps its own body — the next item's
front-matter is where this one ends.
````

Items with no `id:` are filled in by `refdes id`, which inserts each one at its own
item's fence regardless of how many other items share the file.

### `prefix:` per item

`prefix:` may be set on an individual item, not only in `defaults:`. The item's own
value wins:

```yaml
defaults:
  type: decision
  prefix: DEC-PWR
---
prefix: DEC-MECH   # this one item only, everything else still gets DEC-PWR
title: Enclosure fastener torque
---
```

`prefix:` is consumed by the [ID allocator](ids.md); it is never stored as a field,
and it works the same way in a list file's `items:` entries.

## Choosing between them

| Use a list file | Use a markdown file |
|---|---|
| One-line requirements | Decisions with options |
| Test definitions | Anything with more than a paragraph |
| Daily log entries | Anything with several calc blocks |
| Bulk import from a spec | Items you will keep editing |

Both are first-class. A list entry with a `body:` covers most middle cases.

## Fields

Which fields are legal depends on the type, and is declared in `refdes.yaml`:

```yaml
types:
  requirement:
    fields:
      text:    { type: text, required: true, on_change: invalidate }
      status:  { type: enum, choices: [draft, active, retired], default: draft }
      owner:   { type: person, on_change: log }
```

The [standard library](standard-library.md) already declares this for `requirement`
and the other five starter types — this is what a custom type, or an override of
a standard one, looks like.

An unknown field is a **warning**, not an error, and the value is kept. The warning
suggests a correction:

```
WARNING items/requirements/power.yaml:12 [REQ-PWR-002] — unknown field 'sorce'
        on requirement. Did you mean 'source'?
```

Field types are declarative. Today `enum` (checked against `choices`), `limit`
(parsed as a quantity), and `citations` (checked to be a list of entries each
with a `url` — see [citing a datasheet](markdown.md#citing-a-datasheet)) are
enforced; the rest are documentation for readers and for future validation.

### Titles

An item's display title is its `title` field, or its `text` field if there is no
`title`, or its ID if neither exists. This is why requirements use `text` (the
requirement *is* the sentence) and decisions use `title`.

## Reserved keys

These are never treated as fields:

| Key | Meaning |
|---|---|
| `id` | The item's identity |
| `type` | Which item type it is |
| `body` | Markdown body (list files only) |
| `history` | Item-level [`on_change` overrides](change-tracking.md) |
| `prefix` | [ID allocator](ids.md) prefix, item overrides file `defaults:` |
| `board` | [Board](multi-board.md) override, item overrides file `defaults:` |

`prefix` and `board` are reserved only where the item's own type does not already
declare a field of that name — a schema written before either key existed keeps
working unchanged. (The starter schema's `log` type still has its own hand-typed
`board` field for this reason; it predates the reserved key and should eventually
move to it.)

## Folder layout

Everything under `items/` is scanned recursively. Folders carry no meaning — use
whatever helps you find things:

```
items/
  requirements/power.yaml
  requirements/mechanical.yaml
  constraints/thermal.yaml
  decisions/dec-pwr-001-regulator.md
  tests/power.yaml
  log/board-a.yaml
```

For several boards in one project, see [multiple boards](multi-board.md).
