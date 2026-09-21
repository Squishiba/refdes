Status: decided — owner (Jared) approved all five open questions as
recommended, 2026-09-20. Engine implementation landed on ao/refdes-106/root
(rename, links/body widening, conflict errors, shadow warning, doc-only
patches); the base.yaml factoring refactor is deliberately deferred to the
`extends:` pass per question 3. The two `extends:`-dependent tests landed
with the extends engine (`tests/test_composition.py`).

# Composition — widening `include:` beyond fields

## Decision (recap)

Multi-level `extends:` was rejected by the owner. Three reasons, all recorded:
coverage grouping becomes ambiguous in a chain (which ancestor groups a
grandchild's items?), override resolution would have to cross the existing
base → presets → project-overlay merge at every level, and "why does this
type have that field?" becomes an N-place question — you walk a chain to
answer it.

Duplication in the standards, though, is unacceptable. The chosen direction
is composition instead of depth: `extends:` stays single-level and does one
job only — substitutability, the Liskov relationship spec'd in
`docs/design/extends.md` — while anything that *duplicates* becomes
shareable through `include:`.

This document specs that widening: what a shareable set may contain, how
conflicts resolve, what happens to the doc-string trap, how composition and
`extends:` coexist, and what composition must never become. The evidence is
`docs/design/extends.md` §12 and `in-prog-logs/factor-field-sets.md` — an
attempt to factor every duplicated field declaration in
`src/refdes/standards/hardware/v3/base.yaml` into today's `field_sets:` with
the resolved schema held byte-identical as the oracle. The spec answers what
that attempt measured, not what a reader might imagine was duplicated.

**Implementation status:** engine landed (rename `6f2ea68`, widening
`5d05498`, doc-only patches `08b79e4`). The base.yaml refactor and the
`test_hardware3_base_resolves_unchanged` oracle ride the `extends:` pass
(open question 3, decided) -- the `extends:` half of that oracle is
`test_hardware3_base_resolves_unchanged` in `tests/test_extends.py`, the
sets-factoring half is still to do; `test_extends_naming_a_set_is_an_error`
and `test_extends_and_include_together_own_declaration_wins` are implemented.

---

## 1. What a shareable set may contain

Today `include:` carries fields only: `_expand_include`
(`standards.py:305`) merges `field_sets:` entries into `fields:` and pops
itself. §12.3 of `extends.md` measured what is byte-identical across types
but structurally unreachable (the line numbers below are re-cited against
the current `base.yaml`; §12 itself was measured before the P8/P11 commits
landed):

| Block | Groups / lines | Verdict |
|---|---|---|
| `fields:` | 0 as-is; 11 lines doc-only-different | carried today; §3 fixes the doc trap |
| `links:` | 3 groups / 9 lines | **carried** |
| `body:` | 2 groups / 6 lines | **carried** |
| `preview:` | 1 group / 2 lines | left out |
| `coverable:` + `coverable_statuses:` | 1 group / 4 lines | left out |
| `include:` itself | 2 groups / 6 lines | left out (§5) |
| `satisfying_statuses:` / `verifying_statuses:` / `check_severity:` | 0 | left out |

Each verdict argued separately.

### 1.1 `links:` — carried

The largest single cluster of duplication in `base.yaml` is a link:
`part_of: [group]` appears verbatim on five types (:158, :177, :203, :218,
:240 — nine lines, four redundant copies), and `satisfies: [requirement,
bound]` plus `constrained_by: [bound]` repeat on `decision` and `component`
(:197–198, :236–237). A link entry is a `verb: [targets]` pair; sharing one
is sharing a structural fact — "spec-content types belong to groups",
"decisions and components claim requirements and bounds". These are exactly
the facts that drift when a target list widens on one type and not its
twins (the `satisfies` widening of v3 had to be written twice for exactly
this reason, per the v3 header comment). A set may declare a `links:` block
shaped exactly as the type's own.

### 1.2 `body:` — carried

Six of seven types' `body:` lines fall into two byte-identical groups:
`{ on_change: invalidate, required: true }` on requirement/bound (:159,
:178) and `{ on_change: invalidate }` on decision/test/component/log (:204,
:219, :241, :276). `body:` is two semantic keys — `on_change`, `required` —
not identity; there is nothing type-specific about "the body invalidates
downstream when edited". Carried.

### 1.3 `preview:` — left out

One group, two lines (`preview: [status, title]` on requirement :147 and
test :210). Two reasons it stays out. First, a preview is a list of field
names the set does not own: a set carrying `preview: [status, title]`
silently asserts that every includer has `status` and `title` fields, and
that coupling is invisible — remove `title` from one includer and the set's
preview names nothing there, which is refdes's characteristic bug in schema
form. Second, two lines is the cheapest duplication in the file; the
mechanism's cost is in reader-attention, and a `preview:` a reader must
chase into a set to know what a page shows is not worth two lines. Left
out, and said to be left out.

### 1.4 `coverable:` / `coverable_statuses:` — left out

One group, four lines — and it is precisely the requirement/bound pair
(:148–149, :166–167), the same pair `extends:` already collapses: `bound
extends requirement` inherits `coverable` and `coverable_statuses` per
`extends.md` §2.2, decided 2026-09-19. After `extends:` lands, the measured
duplication here is zero. Worse, sharing coverability through a set would
create a second, non-substitutable route to coverage semantics: a type
could become coverable without being a subtype of anything, and coverage
grouping would then have two unrelated mechanisms to consult. Coverage
semantics travel by `extends:` or are declared on the type. Left out.

### 1.5 Status lists and `check_severity:` — left out

Measured duplication: zero groups. `satisfying_statuses` differ per type
(`[accepted]` on decision, `[selected]` on component); `verifying_statuses`
appears once; `check_severity` appears once. There is nothing to share, and
these keys decide coverage arithmetic — the last place to invite a
shareable indirection. Left out.

### 1.6 Identity keys — left out

`prefix`, `label`, `plural`, `append_only`, and the type's own `doc:` stay
on the type, for the reason `extends.md` §2.2 already gave: they are
identity and presentation, and identity is declared, never shared.

### 1.7 Summary

A set is a **type-spec fragment carrying exactly three keys**: `fields:`,
`links:`, `body:`. Nothing else may appear inside a `field_sets:` entry
(§5, §6).

---

## 2. Precedence, exactly

One rule, stated once, covering every shareable part:

> **A set is a fragment of the type's own spec. Sets merge into the type in
> `include:`-list order, later wins on a name collision; then the type's own
> declaration merges last and beats anything it includes. Every merge is
> by-name with whole-spec replacement — no key inside a field spec, a link
> target list, or a `body:` block is ever deep-merged across a set
> boundary.**

This is `_expand_include`'s existing rule for fields — sets in list order,
own fields overlaid last — generalized verbatim to `links:` and `body:`. A
reader can apply it without running the code: find the `include:` line, read
left to right, then the type's own block; the last declaration of a name
wins, whole.

Applied to each part:

- **`fields:`** — unchanged from today. Two sets declaring `source` → the
  later set's definition wins whole. The type's own `source` beats both.
  A field override replaces the whole definition (`extends.md` §9.4,
  decided 2026-09-19); §3 adds the one exception: a doc-only patch.
- **`links:`** — merged by verb key. The case where two included sets
  declare the same verb with **different** targets is an error (§6), not a
  silent replacement: union would widen targets invisibly (the substitution
  defect `extends.md` §10 argues against), and later-wins narrows them
  invisibly — both are correctness changes nobody authored at the point of
  use. Two sets declaring the same verb with **identical** targets is
  benign: the merge result is the same either way. The type's own verb
  declaration always wins, with no error — the type is visible at the point
  of use, so its override is authored where a reader stands.
- **`body:`** — whole replacement, not a merge of the two keys. The last
  set in the include list that declares `body:` supplies it. The case where
  a set declares `body:` and the type also does: **the type's wins whole**
  — `{ on_change: invalidate }` on the type does not inherit `required:
  true` from the set's `{ on_change: invalidate, required: true }`; the
  type's block is the entire story. Two sets declaring `body:` with
  different specs is an error (§6), same reasoning as links; identical
  specs are benign.

Weakest to strongest, always: earlier include < later include < the type's
own declaration. There is no fourth voice at this level; §4 places
`extends:` and the project overlay around it.

---

## 3. The doc-string trap

§12.2 counted it: seven field pairs identical except for `doc:`, in four
clusters, eleven lines — and because `_expand_include` overlays own fields
whole, every one of them is a trap. A shared set either flattens the
per-type wording or is redeclared per type and saves nothing. The trap
count is 7 of 7: **all** field-level duplication in hardware@3 is
doc-only-different. That is why the factoring pass removed zero lines
(`in-prog-logs/factor-field-sets.md`, chunk 2).

**Decision: a partial override is allowed, restricted to `doc:` alone.**

The rule:

> A type may redeclare a field it receives from an included set with a
> spec whose **only key is `doc:`**. That spec patches the `doc:` of the
> included definition and inherits every other key — `type`, `required`,
> `required_when`, `default`, `choices`, `on_change` — from it. Any spec
> containing a key other than `doc` is a full redeclaration and must be
> complete: it must carry `type:`, exactly as `schema.py` already requires
> of every field spec. A spec that gives some semantic keys but not all is
> an error (§6), never a patch.

Keys that may be partially overridden: `doc`. Keys that may not: `type`,
`required`, `required_when`, `default`, `choices`, `on_change` — every key
that affects validation, hashing, or invalidation. A patch that could move
any of those is a different field and must be redeclared whole.

Why doc-only, and why not the alternative:

- The measured trap is 100% doc-only, so a doc-only patch reaches 100% of
  the field-level duplication without a semantic key in sight.
- The alternative on the table — the generic sentences proposed in
  `factor-field-sets.md` chunk 2 — flattens wording that is not flavor.
  The `checks` pair's docs differ substantively: decision's states the
  `check_severity: error` behavior component does not have. The `title`
  generic sentence drops "every decision needs a label". Partial override
  keeps every type's wording exactly as written and still factors the
  structure.
- Backward compatibility is free: a field spec with only `doc:` is invalid
  today (`schema.py` requires `type:`), so no existing file changes meaning.

Effect on the four clusters: `title`/`status`/`rationale` (requirement +
bound) and `title` (component + decision + test) move into sets, each type
keeping one line — `title: { doc: "..." }` — of per-type wording. The
`checks` pair stays fully redeclared on both types unless the owner
separately approves a generic sentence for it (open question 2).

If this decision were reversed, the author writes instead: the full field
definition on every type (today's behavior, eleven lines stay), or the
generic sentences with the caveats `factor-field-sets.md` records (per-type
nuance lost, owner approval required per cluster).

---

## 4. Interaction with `extends:`

A type may both extend a parent and include sets. Four layers are in play.
Weakest to strongest:

1. **The parent's resolved spec.** Fills gaps only; never overrides.
2. **The included sets**, in `include:`-list order, later wins.
3. **The type's own declaration** — including everything the project
   overlay merged into that type.
4. **The project overlay** — not a fifth voice at type level. It is folded
   into whichever layer it targets *before* `extends:` resolution: an
   overlay edit to a type lands in layer 3 for that type; an overlay edit
   to a parent lands in layer 1 for its children; an overlay edit to a set
   lands in layer 2 for every includer.

The parent is weakest because `extends:` expresses "this is a kind of that,
plus a delta": a subtype that could not restate anything it inherited could
not express its delta. The type's own declaration beats its includes
because the include line is a pointer and the type's block is authored at
the point of use.

Where each layer is applied today, by file and function:

| Layer | Applied in |
|---|---|
| base ← presets (types, link types, field sets) | `standards.py::resolve_namespaces` via `_load_standard`; sets merged by `_merge_field_sets` (`standards.py:71`) |
| project overlay ← onto base+presets | `standards.py::resolve_namespaces` lines 71–73: `_merge_field_sets`, `_merge_link_types`, `_merge_types` (types deep-merged by `_merge_type_dict`) |
| included sets → type (layers 2, and 3's fields) | `standards.py::_expand_include`, called from `_merge_types` (`standards.py:361, 371`) — this spec widens it from `fields:` to `fields:`/`links:`/`body:` |
| type's own declaration | same call: own `fields:`/`links:`/`body:` overlaid last inside `_expand_include` / `_merge_types` |
| parent's resolved spec | `_resolve_extends`, the single pass spec'd in `extends.md` §2.3 — runs after `_merge_types` returns, before `schema.py::load_project` constructs `ItemType` objects (`schema.py:489` resolves, the construction loop follows) |

Consequences worth naming:

- **A type that both extends and includes**: its includes are expanded
  into its spec *before* `_resolve_extends` runs, so everything it got from
  sets sits in layer 3 and beats the parent. The parent's own includes were
  expanded into the parent's spec before it was used as a base, so the
  child receives the parent's set contributions at layer 1 — the weakest
  position — and may restate any of them.
- **Overlay edits to a set propagate to every includer.** This is already
  true today (`_merge_field_sets` at line 71 runs before `_merge_types`
  expands includes): a project editing `provenance` changes what base types
  get from it. Widening sets widens the blast radius of that one-hop edit to
  links and body. It stays one hop — the same radius as an overlay edit to
  a parent propagating to its child — and it is the reason the overlay is
  not a fifth layer: it acts *through* the layer it targets.
- **"Why does this type have that field?" stays a three-place question**:
  the type's own block, one of the sets named on its `include:` line, or
  its single `extends:` parent. Never a chain of either. That is the whole
  reason composition was chosen over depth.

---

## 5. What this is not

Composition must not become a second inheritance axis by the back door.
Three refusals, each with the thing that refuses:

- **Sets do not include sets.** An `include:` key inside a `field_sets:`
  entry is a validation error, not a merge. Nested sets would recreate the
  N-place question that killed deep extends — "why does this type have that
  field?" answered through a chain of set references — and give collisions
  a topology to hide in. The refusal is `configcheck.py::field_sets`: the
  set-entry key whitelist becomes `{fields, links, body}` and anything else
  fails at validation, before any merge runs.
- **Sets are not types.** A set has no `prefix`, `label`, or `plural`; it
  cannot be instantiated, cannot appear in a link target list, and cannot
  be named by `extends:`. The refusals: `schema.py::_validate_link_targets`
  validates targets against `types` only; `_resolve_extends` looks up
  `extends:` names in `types` only — naming a set there errors with a
  message that says sets are shareable fragments, not types (§6.5). A set
  name colliding with a type name is itself refused (§6.6) so the two
  namespaces stay unambiguous in every other error message.
- **Nothing is substitutable because it shares a set.** `is_subtype`
  (`extends.md` §3.3) is built from `extends:` edges only. Two types that
  include the same set are unrelated to every ALLOW consumer — link target
  validation, `schema_json` completion, stub-test eligibility. The refusal
  is structural: include leaves no trace the subtype map could read. The
  resolved schema today keeps no record of who included what
  (`_expand_include` pops the key); the vocabulary page infers includers
  from field supersets (`vocabulary.py::_includers`) and must be widened to
  links and body alongside this change — an inference for docs, never an
  engine input.

There is no diamond problem because there is no graph: a type's field can
come from at most its own declaration, one set per name (the winner of a
flat, nameable collision — §2), and one parent. Every conflict is between
two named things visible on one line.

---

## 6. Failure modes and named tests

refdes's characteristic bug is reporting success while doing nothing. In
composition that bug wears two faces: a set that silently contributes
nothing the type keeps, and a merge that silently replaces something
correct with something else. The loud/warning line is drawn by authorship:
**when two sets fight, neither set's author wrote the conflict — that is
an error. When the type outvotes a set it names on its own line, the
override is authored where the reader stands — that is documented
behavior.**

### 6.1 Loud errors (SchemaError, load blocked)

1. **A set declares a key outside `{fields, links, body}`** — catches
   `include:` inside a set, `coverable:`, `prefix:`, everything §1 left
   out:
   > `field_sets.<name> may not declare '<key>': a set carries fields, links and body only`

2. **Two included sets declare the same link verb with different targets**
   (identical targets are benign):
   > `types.<type>.include: sets '<a>' and '<b>' both declare link '<verb>' with different targets (<a-targets> vs <b-targets>); the later would silently replace the earlier — declare '<verb>' once, on the type`

3. **Two included sets declare `body:` with different specs** (identical
   benign):
   > `types.<type>.include: sets '<a>' and '<b>' both declare body with different specs; the later would silently replace the earlier — declare body on the type instead`

4. **A field override that is neither full nor doc-only** — has some
   semantic keys but not `type:`:
   > `types.<type>.fields.<field> overrides an included field but is neither a full definition (missing 'type') nor a doc-only patch; keys given: <keys>`

5. **`extends:` names a set, not a type:**
   > `types.<type>.extends names '<name>', which is a field_set, not a type; sets are shareable fragments — extends names a type`

6. **A set name collides with a type name:**
   > `field_sets.<name> collides with types.<name>; a name may be a type or a set, not both`

### 6.2 Warning (build proceeds)

- **An include that contributes nothing**: every key a set brings is
  shadowed by a later set or the type's own declaration →
  > `types.<type>.include: set '<name>' contributes nothing that survives the merge`

  Warning, not error, because deliberate shadowing is legitimate — a type
  may override every field of a set it includes, and an overlay may
  legitimately empty a set for one project. The silent-total-shadow case
  is legal-but-worth-seeing; the loud cases above are the ones where the
  resolved schema differs from what any single author wrote.

Unknown set names, bare-string `include:`, and unknown keys inside a set's
field specs already error (`_expand_include`'s existing messages,
`configcheck.py`); they are unchanged.

### 6.3 Named tests an implementation must add

Positive:

- `test_include_carries_links` — a set's `part_of: [group]` reaches the
  includer's resolved `links:`.
- `test_include_carries_body` — a set's `body: { on_change: invalidate }`
  reaches the type's resolved body config.
- `test_type_own_body_beats_included_body_wholesale` — type's
  `{ on_change: invalidate }` does not inherit `required: true` from the
  set's body.
- `test_two_sets_same_verb_identical_targets_is_fine`.
- `test_doc_only_field_patch_inherits_the_rest` — patch replaces `doc:`;
  `type`, `on_change`, `choices`, `default` survive from the set.
- `test_extends_and_include_together_own_declaration_wins` — a four-layer
  probe: parent, set, own declaration, overlay edit to the parent; each
  layer's winner asserted.
- `test_hardware3_base_resolves_unchanged` — after `base.yaml` is refactored
  onto widened sets, the resolved-schema JSON dump is byte-identical to the
  pre-refactor dump (the `factor-field-sets.md` oracle, promoted to a
  permanent regression test), and the docs-site output hashes match.

Negative (each asserts the exact message of §6.1):

- `test_set_declaring_include_is_an_error`
- `test_set_declaring_coverable_or_prefix_is_an_error`
- `test_two_sets_same_verb_different_targets_is_an_error`
- `test_two_sets_different_body_is_an_error`
- `test_field_patch_with_semantic_key_is_an_error`
- `test_extends_naming_a_set_is_an_error`
- `test_set_name_colliding_with_type_name_is_an_error`

Structural:

- `test_including_a_set_confers_no_substitutability` — two types include
  one set; a link target list naming one still rejects the other.
- `test_include_contributing_nothing_warns` (and does not error).

---

## 7. Open questions for Jared (all decided as recommended, 2026-09-20)

1. **Rename `field_sets:` to `sets:`?** — **Recommended: YES, now.** The
   moment sets carry links and body, the name `field_sets` is a lie in
   every error message, doc page, and vocabulary entry. hardware@3 is
   unreleased, so the rename costs a find-replace across base.yaml,
   presets, `configcheck.py`, `schema.py` (`SCHEMA_KEYS`), and docs — no
   migration, no content churn. **Cost of keeping the name:** after v3
   ships, the rename needs a `migration.yaml` entry and every pre-existing
   overlay carries the misleading key forever.

2. **Apply the generic doc sentences from `factor-field-sets.md` to the
   `checks` cluster anyway?** — **Recommended: NO.** With doc-only patches
   (§3), per-type wording costs one line per type; flattening decision's
   `check_severity` sentence into a generic one loses information the docs
   are for. **Cost of no:** the `checks` pair stays two full declarations
   (2 duplicated lines) — the only field duplication that survives this
   spec, and the cheapest in the file.

3. **Land the base.yaml refactor in the same pass as the engine change, or
   after?** — **Recommended: same pass as `extends:` adoption**
   (`extends.md` §7.1): one resolved-schema-oracle acceptance run, one
   hash-neutrality proof, one window for drift. **Cost of separate
   passes:** two oracle runs and two windows in which a silent resolved-
   schema change can slip between the refactor and the check.

4. **Total-shadow: warn or stay silent?** — **Recommended: warn** (§6.2).
   **Cost of silence:** a set whose entire contribution is shadowed looks
   like it does something — the characteristic bug wearing a legal face.
   **Cost of error:** blocks the legitimate pattern of a type deliberately
   overriding every field it inherits from a set, and makes sets fragile
   to add fields later (a new field in `provenance` could error every
   project that shadows it).

5. **Should presets be able to define sets that base types include?**
   Today a preset can *edit* an existing set a base type includes —
   `_merge_field_sets` runs before include expansion — and thereby change
   what a base type gets, one hop, invisibly from the base file. This spec
   widens that power to links and body. **Recommended: keep it, and name
   it in the standard-library docs** — it is the same one-hop overlay
   power `extends.md` §2.4 already accepts for presets, and forbidding
   preset edits to sets would break the citation-set pattern that finding
   25 shipped. **Cost of keeping:** a preset can widen a base type's link
   targets without the base file saying so; the mitigation is the
   resolved-schema oracle in `test_hardware3_base_resolves_unchanged` and
   `refdes configcheck` reporting which preset last touched each set.

---

## 8. Where you might disagree

- **Links in sets is too far.** One could carry only `fields:` and `body:`
  and leave `links:` on types, on the grounds that target lists are
  correctness. But the measured file says otherwise: links are the biggest
  duplication cluster (9 lines), the widening history (v3's `satisfies`
  change, written twice) shows the drift is real, and §2's conflict-error
  makes cross-set link fights loud rather than silent. If you disagree,
  the cost of the narrower version is that `part_of: [group]` stays on
  five types.

- **Doc-only patches make `doc:` second-class.** A patch can rewrite the
  sentence but nothing else; someone wanting "same field, same doc, one
  different `on_change`" must redeclare whole. That is deliberate — every
  non-doc key moves hashing or validation — but it means `doc:` is the
  only key with a cheap edit, and a reader may not know that without this
  section.

- **The parent weakest.** `extends.md` §2.3 merges parent-under-child;
  this spec puts sets between them. An alternative is parent-over-sets —
  a parent's declaration beating a child's includes — but then a child
  could not override its parent by adding a set, and the parent's wording
  (the doc trap again) would be unpatchable at the child.

- **`include:` lines stay duplicated** (6 lines, §1.6). Flat composition
  means `include: [provenance, stewardship]` is written four times. Nested
  sets would remove them and reintroduce the N-place question; the six
  lines are the price of every answer being one hop, and it is the right
  price.
