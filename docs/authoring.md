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

One item per markdown file. The filename does not matter — the ID is the identity.

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
      status:  { type: enum, choices: [draft, open, accepted, retired], default: draft }
      owner:   { type: person, on_change: log }
```

An unknown field is a **warning**, not an error, and the value is kept. The warning
suggests a correction:

```
WARNING items/requirements/power.yaml:12 [REQ-PWR-002] — unknown field 'sorce'.
        Did you mean 'source'?
```

Field types are declarative. Today only `enum` (checked against `choices`) and
`limit` (parsed as a quantity) are enforced; the rest are documentation for
readers and for future validation.

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
