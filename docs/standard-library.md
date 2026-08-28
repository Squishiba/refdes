# The standard library

A new project's `refdes.yaml` doesn't need to declare `requirement`,
`bound`, or any of the usual hardware-traceability vocabulary by hand.
`refdes` ships a **standard dictionary** — six item types, their fields, their
status lifecycles, and the link vocabulary connecting them — bundled inside
the package and resolved live, by reference, into every project that opts in.

```yaml
standard:
  base: hardware
  version: 2
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
| `bound` | `BND` | `draft` → `active` → `retired` | A machine-checkable limit, compared against a `calc` result |
| `decision` | `DEC` | `proposed` → `in_progress` → `accepted` / `on_hold` / `rejected` / `superseded` | A settled choice, with options considered |
| `test` | `TST` | `planned` → `passing` / `failing` / `blocked` | Proof a requirement or bound holds |
| `component` | `CMP` | `candidate` → `selected` / `obsolete` | A specific part realizing a decision |
| `log` | `LOG` | — (append-only) | The dated, unedited record of how the design got here |

And thirteen link verbs, each declared on the type that would naturally author
it — `refines`, `derives_from`, `satisfies`, `constrained_by`, `verifies`,
`addresses`, `records`, `amends`, `supersedes`, `selects`, `blocked_by`, plus
the self-inverse `equivalent`/`alternate` pair on `component`. See
[links](links.md) for how declaring one end gives you the other for free.

Every type also carries `owner`/`last_reviewed` (the `stewardship` field set)
and `source`/`note`/`tags` (`provenance`) — see [field_sets and
`include:`](#field-sets-and-include) for how those are assembled without
retyping five fields on every type, and [authoring: `source`, `note`,
`rationale`, `body`](authoring.md#source-note-rationale-body) for what
`source`/`note` are actually for, as distinct from `rationale`/`body`.

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
  version: 2
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

**Selecting a preset at `refdes init`** and **adding or removing one later**
are the same operation — resolution is live, so there's no difference
between "chosen at init" and "added by hand afterward":

```bash
refdes init --preset design-debate         # at project creation
refdes standard add-preset design-debate   # or later, on an existing project
refdes standard remove-preset design-debate
```

Hand-editing `standard.presets:` directly and re-running `refdes build` does
exactly the same thing as either command — they exist for the validation
and reporting step, not because the underlying operation needs a command.
`add-preset` checks the name actually exists at the project's pinned
version before adding it. `remove-preset` reports what the removal would
break — any item whose `type:` or link the preset provided — **before**
writing the config change, then writes it regardless: the point is to
surface the consequence, not to block an author who's already decided to
accept it.

```
$ refdes standard remove-preset design-debate
ERROR   items/main-io/db-001.md:2 [DB-001] — unknown type 'debate' -- it was
        provided by the 'design-debate' preset, which is not listed under
        standard.presets:. Add it back, or migrate this item to a declared type.
1 error(s) above -- fix these, or add the preset back with 'refdes standard add-preset'
removed preset 'design-debate' from standard.presets:
```

The same wording appears for a link name a since-removed preset provided
(`unknown field 'raises' on decision -- it was provided by the
'design-debate' preset...`), rather than a bare "unknown field."

## `refdes init`

Writes a minimal `refdes.yaml` in the current directory — `site:`,
`standard:`, `id:` only, no `types:`/`link_types:`/`field_sets:` — plus
`.vscode/settings.json` wiring up schema completion for `items/**/*.yaml`
(see [editor support](#editor-support-json-schema-emission) below).

```bash
refdes init                            # hardware@<latest>, no presets
refdes init --standard none            # the fully self-declared escape hatch
refdes init --preset design-debate     # repeatable; requires a base standard
```

`--preset` combined with `--standard none` is a load-time error — every
preset's types target base types, so a preset has nothing to attach to
without one. `<latest>` is resolved once, here, to whichever concrete
integer the installed tool currently bundles as newest, and written as that
real number — never the literal word `"latest"`.

## `refdes new <type>`

Scaffolds a starter item's front matter for any type in the merged schema —
standard or project-defined — so "what fields does a decision take again"
never means a trip back to this page:

```bash
refdes new decision > items/power/dec-005.md
```

```yaml
---
id:
type: decision
# source:  # text
# note:  # text
# tags:  # list
# owner:  # person
# last_reviewed:  # date
title:  # required -- text
status: proposed  # choices: proposed, in_progress, accepted, on_hold, rejected, superseded
# rationale:  # text; required when status is 'rejected'
# date:  # date
# options:  # options
# checks:  # checks
# satisfies: []  # target: requirement
# constrained_by: []  # target: bound
# supersedes: []  # target: decision
# selects: []  # target: component
# blocked_by: []  # target: any
---
```

A required field with a declared default is written with that default; a
required field with none gets an empty placeholder; an optional field is
commented out, its comment naming the same type/choices information the
JSON Schema's own `description` carries; a link is commented out the same
way, naming its allowed target types. Prints to stdout — redirect it where
the item should live.

Generated from the identical resolved schema `refdes schema --json` emits,
not a second, hand-maintained template per type — the two can never
independently drift on what a field or link means.

## Editor support: JSON Schema emission

`refdes schema --json` emits a JSON Schema describing the project's
**actual merged schema** — base at its pinned version, plus selected
presets, plus the project's own overlay — not the built-in standard in the
abstract, so it's correct for a project that has customized anything.
Covers field names and types per item type, legal `status` (and every other
enum field's) values, link verb names with their allowed target types
stated in each property's `description`, and reserved/overridable keys
(`id`, `type`, `history`, and `prefix`/`board`/`workspace` where a type
hasn't shadowed them with a same-named field). `additionalProperties:
false` on every branch is what lights up an unknown key — `sattisfies:` —
the moment it's typed, not the next time `refdes check` runs.

**What it can't check**: the allowed-target-type restriction on a link.
Confirming a listed ID actually resolves to an item of an allowed type
means reading other files, which stays `refdes check`'s job — the schema
states the target set for a human to read on hover, nothing more.

Written to `.refdes/schema.json` — gitignored, not committed, a pure
function of the current config regenerated as a cheap side effect of every
command that already loads the project (`build`, `check`, `index`, `id`,
`fetch`, `audit`). `refdes schema --json` is the explicit, standalone form,
for piping into something else or inspecting directly. `refdes check` also
does one cheap mtime comparison — `.refdes/schema.json` older than
`refdes.yaml` — and warns (then refreshes) if a stale copy somehow survived
between commands, the one narrow gap a bare yaml-language-server setup with
no refdes-aware watcher can hit.

**Getting an editor to actually use it**, for `items/**/*.yaml` list files:

```json
// .vscode/settings.json -- refdes init writes this for you
{
  "yaml.schemas": { "./.refdes/schema.json": ["items/**/*.yaml"] }
}
```

This is `redhat.vscode-yaml` (the de facto YAML language server for VS
Code) reading a standard setting; the refdes extension declares it as an
`extensionDependencies` entry, so installing the extension pulls it in.
Any other yaml-language-server-based editor honors the equivalent per-file
modeline instead: `# yaml-language-server: $schema=./.refdes/schema.json`
as a file's first line.

**This does not work for `.md` front matter today, and it isn't a refdes
gap**: `vscode-yaml` does not validate or complete YAML front matter
embedded in Markdown files — a confirmed, open, upstream limitation
([redhat-developer/vscode-yaml#207](https://github.com/redhat-developer/vscode-yaml/issues/207)).
For `.md` — the format most items actually use — the refdes VS Code
extension closes the gap itself instead: `completionProvider` now offers
field and link key names at the start of a front-matter line, once the
current item's `type:` is known from context, reading the same
`refdes index` payload its enum-value and item-ID completions already use.
Nothing here should be built to route around the upstream `.md` gap for
`yaml.schemas` itself — it will start working automatically, no refdes-side
change needed, the day that issue closes.

## Versioning and pinning

`standard.version` is a single pinned integer — never the string `"latest"` —
naming a bundle that is byte-identical forever once shipped:
`hardware@1` means exactly the same thing today as it will after any future
`refdes` upgrade. The installed package carries every version it has ever
shipped, so a project pinned to an old version keeps working unchanged; moving
to a newer one is a deliberate act, not something that happens under a
project on an ordinary upgrade.

`refdes standard upgrade --to N` is a guided, deliberate migration between
pinned versions — see the [CLI reference](cli-reference.md#refdes-standard-upgrade-to-n).
It chains each intervening version's own `migration.yaml`, in order, rewriting
item files and `standard.version:` together and carrying content hashes
forward in baselines and seals so the rename doesn't look like a content
change. Moving to a newer version without it still works exactly as before —
hand-edit `standard.version:` and read `refdes check`'s diagnostics for
whatever changed — but the command does the rewrite for you when the change
is one a `migration.yaml` already describes.

### The versions shipped so far

**`hardware@1`** — the original six types. `constraint` carries a `title:`
field.

**`hardware@2`** — three changes, arriving together. They came out of real
adoption over a single development cycle and none of them was published on
its own, so they are one version rather than three:

1. **`constraint.title` becomes `constraint.text`**, matching
   `requirement.text`'s role as the type's one required content field
   (`title` was a short-label field with nowhere for a constraint's actual
   normative sentence to go but the optional `body:`). `preview` follows it,
   becoming `[status, text, limit]`.

2. **`constraint` becomes `bound`**, prefix `CON` → `BND`. In plain English
   a constraint colloquially *is* a requirement, and that near-synonymy is
   what produced real authoring mix-ups; `bound` doesn't have the problem,
   and it names the `limit:` field that makes the type mechanically distinct
   — a `bound` is a machine-checkable limit, a `requirement` is prose.
   `bound` also gains `refines: [bound]` alongside its existing
   `derives_from: [requirement, bound]`: before this only `requirement`
   could `refines:`, so a constraint narrowing another constraint had
   nowhere to say so. Both verbs stay, because they answer different
   questions — "what does this narrow" versus "what was this derived from"
   — and `derives_from:` alone can still cross into `requirement`, which
   `refines:` deliberately cannot.

3. **`component.equivalent` and `component.alternate` are restricted to
   `[component]`**, where v1 wrote both as `[]`. An empty target list means
   *unrestricted*, which is what it deliberately means on
   `decision.blocked_by:`; on these two verbs it was a slip, and v1's
   dictionary accepted `equivalent: [REQ-PWR-001]` on a component without a
   word while every version of the docs said component → component.

`hardware@1` resolves exactly as it always has; nothing changes for a
project that doesn't touch its pin.

`refdes standard upgrade --to 2` applies parts 1 and 2 to your item files
and their ids. Part 3 renames nothing — it only starts checking what is
already written — so the upgrade has nothing to rewrite for it, but it will
refuse the whole step, rolling back, if an existing `equivalent`/`alternate`
no longer satisfies the restriction, naming the offending link.

**Moving a pin by hand still works**, and gets a specific diagnostic rather
than a generic one: an item still typed `constraint` at `version: 2` is told
the type is now `bound`, which is worth saying because `constraint` and
`bound` share almost no letters, so a did-you-mean suggestion offers
nothing.

**`hardware@3`** — three changes, arriving together for the same reason `@2`'s
three did: none was ever published on its own.

1. **A new link verb, `governed_by`** (inverse `governs`), authored on
   `requirement`, targeting `[requirement, bound]`. Fills a gap `refines` and
   `constrained_by` both leave open: "this specific fact must comply with a
   general rule stated elsewhere" is neither a narrower version of the same
   statement (`refines`) nor a machine-checkable numeric limit
   (`constrained_by`, the case where a `bound` and `checks:` are actually
   involved). Named and shaped to match `constrained_by`/`constrains` and
   `blocked_by`/`blocks`: authored passively from the affected item's side,
   with the active form computed as the backlink. Targets `bound` as well as
   `requirement` for the same reason `constrained_by`/`refines` both already
   do — a general rule is stated as often against a bound as a requirement.

2. **`satisfies` widens to `[requirement, bound]`** on both `decision` and
   `component` (each was `[requirement]`) — before this, a `bound` could be
   `verified` or `addressed` but never *satisfied*, so it could never be
   fully covered no matter how much design work answered to it (coverage is
   computed strictly from the `addressed_by`/`satisfied_by`/`verified_by`
   backlinks; `constrained_by`/`constrains` feeds none of them — see
   [which links feed coverage](coverage.md#which-links-feed-coverage)).
   `component` also gains `constrained_by: [bound]`, which it previously had
   no path to at all, and a `checks:` field, so a component can demonstrate
   compliance with a bound directly rather than a `decision` having to be
   invented purely to host the check — `run_checks()` already iterates every
   local item, so this needed no engine change.

   This course-corrects, before release, what an earlier draft of this
   version shipped as a plain new-verb addition (`governed_by` targeting
   `requirement` only, `satisfies` untouched): reviewing the standard
   against real authoring (issue #7 findings 7 and 22) surfaced both the
   missing `bound` target on `governed_by`/`component` and the fact that
   `constrained_by` was never wired into coverage in the first place. Since
   `hardware@3` had not tagged yet, both are folded into the one version
   rather than shipped narrow and corrected later as a breaking `@4`.

3. **`requirement.text`/`bound.text` merge into `body:`, and `test.method`
   does too.** `title` and `body` become the only free-prose fields any type
   carries. `title` becomes optional on `requirement`/`bound`, falling back
   exactly as `Item.title` already does for every type missing one — write
   `body:` and add `title:` only once the sentence is long enough to want a
   short label in a table. `body:` is now `required: true` on both types,
   the direct replacement for what `text: required: true` used to guarantee
   — but enforced as a **warning**, not a build-blocking error: a
   requirement with no statement isn't one, but a stub still needs to be
   able to exist while it's being drafted. `method:` folds into `body:` on
   the same reasoning, but was never `required:`, so `body:` isn't required
   on `test`. `rationale`, `source`, `note`, and the log's `summary` all
   stay: `rationale` because `required_when:` can require a field but not a
   paragraph inside prose; `source`/`note` because they're `on_change: log`,
   and folding either into an `invalidate` field would silently make a
   provenance note invalidate downstream links; the log's `summary` because
   it's required, and `log` isn't part of this change.

`hardware@1` and `@2` resolve exactly as they always have.

`refdes standard upgrade --to 3` renames `text:`/`method:` to `body:` in
every item file that still writes them. Parts 1 and 2 need no migration —
a widened target list or a new field/link accepts everything a narrower one
already did, so there's nothing existing to rename. The upgrade refuses
(rolling back) rather than silently overwriting or orphaning content on any
item that already has body content of its own before the rename — merge the
two by hand first, then upgrade.

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
  reference](schema-reference.md#required-when). The standard's own
  `decision.rationale` uses it (`required_when: {status: rejected}`), toggled
  off by setting `require_rejection_rationale: false` in
  `refdes-project.yaml`.

## Related features built on this standard

- [`blocked_by:` and the cascade report](links.md#blocked-by-and-the-cascade-report)
- [Parts indexing and the parts page](parts.md)
- [Part equivalence: `equivalent` and `alternate`](links.md#part-equivalence-equivalent-and-alternate)

## Not yet built

A dry-run report of what a project's own usage would need to change ahead
of `refdes standard upgrade`, without applying anything, is designed in
[`docs/design/standard-library.md`](design/standard-library.md) §3 but not
implemented — `refdes revise` supports `--dry-run`; `standard upgrade` does
not yet. Everything else that document specs is built.
