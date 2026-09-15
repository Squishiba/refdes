Status: draft proposal — not decided.

# `extends:` — single-level type inheritance

## Decision (recap)

Add a single-level `extends:` mechanism to the schema engine so that `bound` can
be declared as a specialization of `requirement` rather than a near-duplicate
type. Substitution is **universal (Liskov)**: anywhere a link target list names
`requirement`, a `bound` (or any future subtype) satisfies it — no opt-in
marker. Coverage grouping (whether bounds render under requirements or as their
own section) is a project setting defaulting to current behaviour (separate
sections). Single inheritance, one level only.

The decision is taken. This document specs it; it does not relitigate it.

**Implementation status:** not started — this is the design spec that the
backlog entry (finding 21) requires before implementation begins.

---

## 1. Motivation: the `requirement`/`bound` near-duplication

`hardware@v3/base.yaml` lines 128–161 declare `requirement` and `bound` as two
independent types. They share:

- `title:` (optional) and `body:` (required)
- `status:` enum (`draft`, `active`, `retired` with `default: draft`)
- `rationale:`
- `coverable: true`
- `coverable_statuses: [active]`
- `include: [provenance, stewardship]`
- `body: { on_change: invalidate, required: true }`

The only genuine difference is `bound.limit:` — a required `limit` field.
Everything else is structural duplication. The finding records that this
duplication also propagates to four separate link target lists that each
enumerate `[requirement, bound]` explicitly (`bound.derives_from`,
`test.verifies`, `log.addresses`, and the design-debate preset's
`option.met_by`), and any future requirement-like subtype would need to be
added to all of them manually. With `extends:`, those four lists collapse to
`[requirement]` — `bound` (and any future subtype) is automatically allowed
wherever `requirement` is. Separately, `component.constrained_by` is
traceability-only (finding 7) and does not participate in substitution.

---

## 2. Syntax and resolution order

### 2.1 Declaration syntax

In `refdes-schema.yaml` (project overlay) or a standard/preset `base.yaml`:

```yaml
types:
  bound:
    extends: requirement
    prefix: BND
    label: Bound
    preview: [status, title, limit]
    fields:
      limit: { type: limit, required: true, on_change: invalidate }
    links:
      refines: [bound]
```

The `extends:` key names an existing type (from base, a preset, or the project
overlay). The child type declares only its **delta**: fields to add, links to
add/override, and scalar overrides (`prefix`, `label`, `plural`, `preview`,
`coverable`, `coverable_statuses`, `satisfying_statuses`, `verifying_statuses`,
`check_severity`, `append_only`, `status` enum choices).

### 2.2 What is inherited

| Property | Inherited? | Notes |
|---|---|---|
| `fields` | **yes** (merged, child overrides by key) | Deep merge like `include:` field sets; includes fields contributed by parent's `include:` |
| `include` | **yes** (child may override) | The finding names `include: [provenance, stewardship]` as duplication to remove |
| `links` | **yes** (merged, child overrides by key) | Target lists replaced, not unioned |
| `preview` | **yes** (replaced wholesale if child declares it) | |
| `body` | **yes** (child may override) | The finding names `body:` as duplication to remove; `on_change`/`required` inherited unless overridden |
| `coverable` | **yes** (child may override) | |
| `coverable_statuses` | **yes** (child may override) | |
| `satisfying_statuses` | **yes** (child may override) | |
| `verifying_statuses` | **yes** (child may override) | |
| `check_severity` | **yes** (child may override) | |
| `append_only` | **yes** (child may NOT turn off if parent has `true` — Liskov) | Error if child sets `append_only: false` when parent has `true` |
| `status` enum `choices`/`default` | **yes** (child may override) | Child overrides *replace* the whole enum definition, not extend |
| `prefix` | **no** (error if missing) | Identity-affecting; child must declare |
| `label` | **no** (error if missing) | Child must declare |
| `plural` | **no** (error if missing) | Child must declare |

Rationale: `prefix`/`label`/`plural` are **type-identity** properties — they
affect hashing, rendering, sealing, and authoring conventions. Inheriting
them would make a subtype silently adopt the parent's identity semantics,
which is the opposite of what a deliberate specialization should do.

`include:` and `body:` **are inherited** — the finding explicitly names
`include: [provenance, stewardship]` and `body: { on_change: invalidate,
required: true }` as the duplication to remove. A child may override either.

A child may add fields/links and override a field definition (whole
definition replaced, not deep-merged) or preview. A child may **NOT** make a
parent-required field optional or turn `append_only` off (Liskov) — error.

### 2.3 Resolution order

`standards.resolve_schema()` currently merges three layers:

1. **Base standard** (`hardware@vN/base.yaml`)
2. **Selected presets** (each a full `field_sets`/`link_types`/`types` overlay)
3. **Project overlay** (`refdes-schema.yaml`)

`extends:` resolution is a **single, fourth pass**, run *after* the three-layer
merge produces a complete `types` map (i.e., after `_merge_types()` returns),
but *before* `schema.py` constructs `ItemType` objects. Algorithm:

```python
def _resolve_extends(types: dict[str, Any]) -> dict[str, Any]:
    # Topological order: parents before children
    resolved = {}
    visited = set()
    visiting = set()

    def resolve(tname: str) -> dict[str, Any]:
        if tname in resolved:
            return resolved[tname]
        if tname in visiting:
            raise SchemaError(f"extends: cycle detected involving {tname}")
        visiting.add(tname)

        spec = types[tname]
        parent_name = spec.pop("extends", None)
        if parent_name:
            if parent_name not in types:
                raise SchemaError(f"types.{tname}.extends names unknown type {parent_name!r}")
            parent_spec = resolve(parent_name)
            # Single-level check: parent must not itself extend
            if "extends" in types[parent_name]:
                raise SchemaError(
                    f"types.{tname}.extends -> {parent_name}: multi-level inheritance "
                    f"is not supported (single level only)"
                )
            # Merge: parent first, then child delta
            merged = _merge_type_dict(parent_spec, spec)
        else:
            merged = spec
        resolved[tname] = merged
        visiting.remove(tname)
        return merged

    for tname in types:
        resolve(tname)
    return resolved
```

This runs in `standards.py` after `_merge_types()` (line 328) and before
returning to `schema.py:load_project()` (line 500). The merged,
`extends:`-free `types` dict then flows through the existing `schema.py`
construction loop unchanged.

**Key consequence:** because `extends:` resolves on the *fully merged* schema,
a project overlay that adds a field to `requirement` is automatically
inherited by `bound`. Single-level enforcement and override legality
(parent-required fields staying required, `append_only` not turned off) are
checked on that merged result.

### 2.4 Composing with presets and project overlay

- A **preset** may declare a type with `extends:` pointing at a base-standard type.
- The **project overlay** may declare a type with `extends:` pointing at a base,
  preset, or another project-overlay type.
- A project overlay type **may not** `extends:` a type that itself has
  `extends:` (single-level enforcement).
- A preset type **may not** `extends:` another preset type (presets are
  independent bundles; cross-preset inheritance would create ordering
  dependencies).

---

## 3. Substitution rule: universal (Liskov)

### 3.1 Rule statement

**If type `C` `extends:` type `P`, then `C` is a subtype of `P` and satisfies
every link target list that names `P`.** No opt-in marker (`requirement+`),
no per-link annotation. The `extends:` declaration itself is the substitution
commitment: if a subtype cannot stand in for its parent *everywhere*, it should
not extend it.

This reverses the finding's earlier opt-in-marker draft. Finding 22 established
that `satisfies: [requirement]` excluding `bound` was a defect, not a
deliberate boundary — the fix *is* widening `satisfies` to `[requirement,
bound]`. Universal substitution makes that fix automatic for any future
requirement-like subtype.

### 3.2 Consumers that must honour substitution

| Consumer | File:line | Kind | Change required |
|---|---|---|---|
| Link target validation | `build.py:435` | ALLOW | Expand `allowed` with transitive subtypes before `target.type not in allowed` check |
| Schema JSON link-target completion | `schema_json.py:146` | ALLOW | Emit subtype in parent's discriminated union for completion |
| Stub tests eligibility | `stub_tests.py` | ALLOW | `already_covered` check uses `resolved_links`; subtype links already resolve correctly via link validation |
| Group/conforms_to type test | `build.py` coverage | ALLOW | Any type test that decides whether a type is in a set must use `is_subtype` |
| `{{index type=}}` | `blocks.py:163` | LISTING | Filter `item.type == type_name` — **must NOT** include subtypes by default; opt-in parameter for subtype inclusion |
| Nav / document sections | `render.py:90` | LISTING | Grouping for coverage reports (see §4); item listing unchanged |
| `refdes ls --type` | `cli.py` | LISTING | Lists concrete type only by default; subtype inclusion is explicit opt-in |

The **Kind** column distinguishes:
- **ALLOW** — substitution applies: the consumer decides *whether something is
  allowed* based on a type list. `is_subtype(child, parent)` must return true
  here.
- **LISTING** — substitution does **not** apply by default: the consumer
  produces output grouped by or filtered to a concrete type. The concrete type
  stays visible; subtype inclusion is an explicit opt-in (e.g. an index
  parameter). The coverage-grouping setting (§4) controls presentation only.

### 3.3 Implementation: `is_subtype` helper

Add to `model.py` (or `build.py`):

```python
def _build_subtype_map(types: dict[str, ItemType]) -> dict[str, set[str]]:
    """Return {parent: {child, ...}} for all direct extends: relationships."""
    sub = defaultdict(set)
    for tname, spec in types.items():
        parent = getattr(spec, "extends", None)  # stored on ItemType during construction
        if parent:
            sub[parent].add(tname)
    return sub

def is_subtype(child: str, parent: str, subtype_map: dict[str, set[str]]) -> bool:
    return child == parent or child in subtype_map.get(parent, set())
```

`subtype_map` is built once in `build()` after `resolve_links` and passed to
`compute_coverage`, `_render_index`, etc. Single-level guarantee means no
transitive closure needed — but the function is written to accept it if the
restriction is ever lifted.

**ALLOW consumers** (link validation, schema_json completion, stub tests,
group/conforms_to tests) call `is_subtype(target.type, allowed_type, map)`.

**LISTING consumers** (`{{index type=}}`, nav/document sections, `refdes ls
--type`) do **not** call `is_subtype` by default — they filter on
`item.type == type_name` exactly. The coverage-grouping setting (§4) is a
separate presentation control that groups subtypes under their parent for
display; it does not change which items are listed.

---

## 4. Coverage grouping default

### 4.1 Setting

`refdes-project.yaml`:

```yaml
coverage:
  group_inherited: false   # default = current behaviour (separate sections)
```

When `true`, `coverage.html` and per-board `coverage-<board>.html` render
subtypes under their parent type's section (e.g., `bound` items appear under
"Requirements" with a "(bound)" badge). The default `false` preserves today's
output exactly — adopting `extends:` changes no existing project's coverage
rendering.

**This setting controls presentation only.** It does not affect which items
participate in coverage computation (that is governed by the ALLOW consumers
in §3.2), nor does it change `{{index type=}}`, `refdes ls --type`, or nav
sections — those remain concrete-type listings by default.

### 4.2 Implementation

`render.py:_coverage_rows()` and `_contract_rows()` already sort by stage then
id. Add a `group_key` function:

```python
def _coverage_group_key(item: Item, project: Project, group_inherited: bool) -> str:
    if not group_inherited:
        return item.type
    # Walk up single-level extends: chain
    parent = project.types[item.type].extends
    return parent if parent else item.type
```

`summary_payload()`'s `type_rows` uses the same key for consistent counts.

---

## 5. Hashing, baselines, seals, and migration

### 5.1 Type name in hash

`build.py:1007` (`_hash_payload`) includes `payload["type"] = item.type`. This
**does not change** — the concrete type name stays in the hash. Because
`bound: {extends: requirement}` keeps `item.type == "bound"` (the child type
name is preserved, not replaced by the parent), adopting `extends:` churns **no
hashes** as long as `bound` resolves to the same fields/links/body as today.
The `type` field in the hash payload is the concrete type (`"bound"`), not the
parent (`"requirement"`).

### 5.2 Migration story for `hardware@3` — no migration needed

Since `hardware@3` is still `[Unreleased]` (per `CHANGELOG.md` and `threads.md`
top-of-document decision), it can **amend `base.yaml` directly** rather than
opening a `hardware@4`:

1. Change `bound` in `base.yaml` to declare `extends: requirement` + delta
   (the `limit:` field).
2. **No `migration.yaml` entry is needed.** A `types: {bound: requirement}`
   entry would convert every `bound` into a `requirement`, changing
   `item.type` and churning hashes — exactly what we avoid by using
   `extends:` instead.
3. The acceptance test is that every type's *resolved schema* (the
   `ItemType` objects after `extends:` resolution) is identical before/after.
   Compare the resolved `ItemType` definitions field-by-field, link-by-link,
   scalar-by-scalar. If they match, the change is hash-, baseline-, and
   seal-neutral — no migration, no `revise.py` carry-forward, no standard
   upgrade path change.

**Cost:** ~40 lines of duplication removed from `base.yaml`, replaced with
~15 lines of `extends: requirement` + delta.
**Benefit:** design-debate preset can specialize `decision` instead of
redeclaring it fully; future requirement-like subtypes need only declare
their delta.

### 5.3 Existing projects on `hardware@2`

Unaffected — they pin `version: 2` and see no `extends:` mechanism. Upgrading
to `@3` follows the normal `refdes standard upgrade` path. Since the resolved
`bound` type is identical (same fields, links, body), and `item.type` stays
`"bound"`, hashes do not churn — the upgrade is hash-neutral.

---

## 6. Single level only: enforcement and error

### 6.1 Enforcement points

1. **In `standards.py:_resolve_extends`** (see §2.3): when resolving a child,
   if the parent's raw spec (before resolution) contains `extends:`, error:
   > `types.bound.extends -> requirement: multi-level inheritance is not supported (single level only)`

2. **In `schema.py:_validate_link_targets`** (line 411): already validates
   that link targets exist; no change needed.

3. **Project overlay check**: a project overlay type declaring `extends:` on a
   type that itself `extends:` (from base or preset) is caught by the same
   resolver — the parent's raw spec still has `extends:`.

### 6.2 Error message example

```
ERROR  refdes-schema.yaml:12 — types.thermal_bound.extends names 'bound',
        which itself extends 'requirement'. Single-level inheritance only;
        thermal_bound must extend 'requirement' directly or not use extends:.
```

---

## 7. `hardware@3` adoption and interaction with `threads.md`

### 7.1 Recommendation: adopt `bound extends requirement` in `hardware@3` now

`hardware@3` is the pinned version for this repository and is still
`[Unreleased]`. The `threads.md` decision (2026-09-14) states that the
`log`/`decision` merge lands in `hardware@3`, not a new `hardware@4`.
`extends:` for `bound` is an orthogonal engine feature — adopting it in the
same version is consistent and avoids a version bump solely for this.

**Cost:**
- `base.yaml`: ~40 lines removed from `bound`, replaced with ~15 lines of
  `extends: requirement` + delta.
- **No `migration.yaml` entry needed** — the resolved `bound` type is
  identical, hashes don't churn.
- Zero engine changes beyond the `extends:` implementation itself.

### 7.2 Preset adoption waits for threads Phase 4

The threads interaction is real for **presets**. The design-debate preset's
`debate` type is substantially a `decision` (it shares `title`, `status`,
`rationale`, `date`, `options`, `checks`, `include: [provenance, stewardship,
citations]`, `satisfies: [requirement, bound]`, `constrained_by: [bound]`,
`supersedes`, `selects`, `blocked_by`, `recorded_by: [log]`, `part_of:
[group]`, `body:`). `threads.md` Phase 4 retires `decision` into `log` in
`hardware@3` — when that lands, `debate` would extend the new unified `log`
type (or a new `thread_entry` type), not `decision`.

**State:** preset adoption of `extends:` waits until after threads Phase 4.
Once `decision` is retired and the thread entry type exists, the design-debate
preset's `debate` would declare `extends: <thread_entry_type>` (name TBD by
threads Phase 4) with its delta (primarily the `options`/`checks` fields and
any debate-specific links).

---

## 8. Phasing

| Phase | Scope |
|---|---|
| **1. Engine** | `standards.py` `_resolve_extends` pass; `ItemType.extends` field; `subtype_map` in `Project`; `is_subtype` helper |
| **2. Consumers** | `build.py` link validation + coverage; `blocks.py` index filter; `schema_json.py` completion; `render.py` coverage grouping setting |
| **3. Standard** | `hardware@v3/base.yaml` convert `bound` to `extends: requirement`; `migration.yaml`; update design-debate preset to `extends: decision` |
| **4. Tests** | Positive: subtype satisfies parent link targets, coverage honors parent's `satisfying_statuses`, index groups by parent when setting on. Negative: multi-level `extends:` errors, project overlay extending an extended type errors. |

---

## 9. Open questions for Jared (recommended, Jared to decide)

1. **`prefix`/`label`/`plural` declared by child** — **Recommended: YES** (not inherited; error if missing). Prefix/label/plural are identity-affecting; a subtype must declare its own. `bound` keeps `BND`/`Bound`/`Bounds`.

2. **`coverable` inherited** — **Recommended: YES**. Subtype inherits coverage semantics unless explicitly overridden. A `bound` that didn't inherit `coverable: true` would silently drop out of coverage.

3. **Coverage grouping setting name** — **Recommended: `coverage.group_inherited`**. Describes what it does (groups inherited subtypes under parent). Alternative `group_by_parent` is less precise.

4. **Field override replaces whole definition** — **Recommended: YES**. A child overriding a field replaces the entire field definition (not deep-merged), matching `links` and `preview` semantics. This is simpler and matches the existing `_merge_type_dict` behavior for scalars.

5. **`hardware@3` adopts `extends:` for `bound` now; presets after threads Phase 4** — **Recommended: YES**. `bound extends requirement` lands in `hardware@3` immediately (no migration, hash-neutral). Design-debate preset's `debate` waits for threads Phase 4 (when `decision` retires into `log`/`thread_entry`), then extends the new thread entry type.

---

## 10. Where you might disagree

- **Universal substitution is too permissive.** The finding's original draft
  proposed an opt-in marker precisely because `decision.satisfies:
  [requirement]` accepting `bound` was seen as eroding a deliberate split.
  Finding 22 overturned that — the split was a defect. If you believe there
  *are* link targets where substitution should be opt-in, the mechanism would
  need a per-link `substitutable: true` flag or a `requirement+` marker. I
  recommend against it: one decision at type declaration is cleaner than a
  decision at every target list.

- **Coverage grouping default.** Defaulting to `false` (separate) preserves
  current output but means the primary benefit of `extends:` (unified
  requirement/bound view) is opt-in. An alternative: default to `true` for
  new projects (`refdes init` writes `group_inherited: true`), keep `false`
  for existing. This is a policy choice, not a technical one.

- **`prefix`/`label`/`plural` not inherited.** If `prefix` were inherited,
  `bound` would automatically get `REQ` and lose its distinct `BND` prefix —
  which breaks the visual distinction authors rely on. But it also means
  every subtype must redeclare `prefix`, `label`, `plural`. That's
  intentional (explicit identity), but verbose for deep specializations (not
  allowed here anyway).

- **Single-level restriction.** If a project wants `thermal_bound extends
  bound extends requirement`, they cannot. They must write `thermal_bound
  extends requirement` and include `limit:` in their own delta. This is a
  deliberate simplicity boundary; lifting it adds transitive closure logic
  and diamond-inheritance questions for marginal gain.

- **`include:` and `body:` ARE inherited.** This is the point of the finding
  — removing the duplication. A child may override either, but the default
  is inheritance, not redeclaration.

---

## 11. Backlog update

Finding 21 in `docs/design/backlog.md` should update its **Status** line from:

```
**Status: outstanding.** No `extends`/inheritance concept exists in
`schema.py`; `standards.resolve_schema()`'s layered merge is base → presets
→ project overlay only, with no type→type axis.
```

to:

```
**Status: design draft.** Spec at `docs/design/extends.md` — states the
substitution rule (universal Liskov, no opt-in marker), coverage-grouping
default (`coverage.group_inherited: false`), single-level enforcement, and
hardware@3 adoption plan. Awaiting Jared's decisions on open questions (§9)
before implementation.
```