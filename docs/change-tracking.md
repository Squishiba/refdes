# Change tracking

Every field declares what a change to it *means*. This drives the content hash
today, and [the baseline diff](lifecycle.md#the-diff-what-changed-and-since-when)
built on top of it; it's also what will drive suspect links and item timelines
once the git history layer lands.

## The three modes

| `on_change` | In the timeline | Counts in a baseline diff | Invalidates downstream |
|---|---|---|---|
| `invalidate` | yes | yes | yes |
| `timeline` | yes | no | no |
| `ignore` | no | no | no |

**The last two columns are implemented; the first is not.** `refdes
revision`/`refdes release` stamp a content hash over `invalidate` fields
only, and `refdes audit`'s baseline diff reports an item as changed
precisely when that hash moved — so "counts in a baseline diff" is real,
item-scoped behavior today. "In the timeline" describes a continuous,
field-level history the parked git-reader layer would provide; until it
exists, `timeline` and `ignore` are indistinguishable in every *other*
observable way -- see [what is not built yet](#what-is-not-built-yet).

`invalidate` is for the substance: a requirement's text, a bound's limit, a
verdict entry's rationale. `timeline` is for things worth seeing but harmless: owner, tags,
source reference. `ignore` is for noise: timestamps, generated fields.

Note this controls **significance, not retention**. Git still records every byte.
`ignore` means "the history layer does not treat this as a change", not "this is
not stored".

## Why `timeline` exists

Without it, suspect links are unusable. If a change of owner marks fifty
downstream links suspect, people stop reading the badges within a week and the
feature is dead. Roughly half your fields should be `timeline`.

This is design intent for the history layer. Today a `timeline` field is
excluded from the content hash exactly like an `ignore` field -- with one
exception: a history-backed entry (a log entry) carries a history digest that
covers every field, so a `timeline` change on a captured entry surfaces as
"edited after captured". Marking a field `timeline` now is a forward-looking
choice, not a functional one -- it costs nothing and means the schema is
already correct once the history layer exists.

## Setting it

**Per field, in the schema** — where nearly all of it should live:

```yaml
types:
  bound:
    fields:
      limit:         { type: limit,  on_change: invalidate }
      rationale:     { type: text,   on_change: invalidate }
      source:        { type: text,   on_change: timeline }
      owner:         { type: person, on_change: timeline }
      tags:          { type: list,   on_change: timeline }
      last_reviewed: { type: date,   on_change: ignore }
    body: { on_change: invalidate }
```

Anything not declared falls back to `on_change.default` — a project setting in
`refdes-project.yaml` whose built-in default is `invalidate`.

**Per item**, in the front-matter, when one item genuinely differs:

```yaml
on_change:
  fields:
    owner: ignore
  reason: "Owner rotates weekly during bring-up; not a meaningful change."
```

A `reason:` is expected with a `fields:` override — omitting it is a warning
(a `mode:`-only mapping is not warned on). An entry in `fields:` may also name
`body` — it is a field override, so it wins over the item's whole-item mode; a
body left out of `fields:` follows that mode. One line, and every
suppression is self-documenting. A type that declares its own field named
`on_change` owns that key; the override applies to types without such a field.

**Whole item**, as a scalar:

```yaml
on_change: ignore
```

Useful for draft items not yet baselined, and for items rewritten wholesale by a
spreadsheet re-import. The mapping form works here too — `mode:` with an optional
`reason:` — and is the only way to give a whole-item suppression a reason:

```yaml
on_change:
  mode: ignore
  reason: "Rewritten wholesale by the spreadsheet re-import."
```

Precedence: item field override → whole-item mode → schema field → project default.

## The content hash

Each item's hash is computed over its type, its `invalidate` fields, its links,
its body (if the body is `invalidate`), and — since hash format 5 — the bytes
of the local images its body references, so replacing a figure's bytes marks
every item using it changed even when no text moved. It appears at the foot of
every item page and in `items.json`:

```json
"content_hash": "673e6ba11269f350"
```

Change an owner and it stays identical. Change a limit and it changes. That is the
whole mechanism, once suspect links exist: a link records the hash of its target
at review time, and a mismatch later means the target moved and the link needs
re-reviewing.

Imported items keep the hash their own project computed, so cross-project suspect
links work the same way.

### Hash format versioning

The content hash definition is versioned (`hash_format`, recorded per baseline
and seal entry; currently **6**). When the hash definition changes (e.g. link
targets switching from display-id text to resolved keys, `checks: against:`
entries being reduced to keys, a cross-item calc reference's resolved value
joining the hash, referenced image bytes joining it (format 5), or — format 6 — the
cross-item references of *inline calc spans* joining the hash alongside a
fence's; a span's resolvable `source()` value has been hashing there since
format 4, and format 6 only adds its discovery by `refdes fetch`), a baseline
stamped under the old definition
would show every item as "changed" purely because the *definition* moved, not
because content changed.

**Migration is automatic where content is provably unchanged.** When a
baseline is read (by `refdes audit`, `refdes revision`, `refdes release`,
`refdes former-ids propose`, or `refdes keys adopt`), each entry not already at
the current format is checked: the live item is found and its hash is recomputed
under the entry's recorded format. If that recomputed hash matches what was
stored, the item's content demonstrably hasn't changed — on a writable run the
entry is rewritten in place to the current format (`carried`). If it doesn't
match, the item genuinely changed since the stamp; the entry is left at the
format it was stamped at — with one exception: rebasing a baseline onto keys,
`refdes keys adopt` explicitly marks an uncomparable entry format 1 as it
reports it (described below). An item with no live counterpart (deleted, or
renamed without `former_ids:`) is likewise left alone — that's the ordinary
"removed" case.

This conditional carry-forward means a partially-migrated baseline stays
precisely describable: some entries at format 3, some still at format 1. Those
left-behind entries are what `refdes keys adopt` reports as `uncomparable
baseline entry <name>: <id>` (and `uncomparable seal entry <file>: <id>`), so
the gap is named before anything is rebased. Everywhere else they are reported
as **uncomparable**, never as `changed`: `refdes audit` prints an
`uncomparable N` line with the ids in its baseline diff, and `refdes
revision`/`refdes release` name them when re-stamping an existing name
conflicts. `changed` claims the content moved, and for these entries refdes
cannot make that claim — it can only say it can't tell; they are not counted
as unchanged either. What to do: review the item's content, then stamp a new
baseline once it has been reviewed.

## Auditing

If fields can be excluded from invalidation, somebody could quietly downgrade one
to hide a substantive change. Two things close that:

1. The policy lives in the schema — for a standard-pinned project, in the pinned
   standard's own types (the `standard:` pin is in the repo, so the policy is
   versioned by it); a project that declares its own types puts the policy in its
   `refdes-schema.yaml`.
2. `refdes audit` lists everything currently suppressed.

```
Schema fields not tracked as 'invalidate':
  bound
    last_reviewed    ignore
    note             timeline
    owner            timeline
    source           timeline
    tags             ignore

Item-level overrides:
  REQ-PWR-004    owner -> ignore  — Owner rotates weekly during bring-up.

Append-only entries edited after sealing:
  (none)

Accepted append-only reseals (durable history):
  (none)
```

Suppression is allowed. Invisible suppression is not.

## Changing the policy later

Changing a field's `on_change` changes the content hash of every item with that
field. Once suspect links exist, a one-line config edit would mark everything
suspect at once — which is exactly how a team decides the feature is broken and
turns it off.

The planned handling is to detect that the *policy* changed rather than the
content, re-bless automatically, and record it in the baseline as a policy
migration. Until the history layer exists this is only a hash churn, but it is
worth knowing before you reorganise the schema.

## What is not built yet

The git-backed layer: field-level diffs between revisions, per-item timelines,
and suspect-link badges. The `on_change` policy and the content hash it
depends on are implemented and tested, and baselines (`refdes
revision`/`refdes release`) plus the item-scoped change report between two of
them are built on top of that hash and need no git reader at all -- see
[project lifecycle](lifecycle.md). What's left needs actual history: *what*
changed within an item, not just that it did, and a continuous view across
many small steps rather than two-point comparisons between named baselines.
