# The standard library

A new project's `refdes.yaml` doesn't need to declare `requirement`,
`constraint`, or any of the usual hardware-traceability vocabulary by hand.
`refdes` ships a **standard dictionary** — six item types, their fields, their
status lifecycles, and the link vocabulary connecting them — bundled inside
the package and resolved live, by reference, into every project that opts in.

```yaml
standard:
  base: hardware
  version: 1
  presets: []
```

That's the entire `standard:` block a project needs. No `types:`,
`link_types:`, or `field_sets:` key has to appear anywhere in `refdes.yaml` —
their absence is the point: this file records a *pointer* to the standard, not
a copy of it. See [schema reference](schema-reference.md#standard) for the
key-by-key syntax.

## What's in it

Six types, each with a `prefix`, a `status` lifecycle (where it has one), and
the standard link vocabulary:

| Type | Prefix | Status lifecycle | Purpose |
|---|---|---|---|
| `requirement` | `REQ` | `draft` → `active` → `retired` | What the design must do |
| `constraint` | `CON` | `draft` → `active` → `retired` | A numeric bound, checkable in a `calc` block |
| `decision` | `DEC` | `proposed` → `in_progress` → `accepted` / `on_hold` / `rejected` / `superseded` | A settled choice, with options considered |
| `test` | `TST` | `planned` → `passing` / `failing` / `blocked` | Proof a requirement or constraint holds |
| `component` | `CMP` | `candidate` → `selected` / `obsolete` | A specific part realizing a decision |
| `log` | `LOG` | — (append-only) | The dated, unedited record of how the design got here |

And thirteen link verbs, each declared on the type that would naturally author
it — `refines`, `derives_from`, `satisfies`, `constrained_by`, `verifies`,
`addresses`, `records`, `amends`, `supersedes`, `selects`, `blocked_by`, plus
the self-inverse `equivalent`/`alternate` pair on `component`. See
[links](links.md) for how declaring one end gives you the other for free.

Every type also carries `owner`/`last_reviewed` (the `stewardship` field set)
and `source`/`note`/`tags` (`provenance`) — see [field_sets and
`include:`](#field_sets-and-include) for how those are assembled without
retyping five fields on every type.

## Opting out

`standard: none`, or omitting `standard:` entirely, is the explicit escape
hatch: nothing is pre-seeded, and `types:`/`link_types:` are fully authored by
the project, exactly like every `refdes` project before this feature existed.
A config written before this feature shipped needs no changes to keep working.

## Overriding and extending

The project's own `types:`/`link_types:`/`field_sets:` blocks are **merged**
on top of the resolved standard, not replaced by it. A `types.<name>:` block
naming a type the standard already provides is merged into it field-by-field;
naming something new adds a type from scratch.

```yaml
types:
  requirement:
    fields:
      erratum_ref: { type: text, on_change: log }   # new field, additive
      rationale:   null                              # inherited field removed
      status:      { type: enum, choices: [draft, active, retired, deprecated],
                     default: draft, on_change: invalidate }   # full redeclare
```

- `fields:` and `links:` merge **by key**: a same-named field replaces the
  inherited one, a new key adds one, and `field: null` removes it. A field's
  own spec is never partially merged — redeclaring `status` means redeclaring
  every key on it (`choices:` included), not just the ones you're changing.
- Every other type-level scalar (`label`, `prefix`, `check_severity`,
  `coverable`, `coverable_statuses`, `append_only`, ...) is replaced wholesale
  when the project gives it, left untouched otherwise.
- Removing something the config still relies on is a load-time error, not a
  silent gap: `types.component: null` fails the build if anything still
  declares `selects: [component]`, naming both sides.

```yaml
types:
  component: null   # errors here if any type still declares a link to it
```

## `field_sets` and `include:`

Reusable groups of field definitions, declared once and pulled into a type
with `include:`. The standard is built this way internally:

```yaml
field_sets:
  provenance:
    source: { type: text, on_change: log }
    tags:   { type: list, on_change: ignore }

types:
  requirement:
    include: [provenance]
    fields:
      text: { type: text, required: true }
```

Included fields are merged in list order (a later `include:` wins over an
earlier one on a name collision), then the type's own `fields:` are applied on
top — a type's own declaration always wins over anything it includes. A
project can declare its own `field_sets:` for fields repeated across its own
custom types; they merge with the standard's, by name, under the same rules as
everything else here.

## Presets

Bundled, curated extensions to the base standard, opted into by name:

```yaml
standard:
  base: hardware
  version: 1
  presets: [design-debate]
```

`design-debate` (the only preset shipped today) adds `debate`, `option`,
`claim`, and `position` — a vocabulary for recording the argument that
produces a decision, not just the decision itself. It isn't in the base
standard because most projects don't need it, and pre-seeding it everywhere
would reproduce the exact config bloat the standard exists to avoid.

Presets are **peers**: each is purely additive against the base and against
every other selected preset, and none may extend or override another's type.
A name collision — two presets declaring the same type, or a preset colliding
with the base — is a hard error at load time, naming both sides, never a
silent pick-a-winner:

```
configuration error: preset 'design-debate' declares type 'option', which
preset 'some-later-preset' also declares. Presets must not collide with the
base standard or with each other -- this is a bug in the preset bundle, or
drop one of the two presets.
```

Only the *project's own* overlay may reach into a preset-provided type and
extend or override it, using the same merge rules as anything else.

## Versioning and pinning

`standard.version` is a single pinned integer — never the string `"latest"` —
naming a bundle that is byte-identical forever once shipped:
`hardware@1` means exactly the same thing today as it will after any future
`refdes` upgrade. The installed package carries every version it has ever
shipped, so a project pinned to an old version keeps working unchanged; moving
to a newer one is a deliberate act, not something that happens under a
project on an ordinary upgrade.

`refdes standard upgrade` (a guided, deliberate migration between versions)
and `refdes init` (which would write a fresh project's `standard:` block for
you) are designed but not implemented yet — see
[docs/design/standard-library.md](design/standard-library.md) if you want the
full design. For now, hand-write the `standard:` block shown at the top of
this page.

## `coverable`, `coverable_statuses`, `verifying_statuses`, and `required_when`

These four are general schema-engine capabilities, not standard-specific
plumbing — available to any type in any project, `standard: none` included.
The standard's own types simply use them:

- `coverable:` / `coverable_statuses:` govern whether, and at which statuses,
  an item participates in [coverage](coverage.md#what-gets-coverage) at all.
- `verifying_statuses:` governs which statuses of a linked verifier (a type
  declaring a `verifies`-family link) actually count as having verified,
  rather than merely linked — see [coverage](coverage.md#which-statuses-count-as-verifying).
- `required_when:` makes a field conditionally required on a sibling field's
  value or a link being present — see [schema
  reference](schema-reference.md#required_when). The standard's own
  `decision.rationale` uses it (`required_when: {status: rejected}`), toggled
  off by setting `require_rejection_rationale: false` in
  `refdes-project.yaml`.

## Not yet built

This document describes what's implemented today. The full design in
[`docs/design/standard-library.md`](design/standard-library.md) also covers a
parts index and part-equivalence links, `blocked_by:` and a blocked-decision
cascade report, JSON Schema emission for editor autocomplete, and `refdes
init`/`refdes standard upgrade` — none of those exist yet.
