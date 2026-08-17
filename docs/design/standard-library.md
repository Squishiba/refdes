# The standard library — design spec

## Decision

Refdes today is a schema engine that ships with no schema: `refdes.yaml` must
declare every item type, every field, and every link before a project can hold
a single item. That means every project reinvents what a "requirement" is, and
two projects can both write `satisfies:` and mean different things.

Refdes will instead ship a **standard dictionary** — built-in definitions of
the common hardware-traceability item types, their fields, their status
lifecycles, and the link vocabulary connecting them. A new project gets these
by default, with zero configuration. A project may extend the vocabulary with
its own types and links, and may override or remove parts of the standard it
disagrees with. Reusable field sets (declared once, `include:`d by a type)
remain available as a separate, optional mechanism for projects defining
custom types.

This document specifies that standard: its content, how a project extends or
overrides it, how it is versioned and pinned, how it interacts with imports,
what it leaves for field sets and for two related backlog items to still do,
what it costs existing projects to adopt, and how a project selects it (and
optional presets on top of it) at `init` time and afterward.

Design only. Nothing in this document has been implemented.

---

## 1. The standard dictionary itself

Six types: `requirement`, `constraint`, `decision`, `test`, `component`,
`log`. No more.

Types considered and left out of the base standard: `risk` (FMEA-style
severity × likelihood scoring is a different kind of object than anything
modeled here, and nothing in the record of real usage that informed this
design shows a need for it yet); `interface` as a type distinct from
`requirement` (interface-contract items observed in practice look like
ordinary requirements with a distinct per-item ID prefix, which the tool
already supports without a new type); `part` as distinct from `component`
(the only concrete ask here is to index a field — `part_number` — that
already exists on `component`, not to add a new type). A design-debate
vocabulary (`debate`, `option`, `claim`, `position`) is real and was
prototyped successfully against a real project, but it belongs in an optional
preset, not the base — see §8. Baking it into every zero-config project would
reproduce the exact config-surface bloat this design exists to fix (that
prototype is what took one real project from 5 types to 9 and roughly
doubled its field-declaration count).

The standard is authored using one piece of plumbing that isn't part of the
core decision but is required to keep it from being fifty-odd duplicate
field declarations: **`field_sets:`**, named reusable groups of field
definitions merged into a type's own `fields:` via `include:`. This is the
mechanism the standard is built with, not just a convenience projects may
reach for; see §5.

The standard's types below also use `coverable:`, `coverable_statuses:`, and
`verifying_statuses:` — but those are general schema engine capabilities,
not standard-specific plumbing, exactly like `required:` and
`satisfying_statuses:` already are. They're specified in §2, alongside the
rest of the engine's override-safety machinery, because they're available to
every project's own type declarations whether or not that project uses the
standard at all.

### Types, fields, and status lifecycles

```yaml
# src/refdes/standards/hardware/v1/base.yaml — shipped inside the refdes package

field_sets:
  provenance:
    source: { type: text, on_change: log }
    note:   { type: text, on_change: log }
    tags:   { type: list, on_change: ignore }
  stewardship:
    owner:         { type: person, on_change: log }
    last_reviewed: { type: date,   on_change: ignore }

link_types:
  refines:        { inverse: refined_by,    label: "Refines" }
  derives_from:   { inverse: derived_by,    label: "Derives from" }
  satisfies:      { inverse: satisfied_by,  label: "Satisfies" }
  constrained_by: { inverse: constrains,    label: "Constrained by" }
  verifies:       { inverse: verified_by,   label: "Verifies" }
  addresses:      { inverse: addressed_by,  label: "Addresses" }
  records:        { inverse: recorded_by,   label: "Records" }
  amends:         { inverse: amended_by,    label: "Amends" }
  supersedes:     { inverse: superseded_by, label: "Supersedes" }
  selects:        { inverse: selected_by,   label: "Selects" }

types:
  requirement:
    prefix: REQ
    label: Requirement
    preview: [status, text]
    coverable: true
    coverable_statuses: [active]
    fields:
      text:      { type: text, required: true, on_change: invalidate }
      status:    { type: enum, choices: [draft, active, retired], default: draft, on_change: invalidate }
      rationale: { type: text, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      refines: [requirement]
    body: { on_change: invalidate }

  constraint:
    prefix: CON
    label: Constraint
    preview: [status, limit, rationale]
    coverable: true
    coverable_statuses: [active]
    fields:
      title:     { type: text, required: true, on_change: invalidate }
      limit:     { type: limit, required: true, on_change: invalidate }
      status:    { type: enum, choices: [draft, active, retired], default: draft, on_change: invalidate }
      rationale: { type: text, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      derives_from: [requirement, constraint]
    body: { on_change: invalidate }

  decision:
    prefix: DEC
    label: Decision
    preview: [status, title, date]
    satisfying_statuses: [accepted]
    check_severity: error
    fields:
      title:     { type: text, required: true, on_change: invalidate }
      status:    { type: enum, choices: [proposed, in_progress, accepted, on_hold, rejected, superseded],
                   default: proposed, on_change: invalidate }
      rationale: { type: text, on_change: invalidate, required_when: {status: rejected} }
      date:      { type: date, on_change: log }
      options:   { type: options, on_change: invalidate }
      checks:    { type: checks, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      satisfies:      [requirement]
      constrained_by: [constraint]
      supersedes:     [decision]
      selects:        [component]
    body: { on_change: invalidate }

  test:
    prefix: TST
    label: Test
    preview: [status, title]
    verifying_statuses: [passing]
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [planned, passing, failing, blocked], default: planned, on_change: invalidate }
      method: { type: text, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      verifies: [requirement, constraint]
    body: { on_change: invalidate }

  component:
    prefix: CMP
    label: Component
    preview: [status, title, part_number]
    satisfying_statuses: [selected]
    fields:
      title:       { type: text, required: true, on_change: invalidate }
      part_number: { type: text, on_change: invalidate }
      refdes:      { type: list, on_change: log }
      status:      { type: enum, choices: [candidate, selected, obsolete], default: candidate, on_change: invalidate }
      datasheets:  { type: citations, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      satisfies: [requirement]
    body: { on_change: invalidate }

  log:
    prefix: LOG
    label: Log entry
    plural: Log entries
    append_only: true
    preview: [date, author, summary]
    fields:
      date:    { type: date, required: true, on_change: invalidate }
      summary: { type: text, required: true, on_change: invalidate }
      author:  { type: person, on_change: invalidate }
    include: [provenance]
    links:
      addresses: [requirement, constraint]
      amends:    [log]
      records:   [decision]
    body: { on_change: invalidate }
```

Without `field_sets:` this file is roughly 55 field declarations across six
types. With it, it's 24 type-local fields plus two set definitions (five
fields) reused eleven times — and every future type or preset pays one
`include:` line, not N repeated lines.

Status lifecycles are deliberately *not* collapsed into one shared
definition, even where a field name repeats: `status` means something
structurally different on a `requirement` than on a `decision` than on a
`test`, and real projects that tried to share one definition across all of
them found the lifecycles didn't actually match. Only fields that are
byte-identical across types — `tags`, `note`, `source`, `owner`,
`last_reviewed` — go into a `field_sets:` entry.

`decision`'s status list adds `rejected` beyond the plain
proposed/in-progress/accepted/on-hold/superseded progression, naming "this
was proposed, analyzed, and explicitly ruled out" as distinct from `on_hold`
(paused, might resume) and `superseded` (replaced by a later *accepted*
decision). The status value itself remains the one thing in this document
not backed by observed usage in a real project; if it proves unwanted,
dropping it back to five values is a one-line change to `v1/base.yaml`
before it ships, or a project-level override afterward (§2).

A rejected decision needs somewhere to put *why*. Its absence in an earlier
draft of this standard looked like an oversight, since `requirement` and
`constraint` both carry a `rationale` field and a decision is the type where
"why" is the entire point. `decision.rationale` above carries the same
`on_change: invalidate` treatment as `requirement.rationale` and
`constraint.rationale`, and is conditionally required exactly when it
matters most: `required_when: {status: rejected}`. This is a general schema
mechanism, not a special case wired to this one status — see §2 for its full
specification, including how the requirement is toggled off project-wide,
and how it behaves if a project removes `rejected` from the status list
without also touching the condition.

`rationale` isn't the only place a rejected decision's reasoning can live,
and it isn't always the right one. It's the decision's *current*, single
explanation — mutable, meant to state the reasoning as understood now, and
overwriting it destroys whatever it said before. For reasoning that's
contested or evolved over time — the back-and-forth that led to a rejection,
a trade-off argued one way before the decision landed — the existing `log` →
`records` → `decision` edge (the link table below) is the better home: a
dated, append-only, sealed account of the reasoning as it happened, immune
to later editing. Reach for `rationale` to state the decision's current
justification somewhere a reader can find without digging; reach for one or
more `log` entries when the reasoning itself is worth preserving exactly as
it was argued at the time — a single mutable field can't hold "we considered
X, Y showed it violated the current-limit constraint, we went with Z" as a
real timeline, and shouldn't try to.

`log` gets `include: [provenance]` only, not `stewardship` — an append-only
entry has no reviewer rotation and no "last reviewed" date; it's a historical
record, not a living document.

### Link vocabulary

Ten verbs, each declared on the type that would naturally author it in
front-matter; the other direction is a computed backlink, not something a
project ever writes.

| verb (declared on) | inverse (computed) | source → allowed targets | meaning |
|---|---|---|---|
| `refines` (requirement) | `refined_by` | requirement → requirement | a more detailed restatement of a broader requirement |
| `derives_from` (constraint) | `derived_by` | constraint → requirement, constraint | why this bound exists |
| `satisfies` (decision, component) | `satisfied_by` | decision/component → requirement | claims to fulfill this requirement |
| `constrained_by` (decision) | `constrains` | decision → constraint | bound by, and checkable against, this constraint |
| `verifies` (test) | `verified_by` | test → requirement, constraint | demonstrates the claim holds |
| `addresses` (log) | `addressed_by` | log → requirement, constraint | progress noted, not yet settled |
| `records` (log) | `recorded_by` | log → decision | documents the process behind that decision |
| `amends` (log) | `amended_by` | log → log | append-only correction chain |
| `supersedes` (decision) | `superseded_by` | decision → decision | replacement |
| `selects` (decision) | `selected_by` | decision → component | picks this specific part to realize itself |

Two choices here are worth explaining rather than taking as given:

- **`constrained_by`, not `constrains`, is what a decision author types.**
  "A decision constrains a constraint" reads backwards — a decision is bound
  *by* a constraint, and `constrains` is the constraint's own page saying
  which decisions it binds. This is also the single most heavily used verb
  observed in real project usage, which is corroborating evidence for
  standardizing on this direction rather than the reverse.
- **`selects` replaces `implements`.** A decision→component edge (which
  specific part realizes this decision) is real and useful, but `implements`
  is easy to confuse with `satisfies` if declared against the same target
  types, and in observed usage it was declared that way — zero uses, because
  nothing could tell it apart from `satisfies`. `selects`/`selected_by` names
  the edge distinctly and pairs naturally with `component.status: selected`.
- **`refines` and `derives_from` are kept distinct rather than merged**,
  because they answer different questions: `refines` is same-type
  decomposition (a requirement broken into more specific requirements);
  `derives_from` is cross-kind derivation (a constraint's numeric bound
  traces back to the requirement or constraint that justifies it).

---

## 2. Inheritance and override semantics

**Merge order:** the built-in base standard (`standard.base`, at the pinned
`standard.version`) → any selected presets, applied additively (§8) → the
project's own `refdes.yaml`, applied as an overlay.

The project overlay uses **deep merge, with `null` deleting a key.** A
`types.<name>:` block in the project that names a type already provided by
the base or a preset is merged into it, not replacing it wholesale:

- `fields:` and `links:` are merged *by key*. A project field with the same
  name replaces the inherited one; a new key adds a field; `field: null`
  removes it from the merged type.
- Other type-level scalars (`label`, `prefix`, `check_severity`,
  `satisfying_statuses`, `append_only`, `coverable_statuses`) are replaced
  wholesale when the project gives them, left untouched otherwise.
- A field's own spec (`{type, on_change, choices, ...}`) is not merged within
  itself — redeclaring a field means redeclaring every key on it, so
  `status.choices` can't drift by partial override.
- A `types.<name>:` block that names something not already provided by the
  base or a preset is simply added — this is how a project defines a wholly
  new type.

```yaml
# project refdes.yaml — add a field, remove a field, extend a status list
types:
  requirement:
    fields:
      erratum_ref: { type: text, on_change: log }   # new field, additive
      rationale:   null                              # inherited field removed
      status:      { type: enum, choices: [draft, active, retired, deprecated],
                     default: draft, on_change: invalidate }   # full redeclare, adds a value
```

The alternative — a `types.<name>:` block fully *replacing* the inherited
type the moment it's mentioned at all — was considered and rejected as the
default. It's simpler to implement and reason about (one rule: your YAML is
the config, no hidden merge), but it reintroduces exactly the copy-paste
burden the standard exists to remove: adding one field to `decision` would
mean retyping `title`/`status`/`date`/`options`/`checks` and both `include:`
lines. It remains available as a fallback if deep merge proves too magic in
practice, but deep merge is the recommendation.

**Removing something the config relies on is a load-time error, not a
runtime surprise.** `link_types.satisfies: null` at the project level removes
that verb; if any type still references it in `links:` afterward, that's a
`SchemaError` at load, naming the type and the dangling verb — the same
posture the existing board-registry path-collision check already takes. The
same rule applies to removing a whole type: `types.component: null` errors
if anything still declares `selects: [component]`.

### Coverage participation is schema language, not standard content

`coverable: bool`, `coverable_statuses: list[str]`, and `verifying_statuses:
list[str]` are not part of the standard dictionary — they are general schema
engine capabilities, exactly like `required:`, `on_change:`,
`satisfying_statuses:`, and `check_severity:` already are. They're available
to every project's own `types:` declarations regardless of whether that
project uses the standard, a preset, or `standard: none`. §1's standard
simply uses them on its own six types, the same way any bespoke schema is
free to use them on its own — this is what makes overriding or removing a
standard type safe, per the rule above, rather than something the standard
specifically needs.

They exist to replace three places the coverage computation hardcodes a type
or status *name* directly in Python instead of reading it from
configuration:

- A hardcoded tuple of exactly two type names gates which items get a
  `Coverage` object computed at all → replaced by `coverable: bool` on the
  type.
- A hardcoded `status == "retired"` string excludes retired items from
  coverage → replaced by `coverable_statuses: list[str]` on the type; unset
  means no exclusion beyond a sensible default (below).
- A hardcoded type-name check gates the per-item "claimed but not verified"
  warning and whether "satisfied but not verified" warnings are suppressed
  when nothing verifies anything yet. This one splits in two: which items
  can *verify* something at all is now derived directly from the schema's
  own `links:` declarations — any type that declares a `verifies`-family
  link, by its own name or its computed inverse, is a verifier, which needs
  no new flag since every project's link declarations already carry this
  information. Which *statuses* of a verifier actually count as verified,
  as opposed to merely linked, is `verifying_statuses`, mirroring
  `satisfying_statuses` exactly — unset means every link counts, the same
  default `satisfying_statuses` already uses.

**The compatibility hazard, and the fallback.** These hardcodes are why a
bespoke `standard: none` project with its own hand-authored `requirement`
and `test` types works today without declaring anything — the engine
already knows what those names mean, by convention. If `coverable` became
the *sole* mechanism, every such project would go silently uncovered the
moment it upgraded `refdes`, because a flag that didn't exist when its
schema was written can't be present in it.

So the type-name fallback stays, demoted from the only path to a fallback
with a warning: if a type does not declare `coverable:` at all, the loader
checks whether its name is literally `requirement` or `constraint` —
today's behavior, preserved exactly — and emits one project-level warning
naming the fix:

```
WARNING types.requirement does not declare 'coverable:'; falling back to
  name-based detection (requirement/constraint are coverable by convention).
  Add 'coverable: true' explicitly — this fallback is removed in refdes 1.0.
```

The same fallback, narrowly scoped to preserve today's behavior exactly,
keeps the "claimed but not verified" warning restricted to items literally
named `requirement` when reached through the fallback path — it does not
also start firing for `constraint`-named types just because they happen to
match the same name check, which would be a new warning appearing on an old
project with no config change to explain it. Once a project explicitly
declares `coverable: true` on its own `constraint`-equivalent type, the
warning applies there too, on the general path — an opt-in improvement, not
a compatibility break.

The verifier-detection half needs no equivalent fallback: because it's
derived from `links:` declarations every project already has rather than a
new flag, any project with a test-like type that already declares a
`verifies`-shaped link keeps working with zero changes, standard or not.

`coverable_statuses` left unset on a coverable type defaults to excluding
`status == "retired"` if the type has a `status` field, and excluding
nothing otherwise. This needs no warning — it isn't a name-detection
compatibility shim, just an unconfigured default, the same posture
`satisfying_statuses: None` already takes.

The name-based `coverable` fallback, and its warning, is removed at the next
*major* version of `refdes` itself — the same deprecation horizon §3 already
applies to dropping support for old `standard.version` bundles, kept
consistent rather than inventing a second policy for the same kind of
change.

### Conditional requiredness: `required_when`

A field can be required only when another field on the same item currently
holds a particular value — the mechanism `decision.rationale` uses in §1 to
require a reason exactly when `status: rejected`. Like the coverage flags
above, this is general schema language available to any field on any type,
standard or bespoke — not a special case wired to one field.

```yaml
fields:
  rationale:
    type: text
    on_change: invalidate
    required_when: { status: rejected }
```

- The mapping's keys name other fields on the *same* type; a field cannot
  name itself.
- Each value is a scalar or a list of scalars — a list means "any of these"
  (an OR within that one key).
- Multiple keys are ANDed together: every named field must currently match
  one of its listed values for the dependent field to become required.
- This is deliberately not a general expression language: no OR across
  different keys, no negation, no nesting. A need that can't be expressed as
  "all of these fields currently match one of these values" wants a
  different, separate mechanism, not an extension of this one.
- A field declares `required: true` or `required_when:`, never both —
  combining them is redundant, since unconditional already implies every
  condition, and is a `SchemaError` at load.

**Which field types `required_when` can key off:** the *condition* fields
(the keys in the mapping, e.g. `status`) must be `type: enum`. An enum has a
closed, declared `choices:` list, which is what lets the loader validate
that every value named in a `required_when:` actually exists, and
re-validate that after any override touches the enum's choices (below).
Extending this to free-typed fields — `text`, `list`, `date` — would mean
either no validation of the referenced value at all, or a type-specific
validator per field type; neither is attempted here. The *dependent* field
(the one that becomes conditionally required) has no type restriction — "is
this field present and non-empty" is the same check `required: true` already
performs regardless of type.

**The diagnostic**, at build time, evaluated per item only when the named
condition currently matches, names the specific rule that fired rather than
reporting a bare missing field:

```
ERROR items/main-io/decisions.md:50 [DEC-IO-002] — 'rationale' is required
  when status is 'rejected' (required_when: {status: rejected})
```

**Load-time validation**, run alongside the merge described above, after
base, presets, and the project overlay have all been applied — because only
the final resolved schema matters: a `required_when:` naming a field that
doesn't exist on the type is a `SchemaError` (difflib-suggested against
known fields, the same suggestion machinery used elsewhere in the tool); one
naming a field that exists but isn't an `enum` is a `SchemaError`; and — the
case this was built for — **one naming a value not present in the
referenced enum's resolved `choices:` is a `SchemaError`**:

```
configuration error: types.decision.fields.rationale.required_when
references status: 'rejected', which is not among status's declared
choices: [draft, in_progress, accepted, on_hold, superseded]. Update or
remove the required_when clause.
```

So a project overriding `decision.fields.status.choices` to drop `rejected`
without also touching `rationale.required_when` doesn't silently leave a
dead, unreachable condition in the merged schema — it fails the build,
naming both sides, the same posture this document already takes for every
other case of removing something the config relies on.

**The toggle.** Whether `decision.rationale` ships `required_when: {status:
rejected}` by default is a project-level choice, not a fixed property of the
standard bundle. That toggle belongs in the project-level config file
introduced separately for calc significant figures and item layout, not in
`refdes.yaml`'s `standard:` block — this document doesn't define that file
or the toggle's exact key, only its contract: a boolean, defaulting to
`true`, consulted by the loader before the standard's `decision.rationale`
field is merged in, which drops the `required_when` clause when the toggle
is `false`. The raw override underneath it is always available regardless of
whether that toggle exists yet — a project can set
`types.decision.fields.rationale.required_when: null` directly, using the
normal override syntax above; the toggle is convenience for one well-known
case, not a new capability.

---

## 3. Versioning and the live reference

**A single integer, pinned in the project config, naming the whole bundle —
base plus whichever presets are selected — not semantic versioning.**

```yaml
standard:
  base: hardware
  version: 1
  presets: []
```

The reasoning for an integer over semver: refdes has one maintainer and one
consumer set, so there is no ecosystem needing fine-grained compatibility
signaling, and classifying every change to the standard as breaking or
non-breaking (which semver demands) is itself an error-prone judgment call —
even an "additive" enum value changes what a pinned project's vocabulary
means. The chosen invariant is simpler and stronger: **whatever
`standard.version: N` names is byte-identical to what shipped as
`hardware@N`, forever.** No breaking/non-breaking classification is ever
needed, because every change bumps the number.

**On a `refdes` tool upgrade, nothing changes for a project with
`standard.version` pinned.** The installed tool bundles every version it has
ever shipped (`hardware/v1/`, `hardware/v2/`, ...) and loads whichever the
project names. Old versions are cheap to keep — they're static data — and are
never silently swapped out from under a project. Dropping support for a very
old version is reserved for a `refdes` *major* version bump, and produces the
same loud, specific error the `imports:` version pin already gives on
mismatch — never a silent fallback to latest.

**Migration is deliberate**, mirroring the philosophy `imports:` already
uses for pinning an upstream project's `items.json` to a version and
upgrading it on purpose:

```console
$ refdes standard upgrade --to 2
```

1. Loads the machine-readable diff bundled between versions
   (`hardware/v1-to-v2.diff.yaml`: renamed/removed/added types, fields,
   links, status values, and preset availability).
2. Reports only what *this* project actually uses that changed, as ordinary
   diagnostics with `file:line` — reusing the existing diagnostic machinery
   rather than a bespoke report format.
3. Does not rewrite item files by default — prose and structured content are
   both too risky to auto-edit. `--apply` handles pure mechanical renames
   only (a link key rename with no semantic change).
4. Bumps `standard.version` only once the user has acted on the report, or
   `--force` to bump anyway and leave the new diagnostics as ordinary build
   errors until fixed.

**Escape hatch:** `standard: none` (or omitting `standard:` entirely, in a
config predating this feature) means exactly today's 0.3.0 behavior — nothing
pre-seeded, `types:`/`link_types:` fully authored by the project. This is
what keeps a wholly bespoke vocabulary possible, and it is the compatibility
path for anything that predates this design.

### Why this has to be a live reference, not a scaffold copy

If `refdes init` copied the chosen standard's `types:`/`link_types:` into the
project's `refdes.yaml`, the project would fork from the bundle the instant
the copy was made. `standard.version: 1` would then describe nothing
verifiable — there would be no single source of truth to diff against for
`refdes standard upgrade`, because the project's copy could already have
drifted from what `hardware@1` actually says, through edits indistinguishable
from deliberate overrides.

Pinning and upgrade both require the opposite: the bundle stays *outside* the
project, inside the installed `refdes` package, and `standard: {base,
version, presets}` is resolved fresh against it on every `load_project()`
call. The project file never contains the standard's `types:`,
`link_types:`, or `field_sets:` — only the pointer to them. This is what
`refdes init` actually writes for the base standard:

```yaml
# the entire file `refdes init` produces (hardware base, no presets)
site:
  title: "New Project — Design Reference"
  out: _site

standard:
  base: hardware
  version: 1
  presets: []

id:
  width: 3
  ledger: .refdes/ids.yaml
```

No `types:`, `link_types:`, or `field_sets:` key appears anywhere in this
file. That absence is the point — their presence would mean a copy had been
taken instead of a reference recorded. `<version>` is never written as the
literal string `"latest"`: `init` resolves it to whichever concrete integer
the installed tool currently ships as newest, and writes that integer, so the
pin is real from the moment the file exists.

Because resolution is live rather than a one-time copy, there is no
meaningful distinction between "selected at `init`" and "added later" — both
are just edits to the same `standard:` block, and the loader does not know or
care which happened. See §8 for what that means in practice for presets,
which are the part of this config most likely to change after a project has
already been started.

---

## 4. Interaction with imports

Today, importing another project's built `items.json` (`imports.py:
_absorb`) warns but doesn't reject when an imported item's type isn't
declared locally, and there is no comparison of link semantics at all — two
projects can both declare and use `satisfies:` while meaning different
target-type sets, and nothing notices.

With a shared, versioned standard, `items.json` should additionally carry the
exporting project's `standard: {base, version}` and, better, a hash of its
fully *resolved* schema — types, links, and field sets, after all local
overrides are applied, not just the version pin, since §2 permits overrides
that can reintroduce divergence even under a matching pin. The importer then
compares:

- **Same resolved-schema hash** → `satisfies`/`verifies`/etc. on an imported
  item are provably the same relationship the consuming project would mean,
  by construction. The existing "type not declared here" warning can become
  a real, validated pass for anything covered by the standard's fixed types.
- **Different hash, same `standard.version`** → local overrides have
  diverged the two projects; name what changed if the diff is cheap to
  compute, otherwise a generic "schemas differ despite matching standard
  pin" notice.
- **Different `standard.version`** → a new, higher-signal diagnostic:
  `import 'platform' was built against hardware@1; this project is on
  hardware@2 — link semantics for imported items are not guaranteed to
  agree.` Strictly more informative than what exists today.

**What still can't be guaranteed, plainly, even with a shared standard:**

1. A shared standard closes divergence on the six built-in types and ten
   verbs. It says nothing about project-specific extensions layered on top
   (§2) — two sibling projects can still independently invent overlapping
   custom verbs for anything outside the standard, by design, since
   extension is the point of the whole mechanism.
2. Matching `standard.version` is necessary but not sufficient — local
   overrides can still diverge two projects pinned to the same base version,
   which is why the resolved-schema hash matters more than the version
   number alone.
3. This is a schema-*shape* guarantee, not a content guarantee. `satisfies`
   meaning the same relationship everywhere doesn't mean every author applies
   it with the same rigor — the standard disciplines the vocabulary, not the
   judgment behind using it.

---

## 5. What's left for field sets

Everything the original ask covered, plus one change in priority: **the
standard itself is authored with `field_sets:`** (`provenance`,
`stewardship`, §1). That moves field sets from "ergonomic fix with
arguable ROI for one project's field count" to required plumbing the
standard cannot ship without — without it, the standard's own six types would
carry the exact repetition problem this document exists to fix, just at
permanent, package-wide scale instead of one project's scale.

What's still genuinely left for a project to use `field_sets:` for directly:
custom fields on custom types the standard doesn't and shouldn't know about —
a project's own repeated domain-specific field, or fields shared across
preset-provided types once a preset is layered on (§8, where the design-debate
preset's `option`/`claim`/`position` types reuse the standard's own
`provenance`/`stewardship` sets rather than redeclaring them). Worth
building — its return on investment is now the standard's own existence
proof, not a hypothetical.

---

## 6. What this does to the "memorize the vocabulary" and "no `init`" gaps

**The link-vocabulary-must-be-memorized problem.** Its root cause was a
bespoke, per-project vocabulary that nobody but its author knew. A shipped
standard removes that root cause for anything within the ten verbs: it's
documented once, and — more importantly — identical across every `refdes`
project that exists, so the memorization cost amortizes across projects
instead of resetting per-project. That's a bigger fix than tooling aimed at
the symptom, because it removes the need for the mitigation rather than
improving the mitigation.

Two things stay worth building regardless:

- **A JSON Schema emission command** (`refdes schema --json`), so an editor
  can autocomplete field and link names while writing. Even a fixed,
  well-known vocabulary benefits from this, and it's the only mechanism that
  covers the extension surface (§2) — a project's own added types and fields
  still need discovery, standard or not.
- **A scaffolding command** (`refdes new <type>`), which becomes *more*
  valuable once the standard is fixed: the scaffold text can be hand-curated
  once per standard type (`status: draft  # draft | active | retired`) and
  stays correct for every project, instead of being generated generically
  from arbitrary schema.

**The no-`init` problem.** Nearly disappears as a design problem — see §3
for the concrete file `init` now writes (three top-level keys, no
`types:`/`link_types:` block at all) and §8 for how a project chooses
optional presets at the same time.

---

## 7. Migration impact

### This repository's own sample project

| type | matches the standard as-is | needs change |
|---|---|---|
| `requirement` | fields; self-referencing decomposition link (renamed to `refines`) | `status` choices `[draft, open, accepted, retired]` → `[draft, active, retired]` — **breaking**: any item currently at `status: open` needs a manual call, `draft` or `active`, nothing should guess this automatically |
| `constraint` | fields; decomposition link unchanged | same status-choices collapse |
| `decision` | `status` is a strict subset of the standard's list — additive, no breakage | `constrains:` → `constrained_by:` (rename plus direction flip); `implements: [component]` → `selects: [component]` — both mechanical front-matter renames across every decision item |
| `component`, `test`, `log` | match directly | — |
| `boards:` | untouched — a separate top-level key, not part of `standard:` | — |

Net effect: `refdes.yaml` shrinks to `site:` / `id:` / `standard:` / `boards:`
(roughly fifteen lines), plus two mechanical key renames in decision
front-matter and a manual reclassification pass on any `status: open` item.

### A real project migrating from a hand-written five-type schema

Evidence from converting a real hardware project's schema (five types,
thirty-three field declarations, eight declared but only five actually used
link verbs) against this design:

- **Zero breakage on links.** All five verbs actually in use
  (`constrained_by`, `satisfies`, `refines`, `supersedes`, `addresses`) match
  this standard exactly — the `constrained_by` direction in §1 was in fact
  derived from this project's own usage, so this is confirmation, not
  coincidence. Of the three declared-but-unused verbs, `implements` is
  dropped (nothing to migrate, since it was never used); `verifies` and
  `amends` are kept even though unused today, because they become necessary
  the moment `test` items or a log correction exist.
- **`derives_from` and `records` are net-new capability**, not currently
  declared at all — zero breakage, immediately available.
- **The `provenance` field set reproduces this project's own hand-derived
  convention verbatim**: `tags` on `ignore`, `note`/`source` on `log`,
  repeated across every type. Adopting `include: [provenance]` matches
  exactly; nothing to reconcile.
- **`decision.status` values are independently confirmed** by real items
  observed at `on_hold` and tests planned at `planned` — both already in this
  standard's lists.
- **What can't be verified without the actual config file**: whether
  `requirement`/`constraint` status uses exactly `[draft, active, retired]`
  or carries an undisclosed fourth value. This is precisely what `refdes
  standard upgrade --dry-run` (§3) is for on any real project — run it rather
  than guess.
- **`rejected`**, the one status value in this document not backed by
  observed evidence (§1), has no cost either way here: purely additive if
  unused.
- Item content, IDs, calc blocks, `checks:`, and board/workspace structure
  are entirely untouched — orthogonal to this change.

---

## 8. Optional presets: selection, composition, and change over time

The standard dictionary (§1) is the default — a project gets it with zero
configuration. Anything beyond it, including a design-debate vocabulary
(`debate`, `option`, `claim`, `position`, for recording the argument that
produces a decision rather than just the decision itself), must be opted
into explicitly. `standard: none` remains the separate, explicit opt-out for
a project that wants to define everything itself — today's 0.3.0 behavior,
kept as the compatibility escape hatch.

### Selecting at `init`

```console
$ refdes init                                   # standard: {base: hardware, version: <latest>, presets: []}
$ refdes init --standard none                    # standard: none — 0.3.0 behaviour, escape hatch
$ refdes init --preset design-debate             # standard: {base: hardware, version: <latest>, presets: [design-debate]}
```

`--standard <name>` selects the base library (`hardware` is the only one
today; the key exists so a future non-hardware base doesn't need a breaking
config change later). `--preset <name>` is repeatable and only ever layers on
top of a base. `--preset` combined with `--standard none` is a load-time
error — `presets require a base standard; set standard.base or drop
presets:` — because every preset's types target base types (a design-debate
`option` links `met_by: [requirement, constraint]`) that don't exist without
one.

### Design-debate preset, sketch

```yaml
# src/refdes/standards/hardware/v1/presets/design-debate.yaml
link_types:
  raises:      { inverse: raised_by, label: "Raises" }
  bears_on:    { inverse: borne_on,  label: "Bears on" }
  met_by:      { inverse: meets,     label: "Met by" }
  resolved_by: { inverse: resolves,  label: "Resolved by" }

types:
  debate:
    prefix: DB
    label: Debate
    preview: [status, title]
    fields:
      title:   { type: text, required: true, on_change: invalidate }
      status:  { type: enum, choices: [open, resolved], default: open, on_change: invalidate }
      chat_id: { type: text, on_change: log }
    include: [provenance, stewardship]
    links:
      resolved_by: [decision]
    body: { on_change: invalidate }

  option:
    prefix: OPT
    label: Option
    preview: [status, title]
    check_severity: info      # a failed criterion is a finding, not a defect
    fields:
      title:  { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [candidate, eliminated], default: candidate, on_change: invalidate }
      checks: { type: checks, on_change: invalidate }
    include: [provenance]
    links:
      met_by: [requirement, constraint]
    body: { on_change: invalidate }

  claim:
    prefix: CLM
    label: Claim
    preview: [status, text]
    fields:
      text:   { type: text, required: true, on_change: invalidate }
      status: { type: enum, choices: [open, accepted, rebutted], default: open, on_change: invalidate }
    include: [provenance]
    links:
      bears_on: [option, requirement, constraint]
    body: { on_change: invalidate }

  position:
    prefix: POS
    label: Position
    preview: [participant, stance]
    fields:
      participant: { type: person, required: true, on_change: invalidate }
      stance:      { type: text, on_change: invalidate }
    include: [provenance]
    links:
      raises: [claim]
    body: { on_change: invalidate }
```

`option.check_severity: info` relies on nothing new — per-type check
severity already exists in the schema engine. This preset's types reuse the
standard's own `provenance`/`stewardship` field sets rather than
redeclaring them, and reference base types only as link targets, never
modifying them. Not modeled here: a participant roster, a Pugh-matrix render,
ballots, or transcript ingestion — separate features the schema doesn't
block, out of scope for this document.

### What presets are, generally

Bundled inside the `refdes` package and curated by the tool itself — not a
third-party or plugin mechanism (that's out of scope for now, matching the
"one preset shipped is enough" posture already taken for the base). Each
preset is **purely additive**: it may declare new types and links, but may
not redeclare a name the base or another preset already owns. Attempting to
is a `SchemaError` at load, not a silent override — see collisions, below.

Because presets are selected independently of each other but move in
lockstep with the base's version number, they live inside the same
per-version directory:

```
src/refdes/standards/
  hardware/
    v1/
      base.yaml
      presets/
        design-debate.yaml
    v2/
      base.yaml
      presets/
        design-debate.yaml       # may be absent if a preset didn't survive to v2
```

`standard: {base: hardware, version: 1, presets: [design-debate]}` resolves
to exactly `hardware/v1/base.yaml` plus
`hardware/v1/presets/design-debate.yaml`, loaded fresh and merged — base,
then presets, then the project overlay — on every build. There is no
separate lifecycle for a preset to manage: "v1 of the bundle" already
implies "v1's design-debate."

### Changing presets or version after `init`

Because resolution is live (§3), there is no meaningful difference between
choosing a preset at `init` and adding it later — both are edits to the same
`standard.presets` list, and the loader doesn't know or care which happened.
This is deliberate: presets will be added and dropped by hand after a
project already exists, and the design has to be robust to that as the
normal case, not a special one.

```console
$ refdes standard add-preset design-debate      # validates the name exists at the pinned version, appends it
$ refdes standard remove-preset design-debate   # removes it, then reports what that breaks
```

These commands exist for the validation and reporting step, not because the
underlying operation needs a command — hand-editing `standard.presets:`
directly and re-running `refdes build` does exactly the same thing.

**Adding a preset by hand:** on the next load its types, links, and field
sets simply join the merged schema. No migration step, no re-running `init`.
If a project already has a hand-authored type with the same name as
something the newly added preset provides (for instance, a local `option`
type predating the preset), the project's own declaration wins per §2's
overlay rule — surfaced as a `warning`, not silently: *"types.option is
declared both locally and by preset 'design-debate' — the local declaration
wins; remove it if you intended to use the preset's version."*

**Removing a preset by hand:** every type, link, and field set it provided
disappears from the merged schema on the next load. This needs no new
mechanism — it reduces entirely to §2's existing rule that removing something
the config relies on is a load-time error, because from the loader's
perspective a preset leaving the list is indistinguishable from any other
input to the merge disappearing. Two concrete consequences, using
diagnostics the tool already has, extended slightly:

- An item with `type: option` hits the existing unknown-type suggestion path,
  extended to name the specific fix rather than a near-match guess:
  `unknown type 'option' — it was provided by the 'design-debate' preset,
  which is not listed under standard.presets:. Add it back, or migrate this
  item to a declared type.`
- A link using a preset-only verb (`raises`, `bears_on`, `met_by`) hits the
  existing unknown-link suggestion path, extended the same way — the verb
  wasn't a typo, it was valid a moment ago, and the message should say so.

`refdes standard remove-preset` runs a build in report-only mode before
writing the config change, so these diagnostics surface before the preset is
actually dropped — the same "show the consequence before committing" shape
`refdes standard upgrade --dry-run` already uses (§3).

**Changing `standard.version`** with presets selected works exactly as
described in §3, with one added check: `refdes standard upgrade` must also
confirm every currently-selected preset resolves at the target version. A
preset can be deprecated or renamed between standard versions exactly like a
base type can; an unresolvable preset entry surfaces through the same
diff-report mechanism as any other version-to-version change, not a separate
check.

### Composition

Presets compose: `standard.presets: [design-debate, some-later-preset]` is a
list, and — deliberately — load order within it does not affect the result.
Presets are **peers**, each additive against the union of the base and every
other selected preset, not a pipeline where one can build on another. A
preset may not extend or override another preset's type, for the same reason
this restriction exists for base-vs-preset: it keeps the set of selected
presets commutative — any subset, any order, the same merged schema — which
is what makes "add one later" safe without re-validating interaction effects
against whatever else happens to already be selected. Only the *project's*
own overlay is allowed to reach into a preset-provided type and extend or
override it, using the same deep-merge rule it already uses against the
base.

**A collision between two presets, or between a preset and the base, is a
hard `SchemaError` at load — never a silent resolution:**

```
configuration error: preset 'design-debate' declares type 'option', which
preset 'some-later-preset' also declares. Presets must not collide — this is
a bug in the preset bundle, or drop one of the two presets.
```

This deliberately matches the voice of the existing board-registry
path-collision error: name both sides, state the fix. The reasoning for
treating this as an error rather than letting one side win, in contrast to
the project-overlay-always-wins rule in §2: a project overriding the base is
intentional customization — the entire point of that mechanism. Two curated,
tool-authored bundles claiming the same name has no equivalent intent behind
it; it's either a defect in the shipped presets (catchable by the tool's own
test suite before release, since presets are bundled and curated, not
third-party) or a project has selected two presets that were never meant to
coexist. Guessing a winner in either case would hide a real problem instead
of surfacing it at the same point in the pipeline every other configuration
conflict in this tool already surfaces at.
