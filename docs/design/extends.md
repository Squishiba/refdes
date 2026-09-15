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

- `text:` / `title:` (v3 unified to `body:` + optional `title:`)
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
`test.verifies`, `log.addresses`, `option.met_by` in the design-debate preset),
and any future requirement-like subtype would need to be added to all of them
manually.

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
| `fields` | **yes** (merged, child overrides by key) | Deep merge like `include:` field sets |
| `links` | **yes** (merged, child overrides by key) | Target lists replaced, not unioned |
| `preview` | **yes** (replaced wholesale if child declares it) | |
| `coverable` | **yes** (child may override) | |
| `coverable_statuses` | **yes** (child may override) | |
| `satisfying_statuses` | **yes** (child may override) | |
| `verifying_statuses` | **yes** (child may override) | |
| `check_severity` | **yes** (child may override) | |
| `status` enum `choices`/`default` | **yes** (child may override) | |
| `prefix` | **no** | Identity-affecting; child must declare |
| `label` | **no** | Child must declare |
| `plural` | **no** | Child must declare |
| `append_only` | **no** | Semantic boundary; child must declare |
| `body` | **no** | `on_change`/`required` may differ; child must declare |
| `include` | **no** | Composition mechanism, not inheritance; child declares own |

Rationale: `prefix`/`label`/`plural`/`append_only`/`body` are **type-identity**
properties — they affect hashing, rendering, sealing, and authoring conventions.
Inheriting them would make a subtype silently adopt the parent's identity
semantics, which is the opposite of what a deliberate specialization should do.
`include:` is a field-set composition mechanism, orthogonal to type inheritance.

### 2.3 Resolution order

`standards.resolve_schema()` currently merges three layers:

1. **Base standard** (`hardware@vN/base.yaml`)
2. **Selected presets** (each a full `field_sets`/`link_types`/`types` overlay)
3. **Project overlay** (`refdes-schema.yaml`)

`extends:` resolution is a **fourth pass**, run *after* the three-layer merge
produces a complete `types` map, but *before* `schema.py` constructs
`ItemType` objects. Algorithm:

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
returning to `schema.py:load_project()` (line 500). The merged, `extends:`-free
`types` dict then flows through the existing `schema.py` construction loop
unchanged.

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

| Consumer | File:line | Change required |
|---|---|---|
| Link target validation | `build.py:435` | Expand `allowed` with transitive subtypes before `target.type not in allowed` check |
| Coverage (`_coverage_for`) | `build.py:589–641` | `satisfier_spec` lookup uses `project.types[satisfier.type]`; must also check parent's `satisfying_statuses`/`verifying_statuses` when subtype declares none |
| `{{index type=}}` | `blocks.py:163` | Filter `item.type == type_name` → `item.type == type_name or is_subtype(item.type, type_name)` |
| Nav / document sections | `render.py:90` | Grouping for coverage reports (see §4); item listing unchanged |
| Schema JSON (completion) | `schema_json.py:146` | Emit subtype as its own branch *and* include in parent's discriminated union for completion |
| Stub tests | `stub_tests.py` | `already_covered` check uses `resolved_links`; subtype links already resolve correctly via link validation |
| Imports | `imports.py` | Cross-project link validation uses same `resolve_link_target`; inherits fix automatically |

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
**does not change** — the concrete type name stays in the hash. Consequence:

- Converting `bound` from a standalone type to `extends: requirement` in a
  standard changelog **churns content hashes** for every `bound` item (its
  `type` field changes from `"bound"` to `"requirement"`).
- This is the same as any type rename (`constraint` → `bound`, `text` →
  `title`) and is handled by `revise.py`'s existing baseline/seal carry-forward
  machinery (`_carry_forward_baselines`, `_carry_forward_seals`).

### 5.2 Migration story for `hardware@3`

Since `hardware@3` is still `[Unreleased]` (per `CHANGELOG.md` and `threads.md`
top-of-document decision), it can **amend `base.yaml` directly** rather than
opening a `hardware@4`:

1. Change `bound` in `base.yaml` to declare `extends: requirement` + delta.
2. Add `hardware@v3/migration.yaml`:
   ```yaml
   types:
     bound: requirement   # type rename; delta fields carried by extends:
   fields:
     requirement:         # keyed by OLD type name
       limit: null        # not a rename; limit is new on bound, so no field mapping needed
   ```
   (Actually, since `extends:` resolution happens at load time, the migration
   only needs the type rename; the delta is expressed in the new `base.yaml`.)

3. `refdes standard upgrade --to 3` runs `revise.apply()` with this mapping,
   carrying hashes forward via the existing conditional rule (match old hash
   → swap to new-format hash).

**Cost:** one `migration.yaml` entry (~5 lines), standard upgrade path unchanged.
**Benefit:** ~40 lines of duplication removed from `base.yaml`; design-debate
preset can specialize `decision` instead of redeclaring it fully.

### 5.3 Existing projects on `hardware@2`

Unaffected — they pin `version: 2` and see no `extends:` mechanism. Upgrading
to `@3` follows the normal `refdes standard upgrade` path with hash carry-forward.

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

### 7.1 Recommendation: adopt in `hardware@3`

`hardware@3` is the pinned version for this repository and is still
`[Unreleased]`. The `threads.md` decision (2026-09-14) states that the
`log`/`decision` merge lands in `hardware@3`, not a new `hardware@4`.
`extends:` is an orthogonal engine feature — adopting it for `bound` in the
same version is consistent and avoids a version bump solely for this.

**Cost:**
- `base.yaml`: ~40 lines removed from `bound`, replaced with ~15 lines of
  `extends: requirement` + delta.
- `migration.yaml`: one `types: {bound: requirement}` entry.
- Zero engine changes beyond the `extends:` implementation itself.

**Interaction with threads:** None. `threads.md` Phase 4 merges `log` and
`decision` into a unified `log` type with `follows:` chaining. `extends:`
operates on the type system (`requirement`/`bound`); `threads` operates on
the `log`/`decision` vocabulary. They touch disjoint type sets.

---

## 8. Phasing

| Phase | Scope |
|---|---|
| **1. Engine** | `standards.py` `_resolve_extends` pass; `ItemType.extends` field; `subtype_map` in `Project`; `is_subtype` helper |
| **2. Consumers** | `build.py` link validation + coverage; `blocks.py` index filter; `schema_json.py` completion; `render.py` coverage grouping setting |
| **3. Standard** | `hardware@v3/base.yaml` convert `bound` to `extends: requirement`; `migration.yaml`; update design-debate preset to `extends: decision` |
| **4. Tests** | Positive: subtype satisfies parent link targets, coverage honors parent's `satisfying_statuses`, index groups by parent when setting on. Negative: multi-level `extends:` errors, project overlay extending an extended type errors. |

---

## 9. Open questions for Jared

1. **`prefix` inheritance** — Finding 21 draft shows `bound` keeping `BND`. I recommend **NOT inherited** (prefix is identity-affecting; a subtype must declare its own). Agree?

2. **`coverable`/`coverable_statuses` inheritance** — I recommend **YES** (subtype inherits coverage semantics unless explicitly overridden). A `bound` that didn't inherit `coverable: true` would silently drop out of coverage. Agree?

3. **Coverage grouping setting name** — `coverage.group_inherited` vs `coverage.group_by_parent`. I recommend `group_inherited` (describes what it does). Agree?

4. **Other `extends:` candidates in `hardware@3`** — Only `bound` identified. `group` is deliberately `coverable: false` and non-satisfiable; `log`/`decision` merge is separate (threads.md). Any others?

5. **`status` enum inheritance detail** — Child inherits parent's `choices`/`default` but may override. If child overrides `choices`, does it *replace* or *extend*? Recommend **replace** (simpler, matches field/link merge semantics). Agree?

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

- **`prefix` not inherited.** If `prefix` were inherited, `bound` would
  automatically get `REQ` and lose its distinct `BND` prefix — which breaks
  the visual distinction authors rely on. But it also means every subtype
  must redeclare `prefix`, `label`, `plural`. That's intentional (explicit
  identity), but verbose for deep specializations (not allowed here anyway).

- **Single-level restriction.** If a project wants `thermal_bound extends
  bound extends requirement`, they cannot. They must write `thermal_bound
  extends requirement` and include `limit:` in their own delta. This is a
  deliberate simplicity boundary; lifting it adds transitive closure logic
  and diamond-inheritance questions for marginal gain.

- **`include:` not inherited.** A child type must redeclare `include: [...]`
  if it wants the same field sets. This is verbose but correct: `include:`
  composes *fields*, `extends:` composes *type semantics*. Mixing them would
  make `include:` order-dependent on the inheritance chain.

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