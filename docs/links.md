# Links and traceability

## Declaring links

Links are fields whose values are item IDs. Which link names are legal on a type,
and what they may point at, is declared in `refdes.yaml`:

```yaml
types:
  decision:
    links:
      satisfies:      [requirement]
      constrained_by: [constraint]
      supersedes:     [decision]
```

In an item:

```yaml
satisfies:      [REQ-PWR-002, REQ-PWR-003]
constrained_by: [CON-THM-001]
```

The [standard library](standard-library.md) already declares this vocabulary for
the six starter types, so most projects never write a `types:...links:` block at
all — this is what to reach for on a custom type, or one the standard doesn't
cover.

Pointing at a nonexistent item, or at an item of a type the schema disallows, is a
build error.

## Back-links are computed

Each link type declares its inverse:

```yaml
link_types:
  verifies:  { inverse: verified_by,  label: "Verifies" }
  satisfies: { inverse: satisfied_by, label: "Satisfies" }
```

Declare the edge from **either** end and the other direction appears automatically.
A test saying `verifies: [REQ-PWR-002]` gives the requirement
`verified_by: [TST-PWR-002]` without the requirement mentioning it.

Declare it from whichever end is natural — a test knows what it covers; a decision
knows what it satisfies. Declaring both ends is allowed but redundant.

## Starter link types

| Link | Inverse | Typical use |
|---|---|---|
| `derives_from` | `derived_by` | a requirement derived from another |
| `satisfies` | `satisfied_by` | decision → requirement |
| `constrains` | `constrained_by` | decision → constraint |
| `verified_by` | `verifies` | requirement → test |
| `supersedes` | `superseded_by` | decision → older decision |
| `implements` | `implemented_by` | decision → component |
| `addresses` | `addressed_by` | log entry → requirement or constraint |
| `amends` | `amended_by` | log entry → earlier log entry |
| `records` | `recorded_by` | log entry → decision |

Add your own by declaring them in `link_types` and listing them under a type's
`links:`.

## Cross-references in prose

Two forms, both producing hover previews:

```markdown
The thermal budget in CON-THM-001 drives this.          <- bare, autolinked
See [[REQ-PWR-002|the input voltage range]] for detail.  <- explicit, custom text
```

**Bare IDs autolink** when they resolve to a real item. A token that merely looks
like an ID — `MIL-STD-810`, `DO-254`, `LTC3388-1` — is left as plain text unless
you happen to have an item with that exact ID. Wrap anything in backticks to
suppress linking entirely.

**Explicit `[[...]]` references are validated.** An unresolved one is a warning and
renders in red, so use this form when a broken reference should be noticed.

## Hover previews

Every reference shows a preview card on hover: type badge, ID, title, selected
fields, and the target's **current check state** — so you can see that a constraint
is being violated without leaving the page you are reading.

Which fields appear is set per type:

```yaml
types:
  constraint:
    preview: [status, limit, rationale]
```

Previews are generated at build time and inlined into the page. There are no
network calls. Without JavaScript they degrade to ordinary working links. They are
keyboard-accessible (focus to show, Escape to dismiss) and tap-to-open on touch
devices.

## Traceability on an item page

Each item page lists **Outgoing** links (what it declares) and **Incoming** links
(what points at it), grouped by relationship. Combined with
[coverage](coverage.md), this is the traceability story: from a requirement you can
reach the log entries that worked on it, the decision that satisfies it, and the
test that verifies it.
