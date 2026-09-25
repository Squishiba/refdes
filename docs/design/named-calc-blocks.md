Status: **Architecture decided (2026-09-24)** — all ten §11 questions
answered; §11.5's `id=` key change is the one place the doc's own
recommendation was NOT taken as written (`name=` → `id=`), everything else
confirmed as recommended. **All five phases (§13) have landed**: named fences
and per-item uniqueness (1), `[[ID#calc:name]]` fragments (2), `{{calcblock}}`
(3), the hash pins (4), and the docs (5). §12 records what was
considered and rejected. This spec deliberately *removes* one thing people
expect from a "named block" feature (§4): the research in §2 says the value-reference half is
already solved, and adding a second spelling for it would be the second
representation of one fact this project keeps refusing.

# Named calc blocks: naming a calculation, and referring to the whole of it

## Decision (recap, as decided 2026-09-24)

A calc block's **values** already have names, and any one of them is already
referenceable from another item (`DEC-PWR-001.V_in`, `docs/math.md`
"Referencing another item's values"). What has no name is the **block** — the
fenced ```` ```calc … ``` ```` itself — so an item with two calculations cannot
be talked about as holding two of them: not in prose, not on a page, not in a
diagnostic that wants to say *which* calculation.

Four changes, and the second one is a non-change on purpose:

- **(A) A name on the fence line** (§3) — ```` ```calc id="losses" ````. An
  attribute in the fence's info string, using the same `key="value"`
  microsyntax `{{index}}` and the image `{width=… caption="…"}` suffix already
  use. Opt-in: an unnamed block is legal, renders byte-for-byte as today, and
  needs no name until something wants to point at it.
- **(B) No block-qualified value reference** (§4) — `ITEM.NAME` stays the only
  cross-item value spelling, and `ITEM.block.NAME` is **rejected with an error
  that names the plain form**. Item-wide name uniqueness is already a hard
  error today (`calc.py` `origins`, message quoted in §2), so a qualified
  reference would disambiguate nothing and would put two spellings of one value
  into every project that used it.
- **(C) "All of it" means the block as one citable, renderable unit** (§5) —
  `[[DEC-PWR-001#calc:losses]]` links to that block's table on its owner's
  page (the `#field` fragment precedent, with the `calc:` namespace prefix the
  `cite:`/`fig:`/`calc:` forms already use), and `{{calcblock item= block=}}`
  renders that block's already-evaluated rows on a narrative page. Neither
  evaluates anything.
- **(D) No hash-format change** (§6) — a block name is authored body text, so
  naming a block moves its **owner's** content hash and nobody else's; it never
  enters a dependent's `calc_refs` payload, and it does not move the narrow
  `calc_hash_for()` arithmetic probe, because that probe hashes block *contents*
  and the name lives on the fence line above them.

The through-line: **a block name is a label on a rendering, not a link target
for arithmetic.** Every rejected alternative in §12 that treats it as an
addressable scope — qualified value names, wildcard imports, ordinal block
references — either duplicates a reference mechanism that already works or
derives meaning from something mutable that this project has already ruled on
(`docs/design/backlog.md` finding 36 §1, "permanent meaning derived from
mutable ambient context").

---

## 1. Motivation

Calc blocks are already the place a design argument lives. One item computes a
rail's loss; another computes what that loss costs thermally; a third says
whether the board area allows it. The cross-item reference solved the *number*
problem for that chain: one value, written once, referenced by name, hashed as
a dependency (finding 35, `HASH_FORMAT` 4).

What the chain does not survive is **the block as a unit**. Three concrete
frictions, all of them real in the shape of the repo's own items:

1. **An item with two calculations has no way to say which is which.**
   `DEC-PWR-001` today has one block. Split it — supply assumptions in one,
   loss/thermal arithmetic in the other, which is the split its prose already
   makes ("Working", then the dissipation argument) — and every downstream
   sentence has to say "the second calc block in DEC-PWR-001", which is a
   position, not a name.
2. **A page cannot show one calculation without copying it.** A power/thermal
   overview page that wants the loss table in front of a reader has two bad
   options: retype the numbers (the divergence `docs/math.md` opens with) or
   link to the item and hope the reader finds the right table among several.
   `{{index}}`/`{{compare}}` render *fields* and *check verdicts*; nothing
   renders a calculation.
3. **A diagnostic can locate a block but cannot name it.** Errors already carry
   absolute line numbers (`build.py:_run_item_calcs` threads `start_line`), so
   "the second block" is findable — but a line number is not something a log
   entry, a review note, or a page can quote and still be true next week.

Jared's framing, verbatim: *"honestly, a bit of both? Just being able to
reference **any** or **all** parts of it is what I'm lusting for."* This spec
takes both halves seriously and reports what the research found: **"any"
already exists and is already unambiguous** (§2, §4), and **"all" is the actual
gap** — but "all" is a rendering and citation capability, not an arithmetic one
(§5).

---

## 2. What exists today, exactly

Read `src/refdes/calc.py` and the calc/hashing sections of `src/refdes/build.py`
before writing this. Five facts, because two of them contradict what you would
guess:

| Question | Answer today | Where |
|---|---|---|
| Can a value inside a block be referenced from another item? | **Yes**, fully: `V_in = DEC-PWR-001.V_in`, dependency-ordered evaluation, stored expanded as `DISPLAY-ID@key`, value + unit + tolerance hashed into the referring item (`HASH_FORMAT 4`). | `calc.CROSS_REF_RE`, `build._make_calc_resolver`, `build._calc_reference_values` |
| If one item has two blocks that assign the same name, does the later one silently shadow the earlier? | **No.** It is a hard build error, already worded the house way: `'X' is assigned twice in this item -- first at line 41, again at line 63. A name can only be assigned once per item (blocks share one item-wide scope); rename one of them, e.g. 'X' -> 'X_2'.` `origins` is threaded across every block of the item exactly like `env`. | `calc.evaluate_block`, `build._run_item_calcs` (`origins` comment) |
| Does a block have any identity — a name, a number, anything addressable? | **No.** `extract_blocks_with_lines` returns `(text, line-offset)` pairs; `render_bodies` addresses them by list index for placeholder swapping; nothing in the author-facing grammar can name one. | `calc.extract_blocks_with_lines`, `build.render_bodies` |
| If something goes wrong in the second block, is it locatable? | **By line number only.** `start_line = item.body_line + offset`, so every `CalcOutcome.line` and every diagnostic is absolute. Correct, and not quotable. | `build._run_item_calcs` |
| Is text after ```` ```calc ```` on the fence line legal? | **Yes, and silently ignored.** `CALC_BLOCK_RE` is `` ^```calc[^\n]*\n(.*?)^```$ `` — everything from `calc` to the newline is matched and thrown away. ```` ```calc id=losses ````, ```` ```calc frobnicate ````, ```` ```calc because I felt like it ```` all parse today and mean nothing. | `calc.CALC_BLOCK_RE` |

Two honest corrections to the brief this spec was written from:

- **There is no silent-shadowing gap to close.** The duplicate-name-across-blocks
  case is already a hard error with a fix-naming message, and it has been since
  `origins` was threaded item-wide. This proposal therefore does **not** earn
  its keep on collision-safety. It earns it on §1's three frictions, which are
  about naming and rendering, not about scoping.
- **There *is* a silent-acceptance gap, and it is on the fence line.** Any text
  after ```` ```calc ```` is discarded today. That is precisely the shape of
  quiet failure this project treats as a bug: an author writes
  ```` ```calc id=losses ```` (quotes missing, `name=` left over from an
  earlier draft of this spec, a trailing comment), the build says nothing, and the name they meant to give
  the block simply does not exist. §3.4 turns that silence into a validated
  attribute, and that is a real gap this proposal closes.

---

## 3. (A) Naming a block

### 3.1 Syntax

````markdown
```calc id="losses"
P_out  = V_out * I_load | W
P_diss = P_out * (1/eff - 1) | W
```
````

An unnamed block is unchanged:

````markdown
```calc
V_in = 12 V ± 5%
```
````

### 3.2 Why this shape, against the house precedents

The project spells an attribute on existing markdown syntax in exactly two ways
today, and neither is a direct fit, so the choice is which one to bend:

| Precedent | Shape | Fit for a calc fence |
|---|---|---|
| `{{index by="…" type="…"}}` (`docs/blocks.md`, `docs/design/index-blocks.md` §7) | first token is the name, then `key="value"` pairs, alone on a line | Right microsyntax, wrong envelope: `{{…}}` is a *page* directive and blocks are illegal on items (`docs/blocks.md` §Scope); a calc block is item content. |
| `![alt](path){id="fig-curve" width=60% caption="…"}` (`docs/markdown.md` §Width and captions) | a `{…}` suffix glued to the end of an inline construct | Right idea (attributes belong on the thing they describe), wrong position: a fenced block's closing ```` ``` ```` is not a place to hang anything — the suffix would have to survive markdown's fence parsing, and a `{…}` after a closing fence is just text in the next paragraph. |
| CommonMark's own **fence info string** — the text between ```` ``` ```` and the newline, which `CALC_BLOCK_RE` already skips over | `lang key="value"` | **The only position that needs no new parsing at all.** The regex already tolerates it, the renderer already ignores it, and it is physically attached to the block it names. |

So: the info string carries the attribute, and the attribute is spelled with the
`key="value"` form the other two precedents share. Nothing about this is
invented for calc alone — it is "put the attribute where the syntax already has
room for one."

Rejected alternatives and why, in brief (full list in §12): a bare word
(```calc losses```) — no key, so the next attribute has no grammar and a
misspelled language alias looks like a name; a header line *inside* the block
(`@name losses`) — every line-level parser in `calc.py` (`assigned_names`,
`source_calls_in_block`, `rewrite_line`, `build._calc_line_count`) would have to
learn to skip it, and it becomes a line in the rendered table's row count; a
`{{calcblock}}`-style directive *above* the fence — two-line coupling that has
to survive markdown paragraph splitting between the directive and its block.

### 3.3 Grammar

```
calc-fence  = "```calc" [ 1*WSP attribute *(" " attribute) ] EOL
attribute   = "id=" dquote name dquote
name        = lowercase-letter [ *( lowercase-letter | digit | "_" | "-" ) ]
```

- **Lowercase-initial, `[a-z][a-z0-9_-]*`.** Calc value names are
  `[A-Za-z_][A-Za-z0-9_]*` and are conventionally symbol-shaped (`P_diss`,
  `V_in`); author-chosen labels in this project are lowercase-hyphen (citation
  `id: mp1584-ds`, figure `id="fig-curve"`). Keeping block names in the second
  shape means a bare token's *kind* is readable, and a block name can never be
  pasted where a value name belongs and look right. It is a naming convention
  enforced by a build error, not a scoping trick — block names and value names
  live in different namespaces regardless (§4.2).
- **The key is `id=`, not `name=`** (decided, §11.5). The instinct behind the
  lowercase-hyphen value — a block's identifier should look like the other
  referenceable-thing identifiers in this project — governs the *key's*
  spelling too, not just the value's shape: a citation carries
  `id: mp1584-ds`, a figure carries `id="fig-curve"`, and now so does a calc
  block. Jared's framing: *"the tangential idea here is to make calc blocks
  behave like items do. Or at least, treat them the same, to the point that
  it's intuitive using both because the process for one carries to the
  other."*
- **Quoted value**, `id="losses"`, exactly like `caption="…"` and
  `type="decision"`. Unquoted is rejected: `width=60%` is unquoted in the image
  suffix because it is a number; every string-valued attribute in the project
  is quoted.
- **Length**: 1–40 characters. Long enough for `thermal_headroom`, short enough
  to appear in a caption and an error message without wrapping.
- **One attribute today.** `id` is the only one defined. An unknown attribute
  is an error naming the accepted set (§7), which is what makes "add more later"
  safe rather than a future ambiguity.

### 3.4 Validation, and the compatibility note

The fence line goes from "anything goes, all of it ignored" to "a grammar, or a
build error". The errors (§7) are:

- an info string that is not a valid attribute list (```` ```calc losses ```` —
  a bare word; ```` ```calc id=losses ```` — unquoted; ```` ```calc
  name="losses" ```` — the key from earlier drafts of this spec, now an
  unknown attribute);
- a name outside the grammar (`Losses`, `1losses`, `losses!`);
- a duplicate name within one item.

**Compatibility:** this is a behaviour change for text that is legal today and
means nothing today. It is the right call for the same reason unknown block
parameters became errors rather than shrugs (`docs/blocks.md` §Failure modes):
silently-ignored author intent is the failure, and the fix fits in one word.
Anyone who genuinely has trailing prose on a calc fence finds out once, with a
message that names the fix. `grep -c '^```calc[^[:space:]]*$'` over a project
tells an author in one line whether they have any such fence.

### 3.5 What a name does, and does not, do

- **It renders.** A named block's table gains an anchor `id="calc-<name>"` and
  a caption line carrying the name (the same caption treatment figures already
  get). An unnamed block's HTML is byte-for-byte what it is today — pinned by a
  test (§10), because most items have one unnamed block and nothing about them
  should move.
- **It does not scope anything.** `env` and `origins` stay item-wide. A value in
  block `supply` is visible to block `losses` exactly as it is now, and a name
  reused across two blocks is still the same hard error. Naming a block must not
  quietly become a way to make two `P_diss` values coexist; that would turn the
  one rule that makes `ITEM.NAME` unambiguous into an opt-in, and every
  reference in every project would become ambiguous-by-default. This is the
  single most important non-goal in the document.
- **It is not a key.** No `@key` composite, no expansion pass
  (`links.expand_missing_calc_refs` is untouched), no minting. See §6.2.
- **It is not a value namespace.** §4.

### 3.6 Where the name lives in the model

Surface touched, for scoping only (this spec implements nothing):

- `calc.extract_blocks_with_lines` grows a third element (the name, or `None`);
  a new `calc.parse_fence_attrs()` owns the grammar, and `CALC_BLOCK_RE` keeps
  its shape so every existing caller keeps working.
- `model.CalcLine` grows `block: str = ""` so a row knows which block produced
  it — that is what `{{calcblock}}` (§5.3) and the caption both read, and it is
  why no second walk of the source is needed.
- `build._run_item_calcs` passes the name down and validates uniqueness per item.
- `build._calc_table_html` renders the caption/anchor when `block` is set.
- `calc.rewrite_line` and `refdes calc-rewrite` never touch the fence line —
  they rewrite assignment lines. A test pins that a named fence survives
  `calc-rewrite` unchanged (§10).

---

## 4. (B) Referencing one value: already done, and not block-qualified

### 4.1 The existing mechanism is the mechanism

`V_in = DEC-PWR-001.V_in` (`docs/math.md`) is a real dependency: dependency-
ordered evaluation, `DISPLAY-ID@key` expansion, the target's key plus the
resolved value signature in the referring item's hash payload, a baseline diff
that names which reference moved. It resolves **item-scoped**: the target half
is an item, the name half is any name that item's calc blocks assign, across
all of them, with no exports list.

Because `origins` makes a name unique per item (§2), `DEC-PWR-001.P_diss` is
already unambiguous **even when the item has five blocks**. There is nothing for
a block-qualified spelling to disambiguate.

### 4.2 So `ITEM.block.NAME` is an error, not a second spelling

A reference of the form `DEC-PWR-001.losses.P_diss` is rejected with a message
that names the working form (§7). Justification, in the order the objections
would come:

1. **Two spellings of one value is two facts about one reference.** Which one a
   rename touches, which one a baseline records, which one a diff shows — all of
   that now has two answers. `docs/design/candidate-parts.md` §11.2 rejects a
   fifth representation of "this log entry is about this part" for exactly this
   reason.
2. **It would make the block name load-bearing for arithmetic**, and block names
   are deliberately *not* keyed (§6.2). A reference whose correctness depends on
   an unkeyed label is a reference that breaks on a rename — and it would break
   a *hash input*, not just a link.
3. **It would make the item-wide uniqueness rule optional.** The moment
   qualification exists, "rename one of them" stops being the only fix for a
   duplicate name, and the rule that makes §4.1 unambiguous decays.
4. **The readability want it serves is real, and §3.5 already serves it.** When
   someone reads a three-block item and wants to know which calculation a value
   came from, the answer is on the page: each named block's table is captioned
   with its name. That is a rendering answer to a rendering question, which is
   where this project puts rendering answers.

If a real project later demonstrates a case where `ITEM.NAME` cannot name what
it means, that is a *new* finding, and §12.1 records that it was left open on
evidence rather than closed by taste.

### 4.3 Prose `{{name}}` is unchanged

`{{P_diss}}` and `{{P_diss | mW}}` stay item-local (`build.INLINE_VALUE_RE`
matches a bare name only). There is no `{{DEC-PWR-001.P_diss}}` in prose today
and this spec does not add one; the thread-workbench proposal
(`docs/design/thread-workbench.md` D1) is where inline dotted values in prose
are being decided, and it should not inherit a block-qualified form by accident.

---

## 5. (C) Referencing *all* of a named block

"All of it" needs a concrete verb, or it means nothing. Three candidate
readings were considered; the recommendation is a synthesis of two of them and
a firm rejection of the third.

### 5.1 The candidates, interpreted rather than listed

**(a) A display/documentation aggregate** — pull a named block's whole table
somewhere else: onto a narrative page, or into the workbench pane's D1
decoration. This is the §1.2 friction, it is a *rendering* of values that
already exist and already ran, and it fits the existing family exactly:
`{{index}}`, `{{cascade}}`, `{{tree}}`, `{{compare}}` all "select and arrange
items that already exist" and none of them computes anything.

**(b) A bulk cross-item import** — one line in another item's calc block that
binds every value of a named block, in place of one dotted reference per value.
This is the reading that has to be rejected, and for reasons that are already on
the record:

- **It hands an item's namespace to someone else.** `origins` guarantees one
  name per item because that is what makes `ITEM.NAME` resolvable. A wildcard
  import means an upstream author adding one line to their block can inject a
  name into *your* item — or collide with one you already assigned, in a build
  that was green yesterday. The failure is upstream-caused, downstream-felt, and
  exactly the "confident answer with nothing verifying it" this project keeps
  refusing.
- **It is the completeness trap in a smaller hat.** `docs/design/calc-sources.md`
  §2 rejects summing over items because a set assembled by the tool cannot be
  verified complete. A named block *is* a declared set — better — but the
  consumer's copy of it is still defined by whoever edits the owner, and the
  consumer's page cannot show which values it received without re-deriving the
  set.
- **It is the wildcard the block family rules out** ("no comparison operator, no
  `and`/`or`, no wildcard", `docs/blocks.md` §The non-goal), and it would be the
  first wildcard anywhere in the calc language.
- **It makes the hash payload a moving set.** `calc_refs` today lists
  `[target token, name, value signature]` per reference — an explicit, enumerable
  list authored in this item. A wildcard's contribution changes when the
  upstream block changes shape, not just when a value moves, which muddies the
  precise signal finding 35 bought.
- **And it saves very little.** Six values is six lines, each of which states
  what this item depends on. The verbosity *is* the documentation; that is the
  same argument `docs/math.md` makes for not retyping a number and for
  `source()`'s mandatory unit.

**(c) The block as a citable entity** — the reading the existing grammar
actually points at. `docs/links.md` already has fragment references into an
item: `[[CMP-001#part_number]]` links to that field's row, "it links; it never
inlines the value, so a fragment cannot go stale when the field changes." A
named block is exactly another fragment-addressable part of an item's page, and
`cite:`/`fig:`/`calc:` already established that a bare name in a shared
namespace gets a prefix.

### 5.2 Recommendation

**Recommend (a) + (c) together, reject (b).** They are the same feature seen
from the two ends of a link: the block name makes a calculation *addressable*
(`#calc:losses`) and therefore *renderable* (`{{calcblock}}`). Neither evaluates
anything, neither touches arithmetic, neither changes what a value's name means.

### 5.3 `[[ID#calc:name]]` — the fragment

```markdown
The dissipation argument is in [[DEC-PWR-001#calc:losses]]; the numbers moved
twice since it was written.
```

- Same envelope, same rules as `#field`: it **links** to the target's page,
  scrolled to that block's table (the anchor §3.5 puts on it). It never inlines,
  so it cannot go stale — the reason `#field` fragments refuse to inline,
  inherited whole.
- `[[ID#calc:name|custom text]]` works like `[[ID#field|the MPN]]`.
- **The `calc:` prefix is required**, for the reason `candidate-parts` §3.4
  gives for `calc:` in a `{{compare}}` column list: a bare `#losses` would land
  in the same namespace as field names and would have to be resolved by a
  precedence rule nobody reading the page can see. Field names are
  schema-declared (`part_number`, `status`); block names are author-chosen; the
  prefix keeps "which namespace am I in" readable at the reference site instead
  of settled by a fallback.
- A `#calc:` fragment on a target whose block is unnamed, or on a name that does
  not exist, is a **warning** naming what the target does name — the same level
  and shape as an unresolved `[[…]]` and as `#field` on an undeclared field
  (`docs/links.md`), not an error: a broken prose link must not fail a build.
- A `#calc:` fragment on a `fig:` or `cite:` reference stays the warning it
  already is for `#field` on those forms.

### 5.4 `{{calcblock}}` — the page block

```markdown
{{calcblock item="DEC-PWR-001" block="losses"}}
```

A new `BlockSpec` in `blocks.py::_REGISTRY`, following every convention the
family has (`docs/blocks.md`, `docs/design/index-blocks.md` §7): alone on its
own line, `key="value"` attributes, an unknown block name left completely
untouched, unknown or missing parameter a build error naming the accepted set,
a `⚠` in place of a failed directive, **local items only**, and an empty state
that is a paragraph rather than an error.

| Parameter | Required | Meaning |
|---|---|---|
| `item` | yes | A local item's display id (or `DISPLAY-ID@key` composite). Must resolve, and must not be an imported item — an imported item carries no body or calc rows in this project (`imports._absorb`), so there is nothing to render. |
| `block` | yes | A **named** calc block on that item. Must exist; the error lists the names it does have. |

Rendering: the same table `_calc_table_html` produces on the owner's page —
expression, result, bounds, unit assertion, comment — from `item.calcs` rows
whose `block` field matches, plus a caption line naming the owning item (linked)
and the block name. Nothing else.

Rules that carry over from `{{compare}}` §3.2, unchanged, because they are the
right rules:

- **It renders calculations that already ran; it never runs one.** It reads
  `item.calcs` (the rows the build produced) and formats them. It does not touch
  `item._env`, does not re-evaluate expressions, and cannot produce a number the
  owner's own page does not show. Two evaluators, two answers — rejected.
- **Errors are the owner's, not the block's.** If the owner's calc failed, the
  build already failed at the owner's line; `{{calcblock}}` renders the rows it
  has, error rows included, exactly as the owner's page does. It does not
  restate the failure.
- **Pages only.** Blocks are illegal in item bodies (`docs/blocks.md` §Scope),
  and this is no exception: a calculation belongs on the item that computes it,
  a *survey* of one belongs on a page. An item that wants another item's numbers
  uses `ITEM.NAME` (§4.1), which is the arithmetic-correct route.
- **No `all=`/`blocks=`/`values=` parameter.** One named block, one rendering.
  Two blocks on the page is two directives. A parameter that takes a set is the
  wildcard from §5.1(b) wearing a block's clothes.
- **`--no-write` changes nothing**; it writes nothing, mints nothing, expands
  nothing. Byte-identical pages, pinned by a test (§10).

### 5.5 The workbench pane

`docs/design/thread-workbench.md` D1 decorates `{{value}}` and dotted
references inline in the pane. `CalcLine.block` (§3.6) gives that decoration a
second thing to show at zero cost: which named calculation a value came from,
beside the value itself. That is the "which of the three blocks" readability
want §4.2 claimed a rendering should answer, answered in the pane where an
author is working. No new mechanism — the field is there for `{{calcblock}}`
anyway.

---

## 6. (D) Hashes, identity, seals, imports

Checked against `build.py`'s hash payload code (`_hash_payload`,
`_calc_reference_values`, `_calc_refs_hash_value`, `calc_hash_for`,
`HASH_FORMAT = 4`) rather than assumed.

### 6.1 No `HASH_FORMAT` bump

`HASH_FORMAT` stays **4**. Nothing new enters any payload:

- **The owning item.** The fence line is body text, and body is hashed
  (whitespace-normalized) when its `on_change` is `invalidate`. So naming a
  block changes its owner's `content_hash`. That is correct and should be said
  plainly: it is an author edit to this item's own text, of the same kind as
  editing the prose around it — not an identity-only event. The contrast that
  matters is `compute_hashes`' own note that an item's *key* is deliberately
  absent, because minting a key is "an identity-only event with no content
  behind it": a block name is not that. The author typed it, it appears on the
  rendered page as a caption, and a reader can see it. Content.
- **A dependent item.** `_calc_refs_hash_value` contributes
  `[target token, name, value_signature]` per reference, and reduces the
  reference's target to the target's key in the hashed body. **Block names appear
  nowhere in it.** A block rename therefore cannot move a dependent's hash, and
  cannot silently change what a dependent resolves to — because block names are
  not part of value resolution at all (§4).
- **`calc_hash_for`** (the narrow arithmetic probe from
  `docs/design/stale-arithmetic-signal.md`) hashes `extract_blocks`' captured
  group — the block's *contents* — and the fence line is outside that group. So
  adding, removing, or renaming a block name leaves `calc_hash` unchanged while
  `content_hash` moves. That distinction is exactly the signal that report wants
  ("the item was edited" vs "the arithmetic changed"), and it falls out of the
  existing capture group with no code change. Pinned by a test (§10), because it
  is the kind of property someone "simplifies" away later.

### 6.2 A block name is not a key

No `@key` composite, no expansion pass, no `refdes keys` involvement. The
precedent is explicit and already accepted for calc names generally
(`docs/math.md`): *"Renaming a value inside the target has no surrogate to
protect it (a calc name is not a key): every dependent fails loudly at its own
reference line, which is the report."* Block names take the same posture:

- Renaming a block breaks `#calc:` fragments and `{{calcblock block="…"}}`
  pointing at the old name, loudly, at the referring site, with a message naming
  the names that *do* exist (§7).
- It does not break any arithmetic, because no arithmetic refers to blocks.
- Making block names keyed would mean a second key namespace inside an item,
  per-item key minting, and an expansion pass over fenced content — a large
  machinery cost buying rename-stability for links and a page block, both of
  which are already loud when broken. Not worth it, and §12.4 records it.

### 6.3 Prose fragments are text, and always have been

A `[[DEC-PWR-001#calc:losses]]` in an item's body is body text, so renaming the
block changes the *referring* item's `content_hash` too (the text changed). This
is not new: a bare `BND-THM-001` mention, a `[[fig:id]]`, and a `[[cite:id]]`
all behave the same way today. Prose is prose; keyed identity lives in `links:`
fields. Worth one sentence in `docs/math.md` so nobody is surprised once.

### 6.4 Seals, baselines, `--no-write`, imports

- **Seals.** A named fence inside a sealed `append_only` entry is frozen with
  it; the entry cannot be edited without resealing, so a `#calc:` link into a
  sealed log entry is the one place a block name is *de facto* durable. Nothing
  to design; worth stating because it is the answer to "then what protects a
  block name from a rename?" in the place it matters most (a log entry's
  reasoning).
- **Baselines.** No new field. A block rename shows up as an ordinary item
  change; `calc_reference_snapshot` is untouched because no reference names a
  block.
- **`--no-write`.** Naming a block is a source edit made by the author, not a
  build write. `build --no-write` renders named blocks identically to a writable
  build and writes nothing new to the tree; `{{calcblock}}` mints and expands
  nothing. Same acceptance test shape as `candidate-parts` §3.6.
- **Imports.** Imported items carry no body, no calc blocks, and no calc values
  (`imports._absorb`, and `docs/design/calc-sources.md` §9 for the same
  conclusion about `source()`). So block names are invisible across a project
  boundary, `{{calcblock}}` refuses an imported `item=`, and no import-format
  extension is needed. The upstream item's hash already propagates as it always
  has.

---

## 7. Failure modes

Every one names the fix. Wording follows the existing shapes: the
assigned-twice message (`calc.py`), the cross-item reference messages
(`build._make_calc_resolver`), and the block parameter errors
(`docs/blocks.md`).

**On the fence (build error, at the fence line):**

```
ERROR calc fence: unknown attribute 'name' -- a calc fence accepts
    id="..."; write id="losses".
```

```
ERROR calc fence: 'losses' is not an attribute -- attributes are key="value";
    write id="losses".
```

```
ERROR calc fence: block name 'Losses' must match [a-z][a-z0-9_-]* --
    write 'losses'.
```

```
ERROR calc block 'losses' is named twice in this item -- first at line 41,
    again at line 63. A block name can only be used once per item (values
    already share one item-wide scope); rename one of them, e.g.
    'losses' -> 'losses_2'.
```

**On a reference (build error, at the referring line — this is arithmetic):**

```
ERROR calc P: cross-item reference 'DEC-PWR-001.losses.P_diss' names a block --
    a calc value is named by ITEM.NAME, and DEC-PWR-001.P_diss already names it
    uniquely. Drop '.losses'.
```

**On a link (warning, at the referring line — a broken prose link never fails a
build, same posture as an unresolved `[[…]]`):**

```
WARNING [[DEC-PWR-001#calc:loess]]: DEC-PWR-001 has no calc block named 'loess'
    (it names: losses, supply).
```

```
WARNING [[DEC-PWR-001#calc:losses]]: DEC-PWR-001 has calc blocks but none is
    named -- add id="..." to its fence to make this link work.
```

**On `{{calcblock}}` (build error, `⚠` rendered in place):**

```
{{calcblock item="DEC-PWR-001" block="loess"}} — 'DEC-PWR-001' has no calc block
    named 'loess'. It names: losses, supply.
```

```
{{calcblock item="CMP-PWR-001" block="losses"}} — CMP-PWR-001 has no calc
    blocks. calcblock renders a named ```calc block; this item computes nothing.
```

```
{{calcblock item="DEC-PWR-001"}} — missing required parameter 'block'. calcblock
    accepts: block, item.
```

```
{{calcblock item="IMP-PWR-004" block="losses"}} — 'IMP-PWR-004' is an imported
    item. Imported items carry no calc blocks in this project; render the
    upstream project's own page instead.
```

```
{{calcblock item="DEC-PWR-001" block="losses" all="true"}} — unknown parameter
    'all'. calcblock accepts: block, item.
```

**Not errors, and not warnings:**

- An unnamed block, in an item with one block or five. Naming is opt-in.
- A named block nobody references. A name is documentation on the rendering; a
  warning here would push authors to delete the thing that makes the item
  readable in order to silence the tool.
- A block name equal to a value name in the same item (`id="eff"` alongside
  `eff = 0.93`). Different namespaces, different positions, and the `calc:`
  prefix keeps the shared fragment namespace unambiguous. It is *confusing*, so
  `docs/math.md` says "name a block for what it computes, not for what it
  assigns" — but a build error for a legal, unambiguous thing is not how this
  project expresses a style preference.

---

## 8. Worked example

**Grounding note, stated as required:** the repo's own `items/` tree contains
exactly **one** item with a calc block (`DEC-PWR-001`, one block, eight
assignments) and **no** item with two. So the example below is **constructed**:
it takes the real `DEC-PWR-001` and splits its single block along the seam its
own prose already makes — supply assumptions versus the dissipation argument —
and adds one new decision item, `DEC-THM-002`, in the same `items/decisions/`
directory. Every ID that is not `DEC-THM-002` is a real item in this repo
(`REQ-PWR-002`, `REQ-PWR-003`, `BND-THM-001`, `BND-THM-002`, `CMP-PWR-001`),
and the `@key` composites are the ones committed in `DEC-PWR-001`'s front
matter.

### 8.1 The item with two named blocks

````markdown
---
key: fd24s541bbt
id: DEC-PWR-001
type: decision
title: 3V3 rail regulator topology
status: accepted
board: board-a
satisfies: [REQ-PWR-002@rgsmdxz3w5m, REQ-PWR-003@na934tg83df]
constrained_by: [BND-THM-001@cw45e0ks00n]
selects: [CMP-PWR-001@pktmysgxn8x]
checks:
  - value: eff
    against: BND-THM-002@9sga3wyj9mm
  - value: P_dens
    against: BND-THM-001@cw45e0ks00n
---

## Working

```calc id="supply"
V_in   = 12 V ± 5%      # nominal supply, 5% tolerance
V_out  = 3.3 V
I_load = 1.2 A
eff    = 0.93           # TPS62913 datasheet, half load
```

The converter loses this at full load:

```calc id="losses"
P_out  = V_out * I_load | W
P_diss = P_out * (1/eff - 1) | W
A_board = 1.4 inch * 0.9 inch   # area allocated to the power stage
P_dens = P_diss / A_board | W/in^2
```

The converter loses {{P_diss}} at full load, spread over {{A_board}} of board,
so the power stage runs at {{P_dens}} — against the 0.15 W/in² allowed by
[[BND-THM-001]].
````

Both tables now carry a caption (`supply`, `losses`) and an anchor
(`#calc-supply`, `#calc-losses`) on the item page. `P_out` in `losses` still
sees `V_out` from `supply`: **the scope did not change** (§3.5), and moving a
line between the two blocks is not a semantic edit — which is the property that
keeps `calc_hash_for` honest about what "the arithmetic changed" means (§6.1).

### 8.2 The second item, referencing one value and the whole block

````markdown
---
key: 7ht4m2xk9pq
id: DEC-THM-002
type: decision
title: Thermal re-check after the enclosure change
status: accepted
date: 2026-09-23
board: board-a
constrained_by: [BND-THM-001@cw45e0ks00n]
---

```calc
P_diss      = DEC-PWR-001.P_diss          # one value, existing syntax
enclosure_A = 0.9 inch * 0.6 inch         # the smaller sealed box
dens_new    = P_diss / enclosure_A | W/in^2
```

`DEC-PWR-001.P_diss` is the same reference it was before DEC-PWR-001's block was
split into `supply` and `losses` — it names the item and the value, and that is
all it ever needed to name. The dissipation arithmetic it comes from is
[[DEC-PWR-001#calc:losses|DEC-PWR-001's losses calculation]].
````

What the build says:

- The reference resolves exactly as it did before the split. `DEC-PWR-001`
  defines `P_diss` once, item-wide, so there is nothing to qualify (§4.1).
- Writing `DEC-PWR-001.losses.P_diss` here would be a build error naming the
  form above (§7).
- `[[DEC-PWR-001#calc:losses]]` links to `DEC-PWR-001`'s page at that table.
  Renaming `losses` later breaks this link loudly, at this line, with the names
  that do exist (§6.2).
- If `DEC-PWR-001`'s `P_diss` moves, `DEC-THM-002` shows as `changed` in the
  baseline diff and `refdes audit` names the reference — unchanged behaviour
  from finding 35, and unchanged by anything here.

### 8.3 The page that shows the whole calculation

```markdown
## Where the 3V3 loss goes

{{calcblock item="DEC-PWR-001" block="losses"}}

BND-THM-001 allows 0.15 W/in². The check on DEC-PWR-001 fails today.
```

Rendered: the four `losses` rows — `P_out`, `P_diss`, `A_board`, `P_dens` — as
the same table DEC-PWR-001's own page shows, captioned with a link back to
`DEC-PWR-001 / losses`. Not one expression was re-evaluated to produce it
(§5.4): the rows are the ones the build already made. If someone later edits
`eff`, both pages change on the next build, and neither can disagree with the
other, because there is one evaluator.

---

## 9. Docs that change

| File | Change |
|---|---|
| `docs/math.md` | New §"Naming a calc block": the fence attribute, opt-in, lowercase grammar, what a name is (a label on the rendering) and is not (a scope, a key, a value qualifier). A sentence in "Referencing another item's values" stating that block names never appear in a value reference and why. |
| `docs/links.md` | `#calc:name` fragments alongside `#field`: links, never inlines, warning on a miss, the `calc:` prefix and why. |
| `docs/blocks.md` | `{{calcblock}}` section: parameter table, renders-calcs-never-evaluates rule, local-items-only, empty state, failure modes. The non-goal section gains one line: `{{calcblock}}` takes a *name*, and the absence of `all=` is the no-wildcard rule holding at the calc boundary. |
| `docs/markdown.md` | The fence info string is now meaningful for `calc` fences; anything unrecognized there is an error rather than ignored text. |
| `docs/design/thread-workbench.md` | D1 note: `CalcLine.block` gives inline decoration the block name for free. |
| `docs/design/stale-arithmetic-signal.md` | One sentence: a fence rename moves `content_hash` and not `calc_hash`, which is the distinction this report asks for. |
| `docs/troubleshooting.md` | The three fence errors and the `#calc:` warning, with their fixes. |

---

## 10. Named tests

`tests/test_calc_block_names.py`

| Test | Pins |
|---|---|
| `test_named_fence_parses` | ```` ```calc id="losses" ```` evaluates its lines exactly as an unnamed fence does; the name reaches `CalcLine.block`. |
| `test_unnamed_block_html_unchanged` | An unnamed block's rendered HTML is byte-identical to today's, including an item with several unnamed blocks. |
| `test_named_block_renders_caption_and_anchor` | `id="calc-losses"` and a caption carrying the name. |
| `test_fence_attribute_errors` | The four §7 fence messages — unknown key, bare word, unquoted value, bad name charset — message for message. |
| `test_duplicate_block_name_in_item_errors` | Two `id="losses"` in one item → one error naming both lines and suggesting a rename. |
| `test_same_block_name_in_two_items_is_fine` | Per-item uniqueness only (§11.2). |
| `test_scope_unchanged_by_naming` | A value assigned in block `supply` is used by block `losses`; and a name reused across the two blocks is still the assigned-twice error. |
| `test_block_qualified_reference_errors` | `DEC-PWR-001.losses.P_diss` → the §7 error naming `DEC-PWR-001.P_diss`; the plain form still resolves. |
| `test_calc_rewrite_preserves_fence` | `refdes calc-rewrite` rewrites retired-spelling lines inside a named block and leaves the fence line byte-identical. |
| `test_no_write_identical` | `build --no-write` and `build` produce byte-identical item pages for a project with named blocks. |

`tests/test_calc_block_hash.py`

| Test | Pins |
|---|---|
| `test_hash_format_stays_4` | `build.HASH_FORMAT == 4`; no new payload key for an item with named blocks and no references. |
| `test_naming_moves_owner_hash_only` | Adding `id="losses"` changes the owner's `content_hash` and no other item's. |
| `test_rename_block_leaves_dependents_alone` | Renaming a block does not move a dependent item's hash or its `calc_reference_snapshot`. |
| `test_calc_hash_unaffected_by_fence` | `calc_hash_for` is identical before and after adding/renaming a fence name, while `content_hash` differs. |

`tests/test_calc_block_refs.py`

| Test | Pins |
|---|---|
| `test_calc_fragment_links_to_anchor` | `[[DEC-PWR-001#calc:losses]]` renders a link to `#calc-losses` on the target's page, with custom text support. |
| `test_calc_fragment_unknown_name_warns` | The §7 warning listing the names the item does have; exit 0; text left visible. |
| `test_calc_fragment_on_unnamed_block_warns` | The "none is named" warning shape. |
| `test_calc_fragment_on_fig_or_cite_warns` | `#calc:` on `[[fig:…]]`/`[[cite:…]]` is the same warning `#field` already produces there. |

`tests/test_calcblock.py`

| Test | Pins |
|---|---|
| `test_calcblock_renders_owner_rows` | The §8.3 table, cell for cell, from the fixture. |
| `test_calcblock_never_evaluates` | A row whose expression would now fail still renders exactly as the owner's page renders it; the block produces no verdict of its own. |
| `test_calcblock_unknown_block_lists_names` / `test_calcblock_item_without_calcs` / `test_calcblock_missing_block_param` / `test_calcblock_unknown_param` / `test_calcblock_imported_item_errors` | The five §7 block errors. |
| `test_calcblock_local_items_only` | An imported item is refused, not rendered from upstream text. |
| `test_calcblock_unknown_block_name_untouched` | `{{calcblockx …}}` survives as literal text. |
| `test_calcblock_no_write_identical` | Byte-identical pages under `--no-write`. |

---

## 11. Questions — decided (Jared, 2026-09-24)

All ten were answered on 2026-09-24; each is recorded below as decided, not an
option under continued review. Nine were confirmed as recommended; §11.5 is
the one the doc's own recommendation lost.

1. **Do unnamed blocks stay legal?** — **Decided: yes, naming is opt-in —
   confirmed.**
   Most items have one block and nothing to point at it; requiring a name would
   be mandatory ceremony on 100% of items to serve the few that need it, and it
   would change the rendered HTML of every existing item for no reason (§3.5
   pins the byte-identical case). A name is needed exactly when something —
   prose, a page, a second block — wants to say which one.

2. **Per-item or per-project block-name uniqueness?** — **Decided: per-item
   — confirmed.** A block's whole scope is its item: `env` and `origins` are
   item-wide, and every cross-item reference already names the item first, so a
   project-wide uniqueness rule buys no disambiguation. It would cost real
   pain: renaming a block in one item would be constrained by what someone named
   a block in an unrelated item, and there is no registry for block names —
   inventing one would be the `candidate_sets:` ceremony
   `docs/design/candidate-parts.md` §6.3 rejects, and the same "meaning from
   ambient context" trap finding 36 §1 names.

3. **Is rejecting `ITEM.block.NAME` right, or do you want the qualified spelling
   available anyway?** — **Decided: reject it, with an error that names the
   plain form — confirmed** (§4.2). This is the one place this spec says "no" to the brief's
   "reference any part of it", because the research says that half already works
   and is already unambiguous. If you want it anyway, the cost is §4.2's four
   items, in particular that it makes the one-name-per-item rule optional.

4. **Is the fence attribute the right home, or do you want a header line inside
   the block?** — **Decided: the fence info string — the ```` ```calc ````
   opening line itself, not a header inside the block — confirmed** (§3.2). Inside-the-block headers
   touch every line-level parser in `calc.py` and land in the rendered row count;
   the info string is the one place the existing regex already skips.

5. **`name="losses"` or a bare word?** — **Decided: a key, not a bare word —
   and the key is renamed from `name=` to `id=`.** This is the one question
   answered against the doc's written recommendation. Jared's rationale:
   *"the tangential idea here is to make calc blocks behave like items do. Or
   at least, treat them the same, to the point that it's intuitive using both
   because the process for one carries to the other."* The §3.3 precedent —
   block identifiers look like the other referenceable-thing identifiers here
   (citation `id: mp1584-ds`, figure `id="fig-curve"`) — now governs the
   key's spelling, not just the value's lowercase-hyphen shape. The rest of
   the answer stands: a quoted `key="value"` attribute, matching
   `caption="…"` / `type="decision"`. `#calc:losses` is unaffected — that
   prefix was never `#calc:name`. And this rename touches only the
   block-level attribute: a calc value's own name (`P_diss`, `V_in`) is
   unchanged everywhere, including all of §4.

6. **Is bulk import (`(b)`) really off the table?** — **Decided: rejected,
   off the table — confirmed.** Jared asked why, and the §5.1(b) reasoning
   was given in full and accepted as sufficient: an upstream author could
   inject or collide names in a downstream item's namespace; it is the
   `docs/design/calc-sources.md` §2 completeness trap in miniature; it would
   be the first wildcard anywhere in the calc language; it makes the
   `calc_refs` hash payload an unstable *set* rather than a list of fixed
   references; and it saves little, since six values is six lines that each
   document the dependency. If a project genuinely needs "the same six
   values, here too", the honest version of that is six dotted references, or
   a third item both read from, or a cited CSV both read with `source()`.
   §5.1(b) already states all of this, unchanged.

7. **Does `{{calcblock}}` need a `board=`/`tag=`-style narrowing, or a way to
   render *all* of an item's named blocks?** — **Decided: neither — taken
   as-is.** One item, one named block, one directive; two blocks is two
   directives (§5.4).

8. **Should a block name be required to differ from every value name in its
   item?** — **Decided: no — taken as-is** (§7, last block). They are different namespaces
   and the `calc:` prefix keeps the shared one unambiguous; a build error for a
   legal, unambiguous thing is not how this project spells a style preference.

9. **Should `#calc:` misses be warnings or errors?** — **Decided: warnings —
   confirmed**, matching `[[…]]` and `#field` misses (`docs/links.md`): a
   broken prose link must not fail a build. `{{calcblock}}` misses *are*
   errors, matching every other block's parameter validation.

10. **Does the name render as a caption on the item page?** — **Decided:
    yes, and only for named blocks — taken as-is** (§3.5), because the caption
    is what makes the name visible to a reader who never sees the source —
    which is the point of naming it at all.

---

## 12. Options considered and rejected

1. **Block-qualified value references (`ITEM.block.NAME`).** Rejected — §4.2.
   Item-wide uniqueness already makes `ITEM.NAME` unambiguous, so the qualified
   form adds a second spelling of one reference, makes block names load-bearing
   for arithmetic and hashing, and makes the one-name-per-item rule optional.
   Left open on evidence, not taste: if a project shows a value `ITEM.NAME`
   cannot name, that is a new finding.
2. **Bulk cross-item import of a whole block (wildcard reference).** Rejected —
   §5.1(b). Upstream controls a downstream item's namespace; the completeness
   argument from `calc-sources` §2 in miniature; the first wildcard in the calc
   language; a hash payload whose *set* moves, not just its values.
3. **A header line inside the block (`@name losses`).** Rejected — §3.2. Every
   line-level parser in `calc.py` and `build._calc_line_count` would have to
   learn to skip it, and it appears in the rendered table's row accounting.
4. **Keyed block names (`@key` composites, an expansion pass).** Rejected —
   §6.2. Calc names are already unkeyed and their rename-breakage is loud and
   accepted; block names break the same way, and the machinery cost is a second
   key namespace inside an item.
5. **Ordinal block references (`block=2`, "the second calc block").** Rejected —
   inserting a block above renumbers everything downstream, which is permanent
   meaning derived from mutable ambient position: finding 36 §1, third time.
6. **A bare word on the fence (```` ```calc losses ````).** Rejected — §3.2. No
   key means no grammar for the next attribute, and a mistyped language alias
   becomes a name.
7. **Turning the duplicate-value-name-across-blocks rule into
   block-scoped names.** Rejected — §3.5. It would make the rule that makes
   `ITEM.NAME` resolvable opt-in, which makes every reference in every project
   ambiguous by default. The existing assigned-twice error stays, unchanged, and
   is one of the two rules this spec must not weaken.
8. **`{{calcblock all="true"}}` / `blocks=` / a multi-block rendering.**
   Rejected — §5.4. A parameter that takes a set is §5.1(b) in block clothing,
   and the family's no-wildcard rule is the point of the family.
9. **Inlining a `#calc:` fragment's values into prose.** Rejected — inherited
   from `#field` (`docs/links.md`): "it links; it never inlines the value, so a
   fragment cannot go stale when the field changes." `{{calcblock}}` is the
   inlining surface, on pages, where a survey belongs.
10. **A `{{calcblock}}` inside an item body.** Rejected — blocks are page-only
    (`docs/blocks.md` §Scope), and an item that wants another item's numbers has
    `ITEM.NAME`, which is the route that participates in hashing and dependency
    ordering.
11. **Making a `#calc:` miss a build error.** Rejected — §11.9. Every prose
    reference miss in this project is a warning; a broken link in a sentence is
    not a broken design.
12. **Warning on an unreferenced block name.** Rejected — §7. It would push
    authors to delete the documentation in order to silence the tool.
13. **A `HASH_FORMAT` bump so naming registers as content everywhere.**
    Rejected — §6.1. The owner's body hash already registers it; a bump would
    churn every hash in every baseline for a change that affects one item's
    text, and would put block names into the dependent payload by implication.

---

## 13. Phasing

| Phase | Scope |
|---|---|
| **1. Names** | `calc.parse_fence_attrs` + `CALC_BLOCK_RE` validation; `extract_blocks_with_lines` returns names; `CalcLine.block`; per-item uniqueness check in `build._run_item_calcs`; caption + anchor in `_calc_table_html`; the §7 fence errors; `test_calc_block_names.py`'s parse/error/render cases and the byte-identical-unnamed pin. Independently useful: this alone makes "which calculation" sayable on the page. |
| **2. Fragments** | `[[ID#calc:name]]` resolution to the `#calc-<name>` anchor, the two warnings, `#calc:` on `fig:`/`cite:` behaviour; `test_calc_block_refs.py`. Depends on 1 for the anchor only. |
| **3. `{{calcblock}}`** | `blocks.py::_render_calcblock` + registry entry, local-items-only, the five §7 errors, `--no-write` byte-identity; `test_calcblock.py`. Depends on 1 for `CalcLine.block`. |
| **4. Hash pins** | `test_calc_block_hash.py` — no format bump, owner-only hash move, dependents unmoved, `calc_hash` unmoved. No implementation change expected; the tests exist to keep it that way. |
| **5. Docs** | §9's edits, including the `docs/math.md` sentence on why block names never appear in a value reference. |

Phase 1 ships a usable feature on its own (named, captioned, anchored
calculations). Phases 2 and 3 are the two halves of "all of it" — link and
render — and either can slip without affecting the other. Phase 4 is a
regression net, not a feature.
