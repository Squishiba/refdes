# Authoring items

Two file formats, one object model. Which you use is a matter of how much the item
has to say, not what kind of item it is.

## List files — `items/**/*.yaml`

For items that are mostly one sentence: requirements, bounds, tests, log
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

A file with more than one type in it — see [Sections](#sections) below.

### Bodies in list files

Use a `body:` key with a YAML block scalar. This is what makes a running log
practical without one file per entry:

```yaml
items:
  - id: LOG-005
    date: 2026-03-16
    summary: Thermal check fails at the current power-stage allocation.
    addresses: [BND-THM-001]
    body: |
      Three ways out, none chosen yet:

      1. Widen the allocation to about 2.0 × 1.0 inches.
      2. Improve efficiency — little headroom at this current.
      3. Renegotiate BND-THM-001; the 55 °C ambient may not be real.
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

`defaults:` only applies from that one leading block — it is not something you can
re-declare partway through a file to change what applies to later items. A block
shaped like `defaults:` anywhere else is an error. Use [a section](#sections) to
change the type partway through a file instead.

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

## Sections

A `section: <type>` marker asserts the type for every item after it, until the
next section or the end of the file — the same spelling in both formats, placed
wherever each format's structure naturally allows a marker to sit between items:
a list entry of its own in a list file, a fenced block of its own in Markdown.

```yaml
items:
  - section: requirement
  - id: REQ-IO-AI-001
    text: The AI accelerator rail shall regulate to 0.85 V ±3%.
  - id: REQ-IO-AI-002
    text: The AI accelerator rail shall supply 40 A continuous.

  - section: bound
  - id: BND-IO-001
    limit: "<= 5 A"
    rationale: Trace width on the outer layer at 1 oz copper.
```

```markdown
---
section: requirement
---
id: REQ-IO-AI-001
text: The AI accelerator rail shall regulate to 0.85 V ±3%.
---

---
section: bound
---
id: BND-IO-001
limit: "<= 5 A"
rationale: Trace width on the outer layer at 1 oz copper.
---
```

Neither item above states its own `type:` — the section already did, and every
item under it is that type until the next `section:` or the end of the file.

### A section asserts; `defaults:` provides a fallback

This is the actual difference between the two, not just a second way to spell the
same thing. Under `defaults: {type: requirement}`, an item may still legally
declare `type: decision` — a default is something an item is free to override.
Under `section: requirement`, the container has already stated what its items
are, so an item inside it declaring a conflicting `type:` is an **error** naming
both, not a silent override:

```
ERROR items/main-io/interfaces.yaml:6 — item declares type 'decision' but sits
      inside a 'section: requirement' block (opened at line 2) -- a section
      asserts its items' type; this one disagrees. Move the item out of the
      section, or fix whichever of the two is wrong.
```

`defaults:` keeps working exactly as it always has for everything else — a
section only ever asserts `type:`, nothing more. Every other field a section's
items need still comes from `defaults:` or the item's own keys, with the same
precedence as today.

### Composing a file-level `defaults:` with a section

- `defaults:` fields other than `type:` apply under a section exactly as they
  do outside one — unaffected by whether a section is active.
- If `defaults:` does not set `type:`, a section simply supplies it, and nothing
  can conflict.
- If `defaults:` *does* set `type:` and a section asserts a different one, that
  is the file contradicting itself, not two independent fallbacks to reconcile
  silently — it is an error at the section marker itself, naming both values:

  ```
  ERROR items/main-io/interfaces.yaml:2 — 'section: bound' conflicts with
        this file's own 'defaults: {type: requirement}' -- a section asserts
        what its items are; reconcile the two rather than leaving them to
        silently disagree. Drop 'type:' from defaults:, or make it match.
  ```

  Fix it by dropping `type:` from `defaults:` (the common case — most files
  using sections don't need a file-wide type at all) or by making the two agree.

Because a section asserts its own type, interleaving two types inside one section
is not something a linter has to catch after the fact — an item that disagrees
with its enclosing section is simply an error, so the file cannot express
disorganized interleaving within a section in the first place. There is no
`enforce_grouping:` setting; a section doesn't need one to enforce.

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

### `source`, `note`, `rationale`, `body`

Four fields all hold prose beyond an item's own required content, and it's
easy to reach for the wrong one without seeing them side by side. The real
distinction is each field's [`on_change:`](change-tracking.md) mode:

| Field | `on_change:` | What it's for |
|---|---|---|
| `source:` | `log` | Where a value or decision came from — a spec section, a datasheet, a conversation. Doesn't affect whether the item's content is still correct. |
| `note:` | `log` | An aside that's neither where something came from nor part of the item's actual content — a loose "worth remembering" field. |
| `rationale:` | `invalidate` | Why the content is correct. Part of the record: change it, and whatever depends on this item should be re-reviewed. |
| `body:` | `invalidate` | Overflow content itself — a table, an image, extended prose the item's own fields have no room for. |

`log` vs. `invalidate` is the line that matters, not the words themselves:
`source`/`note` are metadata *about* an item, editable freely without ever
making a downstream link suspect; `rationale`/`body` are part of what the
item actually asserts, so a change there does. Choosing between `note:` and
`rationale:` for something: if a change to it should flag things pointing at
this item as needing another look, it's `rationale:` (or `body:`, if it's
content rather than a *reason*); if not, it's `note:`.

`source` and `note` come from `field_sets.provenance` (see [`field_sets` and
`include:`](standard-library.md#field-sets-and-include)); `rationale` is
declared per type, and required on some (`decision.rationale`, when `status:
rejected`); `body` is a reserved key, not a field at all — see [bodies in
list files](#bodies-in-list-files) and [reserved keys](#reserved-keys) below.

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
  bounds/thermal.yaml
  decisions/dec-pwr-001-regulator.md
  tests/power.yaml
  log/board-a.yaml
```

For several boards in one project, see [multiple boards](multi-board.md).
