# Change tracking

Every field declares what a change to it *means*. This is what will drive suspect
links, baseline diffs, and item timelines once the git history layer lands — and it
already drives the content hash today.

## The three modes

| `on_change` | In the timeline | Counts in a baseline diff | Invalidates downstream |
|---|---|---|---|
| `invalidate` | yes | yes | yes |
| `log` | yes | no | no |
| `ignore` | no | no | no |

`invalidate` is for the substance: a requirement's text, a constraint's limit, a
decision's rationale. `log` is for things worth seeing but harmless: owner, tags,
source reference. `ignore` is for noise: timestamps, generated fields.

Note this controls **significance, not retention**. Git still records every byte.
`ignore` means "the history layer does not treat this as a change", not "this is
not stored".

## Why `log` exists

Without it, suspect links are unusable. If a change of owner marks fifty
downstream links suspect, people stop reading the badges within a week and the
feature is dead. Roughly half your fields should be `log`.

## Setting it

**Per field, in the schema** — where nearly all of it should live:

```yaml
types:
  constraint:
    fields:
      limit:         { type: limit,  on_change: invalidate }
      rationale:     { type: text,   on_change: invalidate }
      source:        { type: text,   on_change: log }
      owner:         { type: person, on_change: log }
      tags:          { type: list,   on_change: log }
      last_reviewed: { type: date,   on_change: ignore }
    body: { on_change: invalidate }
```

Anything not declared falls back to `history.default` (`invalidate` in the starter
schema).

**Per item**, in the front-matter, when one item genuinely differs:

```yaml
history:
  fields:
    owner: ignore
  reason: "Owner rotates weekly during bring-up; not a meaningful change."
```

A `reason:` is expected — omitting it is a warning. One line, and every
suppression is self-documenting.

**Whole item**, as a scalar:

```yaml
history: ignore
```

Useful for draft items not yet baselined, and for items rewritten wholesale by a
spreadsheet re-import.

Precedence: item field override → whole-item mode → schema field → project default.

## The content hash

Each item's hash is computed over its `invalidate` fields, its links, and its body
(if the body is `invalidate`). It appears at the foot of every item page and in
`items.json`:

```json
"content_hash": "673e6ba11269f350"
```

Change an owner and it stays identical. Change a limit and it changes. That is the
whole mechanism: a link records the hash of its target at review time, and a
mismatch later means the target moved and the link needs re-reviewing.

Imported items keep the hash their own project computed, so cross-project suspect
links work the same way.

## Auditing

If fields can be excluded from invalidation, somebody could quietly downgrade one
to hide a substantive change. Two things close that:

1. The policy lives in `refdes.yaml`, in the repo, versioned like anything else.
2. `refdes audit` lists everything currently suppressed.

```
Schema fields not tracked as 'invalidate':
  constraint
    last_reviewed    ignore
    owner            log
    source           log
    tags             log

Item-level overrides:
  REQ-PWR-004    owner -> ignore  — Owner rotates weekly during bring-up.

Append-only entries edited after sealing:
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
suspect-link badges, baselines, and change reports between two baselines. The
`on_change` policy and the content hash it depends on are implemented and tested;
the git reader is not written.
