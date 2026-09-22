Status: proposed (drafted 2026-09-21) — a design spec, not a decision. Every
open question in §10 carries a recommendation, and each recommendation is the
default if Jared lets it stand unanswered. §11 records what was already
considered and rejected, including one rejection Jared made directly.

# Candidate parts: comparing, disqualifying, and selecting

## Decision (recap, as proposed)

Choosing a part today means writing a comparison by hand — a markdown table of
four buck converters against two limits, maintained in parallel with the items
that actually hold the numbers, and stale the moment any of them changes. The
tool already knows every number in that table: candidates are `component`
items, they already carry `checks:` against bounds, and every check already
records a pass/fail verdict and a margin.

Four changes, in one release, because each one is incomplete without another:

- **(A) `{{compare}}`** — a generated block (§3) that renders candidate items
  as rows, their fields and calc values and their checks-against-bounds as
  columns, and marks which rows fail. It is a **view over checks that already
  ran**, never a second evaluator.
- **(B) Status-dependent `check_severity`** (§4) — a type's `check_severity`
  may be written as a mapping from `status` to level, so a failing check on a
  `candidate` is `info` and the same failing check on a `selected` part is an
  `error`. Scalar `check_severity` is unchanged, byte for byte.
- **(C) A `rejected` component status** (§5) — `hardware@3`'s component enum
  becomes `[candidate, selected, rejected, obsolete]`. `rejected` never
  satisfies; it is not `obsolete`.
- **(D) A recommended project layout** (§6) — `items/<board>/candidates.yaml`
  as a list file with `defaults: {type: component, status: candidate}`. A
  convention the tool *supports*; it derives nothing from the path.

The through-line: **a candidate is a component, not a different kind of thing.**
Every rejected alternative in §11 that introduces a parallel `option`/`candidate`
type fails for the same reason — it splits one part into two items at the moment
of selection, and everything keyed to `component` (the parts page, `part_number`
indexing, `drop_in`/`alternate`, `selects:`, coverage) silently loses the loser.

---

## 1. Motivation: the table nobody can keep correct

`docs/checks.md` already names this exact scenario under "Candidates vs.
decisions" — comparing four microcontrollers against a shared
`BND-IO-008 (>= 2 DACs)`, where two lacking a DAC is *the finding*, not a
defect — and its answer is a separate `option` type with `check_severity: info`
(the `design-debate` preset). That answer is half right. It gets the severity
question right and the ontology question wrong:

- A candidate part has a `part_number`, and the parts page indexes
  `part_number` on any item (§2 of `docs/parts.md`). An `option` type carries a
  part number that is not a component's part number, so the same silicon
  appears twice on `parts.html` — once as the thing under consideration and
  once as the thing that got picked.
- `selects:` targets `component` (`hardware@3/base.yaml`). A decision cannot
  select an `option`, so selection means creating a second item for the winner
  and leaving the loser as a different type forever.
- `drop_in:` and `alternate:` are component-to-component. The most useful
  claim to make *during* a comparison — "this one is a drop-in second source
  for that one" — is illegal between an option and a component.

What actually varies during a part selection is not the item's **type**. It is
what a failing check **means** at each stage of that item's life. That is a
severity question (§4), and once severity can depend on status, the comparison
table becomes a rendering question over data that already exists (§3), and the
missing status that makes the whole thing legible becomes obvious (§5).

---

## 2. What already exists, and what each piece adds

| Existing | What it gives the comparison | What it lacks |
|---|---|---|
| `component.checks` (`hardware@3`) | Every candidate already declares `{value, against}` entries and gets `CheckResult.ok`, `.actual`, `.limit`, `.margin` | No way to see N candidates × M bounds in one place |
| `Limit.margin()` (`calc.py:592`) | Fractional headroom, comparable across unrelated quantities, negative = violated | Only surfaces per-item and in `summary.html`'s project-wide sort |
| `check_severity` (scalar, `schema.py:594`) | A failing check on a scoring type can be `info` | One level per **type**; a part is scored as a candidate and asserted as a selection, in the same type |
| `component.status` `[candidate, selected, obsolete]` | `satisfying_statuses: [selected]` — an unsettled part leaves coverage at `claimed` | No way to say "considered and not chosen" without `obsolete`, which means something else (§5.2) |
| `{{index}}` (`blocks.py`) | The block framework: strict params, unknown name left literal, local items only, empty state, `⚠` on validation failure | Groups one type by one field into ID/Title tables; no cross-item columns, no check values |
| `defaults:` in a list file (`parse.py:601-627`) | Merged under every item in the file, item values win | Unused for parts; nothing recommends where candidates should live |

---

## 3. (A) `{{compare}}` — the comparison table

### 3.1 Syntax

```markdown
{{compare type="component" against="BND-PWR-011, BND-PWR-012"}}
```

A new `BlockSpec` in `blocks.py::_REGISTRY`, following every convention the
family already has (`docs/blocks.md`, `docs/design/index-blocks.md` §7): alone
on its own line, `key="value"` attributes, unknown block name left completely
untouched, unknown or missing parameter a build error naming the accepted set,
a `⚠` marker rendered in place of the failed directive, **local items only**,
and an empty state that is a paragraph rather than an error.

| Parameter | Required | Meaning |
|---|---|---|
| `type` | yes | The item type to compare. Must be a declared type. Must declare a `checks` field when `against=` is present — otherwise there is nothing to compare on, and that is an error naming the fix, not an empty table. |
| `against` | no | Comma-separated bound IDs. Each becomes one column. Every ID must resolve to an item whose type declares a `limit` field; imported bounds are allowed, because `checks: against:` already allows them (`docs/checks.md`, "Why this matters across projects"). |
| `columns` | no | Comma-separated column list. A bare name is a field declared on `type`; `calc:NAME` is a value from that item's calc blocks. Default: the type's declared `preview:` list, falling back to `title`. Order here is the rendered column order. |
| `status` | no | Comma-separated `status` values to include. Each must be one of the type's declared `choices`. Default: every status the type declares. |
| `board` | no | Same semantics and validation as `{{index}}`. |
| `tag` | no | Same semantics and validation as `{{index}}`. |
| `subtypes` | no | Same semantics and default as `{{index}}` (`coverage.group_inherited`). |

`against=` is optional so a spec-only comparison (four parts, their
`part_number`, `V_in_max`, `I_q` — no bounds) is the same block rather than a
second one. With no `against=`, no check columns and no Checks score column are
rendered.

### 3.2 It renders checks that already ran; it never runs one

This is the load-bearing rule of the block, and the reason it is a block and
not a query language.

`run_checks` (`build.py:1232`) is the only thing in refdes that evaluates a
`checks:` entry. It produces `CheckResult(value_name, against, ok, detail,
actual, limit, margin)` and stores it on the item. `{{compare}}` reads
`item.checks` and formats it. It does not touch `item._env`, does not parse a
limit, and does not compare anything.

The alternative — the block evaluating `against=` bounds against each row's
calc env itself — is rejected (§11.3), and the reason is the one this project
keeps arriving at: two evaluators means two answers. A page that computes its
own verdicts can disagree with `index.html`'s failing-check count, with
`items.json`, and with the release gate, and the disagreement is invisible
because both render green-or-red without saying which engine said so. It would
also be the first block that *decides* something, which `docs/blocks.md`'s
non-goal section rules out in as many words: "a block only ever selects and
arranges items that already exist in the project; it cannot decide that
something exists, is true, or is correct."

Consequence worth stating plainly: **a candidate that never declares a
`checks:` entry against a bound shows `—` in that bound's column, not a
computed result.** "Nobody checked" is a real and visible state, and it is not
the same cell as "checked and passed".

### 3.3 Rows

Rows are the local items of `type` surviving the `board=`/`tag=`/`status=`
filters, in the same single comprehension `{{index}}` uses. **Ordering is by
ID ascending, always, with no `order=` or `sort=` parameter.**

`{{index}}` already refuses `sort=` (docs/design/index-blocks.md §2) and the
argument transfers intact, with one addition specific to this block: a
comparison table whose row order depends on check results reorders itself when
someone edits a bound, which turns a review diff of the page into noise, and
silently moves the failing row out of first-glance position. Ranking is
already a project-level view — `summary.html` sorts every margin
tightest-first (`render.py:427`) — and that is where a *ranking* belongs.
The block is the roster.

### 3.4 Columns

Left to right:

1. **ID** — linked, as in every other generated table.
2. **`columns=`** in the order written.
   - A bare name must be a field declared on `type`; otherwise:
     `type 'component' has no field 'Iout'. Declared fields: checks,
     part_number, refdes, rationale, status, title.` — the same message shape
     `{{index}}` produces, so an author who has seen one has seen both.
   - `calc:NAME` is a namespaced reference to a calc value, formatted with
     `calc.format_value` (nominal with units, 4 significant figures). The
     prefix is not new syntax invented here: `cite:` and `fig:` already
     namespace a bare name in this project's markdown (`docs/markdown.md`).
     It exists so a field named `I_out` and a calc named `I_out` cannot be
     resolved by a silent precedence rule nobody reading the page can see —
     the same objection `keys.md` §3 raises against a display-id fallback.
     A bare name that is *also* a calc name is not an error; it means the
     field, which is what it says.
   - A `calc:` name no row in the current selection defines is an error
     naming what the first row does define (a typo); a name some rows define
     and others don't is legal, and the rows without it render `—`.
3. **One column per `against=` bound**, in the order written. Header is the
   bound's display id and its limit text (`BND-PWR-011 ≥ 3 A`). Cell content is
   the verdict and the margin: `pass +88%`, `fail −33%`. `ok is None` (the
   check could not be evaluated) renders `error` — and that row already failed
   the build, because unevaluable checks are errors regardless of severity
   (`docs/checks.md`).
4. **A Checks score column**, present whenever `against=` is present:
   `passed/total` across the bound columns shown — `2/2`, `1/2`, `0/2`, `—`
   when the row declares no checks against any of them. This is the
   disqualification signal, and it is arithmetic over the columns to its left,
   not a verdict the block invents: there is no rule here about how many
   failures disqualify a part, because that is an engineering judgement the
   decision item records in prose.

Failing cells carry `class="check-fail"`; the row itself is not styled, because
a row with one failed criterion and a second good one is exactly the row an
author is weighing, and greying it out pre-judges it.

### 3.5 Missing values

`—` (em dash) with `class="compare-missing"`, for: an unset field, a calc the
item doesn't define, a check the item doesn't declare against that bound.
Never blank, never `0`, never `None`, never the previous row's value. The
legend under the table spells the three states out once:

```
— not specified    pass/fail checked    error check could not be evaluated
```

This matters more here than in `{{index}}`, because in a comparison an empty
cell is read as "no" by a reviewer, and "nobody wrote it down" and "it fails"
are different findings with different fixes.

### 3.6 Hashes, seals, baselines, and `--no-write`

- **Never hashed.** Blocks live on narrative pages; pages are not items and
  carry no content hash. A `{{compare}}` directive's text is not hashed, and
  nothing it renders enters any item's hash. Editing a bound's `limit` changes
  the table's cells; it changes the *bound's* hash (limits are
  `on_change: invalidate`) and therefore the suspect-link state of items that
  link to the bound — which is the existing, correct behaviour, and the table
  adds nothing to it.
- **No sealing interaction.** Only `append_only` items (the log) are sealed,
  and blocks are illegal in item bodies, so no seal can ever contain a
  `{{compare}}` directive or its output. A sealed log entry describing a part
  selection is a frozen record; the live table beside it is the project's
  current state. Those two disagreeing is correct — the entry says what was
  believed on 2026-09-21, the table says what is true today — and it is the
  reason a *frozen* comparison belongs on the decision item's `options:`
  panel (`name`/`verdict`/`because`, rendered as the options-considered panel)
  rather than in a snapshot of this table.
- **`--no-write` changes nothing.** The block writes nothing to the source
  tree — it mints no keys, expands no references, seals nothing — so
  `refdes build --no-write` renders it identically to a writable build, and
  `_site/` is still written exactly as `docs/design/keys.md` §2 specifies.
  Acceptance test: build the fixture twice, once with `--no-write`, and diff
  the rendered page byte-for-byte (§9).
- **Imports.** Rows are local-only, matching `{{index}}`. An imported
  component is another project's candidate with another project's checks, and
  listing it here would put a row on this page whose numbers this build did
  not produce. Bounds may be imported; rows may not.

### 3.7 Failure modes

Every one names the exact fix, the family's standing bar:

```
{{compare type="compnent"}} — unknown type 'compnent'. Did you mean 'component'?
```

```
{{compare type="component" columns="Iout"}} — type 'component' has no field
    'Iout'. Declared fields: checks, part_number, refdes, rationale, status, title.
    For a calc value, write calc:Iout.
```

```
{{compare type="component" against="REQ-PWR-004"}} — 'REQ-PWR-004' declares no
    limit. compare's against= needs a bound (a type with a 'limit' field).
```

```
{{compare type="component" status="maybe"}} — type 'component' has no status
    'maybe'. Declared choices: candidate, selected, rejected, obsolete.
```

```
{{compare type="requirement" against="BND-PWR-011"}} — type 'requirement'
    declares no 'checks' field, so there is nothing to compare against
    BND-PWR-011. Drop against=, or compare a type that declares checks.
```

```
{{compare type="component" calc="I_out"}} — unknown parameter 'calc'. compare
    accepts: against, board, columns, status, subtypes, tag, type.
```

Plus one **warning**, not an error: a bound named in `against=` that no row
item checks against. All-`—` columns read as a completed comparison, which is
the project's characteristic bug — a build that reports success while the
thing is missing. The message names the bound and the page:

```
WARNING {{compare}} on power-rail.md: no component in this selection has a
    checks: entry against BND-PWR-011. Its column will be empty.
```

---

## 4. (B) Status-dependent `check_severity`

### 4.1 Syntax

`check_severity` keeps accepting the scalar and additionally accepts a mapping
from a `status` value to a level:

```yaml
types:
  component:
    check_severity:
      candidate: info      # a candidate failing a criterion is the finding
      selected: error      # the part you actually chose must pass
      rejected: info       # history, not a defect
      obsolete: info
```

```yaml
types:
  decision:
    check_severity: error   # unchanged; today's default, spelled or implicit
```

### 4.2 Resolution

One function, one place: `_severity_for(spec, item)` in `build.py`, replacing
the single line `check_severity = spec.check_severity if spec else ERROR`
(`build.py:1238`). Scalar spec → that value, no other code path. Mapping spec →
`mapping[item.fields["status"]]`.

Everything else about a `checks:` entry is untouched: a malformed entry, an
unresolved `against:` target, a target with no limit, a dimensional mismatch
stay `project.error` regardless of type or status, exactly as `docs/checks.md`
already states. Only the *ran-and-failed* diagnostic moves.

The item page's `fail` badge and the Checks table are unaffected — a failing
candidate still shows `fail`, because a comparison table needs every row read
the same way (`docs/checks.md` §Candidates vs. decisions). Severity governs
diagnostics, never the verdict.

### 4.3 Validation (load-time, `SchemaError`)

| Condition | Error |
|---|---|
| Mapping on a type with no `status` field | `types.foo.check_severity is a mapping but type 'foo' declares no 'status' field. Write check_severity: error, or declare status.` — mirrors the existing rule that `satisfying_statuses:` requires a `status` field (`docs/schema-reference.md` §type keys). |
| A key that is not one of the status enum's `choices` | `types.component.check_severity key 'choosen' is not a declared status. Declared choices: candidate, selected, rejected, obsolete.` A key that can never match is dead configuration. |
| A value outside `DIAGNOSTIC_LEVELS` | today's message, extended to name the key: `types.component.check_severity[candidate] must be one of [error, warning, info], got 'note'`. |
| A status with no entry and no `default:` | `types.component.check_severity does not cover status 'rejected'. Add it, or add default: <level>.` See §4.4. |
| `default:` as a mapping key | Legal, and it is the fallback for any status not listed. Its value is validated like any other. |

`extends:` inheritance follows the rule already settled for every other type
key: the child's definition **replaces** the parent's wholesale
(`docs/design/extends.md` §9.4, `docs/schema-reference.md` §extends). A scalar
child overrides a mapping parent and vice versa; mappings are never merged.
`composition.md` §1.5 keeps `check_severity:` out of shareable sets — unchanged,
and unchanged for the mapping form.

### 4.4 Exhaustive, or `default:`

A mapping must cover every declared status unless it declares `default:`.

The tempting shortcut is "unlisted means `error`". It is rejected because the
failure lands at the worst possible moment: someone adds a fifth status to the
enum — `deferred`, say — and every item in that new status immediately fails
the build on a severity nobody chose, in a project whose author never edited a
severity in their life. An exhaustive mapping turns that into a load error
naming the missing status, which is the same posture `coverable_statuses`
takes in reverse (unlisted statuses are excluded *entirely*, and loudly
documented as such). It is stricter than house style, and §11.8 records the
objection.

### 4.5 The release gate

`_rule_info_check_failures` (`lifecycle.py:559`) currently reads
`spec.check_severity != INFO` and skips the item. It becomes per-item: an item
whose **resolved** severity is `info` and which has a failing check is an
offender.

The consequence must be documented in `docs/lifecycle.md`, because it is the
one behaviour here a release engineer will feel: **a status change alone can
change the readiness gate.** A component moving `candidate → selected` moves
its failing checks from the `info_check_failures` bucket (default off, both at
`revision` and `release`) into build-blocking errors. That is the feature, not
a side effect — the moment you commit to a part is the moment its numbers have
to hold — but it means `refdes release` can go from clean to blocked on a
one-word edit, and the gate report should say so. The rule's offender list
stays item IDs; the diff view already reports status changes.

### 4.6 Byte-identical when unused

Requirement, with tests (§9):

- Resolved-schema oracle: for every bundled standard and every test fixture
  that does not use the mapping form, the resolved `ItemType.check_severity`
  is the same scalar it was before this change.
- Full-suite diagnostic capture: for a project with only scalar severities,
  the diagnostic list, ordering, levels, and exit codes are unchanged.
- `schema_json.py` emits the mapping as-is in the generated JSON Schema, and
  the pinned example in `docs/schema-reference.md` is regenerated by
  `docs-site/gen_examples.py` rather than hand-edited (the rule
  `tests/test_docs_examples.py` enforces).

### 4.7 Why not a separate `option` type

Because the thing under consideration is the part. `docs/checks.md`'s
`option`-with-`check_severity: info` example solves the severity half of this
problem by inventing a type, and then inherits the ontology problem described
in §1: two items for one part, a split-brain parts page, `selects:` that cannot
point at the loser, and drop-in claims that become illegal exactly when they
are most useful. Status-dependent severity makes the *severity* vary and leaves
the *item* alone, so the candidate that loses stays a component, keeps its
`part_number`, stays on `parts.html`, and can still be linked
`alternate:` to the winner.

The `design-debate` preset's `option` type is not removed by this proposal —
it is a debate option, which is a different thing from a candidate part, and
`check_severity: info` on it keeps working unchanged.

---

## 5. (C) A `rejected` component status

### 5.1 The change

`hardware@3/base.yaml`, component:

```yaml
status: { type: enum, choices: [candidate, selected, rejected, obsolete],
          default: candidate, on_change: invalidate,
          doc: "Where the part stands in this design. Only a selected component
                counts as settled and closes coverage on what it satisfies; a
                rejected one was considered and not chosen, and never satisfies." }
```

`hardware@3` is **unreleased**, so this edits `base.yaml` in place: no
`v4/base.yaml`, no migration, no `refdes upgrade` step, no resolved-schema
oracle comparing two versions. The precedent is the same release's in-place
`bound extends requirement` conversion and the `vendor:` → `keep_copy:`
rename — both changed `hardware@3` without a version bump because nothing
outside the repo has pinned it yet. `docs/standard-library.md`'s changelog
entry for the unreleased v3 gains a bullet; no per-version file appears.

### 5.2 `rejected` is not `obsolete`

| | `rejected` | `obsolete` |
|---|---|---|
| Meaning | This design considered it and chose not to use it | This part is no longer usable going forward — EOL, NRND, replaced by a newer package |
| Subject | A decision this project made | A fact about the part, usually reported by the manufacturer |
| Could a `selected` part become this? | No — you would move it back to `candidate` first, or supersede the decision | **Yes** — the part you shipped went EOL |
| Satisfies coverage? | No | No |
| Carries a rationale? | Effectively always (see §5.3) | Not necessarily |

Collapsing them would destroy the second row: "we did not pick it" and "we
picked it and the world changed" are different findings, and the second one is
a supply-chain alert while the first is history. Keeping both also means
`obsolete` keeps its current meaning for every project already using it.

### 5.3 Coverage and links

- `satisfying_statuses: [selected]` is **unchanged**, and that single fact
  does all the coverage work: a `rejected` component that `satisfies:` a bound
  leaves that requirement at `claimed`, never `satisfied`. No new coverage
  code, no new flag, and the four-stage model in `docs/coverage.md` is
  untouched.
- `coverable_statuses` is not declared on `component` (components are
  satisfiers, not coverable), so nothing changes there.
- **`selects:` disagreement already works.** `status_links.py` pairs
  `selects`/`selected` and warns on "link without status" — a decision
  `selects:` a component whose status is anything but `selected`. A decision
  selecting a `rejected` part therefore already warns, with no new code,
  because the pair's guard is "the target's status choices include the paired
  value" and the paired value is `selected`. §9 pins this as a named test so
  nobody "improves" it into a derivation.
- **No `rejects:` link verb.** Rejected by Jared (§11.2). Rejection is a
  property of the candidate's status plus the decision's prose and its
  `options:` panel; a second representation of the same fact is what
  `status_links.py` exists to warn about, not to add more of.

### 5.4 Check severity for `rejected`

With §4, `hardware@3`'s component ships:

```yaml
check_severity: { candidate: info, selected: error, rejected: info, obsolete: info }
```

A rejected part failing a criterion is *why it was rejected* — recording it is
the point, blocking the build on it is nonsense. A `selected` part failing is
a broken design. This is a deliberate behaviour change to the unreleased
standard: today a component's failing check is an `error`. Projects that want
that write `check_severity: error` in their overlay, and the change is
announced in `docs/standard-library.md`'s v3 notes.

### 5.5 The parts page

`parts.html` keeps listing rejected components. The index is "every part
number this project has written down", and a rejected MPN is precisely the one
a reviewer wants to find — it is the part someone will later try to substitute
into a BOM. Its row shows `status: rejected`, and the where-used backlinks
show which decision did not pick it. Filtering rejected parts out would hide
the fact that they were ever considered, which is the opposite of what a
design record is for.

### 5.6 Display order

Enum declaration order is `[candidate, selected, rejected, obsolete]`: the two
outcomes of a comparison adjacent to each other, retirement last. `{{index}}`
orders enum groups by declared choice order, so this is also the order a
by-status index shows them in, and the order `refdes new` prints in its
`# choices:` hint (`scaffold._field_hint`).

---

## 6. (D) A recommended project layout — a convention, not a semantic

### 6.1 The recommendation

```
items/
  power/
    candidates.yaml        # the shortlist: defaults set, nobody is selected yet
    power-supply.md        # the narrative page holding the {{compare}} block
```

```yaml
# items/power/candidates.yaml
defaults:
  type: component
  status: candidate

- id: CMP-PWR-014
  title: MP1584EN buck module
  part_number: MP1584EN-LF-Z
  ...
```

`defaults:` is already merged under every item in a list file with the item's
own value winning (`parse.py:601-627`), so `status: candidate` is written once
and the winner overrides it in place:

```yaml
- id: CMP-PWR-014
  title: MP1584EN buck module
  status: selected        # DEC-PWR-007 selects this one
```

The winner does **not** move to a `chosen.yaml`. Moving it would split the
comparison across two files, take the loser out of the same `{{compare}}`
selection scope (same file, same tag, same board — pick one, they all work),
and turn a review into a file-move diff plus a status diff. One file, one
status edit, one `selects:` link.

### 6.2 What the path means: nothing

**refdes never derives `status: candidate` from a folder or file name.** Not
at build time, not at `refdes new` time, not as a default.

This is the third time this project has corrected the same mistake, and
`docs/design/backlog.md` finding 36 §1 names it: *"permanent meaning derived
from mutable ambient context"* — corrected once for board-from-path and once
for the group/file-link question finding 14 rejected. The board case is the
instructive one because it looks like a counterexample and isn't: a board *is*
the first path segment under `items/`, but only through an explicit `boards:`
registry with an optional `path:` override, and a segment that is not
registered gets no board rather than a guessed one (`docs/multi-board.md` §
"Naming the boards" — "folders are just organisation until you register
them"). Registration is the difference between a convention and a semantic.

So `candidates.yaml` is a convention the docs recommend and the tool
scaffolds, and renaming it changes nothing but the filename.

### 6.3 The one optional check, and why it is not path-shaped

A warning worth having, definable entirely from parsed content:

> **A file whose `defaults:` declares `status: candidate` contains no item in
> that status.**

The `defaults:` line is an assertion about the file's contents, and an
assertion nothing satisfies is dead configuration — the same category as a
`defaults:` key for a field the type doesn't declare. It reads the file's own
declared intent, never its name, so it survives a rename, a move, and a
reorganisation, and it fires on the real mistake (someone set every item's
status explicitly and the `defaults:` is a lie).

Warning, not error; project-suppressible like the other authoring warnings.
Nothing else. In particular, no `candidate_sets:` registry mirroring `boards:`
— there is no page, no scope, and no coverage rule that needs candidate sets to
be registered, so a registry would be ceremony around a convention.

### 6.4 Scaffolding

- **`refdes new component`** — unchanged. It already generates front matter
  from the resolved `ItemType` (`scaffold.new_item_text`), so `status:` prints
  with its default and its `# choices: candidate, selected, rejected,
  obsolete` hint automatically, once §5 lands. No new template, no second
  source of truth.
- **`refdes new component --list`** (new flag) — prints a list-file skeleton
  instead of a single item:

  ```
  ---
  defaults:
    type: component
    status: candidate

  - id:
    title:
    part_number:
  ```

  `defaults.type` from the requested type; `defaults.status` from that type's
  `status` enum default, and omitted when the type declares no `status` field.
  Stdout only, exactly like `refdes new` today — it writes nothing, so it is
  safe under `--no-write` and composes with `> items/power/candidates.yaml`.
- **`refdes init`** — unchanged. It writes `refdes-project.yaml` and the
  `.vscode` settings and nothing else; it cannot know the project's boards or
  domains, so it must not invent `items/power/`. Its closing message gains one
  line pointing at the layout section of `docs/parts.md`, which is the
  discoverability fix.

---

## 7. Worked example: three bucks against two limits

### 7.1 Bounds

```yaml
- id: BND-PWR-011
  type: bound
  title: 3V3 rail output current
  status: active
  limit: ">= 3 A"
- id: BND-PWR-012
  type: bound
  title: Standby quiescent budget
  status: active
  limit: "<= 500 uA"
```

### 7.2 Candidates — `items/power/candidates.yaml`

```yaml
defaults:
  type: component
  status: candidate

- id: CMP-PWR-014
  title: MP1584EN buck module
  part_number: MP1584EN-LF-Z
  status: selected
  citations:
    - path: datasheets/mp1584.pdf
      id: mp1584-ds
      keep_copy: true
  checks:
    - { value: I_out, against: BND-PWR-011 }
    - { value: I_q,   against: BND-PWR-012 }
  ---
  ```calc
  I_out = source("datasheets/mp1584.csv", "i_out_max") | A
  I_q   = source("datasheets/mp1584.csv", "i_q_typ")   | uA
  ```

- id: CMP-PWR-015
  title: TPS562200 buck regulator
  part_number: TPS562200DDCR
  status: rejected
  rationale: >
    Fails the 3 A rail requirement by a third. Nothing else about it is wrong
    — its quiescent current is the best of the three — but BND-PWR-011 is not
    negotiable, so it is out.
  citations:
    - path: datasheets/tps562200.pdf
      id: tps562200-ds
  checks:
    - { value: I_out, against: BND-PWR-011 }
    - { value: I_q,   against: BND-PWR-012 }
  ---
  ```calc
  I_out = source("datasheets/tps562200.csv", "i_out_max") | A
  I_q   = source("datasheets/tps562200.csv", "i_q_typ")   | uA
  ```

- id: CMP-PWR-016
  title: LM2596-ADJ switching regulator
  part_number: LM2596S-ADJ
  status: rejected
  rationale: >
    Current is fine; quiescent is ten times the standby budget. Kept as an
    alternate for the non-battery variant, where BND-PWR-012 does not apply.
  alternate: [CMP-PWR-014]
  citations:
    - path: datasheets/lm2596.pdf
      id: lm2596-ds
  checks:
    - { value: I_out, against: BND-PWR-011 }
    - { value: I_q,   against: BND-PWR-012 }
  ---
  ```calc
  I_out = source("datasheets/lm2596.csv", "i_out_max") | A
  I_q   = source("datasheets/lm2596.csv", "i_q_typ")   | uA
  ```

- id: CMP-PWR-017
  title: TBD — second-source search still open
  status: candidate
```

Every `source()` line carries its own unit assertion, per
`docs/design/calc-sources.md` §6: the CSV holds bare decimals, the calc owns
the unit, and a `1850` that meant mW renders as `1850 W` rather than being
guessed at. The datasheet PDF is a `citations:` entry with an `id:`, so prose
links it with `[[cite:mp1584-ds]]` (`docs/markdown.md` §Citing a datasheet).

### 7.3 The decision

```yaml
id: DEC-PWR-007
type: decision
title: 3V3 rail regulator is the MP1584EN
status: accepted
selects: [CMP-PWR-014]
satisfies: [BND-PWR-011]
options:
  - name: TPS562200
    verdict: rejected
    because: 2 A maximum against a 3 A requirement.
  - name: LM2596-ADJ
    verdict: rejected
    because: 5 mA quiescent against a 500 uA standby budget.
---
Three candidates were compared against BND-PWR-011 and BND-PWR-012 in
[power-supply.md](power-supply.md). The MP1584EN is the only one that passes
both, and it passes the current limit exactly at its rated maximum — margin
0%, which is the tightest check in this project and the reason
[[BND-PWR-011]] is called out here.
```

`options:` is the frozen record of the comparison as decided; `{{compare}}` is
the live view of it. Both exist on purpose (§3.6).

### 7.4 The page — `items/power/power-supply.md`

```markdown
## Candidate comparison

{{compare type="component" against="BND-PWR-011, BND-PWR-012" columns="part_number, status, calc:I_out, calc:I_q"}}
```

Rendered, in markdown terms:

| ID | part_number | status | I_out | I_q | BND-PWR-011 ≥ 3 A | BND-PWR-012 ≤ 500 µA | Checks |
|---|---|---|---|---|---|---|---|
| CMP-PWR-014 | MP1584EN-LF-Z | selected | 3 A | 60 µA | pass 0% | pass +88% | 2/2 |
| CMP-PWR-015 | TPS562200DDCR | rejected | 2 A | 17 µA | **fail −33%** | pass +97% | 1/2 |
| CMP-PWR-016 | LM2596S-ADJ | rejected | 3 A | 5 mA | pass 0% | **fail −900%** | 1/2 |
| CMP-PWR-017 | — | candidate | — | — | — | — | — |

`— not specified    pass/fail checked    error check could not be evaluated`

What the build says about it:

- CMP-PWR-015 and CMP-PWR-016 each have one failing check. Both are
  `status: rejected`, both resolve to `info` under §5.4, so both are hidden
  without `-v` and neither fails the build.
- CMP-PWR-014 is `selected`; its two checks pass, so nothing is reported. If
  someone tightens `BND-PWR-011` to `>= 3.5 A`, its check fails at **`error`**
  — the build breaks, `refdes release` blocks, and the page's cell turns red —
  which is the whole point of §4.
- CMP-PWR-017 declares no checks and no part number: four `—` cells, no
  warning (it is a candidate, and "not yet specified" is a normal state for
  one), and it is still a row, because a shortlist with a hole in it should
  show the hole.
- `BND-PWR-011` is satisfied by `DEC-PWR-007` (accepted) and by
  `CMP-PWR-014` (selected). The two rejected components' `satisfies:` links —
  neither has one here, and if they did — would leave it at `claimed`, never
  `satisfied` (§5.3).

---

## 8. Docs that change

| File | Change |
|---|---|
| `docs/blocks.md` | `{{compare}}` section: parameter table, the renders-checks-never-evaluates rule, missing-value legend, failure modes. The non-goal section gains a sentence: `{{compare}}` is the strongest test the parameters-not-expressions rule has met, and it passes because its columns are names, not comparisons. |
| `docs/checks.md` | §Candidates vs. decisions: the mapping form of `check_severity`, the exhaustive-or-`default:` rule, and the gate consequence. |
| `docs/schema-reference.md` | `check_severity` row: scalar or mapping. Regenerate the pinned example via `gen_examples.py`. |
| `docs/standard-library.md` | Unreleased-v3 changelog bullet: `rejected` added to `component.status`; component `check_severity` becomes a status mapping. |
| `docs/coverage.md` | One sentence: `rejected` is not a satisfying status, and why it is not `obsolete`. |
| `docs/parts.md` | New §Candidate parts: the layout convention, `parts.html` keeps rejected rows, `refdes new --list`. |
| `docs/lifecycle.md` | `info_check_failures` resolves severity per item; a status change alone can change the gate. |
| `docs/index.md` | The Generated blocks row: `{{index}}`, `{{cascade}}`, `{{tree}}`, `{{compare}}`. |

---

## 9. Failure modes and named tests

`tests/test_compare_block.py`

| Test | Pins |
|---|---|
| `test_compare_renders_pass_and_fail_columns` | The §7 table, cell for cell, from the fixture. |
| `test_compare_missing_values_are_em_dash` | Unset field, undefined calc, undeclared check all render `—`, never blank or `0`. |
| `test_compare_never_evaluates` | A row with a calc value but no `checks:` entry shows `—` in the bound column even though the value exists in `_env`. |
| `test_compare_rows_sorted_by_id` | Insertion order, status order, and margin order all differ from ID order; output is ID order. |
| `test_compare_no_sort_parameter` | `sort="margin"` → unknown-parameter error listing the accepted set. |
| `test_compare_unknown_type_field_status_and_bound` | The four §3.7 errors, message for message, including the `calc:Iout` hint and the no-`limit` bound. |
| `test_compare_type_without_checks_field_errors` | `type="requirement" against=...` errors rather than rendering an empty column set. |
| `test_compare_warns_on_unchecked_bound` | A bound no row checks against → one warning naming the bound and the page; not an error. |
| `test_compare_empty_selection_is_a_paragraph` | No matching rows → `<p class="compare-empty">`, exit 0. |
| `test_compare_unknown_block_name_untouched` | `{{comparex ...}}` survives as literal text. |
| `test_compare_no_write_identical` | `build --no-write` and `build` produce byte-identical pages; nothing in the source tree changes. |
| `test_compare_local_rows_only` | An imported component with the same `part_number` is not a row; an imported bound is a column. |

`tests/test_check_severity_status.py`

| Test | Pins |
|---|---|
| `test_scalar_severity_unchanged` | Resolved-schema oracle over every bundled standard: identical resolved `check_severity` scalars. |
| `test_mapping_selects_by_status` | Same failing check, `candidate` → info, `selected` → error, exit code differs. |
| `test_mapping_requires_status_field` / `test_mapping_rejects_unknown_key` / `test_mapping_rejects_unknown_level` / `test_mapping_requires_exhaustive_or_default` | The four §4.4 load errors, message for message. |
| `test_unevaluable_checks_stay_errors` | A typo'd value name on a `candidate` is still `error`, whatever the mapping says. |
| `test_badge_unaffected_by_severity` | The item page shows `fail` at every severity. |
| `test_extends_replaces_whole_definition` | Scalar child over mapping parent and mapping child over scalar parent; never merged. |
| `test_gate_follows_status_change` | Flipping one component `candidate → selected` with a failing check moves it from `info_check_failures` (skipped) to a build error. |

`tests/test_component_rejected.py`

| Test | Pins |
|---|---|
| `test_rejected_never_satisfies` | A `rejected` component `satisfies:` a bound → stage stays `claimed`. |
| `test_selects_rejected_component_warns` | The existing `selects`/`selected` pair fires on a `rejected` target; warning, not derivation. |
| `test_rejected_stays_on_parts_page` | `parts.html` lists it with its status. |
| `test_hardware3_component_choices` | `[candidate, selected, rejected, obsolete]`, default `candidate`. |
| `test_defaults_status_warning` | A file whose `defaults: {status: candidate}` matches no item warns; renaming the file changes nothing. |
| `test_new_list_skeleton` | `refdes new component --list` emits the `defaults:` skeleton; a type with no `status` field emits none; nothing is written under `--no-write`. |

---

## 10. Open questions for Jared

Each carries a recommendation; unanswered means the recommendation stands.

1. **Block name: `{{compare}}` or `{{table}}`?** — **Recommended: `compare`.**
   `table` names the shape, and three of the four existing blocks render
   something table-shaped. `compare` names the job, which is what the family's
   names do.

2. **Is `{{compare}}` the right verb for non-parts comparisons, or does it
   invite misuse?** — **Recommended: keep it.** `type="test"` against bounds is
   a legitimate comparison. The block is about items × bounds, not about
   parts; only the docs' examples are part-shaped.

3. **`calc:NAME` prefix for calc columns?** — **Recommended: yes.** The
   alternative (bare names, fields win on collision) resolves an ambiguity by
   a rule that is invisible on the page, which is the objection `keys.md` §3
   makes against display-id fallbacks.

4. **Is `against=` optional?** — **Recommended: yes**, so a spec-only
   comparison is the same block. A required `against=` would push the
   no-bounds case back to hand-written markdown.

5. **A Checks score column (`2/2`)?** — **Recommended: yes.** It is arithmetic
   over the columns beside it, not a verdict. A reviewer scanning 12 rows needs
   one column to scan.

6. **Is `sort=` still refused?** — **Recommended: refused**, for the
   `index-blocks` §2 reason plus the review-diff reason in §3.3.

7. **Mapping must be exhaustive or declare `default:`?** — **Recommended:
   yes.** §4.4. This is stricter than `coverable_statuses`, and §11.8 records
   the objection.

8. **Does `hardware@3` ship component `check_severity` as a status mapping?** —
   **Recommended: yes** (§5.4). It changes the unreleased standard's behaviour
   for a failing check on a candidate component from `error` to `info`.

9. **`rejected` added in place to `hardware@3`, no v4?** — **Recommended:
   yes**, on the precedent of this same unreleased version's `extends:`
   conversion and the `keep_copy:` rename.

10. **Any warning for a file whose `defaults:` status matches nothing?** —
    **Recommended: yes, warning only** (§6.3), and nothing path-shaped.

11. **Does `refdes new` need a `--list` flag?** — **Recommended: yes**, stdout
    only, writes nothing (§6.4). `refdes init` stays as it is.

12. **Should `obsolete` gain a `required_when` rationale, as `rejected`
    effectively has one?** — **Recommended: no.** A manufacturer EOL note is
    provenance, not a design rationale, and `required_when` on a status the
    author may set in bulk would force filler text.

---

## 11. Options considered and rejected

1. **A separate `option`/`candidate` type for candidate parts.** Rejected —
   §4.7. It splits one part into two items at selection, duplicates the
   component schema, breaks `selects:` and `drop_in:`/`alternate:` across the
   two, and shows the same silicon twice on `parts.html`.
2. **A new link verb from log entries to components** (e.g. `evaluates:`,
   `considered:`) to carry the comparison narrative. **Rejected by Jared
   (2026-09-21).** The comparison is carried by the decision's `selects:` link,
   the candidates' own statuses, the decision's `options:` panel, and the
   `{{compare}}` block on the page. A fifth representation of "this log entry
   is about this part" is a fact stored twice with nothing checking whether the
   two agree — which is what `status_links.py` exists to warn about, not to
   add more of.
3. **`{{compare}}` evaluating bounds against each row's calc env.** Rejected —
   §3.2. Two evaluators, two answers, and the first block that decides
   something rather than arranging what exists.
4. **`{{table}}` as the name.** Rejected — names the shape, not the job.
5. **A `sort=`/`order=` parameter (tightest margin first, failures last).**
   Rejected — §3.3. Ranking is `summary.html`'s existing job; a self-reordering
   table makes page diffs noisy and moves failures out of first-glance
   position.
6. **Deriving `status: candidate` from the folder or filename.** Rejected —
   §6.2. The third instance of the pattern `backlog.md` finding 36 §1 says this
   project has already corrected twice.
7. **Folding `rejected` into `obsolete`.** Rejected — §5.2. "We did not choose
   it" and "we chose it and it went EOL" are different findings, and the second
   is a supply-chain alert.
8. **Unlisted statuses in a `check_severity` mapping defaulting to `error`.**
   Rejected — §4.4. It fires at the worst moment (someone adds a status) in the
   project that never touched severities. The objection, recorded fairly:
   `coverable_statuses` and `satisfying_statuses` are both partial lists, so
   exhaustiveness is inconsistent with house style, and a project overlaying a
   custom status onto `component` must now also edit `check_severity`. That is
   the cost of not having silent severities, and it is worth paying.
9. **A `rejects:` link verb.** Rejected — same reasoning as 2, and the
   `selects`/`selected` disagreement warning already covers the case where a
   decision points at a rejected part.
10. **Filtering rejected components out of `parts.html`.** Rejected — §5.5. The
    rejected MPN is the one a future substitute will reach for.
11. **A `{{compare}}` directive inside an item body.** Rejected — blocks are
    narrative-page-only (`docs/blocks.md` §Scope), and an item-scoped survey
    belongs on the item as its own `checks:` table, which already exists.
12. **A `candidate_sets:` project registry mirroring `boards:`.** Rejected —
    §6.3. Nothing scopes, pages, or covers by candidate set, so registration
    would be ceremony.

---

## 12. Phasing

| Phase | Scope |
|---|---|
| **1. Standard** | `hardware@3/base.yaml`: `rejected` in `component.status`; component `check_severity` mapping. `docs/standard-library.md` v3 notes. |
| **2. Severity engine** | `schema.py` mapping validation; `build._severity_for`; `lifecycle._rule_info_check_failures` per-item; `schema_json.py`; scalar-unchanged oracle. |
| **3. Block** | `blocks.py::_render_compare` + registry entry; column resolution (field / `calc:` / bound); missing-value rendering; the unchecked-bound warning. |
| **4. Layout** | `scaffold.new_list_text` + `refdes new --list`; the `defaults:`-status warning; `refdes init` closing line. |
| **5. Docs & tests** | §8's doc edits; §9's three test files; `docs-site/gen_examples.py` regeneration. |

Phase 2 is independently useful and independently shippable; phases 1 and 2
together make a candidate's failing check non-blocking without any block at
all. Phase 3 depends on 1 only for the `rejected` status name in an error
message. Phase 4 depends on nothing.
