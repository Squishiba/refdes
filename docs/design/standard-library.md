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

**Implemented**, as of v0.5.0 (unreleased) — `refdes/standards.py` and the
bundled dictionaries under `refdes/standards/hardware/{v1,v2,v3}/`, including
merge/override, `field_sets`/`include:`, versioning and pinning, migrations,
and `--standard`/`--preset` at `init`. The bundled standard is currently
pinned at `hardware@3`, itself unreleased. This header is stale from an
earlier draft; the document's prose describes the landed shape accurately —
verify specifics against `standards.py` rather than assuming this file is
current.

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
  blocked_by:     { inverse: blocks,        label: "Blocked by" }
  equivalent:     { inverse: equivalent,    label: "Equivalent" }   # self-inverse; see §11
  alternate:      { inverse: alternate,     label: "Alternate" }    # self-inverse; see §11

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
      blocked_by:     []   # empty target list = unrestricted; see §9
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
      rationale:   { type: text, on_change: invalidate, required_when: {links: alternate} }
      datasheets:  { type: citations, on_change: invalidate }
    include: [provenance, stewardship]
    links:
      satisfies:  [requirement]
      equivalent: []   # self-inverse; see §11
      alternate:  []   # self-inverse; see §11
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

Thirteen verbs, each declared on the type that would naturally author it in
front-matter; the other direction is a computed backlink, not something a
project ever writes — except the last two, which are their own backlink; see
below.

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
| `blocked_by` (decision) | `blocks` | decision → any type, unrestricted | names what's holding this decision up |
| `equivalent` (component) | `equivalent` (self) | component → component | drop-in; no review needed before substituting |
| `alternate` (component) | `alternate` (self) | component → component | close, but check before substituting |

Five choices here are worth explaining rather than taking as given:

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
- **`blocked_by` is new, and resolves further than the direct edge it
  declares.** The edge itself is direct, like every other link here; the
  report built around it (§9) walks the chain to the root cause, treats a
  cycle as a hard error, and is deliberately unrestricted in what it may
  target. See §9 for the full design, including how it feeds back into
  coverage.
- **`equivalent` and `alternate` are the only self-inverse verbs in this
  vocabulary** — every other link here is directional (satisfying is not the
  same claim as being satisfied), but two components being interchangeable
  is the same fact regardless of which one's front-matter states it, so both
  declare themselves as their own inverse rather than inventing a passive
  form (`equivalent_by`) that would mean nothing different. See §11 for how
  the model handles that without special-casing, and for why `alternate`'s
  rationale is required and `equivalent`'s isn't.

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

**As actually shipped (finding 12), this narrowed one way and grew
another.** There is no separate report-then-`--apply`-then-`--force`
sequence: `refdes standard upgrade --to N` always rewrites, in one
verified operation per version step, chained through every intervening
version's own `migration.yaml` (`hardware/v2/migration.yaml`, not a
`v1-to-v2.diff.yaml` sibling file) rather than stopping short of item
files by default. What grew: the rewrite carries every affected item's
content hash forward in stamped baselines *and* seal files, id by id, so
the same rename that would otherwise read as a content change (or, for a
sealed `log` entry, a build-breaking seal violation) doesn't. A
project-local equivalent, `refdes revise <mapping-file>`, applies the same
engine from a hand-written mapping instead of a bundled `migration.yaml`,
for vocabulary that isn't part of the standard at all — see the [CLI
reference](../cli-reference.md#refdes-standard-upgrade-to-n). The
report-first, no-rewrite-by-default posture below is what was designed;
it is not what got built.

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
  version: 2
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
  still need discovery, standard or not. Fully specified in §12.
- **A scaffolding command** (`refdes new <type>`), which becomes *more*
  valuable once the standard is fixed: the scaffold stays correct for every
  project because it's generated from the same resolved schema §12 emits,
  not hand-maintained text that could quietly drift from it — see §12's
  closing section.

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
| `test`, `log` | match directly | — |
| `component` | fields, `satisfies` unchanged | additive only: `rationale`, `equivalent`, `alternate` are new declarations with no existing counterpart to collide with |
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
- **`derives_from`, `records`, `blocked_by`, `equivalent`, and `alternate`
  are net-new capability**, not currently declared at all — zero breakage,
  immediately available. `blocked_by` in particular has direct cited
  evidence of need: the real project's own follow-up notes describe exactly
  this cascade by hand — a decision on hold with three (four, counting a
  pair of decisions about the
  same GPIO-expansion question) other decisions assuming its outcome,
  recorded as a bullet list inside the blocked decision's body that nothing
  validated and nothing updated when the situation changed. Adopting the
  edge replaces that list with something the build checks.
- **Parts indexing (§10) is likewise additive**, and answers a question the
  same follow-up notes ask directly: the real project's documentation names
  real silicon by part number across several boards without any way to see
  where else a given part is used short of a grep. `component.rationale`
  and the `equivalent`/`alternate` links (§11) are new declarations on a
  type that already exists, with nothing to collide with.
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

---

## 9. `blocked_by:` and the cascade report

A decision on hold pending an unresolved question routinely has several
other decisions depending on its outcome. Today that cascade is a
hand-written bullet list inside the blocked decision's body — nothing checks
it, nothing updates it when the situation changes. `on_hold` (§1's decision
status list) currently has nowhere to point: a blocked item can record *that*
it's blocked, in a `note`, but not *on what*. And coverage already
distinguishes `claimed` from `satisfied` for exactly this kind of unsettled
state — the sentence a review needs and doesn't get is "three requirements
are unsettled *because of* one open question."

### The edge, and why the report resolves further than it does

`blocked_by:` is declared on `decision`, targeting any item type with no
restriction (§1's YAML):

```yaml
link_types:
  blocked_by: { inverse: blocks, label: "Blocked by" }

types:
  decision:
    links:
      blocked_by: []   # empty target list = unrestricted, an existing engine behavior
```

An empty target list isn't new schema surface. `build.py`'s link-target
validation only enforces an allowed-types check when the declared list is
non-empty (`if allowed and target.type not in allowed`), so an empty list
already means "no restriction" for any link in this schema — `blocked_by` is
simply the first standard verb to use that behavior deliberately rather than
by omission.

`blocked_by` is standard on `decision` only, not on every type — matching
the only case with direct evidence (below), and keeping the vocabulary at
the size §1 already argues for, where each verb earns its place. A project
that needs a `requirement` or `test` blockable the same way adds
`blocked_by:` to that type's own `links:` under §2's ordinary extension
rule; nothing about the link type itself is decision-specific.

**The declared edge is direct** — an item names only its immediate
blocker(s), the same as every other link in this vocabulary:
`blocked_by: [DEC-IO-001]`. **The report resolves transitively**, because
naming the root cause, not the nearest link in the chain, is the entire
value of building this at all. DEC-IO-016 declaring
`blocked_by: [DEC-IO-003]`, itself `blocked_by: [DEC-IO-001]`, should read as
blocked on DEC-IO-001 — with the path shown, not collapsed straight to the
root:

```
DEC-IO-016  <- DEC-IO-003 <- DEC-IO-001 (on_hold, root)
```

"Root" here is structural, not status-based: the walk follows `blocked_by`
edges until it reaches an item declaring none of its own. Whether that root,
or any link along the path, has since become settled is a separate
question — see the stale-blocker check, below. The walk continues across an
import boundary for free: an imported item already carries its own `links:`
(§4), so a `blocked_by` chain that crosses into an upstream project resolves
the same way a local one does, with no special-casing needed.

### Cycle detection

A `blocked_by` graph is a project asserting a DAG, and nothing about a
hand-written link stops someone from declaring `DEC-IO-001: blocked_by:
[DEC-IO-003]` alongside `DEC-IO-003: blocked_by: [DEC-IO-001]`. Walking that
structurally would recurse forever looking for a root that doesn't exist, so
it's checked once, as a dedicated build step run after ordinary link
resolution — once every `blocked_by` edge is in hand — and a cycle is a hard
`error`, never a warning and never silent truncation:

```
ERROR items/main-io/decisions.md:12 [DEC-IO-003] — blocked_by cycle:
  DEC-IO-003 -> DEC-IO-001 -> DEC-IO-003
```

Reported at the `file:line` of the edge that closes the loop — the concrete
declaration whoever reads the error would actually edit — not at some
arbitrary "first" node picked out of the cycle. This check runs before
coverage, checks, or the report below, all of which assume the `blocked_by`
graph is acyclic; none of them need their own cycle handling as a result.

### No status restriction on the target

`blocked_by:` may point at an item of any type, in any status, with nothing
checked at declaration time — deliberately. The alternative — validating
that a `blocked_by:` target is currently "unsettled" — was considered and
rejected: status is mutable, so that validation would have to re-run on
every build forever just to keep agreeing with itself, and it would be wrong
on arrival for real cases that aren't about an unsettled *decision* at all —
blocked on a test that hasn't passed yet, blocked on a component that hasn't
been selected. The edge records a real dependency regardless of the
blocker's current state; what changes over time is whether that dependency
is still *live*, which is a question about the blocker's status at read
time, not something worth gating at write time.

### The stale-blocker diagnostic

The moment a `blocked_by:` edge stops being live — its target reaches a
settled status while the blocked item still declares the edge — is the
actionable moment, and the entire reason recording the edge is worth doing
instead of leaving it as a note. "Settled" reuses the mechanism §2 already
established rather than inventing a third parallel notion of done: a blocker
counts as settled when its own type declares `satisfying_statuses` (or, for
a verifier-shaped type, `verifying_statuses`) and its current status is in
that list. A type that declares neither simply never triggers this check —
the same "unconfigured means nothing special happens" default used
throughout this document.

```
INFO items/main-io/decisions.md:80 [DEC-IO-005] — blocked_by DEC-IO-001, which is now
  'accepted' — is it still blocked? Remove the edge if resolved, or say in 'rationale'
  why it still applies.
```

`info`, per the severity finding 8 established: default-hidden, because a
project mid-resolution will trip this repeatedly as blockers clear one at a
time, and that's a normal state, not a defect. It's a per-item diagnostic
like any other, so it follows the same visibility rules as every other
`info`-level finding in the ordinary diagnostic stream — but because `refdes
audit` is already the "show me everything interesting regardless of
severity" surface (below), the stale flag also appears there
unconditionally, not gated behind whatever visibility setting governs
`check`/`build` output.

### The report

Folded into three surfaces that already exist, not a new command and not a
new page — consistent with keeping the tool's learnable surface from growing
every time a feature does.

**`refdes audit`** gets a new section, in the same style as its existing
"Board moves" and "Imported projects" sections: grouped, one line per
blocked item, showing the full path to root and flagging staleness inline.

```
Blocked chains:
  DEC-IO-005  <- DEC-IO-001 (on_hold, root)
  DEC-IO-009  <- DEC-IO-001 (on_hold, root)
  DEC-IO-003  <- DEC-IO-001 (on_hold, root)
  DEC-IO-016  <- DEC-IO-003 <- DEC-IO-001 (on_hold, root)
  DEC-IO-020  <- DEC-IO-014 (accepted)  -- stale: edge still declared, blocker settled
```

`(none)` when the project declares no `blocked_by:` edges at all, matching
every other conditional section in `audit` today.

**The blocked item's own page** gets a small panel alongside its existing
links section, showing its direct blocker(s) and, if the chain runs deeper
than one hop, the resolved root — the same fact `refdes audit` shows, in the
same shape, on the page a reader actually lands on after following a link to
DEC-IO-016.

**`coverage.html`** is where the feature's headline sentence actually
belongs, because that's where a review already reads "why isn't this
settled" — see below.

None of these needs a new page, a new artifact, or a new subcommand:
`audit` already exists as the terminal report, item pages already render a
links section, and `coverage.html` already exists as the page a reviewer
opens for precisely this question.

### Interaction with coverage

This is the sentence the whole feature exists to produce, so it has to land
in the two coverage surfaces that already carry "claimed but not settled"
information, not a third, separate one.

**The existing per-item "claimed but not verified" warning** — kept
per-item deliberately, per finding 8, because it's the one coverage warning
that's individually actionable — gets the blocker chain appended when the
claiming decision is blocked:

```
WARNING items/main-io/requirements.md:40 [REQ-IO-CONN-002] — claimed but not verified
  (no test links to it); claimed by DEC-IO-016, which is blocked_by DEC-IO-003 <- DEC-IO-001
  (on_hold)
```

No ambiguity to resolve here — it's naming this one item's actual claimer(s)
and their actual chain, whatever that is.

**A new aggregate line, grouped by root blocker**, sits alongside the
existing summary lines (`N item(s) with no coverage`, `N requirement(s)
satisfied but not verified`) rather than replacing the per-item warnings
above:

```
2 requirement(s) unsettled because DEC-IO-001 is on_hold — see coverage.html
```

One line per distinct root blocker that accounts for at least one
claimed-but-unsettled requirement. This is deliberately conservative about
when it fires: a requirement whose claim traces to a blocked decision with
**exactly one** root blocker is grouped under that root; a requirement whose
claimer has no `blocked_by` chain at all, or whose several claimers trace to
*different* root blockers, is left out of this grouping and simply keeps its
ordinary per-item warning — forcing an ambiguous case into a misleading
one-line summary would be worse than not summarizing it. This doesn't reopen
finding 8's decision to keep "claimed" per-item rather than aggregated: it's
an additional, sharper cut across the same per-item facts for the specific,
common case where several unsettled requirements really do share one cause,
not a replacement for the detail underneath it.

**`coverage.html`** extends the existing per-item row for a claimed item —
which already names its claiming decision(s) — to show the blocker chain
inline when the claimer is blocked, using the same path notation as `refdes
audit`. This is where "three requirements are unsettled because of one open
question" is actually meant to be read: the aggregate CLI line is the
pointer, the page is where the full "these three, that one cause" picture
lives.

---

## 10. Indexing part numbers, and the parts page

The docs name a lot of real silicon, and today "what changes if the
STM32G474 is dropped" means grepping for the string across every item and
citation. Two sources of a part number already exist in the schema —
`component.part_number` and the nested `part_number` inside a `citations:`
entry — and neither needs to be duplicated into a new type to answer that
question. This is explicitly **not** a `part` item type: the ask is indexing
a field that already exists, twice over.

### No new type, no new field type — indexing what's already there

Two sources, both already in §1's standard, neither requiring a new
declaration:

1. `component.part_number` — a plain `text` field.
2. The nested `part_number` key inside every `citations:`-typed field's
   entries (`CitationSpec.part_number`, `citations.py:37,118`) — present on
   *any* type that declares a `citations:` field, not only `component`. §1's
   standard only puts one on `component.datasheets`, but §2 lets a project
   add a `citations:` field to any type, and the nested key follows it
   there automatically. This is the case that covers "cited a datasheet for
   it, never made a component item" — a part that's real enough to have a
   spec sheet pinned but hasn't (yet, or ever) become a BOM line.

Recognized **by field name**, the same way `limit`, `options`, and `checks`
already are (schema-reference.md's "three field names have behaviour
attached regardless of declared type") — not by declared field `type:`,
because `part_number` is a plain string with no structure of its own, unlike
`citations`, which is recognized by its declared type precisely because it
*does* have structure. Any field literally named `part_number`, on any item
type, feeds the index. A project that later adds `part_number` to some other
type — a connector spec, say — is picked up automatically, with no config
change.

### Exact string, deliberately

Indexed on the literal string, with no normalization, no family grouping, no
guessing that `STM32G474` and `STM32G474RET6` are the same part or even
related parts. Every normalization scheme considered — strip a package
suffix, match a manufacturer prefix, fuzzy-match — is right for some
vendors' part-numbering conventions and wrong for others, and wrong here is
worse than not trying: a false grouping silently answers "what uses this
part" with the wrong set of items, which is a worse outcome than answering
"nothing, under this exact string" and leaving the reader to notice the near
match themselves. If family grouping is ever wanted, it's a **declared
field** — a project adds, say, `family: STM32G4` to its own components and
indexes on that field name instead of (or alongside) `part_number` — which
this feature already supports for free, since it only needs a project to
pick a field name; never a heuristic the tool invents on a project's behalf.

### Why this isn't an `{{index}}` block

`{{index by="part_number" type="component"}}` already works today, exactly
as `docs/design/index-blocks.md` §2 specifies — `part_number` is a plain
`text` field on one type, which is exactly what that family is built to
group. But it only reaches the component half of the picture, and it
*cannot* be extended to reach the nested half without breaking two
restrictions that document states are load-bearing, not incidental:

- §3 of that document explicitly rejects `citations` as a groupable field
  type — "structured records... not a value with a current reading a
  heading could name." The nested `part_number` sub-key is exactly that
  structured-record case.
- §2 of that document makes `type=` deliberately singular — "if a project
  wants decisions and components indexed by the same field, that's two
  blocks, not one." The parts page needs to reach *every* type that happens
  to declare a `citations:` field, an open-ended set, not two named types.

Both restrictions exist so that family stays a small, closed set of
parameter-only blocks with one fixed meaning each (index-blocks.md §7's
whole non-goal). Reaching this page's actual requirement would mean rebuilding
both restrictions specifically to accommodate one page — exactly the "each
block reinvents its own version" outcome that document's §6 exists to
prevent. The parts page is a dedicated, purpose-built report instead,
following `references.html`'s precedent, not `{{index}}`'s. An author who
only cares about the component half is still free to drop
`{{index by="part_number" type="component"}}` into a narrative page today;
the dedicated report below is for the question that block can't answer.

### The report: global and per-board, following `references.html`'s shape

`citations.py` already has the exact mechanism to mirror: `collect()` walks
every local item's every `citations:`-typed field regardless of which type
declares it, and `by_url(project, board=None)` regroups the result by URL,
optionally scoped to one board — this is precisely what `references.html`
and `references-{board}.html` render, and precisely what `refdes audit`'s
existing "Citations:" section prints. Parts indexing adds a sibling,
`by_part_number(project, board=None)`, doing the identical regroup keyed on
`spec.part_number` instead of `spec.url` (entries with no part number are
skipped — most citations won't have one filled in), plus a second, equally
small walk over `component.part_number` and any other field named
`part_number` on any local item. Both feed one merged, sorted-by-exact-string
structure — one entry per part number, carrying whichever components declare
it directly and whichever citations name it in their nested `part_number`.
No new traversal logic: this reuses `collect()`'s walk and `by_url()`'s
grouping shape wholesale.

Rendered exactly like citations: **`parts.html`**, global, plus
**`parts-{board}.html`** per board, both from one template, following the
same "global page has no board filter, board page filters both sources to
`item.board == board`" rule `by_url` already uses. `"parts"` and
`"parts-{board}"` join the existing `reserved` name set in `render_site`
(`render.py:480-492`) alongside `"references"` and `"references-{board}"`,
so a narrative page can't collide with the generated report — the same
mechanism, one more literal string.

**`refdes audit`** gets a "Parts:" section, in the same shape as its
existing "Citations:" section — every part number, not filtered to
multiply-used ones, so a reader skims for the multi-board rows themselves
rather than the tool pre-deciding what's interesting:

```
Parts:
  STM32G474      used by CMP-014, CMP-019 (components), REQ-IO-SYS-004 (citation)
                 — boards: main-io, expansion
  STM32H523      used by CMP-021 (component) — board: main-io
```

Each component page's existing fields table already shows its own
`part_number`; a small addition there — "also used by: ..." — links straight
to the part's section on `parts.html` rather than duplicating the full list
on every component page that happens to share a part.

### Workspaces, and why the cross-workspace lint doesn't apply here

**"Workspace" isn't a concept this codebase defines** — `docs/design/index-blocks.md`
§2 reached the identical conclusion when asked to scope index blocks by
workspace, and the reasoning is unchanged here: inventing one to satisfy
this brief would add a concept the rest of the tool doesn't have. Scoping is
board-only, matching every other generated report in the tool. If a
workspace concept and a cross-workspace lint (the "further ideas" note about
grouping boards under a shared-ownership boundary) are ever built, this
section states the invariant that design will have to respect, so it isn't
discovered as a conflict after the fact:

**The parts page is a derived view, not an authored link.** It stores
nothing on any item, declares no `links:`, and creates no edge a project
would ever write down — it's computed fresh, at build time, from field
values that already exist. A future cross-workspace lint has something real
to check *because* `refines`/`satisfies`/`constrained_by`/etc. are edges a
project author deliberately typed, each one a real claim of dependency that
makes a workspace harder to extract on its own. The parts page produces
none of those. Two boards in different workspaces using the same
microcontroller is a coincidence of the bill of materials, not a claimed
dependency between them, and it is exactly the coincidence this page exists
to surface — it's what answers "what's affected if this part goes end of
life" or "where else could a second source qualify," across the whole
project, on purpose. A cross-workspace lint should be scoped to declared
`links:`, never to which items happen to share a `part_number`; nothing
about this design needs to wait for that lint to exist, and nothing about
that lint, whenever it's built, should need to touch this page.

---

## 11. Part equivalence: two relationships, and the self-inverse link

**This is not a parts database.** A manufacturer's own equivalence data —
"these two op-amps are pin-compatible per the datasheet" — is parts data,
and belongs in whatever system of record already holds part numbers,
package outlines, and AVL lists, not in refdes. What belongs here is
narrower and different in kind: *this project's author has decided* two
parts are interchangeable for *this design*. That's a reviewable claim, not
a fact about silicon — it can be wrong, it can go stale when a requirement
changes, and someone can disagree with it. Staleness and reviewability are
exactly refdes's domain everywhere else in this document (§9's stale-blocker
check is the same shape of problem), so the design follows that lead rather
than reaching for a parts-database shape.

### Two verbs, and why not one field

`equivalent` — drop-in, no review needed before substituting; rationale
optional, because the claim ("these are interchangeable") is complete on its
own. `alternate` — functionally close but check before substituting;
rationale required, because unlike `equivalent` the entire content of the
claim is *which way* it isn't quite a drop-in — "there's something you
should know" with no statement of what is worse than not recording the
relationship at all.

Two alternatives to a pair of links were considered and rejected:

- **A `component.equivalents:` field**, shaped like `options:` (a flat list
  of `{name, verdict, because}` panels with no items behind them). Rejected
  because, unlike a decision's considered-and-rejected options, both sides
  of an equivalence claim already exist as real component items — the field
  would mean re-typing the other part's identity as a bare string, losing
  the validated ID reference, the computed backlink that lets the *other*
  component's page show the claim too, and any hook for `required_when` to
  gate on which kind of claim it is.
- **One shared link plus an enum field** naming the relationship kind
  (`substitute_kind: {choices: [equivalent, alternate]}`) instead of two
  verbs. Rejected because it can't represent a component that has *both* an
  equivalent and a different alternate at once — exactly the second-sourcing
  case §10 exists to surface (a drop-in second source *and* a functionally
  close but imperfect option, simultaneously) — since one enum field per
  component can only record one relationship kind at a time.

Two link verbs, declared on `component` and restricted to `component`
targets, is the only shape that gives each pairing its own kind without
losing the identity or reviewability of either side.

### The symmetry problem, and how the model handles it

Every other verb in this vocabulary is directional — satisfying is not the
same claim as being satisfied, so each gets its own inverse name
(`satisfies`/`satisfied_by`, `refines`/`refined_by`, and so on). Equivalence
doesn't have a natural passive form: if CMP-014 is `equivalent` to CMP-019,
CMP-019 is not "equivalented by" CMP-014 — it is, identically,
`equivalent` to CMP-014. The same is true of `alternate`. Inventing a
distinct inverse name for either would create a word that means nothing
different from the verb it's the inverse of, which is worse than not having
one.

**The loader already tolerates this without special-casing.** A
`link_types` entry's `inverse:` is just a string (§1's YAML: `equivalent: {
inverse: equivalent, ... }`), and nothing in the load path requires it to
differ from the verb's own name — `inverse_of["equivalent"] = "equivalent"`
is set once, and the pass that fills in the reverse direction
(`inverse_of.setdefault(inverse, name)`, `schema.py`) is a no-op against a
key that's already set to the same value. Declaring a self-inverse link
needs no schema-loader change.

**Rendering is where the accommodation actually has to happen, and it's
worth stating plainly rather than leaving implicit.** Every other link
renders its forward declarations (`item.links[verb]`) and its computed
backlinks (`item.backlinks[inverse]`) as two differently-labeled sections,
because the labels genuinely mean different things — "Satisfies" is not
"Satisfied by." For a self-inverse verb, `links["equivalent"]` and
`backlinks["equivalent"]` share not just a key name but an identical
meaning, and rendering them as two same-labeled sections would show a
reader the same fact twice, differing only in which of the two components
happened to type the YAML — information nobody reading the page cares
about. **The least ugly accommodation**: an item page merges
`links.get(verb, [])` with `backlinks.get(inverse, [])` into one
de-duplicated set before rendering, whenever `verb == inverse` for that
link type. This is a general rule, keyed off `LinkType.inverse ==
LinkType.name`, not a special case hardcoded to these two verb names — any
future self-inverse verb gets the same treatment automatically. A component
declaring `equivalent: [CMP-019]` and CMP-019 separately, redundantly, also
declaring `equivalent: [CMP-014]` back is harmless under this rule: the
merge de-duplicates to the same single visible entry either way, so there's
nothing to validate and nothing worth warning about — unlike a misspelled
link name, a redundant symmetric declaration costs nothing and names
nothing wrong.

### `alternate`'s required rationale, and the one narrow extension to `required_when`

§2 specifies `required_when:` with condition keys naming an `enum` field on
the same type — deliberately, so the loader can validate every named value
against a closed, declared `choices:` list. Gating `component.rationale` on
"does this component declare an `alternate:` link" is a different kind of
condition: not a field currently holding one of several values, but a link
currently holding at least one target. This needs a second, narrow
condition kind, not a rewrite of the mechanism:

```yaml
rationale:
  type: text
  on_change: invalidate
  required_when: { links: alternate }
```

Inside a `required_when:` mapping, the key `links` is reserved (a field can
never legitimately be named `links` in the first place, so this introduces
no ambiguity) and its value names one or more link names declared on the
same type; the condition is satisfied when the item declares at least one
target under any of them. This combines with field-value conditions by the
same AND rule already specified — a `required_when:` mapping may name both
kinds at once, though nothing in this standard currently needs to.
Load-time validation mirrors the enum case exactly: a `links` condition
naming something not declared as a link on the type (after the full merge —
base, presets, project overlay) is a `SchemaError`, the same posture as a
`required_when` naming a value absent from an enum's resolved `choices:` —
removing or renaming the `alternate` link without also touching
`rationale`'s `required_when` doesn't silently stop enforcing anything, it
fails the build.

**One simplification, stated rather than hidden**: `rationale` is a single
field per component, not one entry per `alternate` edge. A component with
two different `alternate` candidates, each imperfect for a different
reason, has one shared rationale text to explain both, not two independent
ones. This is a deliberate trade against building per-edge structured
rationale (an `alternate:` entry shaped like a `citations:` entry, each
carrying its own `because:`) — rejected because it would make `alternate`
behave unlike every other link in this vocabulary and unlike `equivalent`
right next to it, for a case (a component with multiple simultaneous
imperfect alternates) that's plausible but not evidenced. `rationale` is
free text, so it degrades gracefully to one combined explanation rather than
becoming wrong; if per-edge rationale is ever needed, that is a real fork
worth its own design, not a default to build in ahead of the need.

### What a part needs before it can carry this claim

A link connects items, and a part known only through a citation's nested
`part_number` — the case §10 exists to surface — has no item and no ID to
link from or to. It can't carry an `equivalent` or `alternate` claim until
it's promoted to a real `component` item. That's not a gap so much as the
natural shape of the workflow: §10's parts page is how a citation-only part
becomes visible as a candidate worth a second look; making a reviewable
equivalence claim about it is a reason to give it an item, not something
this design needs to support without one.

### What this doesn't touch

`compute_coverage` reads `satisfied_by`/`addressed_by`/`verified_by`-shaped
backlinks only; `equivalent` and `alternate` aren't satisfies-shaped, so
coverage is entirely unaffected — no interaction to design. Neither verb
adds a new field *type*, unlike `citations`: `equivalent`/`alternate` are
ordinary links, and `component.rationale` is an ordinary `text` field
already used the same way on three other standard types.

---

## 12. JSON Schema emission, and what it actually reaches

Most of finding 21 — "the link vocabulary must be memorised, because
nothing helps while you are writing" — dissolves once the vocabulary is
tool-defined (§6): there's nothing left to memorize when the fields and
links are the same across every `refdes` project. What's left is real,
though: nothing today tells an *editor* what the resolved schema is, so
completion and validation while typing still don't exist. This section
specifies the command that fixes that, `refdes schema --json`, and — because
this is the part most likely to be built and then quietly not work — spends
real space on where the output actually lands and where it doesn't.

### One serializer, reused three ways

`items.json`'s `types` key already carries almost everything this needs:
`items_json` (`render.py:288-306`) walks `project.types.items()` and emits,
per type, `label`, `prefix`, `append_only`, every field's `type`/
`on_change`/`required`/`choices`, and `links` (the link-name → allowed-target
list). That function reads the fully *resolved* `Project` object — after
base, presets, and the project overlay have all been merged (§2) — so it is
already, in substance, a serialization of the exact thing this command needs
to emit. It's just not shaped as a JSON Schema: no `$schema`, no
`properties`/`required` envelope, no discriminated union across types, no
`additionalProperties: false`.

`refdes schema --json` doesn't recompute anything new — it's a second,
sibling serializer over the identical `project.types`/`project.link_types`
objects `items_json` already reads, rendering the standard JSON Schema
envelope instead of `items.json`'s lighter shape. One in-memory model, two
serializations, generated at the same point in the same load — not two
places that could independently drift, the same posture §4 already takes
toward a resolved-schema hash for imports. §12's closing section reuses the
same per-type serializer a third time, for `refdes new <type>`.

### What it covers

- **Item front-matter fields per type**: name, JSON-Schema `type`
  (`text`→`string`, `date`→`string` with `format: date`, `list`→`array`,
  `enum`→`enum` with the type's declared `choices:` and `default:`, and so
  on through the field types §1's reference already lists).
- **Status (and every other enum field's) legal values per type** — directly
  from `choices:`, so `decision.status` offers exactly `proposed`,
  `in_progress`, `accepted`, `on_hold`, `rejected`, `superseded` and nothing
  else, matching §1 exactly because it's read from the same place §1's own
  YAML is.
- **Link verb names, as legal property keys** — `refines`, `constrained_by`,
  `blocked_by`, and so on, each `{"type": "array", "items": {"type":
  "string"}}`. **The allowed-target-type restriction is not, and cannot be,
  enforced by the schema** — JSON Schema validates one document in
  isolation, and confirming that a listed ID actually resolves to an item of
  an allowed type requires reading other files, which is `refdes check`'s
  job, unchanged. The schema gets an author the link *name* — no more typing
  `sattisfies:` and finding out at build time — and the target set is stated
  in the property's `description` for a human to read on hover, not
  something the validator itself checks.
- **Reserved and overridable keys** — `id` (deliberately unconstrained, see
  below), `type` (the discriminator, see below), `history` (both shapes
  documented in schema-reference.md: a scalar mode or a `{fields, reason}`
  mapping), and `prefix`/`board` included as legal properties on a type's
  branch *only when that type doesn't already declare a same-named field* —
  mirroring `OVERRIDABLE` (`parse.py:35`) exactly rather than approximating
  it.
- **`additionalProperties: false`** on every branch, which is what makes an
  unknown key light up the moment it's typed rather than the next time
  `refdes check` runs. This is a real capability gain, not a duplicate of
  `parse.py`'s existing difflib-suggestion diagnostic (`unknown field
  'sattisfies' … did you mean the link 'satisfies'?`) — the schema catches
  the same class of mistake *sooner*, with a generic validator message; the
  CLI's message remains the more informative one when it does run. Neither
  replaces the other.

`id` is deliberately **not** in `required`, and carries no pattern
restriction. An item mid-authoring, before `refdes id` has allocated it, is
the tool's own normal workflow (`project.pending`, `parse.py:305-323`) —
requiring `id` in the schema would put a red squiggle on exactly the case
the two-phase author-then-allocate flow exists to support.

A single type's branch, illustrated (`requirement`, abbreviated):

```json
{
  "type": "object",
  "properties": {
    "id":            { "type": "string" },
    "type":          { "const": "requirement" },
    "text":          { "type": "string" },
    "status":        { "enum": ["draft", "active", "retired"], "default": "draft" },
    "rationale":     { "type": "string" },
    "refines":       { "type": "array", "items": { "type": "string" },
                        "description": "target: requirement" },
    "source":        { "type": "string" },
    "note":          { "type": "string" },
    "tags":          { "type": "array", "items": { "type": "string" } },
    "owner":         { "type": "string" },
    "last_reviewed": { "type": "string", "format": "date" },
    "history":       { "$ref": "#/$defs/history" }
  },
  "required": ["text"],
  "additionalProperties": false
}
```

### Two document shapes, one schema

An item is authored in two physical shapes (§1's intro; `parse.py`'s module
docstring), and the emitted schema has to describe both from one file, since
one `yaml.schemas` association maps one schema to a glob, not one per file:

- **A bare item** — `.md` front matter, or one entry inside a list file's
  `items:` array — is one of the per-type branches above.
- **A list file** — `{defaults?: {...}, items: [...]}` — is a second shape,
  whose `items:` entries are the *same* per-type union, and whose
  `defaults:` mapping is deliberately left as `additionalProperties: true`
  and *not* validated against any one type's fields, because `defaults:`
  merges into whichever type each entry declares and the schema has no way
  to know that in advance for the block as a whole.

The top level of the emitted file is `oneOf` between these two shapes,
discriminated structurally (a list file has an `items:` key at the top
level; a bare item doesn't). One difference between the two bare-item
contexts is worth stating precisely rather than glossing over: `body` is a
legal key *inside a list-file entry* (the markdown body as a string,
`parse.py:31`'s `RESERVED`) but is never a legal key in `.md` front matter,
where the body is the text after the closing fence, not a YAML key at all.
The per-type branch used for list-file entries includes `body`; the one
conceptually describing `.md` front matter — see below for why "conceptually"
is doing real work in that sentence — does not.

### Where it lives, and why it isn't committed

`.refdes/schema.json`, joining the directory's other generated artifacts.
Unlike `.refdes/ids.yaml`, `.refdes/citations.yaml`, `.refdes/boards.yaml`,
and `.refdes/log-seal.yaml` — all committed, per the repository's own
`.gitignore`, because each records state that must persist and be shared
across branches (burned IDs, fetched hashes, the board-move drift baseline,
sealed content) — `schema.json` carries no history at all. It's a pure
function of the current merged config; deleting it loses nothing, and by
definition it should always exactly match what the current config would
produce. That puts it in the same category as `_site/` and
`.refdes/vendor/`: a derived artifact, not a record. It's gitignored, with a
comment in the same voice the existing gitignore comment already uses:

```
# .refdes/schema.json is regenerated on every command that loads the
# project -- deleting it loses nothing, and a committed copy would just be
# one more thing that can silently disagree with refdes.yaml.
.refdes/schema.json
```

### Regeneration and staleness

Every command that loads a project already resolves the full merged schema
as part of doing its own job — writing it to `.refdes/schema.json` is a
cheap side effect tacked onto that, the same way `build` already writes
`.refdes/boards.yaml` and the ID ledger as housekeeping alongside its main
work. So `build`, `check`, `index`, `id`, `fetch`, and `audit` all refresh
it, not just an explicit invocation — "stale schema files are worse than
none" is answered by making staleness hard to sustain rather than by
detecting it after the fact. `refdes schema --json` itself remains the
explicit, standalone command (finding 21's own proposed spelling),
printing to stdout like `refdes index` already does, for piping into
something else or inspecting directly.

The one gap this doesn't close: a project with only `yaml.schemas`
configured and no refdes-aware file watcher running (someone editing `.yaml`
list files with a bare yaml-language-server setup, no refdes extension
active) has nothing that re-triggers a refdes command on save, so
`.refdes/schema.json` can go stale between a `refdes.yaml` edit and the next
CLI invocation. `refdes check` closes this with one cheap mtime comparison —
if `.refdes/schema.json` exists and is older than `refdes.yaml`, warn that
it's stale and about to be refreshed. Given how aggressively it's already
regenerated, this is a trip-wire for one narrow gap, not the primary
defense.

### Getting an editor to use it, and the gap in doing so for `.md` files

For `items/**/*.yaml`, the standard mechanism is `yaml.schemas`, a setting
`redhat.vscode-yaml` (the de facto YAML language server for VS Code) reads
to map a schema file to a glob:

```json
// .vscode/settings.json
{
  "yaml.schemas": { "./.refdes/schema.json": ["items/**/*.yaml"] }
}
```

`refdes init` (§3, §8) writes this file as part of its scaffold, so a new
project has it from the start rather than requiring anyone to know the
setting exists; a project predating this feature adds the same four lines
by hand. `editors/vscode/package.json` declares `redhat.vscode-yaml` under
`extensionDependencies`, so installing the refdes extension pulls it in —
without it, the `yaml.schemas` setting is inert. For a setup that doesn't
read VS Code workspace settings at all (a bare yaml-language-server
configuration in another editor), the equivalent is a per-file modeline,
`# yaml-language-server: $schema=./.refdes/schema.json` as the first line —
more repetitive across files, but editor-agnostic, and worth documenting as
the portable fallback rather than the primary mechanism.

**For the Markdown item format — the one most items actually use — this
does not work today, and it isn't a refdes gap.** `vscode-yaml` does not
validate or
complete YAML front matter embedded in Markdown files; this is a confirmed,
open, unresolved upstream limitation
([redhat-developer/vscode-yaml#207](https://github.com/redhat-developer/vscode-yaml/issues/207)),
not a matter of configuration. Associating the schema with `.md` files via
`yaml.schemas` has no effect. This is worth stating plainly rather than
shipping a design that quietly doesn't work for the primary case: the schema
file is genuinely useful for `.yaml` list files and portable to any
yaml-language-server-based editor today, and it will start working for
`.md` front matter automatically, with no refdes-side change, the day that
upstream issue closes. Nothing here should be built to work around it in the
meantime — that would be exactly the kind of tool-specific patch this
design otherwise avoids.

### What the VS Code extension gains, and the one change it needs

For `.yaml` files, the extension gains real completion and validation with
**zero changes to `extension.js`** — it's `yaml.schemas` plus
`redhat.vscode-yaml`, both configuration, described above.

For `.md` front matter — where the upstream gap means yaml-language-server
contributes nothing — the gain has to come from the extension itself, and it
needs one concrete, small change. `completionProvider` (`extension.js:237`)
already offers two things: enum values after `field: ` (`enumChoicesFor`,
reading `index.data.types[type].fields[name].choices` — data `refdes index
--compact` already returns on every refresh) and item IDs after `[[` or a
prefixed hyphen. It does not currently complete *field or link key names*
while typing inside front matter, which is the actual gap finding 21 named.
The fix reuses data the extension already has in hand: `index.data.types`
already carries every field name and every link name per type (the same
payload `enumChoicesFor` reads today), so `completionProvider` needs a third
trigger — offering `Object.keys(type.fields)` and `Object.keys(type.links)`
as key completions at the start of a front-matter line, once the current
item's `type:` is known from context — not a new file to read, not a
dependency on `.refdes/schema.json`'s freshness, just a second way of using
data the extension is already fetching. Hover, go-to-definition, and
diagnostics are unaffected; nothing about those needs the schema.

### `refdes new <type>`, without a second source of truth

`refdes new <type>` scaffolds a starter item by calling the identical
per-type serializer this section already specified, not a second,
independently-maintained template per type — the concern named at the top
of this task ("shipping two sources of it would guarantee they drift")
applies here as directly as it does to the schema-versus-`items.json`
question above, and gets the identical answer: one function, reused. A
required field with a declared `default:` is written with that default;
a required field with none gets a placeholder; an optional field is written
commented-out, its comment showing the same `choices:`/type information the
schema's own `description` carries; a link is written commented-out, naming
its allowed target types the same way. None of this is hand-curated text
maintained separately per standard type, correcting what §6 originally
suggested — generating it from the resolved schema is what keeps it correct
automatically as the standard itself changes across versions (§3), rather
than needing its own migration step alongside `refdes standard upgrade`.
